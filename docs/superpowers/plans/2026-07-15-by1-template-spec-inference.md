# By1 Template and Specification Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a time-safe, template-assisted inference pipeline that returns both `by1` candidates and an auditable specification result from historical product descriptions.

**Architecture:** Generate three description views from one lossless standardization pass: raw text for evidence, structural text for by1 template retrieval, and full text for size/specification inference. Build deterministic template clusters inside each known `by1`, attach a `(by1, template, form_code, size, spec)` profile, and use template evidence to recall and rerank by1 candidates while preserving exact historical and mature rule precedence. Roll out through `off`, `shadow`, and `on` modes without replacing the existing `/edesc/search` path.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, NumPy, scikit-learn, pandas, openpyxl, Qdrant, pytest, JSON indexes.

## Global Constraints

- Preserve `raw_description`; never overwrite or rewrite the original historical description.
- Keep one `by1` associated with multiple template clusters when historical structure requires it.
- Use `structural_description` for by1 retrieval and `full_description` for specification inference.
- Unknown attributes remain unknown; do not fill missing materials, seats, discs, drives, or specifications with business defaults.
- Template representatives must be real historical members; no generated representative descriptions.
- Build templates, profiles, mature rules, and confidence calibration only from the training time window.
- Use validation only for tuning and the blind test window only for final evaluation.
- Preserve `/edesc/search`; do not add a separate recommendation endpoint.
- Low-confidence specification inference returns `inferred_spec = null` plus ranked alternatives and evidence.
- Template retrieval failure, index failure, and reranker failure must degrade to the existing historical/vector paths.
- Do not modify unrelated dirty-worktree files or generated assets until the task that owns them explicitly requires it.

---

## File Map

| File | Responsibility |
|---|---|
| `scripts/edesc_standardizer.py` | Lossless canonicalization and structural/full description views. |
| `service/template_models.py` | Typed records exchanged by builders, indexers, and runtime retrieval. |
| `tools/build_by1_template_index.py` | Training-window template clustering, medoid selection, spec profiles, and JSON export. |
| `service/by1_template_retriever.py` | Qdrant or local-index retrieval of template candidates with compatibility filtering. |
| `service/recommendation.py` | Joint by1/spec evidence ordering and compatibility scoring. |
| `api.py` | Rollout mode and stable response integration. |
| `config.py` | Versioned template index and rollout configuration. |
| `tools/evaluate_by1_template_inference.py` | Chronological evaluation, ablations, and segmented metrics. |
| `tests/unit/test_template_models.py` | Contract tests for data records and serialization. |
| `tests/unit/test_by1_template_index.py` | Clustering, medoid, profile, and leakage tests. |
| `tests/unit/test_by1_template_retriever.py` | Retrieval, conflict filtering, and fallback tests. |
| `tests/unit/test_recommendation.py` | Joint by1/spec ranking and abstention tests. |
| `tests/unit/test_template_inference_evaluation.py` | Metric and split tests. |

---

### Task 1: Add the multi-view standardization contract

**Files:**
- Create: `service/template_models.py`
- Modify: `scripts/edesc_standardizer.py`
- Test: `tests/unit/test_template_models.py`
- Test: `tests/unit/test_edesc_standardizer.py`

**Interfaces:**
- `standardize_description_views(edesc: str) -> DescriptionViews`
- `DescriptionViews.raw_description: str`
- `DescriptionViews.normalized_description: str`
- `DescriptionViews.structural_description: str`
- `DescriptionViews.full_description: str`
- `DescriptionViews.attributes: dict[str, AttributeEvidence]`
- `AttributeEvidence(value: str | None, source: str, confidence: float, evidence: str)`

- [ ] **Step 1: Write failing tests for the view contract.**

