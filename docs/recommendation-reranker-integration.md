# Recommendation Reranker Integration

The existing `POST /edesc/search` path now supports an optional HTTP reranker.
No new API endpoint is introduced.

## Runtime configuration

```text
RERANKER_URL=http://10.0.12.12:9997/v1/rerank
RERANKER_TIMEOUT=3
RERANKER_MODEL=bge-reranker-v2-m3
```

`RERANKER_URL` is the complete HTTP POST endpoint. The request body contains
`query`, `documents`, and `model` when configured. The response may use the
common `results: [{"index": 0, "score": 0.9}]` shape or
`relevance_score` instead of `score`.

## Runtime behavior

Historical exact matches keep their existing priority. When history misses,
the full child vector index retrieves candidates and the reranker scores the
candidate by1 evidence descriptions. The final score combines reranker score,
vector score, form compatibility, and historical support.

If the URL is empty, the request fails, or the response is incomplete, the
service returns the original vector ranking. This degradation path keeps
`/edesc/search` available when the optional model service is unavailable.

## Validation

The configured service was verified at
`http://10.0.12.12:9997/v1/rerank` with `bge-reranker-v2-m3`.

On the time-safe holdout after `2024-09-01`, the 92 requests that missed the
deterministic historical index all reached `vector_reranked` with 100% coverage.
Their by1 Top5 accuracy was 67.39%, equal to the current vector-only ranking;
the integration is operational, but its weights and document construction need
further tuning before claiming an accuracy gain.
