from service.candidate_reranker import (
    CandidateReranker,
    RerankerClient,
    parse_rerank_response,
)


def test_parse_rerank_response_accepts_relevance_scores() -> None:
    scores = parse_rerank_response(
        {
            "results": [
                {"index": 1, "relevance_score": 0.92},
                {"index": 0, "relevance_score": 0.41},
            ]
        },
        document_count=2,
    )

    assert scores == {0: 0.41, 1: 0.92}


def test_candidate_reranker_reorders_candidates_and_keeps_evidence() -> None:
    class FakeClient:
        def rerank(self, query, documents):
            assert "90F" in query
            assert documents[0] == "D71X4: candidate one"
            return {0: 0.20, 1: 0.95}

    candidates = [
        {
            "by1": "D71X4",
            "score": 0.90,
            "support": 5,
            "matched_descriptions": ["candidate one"],
        },
        {
            "by1": "D71XLV99",
            "score": 0.85,
            "support": 4,
            "matched_descriptions": ["candidate two"],
        },
    ]

    result = CandidateReranker(FakeClient()).rerank(
        "wafer valve",
        "90F",
        candidates,
    )

    assert result[0]["by1"] == "D71XLV99"
    assert result[0]["reranker_score"] == 0.95
    assert result[0]["reranker_used"] is True
    assert result[0]["matched_descriptions"] == ["candidate two"]


def test_candidate_reranker_returns_original_candidates_on_client_failure() -> None:
    class FailingClient:
        def rerank(self, query, documents):
            raise TimeoutError("reranker timeout")

    candidates = [{"by1": "D71X4", "score": 0.90}]
    result = CandidateReranker(FailingClient()).rerank(
        "wafer valve",
        "90F",
        candidates,
    )

    assert result == candidates


def test_reranker_client_posts_standard_json_payload(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'{"results": [{"index": 0, "score": 0.88}]}'

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("service.candidate_reranker.urlopen", fake_urlopen)
    scores = RerankerClient("http://reranker.test/rerank", timeout=2.5).rerank(
        "query 90F",
        ["document"],
    )

    assert captured["url"] == "http://reranker.test/rerank"
    assert captured["timeout"] == 2.5
    assert scores == {0: 0.88}