```python
from scripts.edesc_standardizer import standardize_description_views


def test_views_keep_raw_full_and_size_reduced_structural_text() -> None:
    raw = 'DI LUG WAFER BUTTERFLY VALVE EPDM SEAT GEAR 4"/DN100 PN16'
    result = standardize_description_views(raw)

    assert result.raw_description == raw
    assert "DN100" not in result.structural_description
    assert "WAFER" in result.structural_description
    assert "EPDM" in result.structural_description
    assert "DN100" in result.full_description
    assert result.attributes["connection"].value == "LUG WAFER"


def test_missing_material_is_unknown_not_epdm_or_di() -> None:
    result = standardize_description_views("DI WAFER BUTTERFLY VALVE DN100")

    seat = result.attributes.get("seat_material")
    assert seat is None or seat.value in (None, "unknown")
    assert "EPDM" not in result.structural_description
    assert "DI DISC" not in result.structural_description
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run:

```powershell
python -m pytest -q tests/unit/test_template_models.py tests/unit/test_edesc_standardizer.py
```

Expected: FAIL because `DescriptionViews`, `AttributeEvidence`, and `standardize_description_views` do not yet exist.

- [ ] **Step 3: Implement the typed view model and standardization function.**

Add the frozen dataclasses below to `service/template_models.py`:

```python
@dataclass(frozen=True)
class AttributeEvidence:
    value: str | None
    source: str
    confidence: float
    evidence: str


@dataclass(frozen=True)
class DescriptionViews:
    raw_description: str
    normalized_description: str
    structural_description: str
    full_description: str
    attributes: dict[str, AttributeEvidence]
```

Implement `standardize_description_views` in `scripts/edesc_standardizer.py` by reusing `preprocess`, `extract_features`, `standardize_edesc`, and `standardize_edesc_for_by1`. Build `structural_description` from only explicitly observed non-size segments and build `full_description` from the full standardized representation. Convert `UNKNOWN` values to absent/`unknown` evidence rather than rendering them into text. Preserve the raw input byte-for-byte after converting only the outer Python string value.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run:

```powershell
python -m pytest -q tests/unit/test_template_models.py tests/unit/test_edesc_standardizer.py
```

Expected: PASS with all tests in both files passing.

- [ ] **Step 5: Commit the standardization contract.**

```powershell
git add service/template_models.py scripts/edesc_standardizer.py tests/unit/test_template_models.py tests/unit/test_edesc_standardizer.py
git commit -m "feat: add multi-view description standardization"
```

### Task 2: Build deterministic by1-scoped template clusters and specification profiles

**Files:**
- Create: `tools/build_by1_template_index.py`
- Modify: `service/template_models.py`
- Test: `tests/unit/test_by1_template_index.py`

**Interfaces:**
- `TemplateMember(point_id: str, by1: str, views: DescriptionViews, structural_vector: np.ndarray, form_code: str, spec: str, parsed_size: str, support: int)`
- `TemplateCluster(template_id: str, by1: str, cluster_id: int, member_ids: tuple[str, ...], representative_point_id: str, structural_signature: str, cohesion: float, outlier_count: int)`
- `build_template_clusters(members: Sequence[TemplateMember]) -> list[TemplateCluster]`
- `build_spec_profiles(members, clusters) -> list[dict[str, object]]`
- `build_template_index(rows, train_before: str, embedder: Any) -> dict[str, object]`

- [ ] **Step 1: Write failing tests for same-by1 clustering, medoids, and profiles.**

```python
import numpy as np

from service.template_models import DescriptionViews, TemplateMember
from tools.build_by1_template_index import build_spec_profiles, build_template_clusters


def make_members(*items: tuple[str, str, str]) -> list[TemplateMember]:
    vectors = {
        "WAFER EPDM GEAR": np.array([1.0, 0.0, 0.0]),
        "GROOVED EPDM GEAR": np.array([0.0, 1.0, 0.0]),
    }
    result = []
    for index, (by1, structural, spec) in enumerate(items):
        result.append(
            TemplateMember(
                point_id=f"p{index}",
                by1=by1,
                views=DescriptionViews(
                    raw_description=structural,
                    normalized_description=structural,
                    structural_description=structural,
                    full_description=f"{structural} {spec}",
                    attributes={},
                ),
                structural_vector=vectors[structural],
                form_code="90F",
                spec=spec,
                parsed_size=spec.removeprefix("D"),
                support=1,
            )
        )
    return result


def test_same_by1_can_produce_two_structural_templates() -> None:
    members = make_members(
        ("D71XLV99", "WAFER EPDM GEAR", "D100"),
        ("D71XLV99", "WAFER EPDM GEAR", "D150"),
        ("D71XLV99", "GROOVED EPDM GEAR", "D100"),
    )

    clusters = build_template_clusters(members)

    assert len(clusters) == 2
    assert {cluster.by1 for cluster in clusters} == {"D71XLV99"}
    assert all(cluster.representative_point_id in cluster.member_ids for cluster in clusters)


def test_spec_profile_keeps_size_to_spec_mapping_and_nonstandard_values() -> None:
    members = make_members(
        ("D71XLV99", "WAFER EPDM GEAR", "D100"),
        ("D71XLV99", "WAFER EPDM GEAR", "D150"),
        ("D71XLV99", "WAFER EPDM GEAR", "N125X1220"),
    )
    clusters = build_template_clusters(members)

    profiles = build_spec_profiles(members, clusters)

    assert profiles[0]["size_to_spec_distribution"]["100"]["D100"] == 1
    assert "N125X1220" in profiles[0]["nonstandard_specs"]
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run:

```powershell
python -m pytest -q tests/unit/test_by1_template_index.py
```

Expected: FAIL because the builder interfaces do not yet exist.

- [ ] **Step 3: Implement deterministic template clustering.**

Use this deterministic sequence in `tools/build_by1_template_index.py`:

```python
grouped = group_by_by1(members)
for by1, by1_members in sorted(grouped.items()):
    buckets = bucket_by_structural_signature(by1_members)
    for signature, bucket in sorted(buckets.items()):
        vectors = normalize(np.vstack([member.structural_vector for member in bucket]))
        labels = choose_labels(vectors)
        representative = medoid(bucket, vectors, labels)
        for cluster_id in sorted(set(labels)):
            member_indices = np.flatnonzero(labels == cluster_id)
            cluster_members = [bucket[index] for index in member_indices]
            medoid_member = representative[cluster_id]
            yield TemplateCluster(
                template_id=stable_template_id(by1, signature, int(cluster_id)),
                by1=by1,
                cluster_id=int(cluster_id),
                member_ids=tuple(member.point_id for member in cluster_members),
                representative_point_id=medoid_member.point_id,
                structural_signature=signature,
                cohesion=cluster_cohesion(cluster_members, medoid_member),
                outlier_count=count_outliers(cluster_members),
            )
```

Reuse the existing deterministic cosine/agglomerative behavior in `tools/cluster_by1_descriptions.py`, but make the input member order `(by1, point_id)` and make cluster IDs contiguous within each by1. For one-member groups set `template_status = "insufficient_sample"`; for outliers use the same-by1 nearest-neighbor threshold from the existing clustering design. Serialize vectors only when required by the local index; never recompute embeddings for existing Qdrant vectors.

- [ ] **Step 4: Implement training-window filtering and spec profiles.**

Filter rows with `contract_date < train_before` before clustering or profile aggregation. Build profiles by `(by1, template_id, form_code)` and store counts for `spec_distribution`, `size_to_spec_distribution`, `nonstandard_specs`, `support`, `date_min`, and `date_max`. Use `parse_specification` and `infer_size` for standard sizes; retain nonstandard specifications verbatim in `nonstandard_specs`.

- [ ] **Step 5: Run focused tests and verify determinism.**

Run:

```powershell
python -m pytest -q tests/unit/test_by1_template_index.py
python -m pytest -q tests/unit/test_description_clustering.py tests/unit/test_by1_template_index.py
```

Expected: PASS, and two invocations with the same fixture must produce byte-identical JSON after removing only the generated timestamp field.

- [ ] **Step 6: Commit the builder and profile index.**

```powershell
git add tools/build_by1_template_index.py service/template_models.py tests/unit/test_by1_template_index.py
git commit -m "feat: build by1 scoped template and spec profiles"
```

### Task 3: Add template retrieval with compatibility filtering

**Files:**
- Create: `service/by1_template_retriever.py`
- Modify: `config.py`
- Test: `tests/unit/test_by1_template_retriever.py`

**Interfaces:**
- `By1TemplateRetriever.retrieve(query_views: DescriptionViews, form_code: str, top_k: int = 50) -> list[dict[str, object]]`
- Candidate fields: `template_id`, `by1`, `structural_score`, `attribute_match_ratio`, `form_match`, `support`, `representative_description`, `spec_profile`, `evidence`.

- [ ] **Step 1: Write failing tests for compatibility and graceful fallback.**

```python
def test_explicit_connection_conflict_is_filtered() -> None:
    retriever = make_retriever(
        hit("wrong", {"connection": "FLANGED"}),
        hit("right", {"connection": "WAFER"}),
    )
    views = standardize_description_views('DI WAFER BV 4"/DN100')

    result = retriever.retrieve(views, form_code="90F", top_k=5)

    assert [item["template_id"] for item in result] == ["right"]


def test_retrieval_error_returns_empty_candidates() -> None:
    retriever = make_failing_retriever()
    views = standardize_description_views("DI WAFER BV DN100")

    assert retriever.retrieve(views, form_code="90F") == []
```

- [ ] **Step 2: Run the focused test and verify it fails.**

```powershell
python -m pytest -q tests/unit/test_by1_template_retriever.py
```

Expected: FAIL because `By1TemplateRetriever` does not yet exist.

- [ ] **Step 3: Implement local-index and Qdrant retrieval.**

Construct the query vector from `structural_description`, query the versioned template collection or local JSON index, and apply these rules:

```python
explicit = explicit_query_attributes(query_views.attributes)
if has_conflict(explicit, candidate.attributes):
    continue
candidate["attribute_match_ratio"] = matched / len(explicit) if explicit else 0.0
candidate["form_match"] = form_code in candidate["supported_form_codes"]
candidate["score"] = (
    0.70 * candidate["structural_score"]
    + 0.20 * candidate["attribute_match_ratio"]
    + 0.05 * float(candidate["form_match"])
    + 0.05 * normalized_support(candidate["support"])
)
```

An absent candidate field is not a conflict; an explicitly contradictory field is a conflict. Catch Qdrant, embedding, malformed-payload, and timeout errors, log the version and collection, and return an empty candidate list so the caller can use the existing path.

- [ ] **Step 4: Add configuration with an explicit disabled default.**

Add:

```python
BY1_TEMPLATE_MODE = os.getenv("BY1_TEMPLATE_MODE", "off").lower()
BY1_TEMPLATE_INDEX_PATH = os.getenv(
    "BY1_TEMPLATE_INDEX_PATH",
    os.path.join(BASE_DIR, "data", "by1_template_index.json"),
)
BY1_TEMPLATE_COLLECTION = os.getenv(
    "BY1_TEMPLATE_COLLECTION",
    "by1_templates_v1",
)
BY1_TEMPLATE_CANDIDATES = int(os.getenv("BY1_TEMPLATE_CANDIDATES", "100"))
```

- [ ] **Step 5: Run focused retrieval tests.**

```powershell
python -m pytest -q tests/unit/test_by1_template_retriever.py
```

Expected: PASS with conflict filtering, missing fields, form compatibility, and retrieval failure covered.

- [ ] **Step 6: Commit the retriever.**

```powershell
git add service/by1_template_retriever.py config.py tests/unit/test_by1_template_retriever.py
git commit -m "feat: add by1 template retrieval"
```

### Task 4: Integrate template evidence into joint by1/spec inference

**Files:**
- Modify: `service/recommendation.py`
- Modify: `api.py`
- Modify: `tests/unit/test_recommendation.py`
- Modify: `tests/unit/test_api_models.py`

**Interfaces:**
- `RecommendationService(index_path, retriever=None, reranker=None, template_retriever=None)`
- `RecommendationService.recommend(query: str, form_code: str = "", customer: str = "", top_k: int = 5) -> dict[str, object]`
- New result keys: `template_candidates`, `template_match_level`, `inferred_spec`, `spec_confidence`, `spec_confidence_score`, `spec_alternatives`, `evidence`.

- [ ] **Step 1: Write failing tests for template-assisted by1 and spec results.**

```python
class FakeTemplateRetriever:
    def __init__(self, candidates):
        self.candidates = candidates

    def retrieve(self, views, form_code, top_k=50):
        return list(self.candidates)


def test_template_candidates_are_aggregated_to_distinct_by1_values() -> None:
    service = service_with_template_candidates(
        {"template_id": "t1", "by1": "D71X", "score": 0.91, "form_match": True},
        {"template_id": "t2", "by1": "D71X", "score": 0.88, "form_match": True},
        {"template_id": "t3", "by1": "D72X", "score": 0.89, "form_match": False},
    )

    result = service.recommend("DI WAFER BV DN100", form_code="90F", top_k=5)

    assert [item["by1"] for item in result["by1_candidates"]] == ["D71X", "D72X"]
    assert result["template_candidates"][0]["template_id"] == "t1"


def test_weak_template_spec_evidence_abstains() -> None:
    service = service_with_template_spec("D100", support=1, score=0.41)

    result = service.recommend("unseen description", form_code="90F")

    assert result["inferred_spec"] is None
    assert result["spec_confidence"] == "low"
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

```powershell
python -m pytest -q tests/unit/test_recommendation.py tests/unit/test_api_models.py
```

Expected: FAIL because recommendation does not yet accept template evidence.

- [ ] **Step 3: Add template evidence after exact-history lookup and before vector fallback.**

Keep the existing precedence:

```python
    exact_by1, exact_level = self._select_by1_counts(description, normalized_form, customer_key)
if exact_by1:
    by1_candidates = self._rank_candidates(exact_by1, limit)
else:
    template_candidates = self.template_retriever.retrieve(views, normalized_form, top_k=50)
    by1_candidates = aggregate_template_candidates(template_candidates, limit)
    if not by1_candidates:
        by1_candidates = self.retriever.retrieve(
            raw_query,
            form_code=normalized_form,
            top_k=limit,
        )
```

Aggregate multiple templates into distinct by1 values using the highest template score, a bounded support term, form compatibility, and the best raw-member similarity. Preserve the matched templates as evidence.

- [ ] **Step 4: Add joint specification inference and compatibility checks.**

Use existing exact-history and mature-rule methods first. When those do not answer, inspect the selected template `spec_profile` using parsed size and form_code. Return a unique spec only when the confidence threshold and historical compatibility check pass; otherwise return `None` and sorted alternatives. Add `by1`, template, form, size, and spec compatibility to `evidence`.

- [ ] **Step 5: Add API lazy initialization and safe degradation.**

Initialize the template retriever only when `BY1_TEMPLATE_MODE` is `shadow` or `on`. Catch missing/corrupt template assets and retain the existing recommendation/vector path. In `/edesc/search`, keep the current request shape and add only the documented result fields. Do not initialize a template service when mode is `off`.

- [ ] **Step 6: Run the full inference test set.**

```powershell
python -m pytest -q tests/unit/test_recommendation.py tests/unit/test_api_models.py tests/unit/test_candidate_retriever.py
```

Expected: PASS, including exact-history precedence, template aggregation, specification abstention, API fallback, and mode-off behavior.

- [ ] **Step 7: Commit joint inference integration.**

```powershell
git add service/recommendation.py api.py tests/unit/test_recommendation.py tests/unit/test_api_models.py
git commit -m "feat: integrate template evidence into joint inference"
```

### Task 5: Add chronological evaluation and shadow rollout checks

**Files:**
- Create: `tools/evaluate_by1_template_inference.py`
- Create: `tests/unit/test_template_inference_evaluation.py`
- Modify: `README.md`
- Modify: `docs/recommendation-phase2-optimization-plan.md`

**Interfaces:**
- `evaluate_rows(rows, train_before, validation_before, mode) -> dict[str, object]`
- `evaluate_prediction(prediction, truth) -> dict[str, bool]`
- Output keys: `by1_top1`, `by1_top5`, `by1_coverage`, `spec_top1`, `spec_answered_accuracy`, `joint_accuracy`, `high_confidence_accuracy`, `segments`, `template_purity`, `template_cohesion`, `template_coverage`, `spec_consistency`.

- [ ] **Step 1: Write failing tests for temporal filtering and metrics.**

```python
def test_test_rows_do_not_contribute_to_template_statistics() -> None:
    rows = fixture_rows(
        ("2024-01-01", "D71X", "D100"),
        ("2024-05-01", "D72X", "D100"),
    )

    result = evaluate_rows(
        rows,
        train_before="2024-04-28",
        validation_before="2024-09-01",
        mode="shadow",
    )

    assert result["training_rows"] == 1
    assert result["evaluation_rows"] == 1


def test_joint_accuracy_requires_by1_and_spec_to_be_correct() -> None:
    prediction = {"by1_candidates": [{"by1": "D71X"}], "inferred_spec": "D100"}
    truth = {"by1": "D71X", "spec": "D150"}

    result = evaluate_prediction(prediction, truth)

    assert result == {"by1_top1": True, "by1_top5": True, "spec_top1": False, "joint": False}
```

- [ ] **Step 2: Run the focused test and verify it fails.**

```powershell
python -m pytest -q tests/unit/test_template_inference_evaluation.py
```

Expected: FAIL because the evaluation module does not yet exist.

- [ ] **Step 3: Implement time-safe evaluation and segmentation.**

Partition input rows before any template/profile construction. Compute row-weighted and deduplicated metrics, then segment by description-known status, by1-known status, form presence, specification class, product role, template support tier, and size presence. Use explicit denominators for coverage and answered accuracy; do not report an accuracy metric when its denominator is zero.

- [ ] **Step 4: Add shadow acceptance checks.**

Require the evaluator to fail the command when template mode changes the existing result for a low-confidence case, when a template representative is not a member, when cluster IDs are not contiguous, or when a non-finite similarity is written. Store output JSON under `outputs/by1_template_inference/` with input hash, index version, and rule version.

- [ ] **Step 5: Document the build and evaluation commands.**

Add exact commands to `README.md`:

```powershell
python tools\build_by1_template_index.py --input history_orders.xlsx --train-before 2024-04-28 --output data\by1_template_index.json
python tools\evaluate_by1_template_inference.py --input history_orders.xlsx --index data\by1_template_index.json --train-before 2024-04-28 --validation-before 2024-09-01 --output outputs\by1_template_inference\metrics.json
```

Document that `BY1_TEMPLATE_MODE=shadow` is required before enabling `on`, and document the fallback behavior for missing assets and low-confidence specifications.

- [ ] **Step 6: Run the repository verification suite.**

```powershell
python -m pytest -q
python -m compileall -q api.py config.py service scripts tools tests
git diff --check
```

Expected: all tests pass, compilation succeeds, and `git diff --check` reports no errors.

- [ ] **Step 7: Commit evaluation and rollout documentation.**

```powershell
git add tools/evaluate_by1_template_inference.py tests/unit/test_template_inference_evaluation.py README.md docs/recommendation-phase2-optimization-plan.md
git commit -m "feat: add template inference evaluation and shadow gates"
```

## Final Review Checklist

- [ ] Every template representative is a historical member.
- [ ] Every template cluster is scoped to one by1.
- [ ] One by1 may have multiple template clusters.
- [ ] `structural_description` excludes size-driven similarity without deleting structural evidence.
- [ ] `full_description` preserves size and nonstandard specification evidence.
- [ ] Unknown fields are not rendered as invented defaults.
- [ ] Exact history outranks template retrieval.
- [ ] Template retrieval failure falls back to the current path.
- [ ] Low-confidence specs abstain with alternatives.
- [ ] Training, validation, and test windows are isolated.
- [ ] by1, spec, and joint metrics are reported with explicit coverage denominators.
- [ ] Shadow mode is tested before on-mode changes the response.

**Plan complete and ready for execution only after all checklist items are verified.**
