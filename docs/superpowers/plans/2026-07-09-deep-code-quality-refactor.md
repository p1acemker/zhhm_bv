# Deep Code Quality Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the existing FastAPI + Qdrant service for clearer boundaries, readable documentation, stronger typing, and deterministic offline tests while preserving the four supported API entry points.

**Architecture:** Keep the existing top-level modules but sharpen responsibilities: `api.py` handles HTTP models and routes, `service/` orchestrates business flows, `repo/` handles Qdrant access, `strategy/` handles import candidate selection, `embedder/` handles embedding calls, and `qdrant_store.py` handles collection infrastructure. Add offline unit tests first, then make boundary changes behind those tests, with optional integration tests gated by an environment variable.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, pytest, qdrant-client, requests.

## Global Constraints

- Preserve these API routes: `POST /edesc/search`, `POST /edesc/add`, `POST /edesc/batch-import`, `POST /valve/parse`.
- Do not add product features.
- Do not replace Qdrant or the embedding provider.
- Do not change collection names or default configuration values unless the existing code is internally inconsistent.
- Do not make default tests depend on live Qdrant or embedding services.
- Do not continue destructive feature removal beyond code confirmed unused by the four supported API call chains.
- Treat the current working tree as the starting point and do not revert unrelated existing changes.
- Default `pytest` must pass without network access.

---

## File Structure

- Modify: `H:\zhhm_bge_db\api.py`
  - Own FastAPI app metadata, request models, route functions, dependency wiring, and HTTP exception mapping.
- Modify: `H:\zhhm_bge_db\config.py`
  - Own defaults for logging, Qdrant, embedding, collections, and search settings.
- Modify: `H:\zhhm_bge_db\embedder\base.py`
  - Define the typed embedding protocol.
- Modify: `H:\zhhm_bge_db\embedder\bge_embedder.py`
  - Implement the remote BGE embedding client.
- Modify: `H:\zhhm_bge_db\embedder\__init__.py`
  - Export the public embedder types.
- Modify: `H:\zhhm_bge_db\qdrant_store.py`
  - Own client creation, collection lifecycle, and stats.
- Modify: `H:\zhhm_bge_db\repo\qdrant_repo.py`
  - Own Qdrant reads and writes only.
- Modify: `H:\zhhm_bge_db\repo\__init__.py`
  - Export `QdrantRepo`.
- Modify: `H:\zhhm_bge_db\service\edesc_service.py`
  - Own search, add, and batch-import orchestration.
- Modify: `H:\zhhm_bge_db\service\variety_type.py`
  - Own valve-model parsing.
- Modify: `H:\zhhm_bge_db\service\__init__.py`
  - Export `EDescService` and `VarietyTypeService`.
- Modify: `H:\zhhm_bge_db\strategy\import_strategy.py`
  - Own prefix scoring, candidate ranking, and best-candidate selection.
- Modify: `H:\zhhm_bge_db\strategy\__init__.py`
  - Export strategy public functions and types.
- Modify: `H:\zhhm_bge_db\main.py`
  - Keep CLI maintenance commands but make output readable and route Qdrant writes through repo where practical.
- Create: `H:\zhhm_bge_db\tests\unit\test_api_models.py`
- Create: `H:\zhhm_bge_db\tests\unit\test_import_strategy.py`
- Create: `H:\zhhm_bge_db\tests\unit\test_edesc_service.py`
- Create: `H:\zhhm_bge_db\tests\unit\test_variety_type.py`
- Create: `H:\zhhm_bge_db\tests\integration\test_qdrant_repo_contract.py`
- Create: `H:\zhhm_bge_db\tests\fixtures\edesc_samples.py`

---

### Task 1: Add Offline Test Scaffold And Lock Public API Shape

**Files:**
- Create: `H:\zhhm_bge_db\tests\unit\test_api_models.py`
- Create: `H:\zhhm_bge_db\tests\unit\test_import_strategy.py`
- Create: `H:\zhhm_bge_db\tests\unit\test_variety_type.py`
- Create: `H:\zhhm_bge_db\tests\fixtures\edesc_samples.py`
- Modify: `H:\zhhm_bge_db\tests\__init__.py`

**Interfaces:**
- Consumes: Existing `SearchRequest`, `AddEDescRequest`, `BatchImportRequest`, `ValveParseRequest`, `app`, `Candidate`, `select_best`, and `VarietyTypeService`.
- Produces: An offline pytest baseline that verifies current public API route names, model defaults, import strategy behavior, and basic valve parsing.

- [ ] **Step 1: Create fixture constants**

Add this file at `H:\zhhm_bge_db\tests\fixtures\edesc_samples.py`:

```python
"""Shared sample values for offline unit tests."""

SEARCH_QUERY = "DI LUG WAFER BUTTERFLY VALVE DN100"
BY1 = "D371X4"
EDESC = "DI LUG WAFER BUTTERFLY VALVE"
VALVE_MODEL = "D371X4"
```

- [ ] **Step 2: Create API model and route tests**

Add this file at `H:\zhhm_bge_db\tests\unit\test_api_models.py`:

```python
from api import (
    AddEDescRequest,
    BatchImportRequest,
    SearchRequest,
    ValveParseRequest,
    app,
)


def test_supported_routes_are_registered() -> None:
    routes = {
        (next(iter(route.methods)), route.path)
        for route in app.routes
        if getattr(route, "methods", None)
    }

    assert ("POST", "/edesc/search") in routes
    assert ("POST", "/edesc/add") in routes
    assert ("POST", "/edesc/batch-import") in routes
    assert ("POST", "/valve/parse") in routes


def test_search_request_defaults() -> None:
    request = SearchRequest(query="abc")

    assert request.query == "abc"
    assert request.top_k == 10
    assert request.customer is None


def test_add_edesc_request_accepts_optional_metadata() -> None:
    request = AddEDescRequest(by1="D371X4", edesc="desc")

    assert request.by1 == "D371X4"
    assert request.edesc == "desc"
    assert request.metadata is None


def test_batch_import_default_strategy() -> None:
    request = BatchImportRequest(by1_list=["D371X4"])

    assert request.by1_list == ["D371X4"]
    assert request.strategy == "most_references"


def test_valve_parse_request_keeps_model_field() -> None:
    request = ValveParseRequest(model="D371X4")

    assert request.model == "D371X4"
```

- [ ] **Step 3: Create strategy tests**

Add this file at `H:\zhhm_bge_db\tests\unit\test_import_strategy.py`:

```python
import pytest

from strategy.import_strategy import Candidate, select_best


def test_candidate_to_dict_rounds_score() -> None:
    candidate = Candidate(
        by1="D371X4",
        score=0.87654,
        prefix_match_len=4,
        edesc_count=12,
    )

    assert candidate.to_dict() == {
        "by1": "D371X4",
        "score": 0.8765,
        "prefix_match_len": 4,
        "edesc_count": 12,
    }


def test_select_best_prefers_highest_edesc_count() -> None:
    selected = select_best(
        [
            Candidate(by1="A", score=0.9, prefix_match_len=2, edesc_count=1),
            Candidate(by1="B", score=0.5, prefix_match_len=1, edesc_count=5),
        ]
    )

    assert selected.by1 == "B"


def test_select_best_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="candidate"):
        select_best([])
```

- [ ] **Step 4: Create valve parser tests around current behavior**

Add this file at `H:\zhhm_bge_db\tests\unit\test_variety_type.py`:

```python
import pytest

from service.variety_type import VarietyTypeService


def test_parse_with_normalized_returns_expected_keys() -> None:
    result = VarietyTypeService().parse_with_normalized("D371X4")

    assert set(result) == {
        "type",
        "driveMode",
        "connectMode",
        "form",
        "material",
        "standardizedProduct",
    }
    assert result["standardizedProduct"] == "D371X"


def test_parse_with_normalized_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        VarietyTypeService().parse_with_normalized(" ")
```

- [ ] **Step 5: Keep package marker simple**

Replace `H:\zhhm_bge_db\tests\__init__.py` with:

```python
"""Tests for zhhm_bge_db."""
```

- [ ] **Step 6: Run the new focused tests and capture current failures**

Run:

```powershell
pytest tests/unit/test_api_models.py tests/unit/test_import_strategy.py tests/unit/test_variety_type.py -q
```

Expected: at least one failure from mojibake field names or messages. The failure is useful because later tasks make the code readable and stable.

- [ ] **Step 7: Commit test scaffold**

Run:

```powershell
git add -- tests/unit/test_api_models.py tests/unit/test_import_strategy.py tests/unit/test_variety_type.py tests/fixtures/edesc_samples.py tests/__init__.py
git commit -m "test: add offline refactor baseline"
```

Expected: commit succeeds with only test files staged.

---

### Task 2: Clean Public Text, Typing, And Low-Risk Module Metadata

**Files:**
- Modify: `H:\zhhm_bge_db\api.py`
- Modify: `H:\zhhm_bge_db\config.py`
- Modify: `H:\zhhm_bge_db\embedder\base.py`
- Modify: `H:\zhhm_bge_db\embedder\bge_embedder.py`
- Modify: `H:\zhhm_bge_db\embedder\__init__.py`
- Modify: `H:\zhhm_bge_db\qdrant_store.py`
- Modify: `H:\zhhm_bge_db\service\variety_type.py`

**Interfaces:**
- Consumes: Test scaffold from Task 1.
- Produces: Readable FastAPI metadata, request model docstrings, embedder/store public types, and `VarietyTypeService.parse_with_normalized(model: str) -> Dict[str, Optional[str]]` returning a readable `standardizedProduct` key.

- [ ] **Step 1: Rewrite `config.py` metadata without changing values**

Replace the top-level comments and docstring in `H:\zhhm_bge_db\config.py` with:

```python
# -*- coding: utf-8 -*-
"""Runtime configuration for the four supported API workflows."""
```

Keep these existing constants unchanged:

```python
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
QDRANT_URL = "http://10.0.8.238:6333"
EMBEDDING_API_URL = "http://10.0.12.12:9997/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024
PARENT_COLLECTION = "products_tests"
CHILD_COLLECTION = "products_test_child"
DEFAULT_TOP_K = 10
DEFAULT_SCORE_THRESHOLD = 0.5
```

- [ ] **Step 2: Rewrite `api.py` FastAPI metadata and request models**

Use readable metadata:

```python
app = FastAPI(
    title="EDesc maintenance API",
    description="Maintains product descriptions and parses valve model codes.",
    version="3.0.0",
)
```

Use these request model docstrings and field annotations:

```python
class SearchRequest(BaseModel):
    """Request body for vector search by product description."""

    query: str = Field(..., description="Raw product description text.")
    top_k: int = Field(10, ge=1, le=100, description="Maximum results to return.")
    customer: Optional[str] = Field(None, description="Optional customer name.")


class AddEDescRequest(BaseModel):
    """Request body for adding one description to one product."""

    by1: str
    edesc: str
    metadata: Optional[dict] = None


class BatchImportRequest(BaseModel):
    """Request body for importing descriptions for multiple products."""

    by1_list: List[str]
    strategy: str = "most_references"


class ValveParseRequest(BaseModel):
    """Request body for valve model parsing."""

    model: str = Field(..., description="Raw valve model code, such as D371X4.")
```

- [ ] **Step 3: Make route comments and logs readable**

In `H:\zhhm_bge_db\api.py`, keep the same four route decorators and rewrite route docstrings to concise English:

```python
@app.post("/edesc/search", tags=["edesc"])
async def search_edesc(request: SearchRequest):
    """Search products by raw description text."""
```

Apply the same pattern for `/edesc/add`, `/edesc/batch-import`, and `/valve/parse`.

- [ ] **Step 4: Make embedder protocol explicit**

Replace `H:\zhhm_bge_db\embedder\base.py` with:

```python
# -*- coding: utf-8 -*-
"""Embedding client interface."""

from abc import ABC, abstractmethod
from typing import List, Union

Embedding = List[float]
EmbeddingInput = Union[str, List[str]]
EmbeddingOutput = Union[Embedding, List[Embedding]]


class BaseEmbedder(ABC):
    """Abstract interface implemented by embedding clients."""

    @abstractmethod
    def encode(self, texts: EmbeddingInput, batch_size: int = 32) -> EmbeddingOutput:
        """Encode one text or a batch of texts into embedding vectors."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return whether the embedding service is reachable and well-formed."""
```

- [ ] **Step 5: Clean `BGEEmbedder` typing and docstrings**

In `H:\zhhm_bge_db\embedder\bge_embedder.py`, use:

```python
from typing import List, Optional, Union, cast
```

Update signatures:

```python
def __init__(
    self,
    api_url: Optional[str] = None,
    model: Optional[str] = None,
    embedding_dim: Optional[int] = None,
    timeout: int = 30,
) -> None:
```

Keep `encode()` behavior, and make `health_check()` validate the single-text output:

```python
def health_check(self) -> bool:
    """Return True when the remote embedding service returns one vector."""
    try:
        result = cast(List[float], self.encode("test"))
        return len(result) == self.embedding_dim
    except Exception as exc:
        logger.warning("Embedder health check failed: %s", exc)
        return False
```

- [ ] **Step 6: Clean `qdrant_store.py` without behavior changes**

Change constructor typing:

```python
from typing import Any, Dict, Optional


def __init__(
    self,
    url: Optional[str] = None,
    embedding_dim: Optional[int] = None,
    parent_collection: Optional[str] = None,
    child_collection: Optional[str] = None,
) -> None:
```

Change `get_stats` signature:

```python
def get_stats(self) -> Dict[str, Dict[str, Any]]:
```

Keep collection names, vector sizes, and payload indexes unchanged.

- [ ] **Step 7: Rename valve output key to readable API field**

In `H:\zhhm_bge_db\service\variety_type.py`, change:

```python
parsed["鏍囧噯鍖栧搧绉?] = norm
```

to:

```python
parsed["standardizedProduct"] = norm
```

Update `parse_with_normalized` signature:

```python
def parse_with_normalized(self, model: str) -> Dict[str, Optional[str]]:
```

- [ ] **Step 8: Run Task 1 tests again**

Run:

```powershell
pytest tests/unit/test_api_models.py tests/unit/test_import_strategy.py tests/unit/test_variety_type.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Compile cleaned modules**

Run:

```powershell
python -m py_compile api.py config.py qdrant_store.py embedder\base.py embedder\bge_embedder.py service\variety_type.py
```

Expected: command exits with code 0.

- [ ] **Step 10: Commit text and typing cleanup**

Run:

```powershell
git add -- api.py config.py qdrant_store.py embedder/base.py embedder/bge_embedder.py embedder/__init__.py service/variety_type.py
git commit -m "refactor: clean public text and typed interfaces"
```

Expected: commit succeeds with only the listed source files staged.

---

### Task 3: Move Prefix Ranking Out Of The Repository

**Files:**
- Modify: `H:\zhhm_bge_db\strategy\import_strategy.py`
- Modify: `H:\zhhm_bge_db\strategy\__init__.py`
- Modify: `H:\zhhm_bge_db\repo\qdrant_repo.py`
- Modify: `H:\zhhm_bge_db\service\edesc_service.py`
- Modify: `H:\zhhm_bge_db\tests\unit\test_import_strategy.py`

**Interfaces:**
- Consumes: `Candidate` and `select_best(candidates: List[Candidate]) -> Candidate`.
- Produces:
  - `prefix_similarity(left: str, right: str) -> float`
  - `rank_prefix_matches(new_by1: str, existing_by1s: List[str], top_k: int = 10) -> List[Dict[str, Any]]`
  - `QdrantRepo.get_all_by1s(limit: int = 10000) -> List[str]`
  - `EDescService._import_single(new_by1: str) -> Dict[str, Any]` using strategy prefix ranking.

- [ ] **Step 1: Add failing prefix strategy tests**

Append to `H:\zhhm_bge_db\tests\unit\test_import_strategy.py`:

```python
from strategy.import_strategy import prefix_similarity, rank_prefix_matches


def test_prefix_similarity_scores_common_prefix() -> None:
    assert prefix_similarity("D371X4", "D371X7") == pytest.approx(5 / 6)
    assert prefix_similarity("D371X4", "Q41F") == 0.0


def test_rank_prefix_matches_excludes_identical_and_sorts() -> None:
    results = rank_prefix_matches("D371X4", ["D371X4", "D371X7", "D37A", "Q41F"], top_k=2)

    assert [item["by1"] for item in results] == ["D371X7", "D37A"]
    assert results[0]["prefix_match_len"] == 5
```

- [ ] **Step 2: Run tests and verify prefix functions are missing**

Run:

```powershell
pytest tests/unit/test_import_strategy.py -q
```

Expected: failure importing `prefix_similarity` or `rank_prefix_matches`.

- [ ] **Step 3: Implement prefix functions in strategy**

Add to `H:\zhhm_bge_db\strategy\import_strategy.py`:

```python
def prefix_similarity(left: str, right: str) -> float:
    """Return common-prefix similarity normalized by the longer string."""
    a = left.upper()
    b = right.upper()
    prefix_len = 0
    for index in range(min(len(a), len(b))):
        if a[index] != b[index]:
            break
        prefix_len += 1
    max_len = max(len(a), len(b))
    return prefix_len / max_len if max_len else 0.0


def rank_prefix_matches(
    new_by1: str, existing_by1s: List[str], top_k: int = 10
) -> List[Dict[str, Any]]:
    """Rank existing product codes by common-prefix similarity."""
    matches: List[Dict[str, Any]] = []
    for by1 in existing_by1s:
        if by1 == new_by1:
            continue
        score = prefix_similarity(new_by1, by1)
        if score > 0:
            matches.append(
                {
                    "by1": by1,
                    "score": score,
                    "prefix_match_len": int(score * max(len(new_by1), len(by1))),
                }
            )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:top_k]
```

- [ ] **Step 4: Export strategy functions**

Replace `H:\zhhm_bge_db\strategy\__init__.py` with:

```python
"""Import strategy helpers."""

from .import_strategy import Candidate, prefix_similarity, rank_prefix_matches, select_best

__all__ = [
    "Candidate",
    "prefix_similarity",
    "rank_prefix_matches",
    "select_best",
]
```

- [ ] **Step 5: Remove prefix scoring from repo**

In `H:\zhhm_bge_db\repo\qdrant_repo.py`, delete `search_by_prefix()` and `_calculate_prefix_similarity()`.

Keep `get_all_by1s()` as the repository method that fetches source product names.

- [ ] **Step 6: Use strategy ranking in service**

In `H:\zhhm_bge_db\service\edesc_service.py`, change imports:

```python
from strategy.import_strategy import Candidate, rank_prefix_matches, select_best
```

Change `_import_single()`:

```python
all_by1s = self.repo.get_all_by1s()
similar = rank_prefix_matches(new_by1, all_by1s, top_k=5)
```

- [ ] **Step 7: Run strategy tests**

Run:

```powershell
pytest tests/unit/test_import_strategy.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Compile affected modules**

Run:

```powershell
python -m py_compile strategy\import_strategy.py strategy\__init__.py repo\qdrant_repo.py service\edesc_service.py
```

Expected: command exits with code 0.

- [ ] **Step 9: Commit strategy boundary change**

Run:

```powershell
git add -- strategy/import_strategy.py strategy/__init__.py repo/qdrant_repo.py service/edesc_service.py tests/unit/test_import_strategy.py
git commit -m "refactor: move prefix ranking into strategy"
```

Expected: commit succeeds with only the listed files staged.

---

### Task 4: Add EDesc Service Fakes And Tighten Service-Orchestration Contract

**Files:**
- Create: `H:\zhhm_bge_db\tests\unit\test_edesc_service.py`
- Modify: `H:\zhhm_bge_db\service\edesc_service.py`
- Modify: `H:\zhhm_bge_db\repo\qdrant_repo.py`

**Interfaces:**
- Consumes:
  - `EDescService.search_by_edesc_raw(query: str, top_k: int = 10, score_threshold: Optional[float] = None, customer: Optional[str] = None) -> List[Dict[str, Any]]`
  - `EDescService.add_edesc(by1: str, edesc: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`
  - `EDescService.batch_import(by1_list: List[str], strategy: str = "most_references") -> Dict[str, Any]`
- Produces: Service unit tests that do not import Qdrant, do not call embedding HTTP services, and document expected result shapes.

- [ ] **Step 1: Add service fake tests**

Add this file at `H:\zhhm_bge_db\tests\unit\test_edesc_service.py`:

```python
from typing import Any, Dict, List, Optional

import service.edesc_service as edesc_module
from service.edesc_service import EDescService


class FakeStore:
    def get_stats(self) -> Dict[str, Any]:
        return {
            "parent_collection": {"name": "parents", "points_count": 1},
            "child_collection": {"name": "children", "points_count": 2},
        }


class FakeEmbedder:
    def __init__(self) -> None:
        self.inputs: List[Any] = []

    def encode(self, texts: Any, batch_size: int = 32) -> Any:
        self.inputs.append(texts)
        if isinstance(texts, list):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]
        return [1.0, 0.0, 0.0, 0.0]


class FakeRepo:
    def __init__(self) -> None:
        self.products: Dict[str, Dict[str, Any]] = {
            "D371X4": {
                "by1": "D371X4",
                "parent_id": "parent-D371X4",
                "edesc_list": ["STANDARD DESC"],
                "edesc_count": 1,
                "metadata": {"by1": "D371X4", "edesc_count": 1},
            },
            "D371X7": {
                "by1": "D371X7",
                "parent_id": "parent-D371X7",
                "edesc_list": ["SOURCE DESC", "SECOND DESC"],
                "edesc_count": 2,
                "metadata": {"by1": "D371X7", "edesc_count": 2},
            },
        }
        self.deleted: List[str] = []

    def search(
        self, query_vector: List[float], top_k: int = 10, score_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        return [
            {
                "productName": "D371X4",
                "edesc_list": ["STANDARD DESC"],
                "edesc_count": 1,
                "parent_id": "parent-D371X4",
                "score": 0.95,
                "matched_edescs": ["STANDARD DESC"],
                "metadata": {},
            }
        ][:top_k]

    def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:
        return self.products.get(by1)

    def get_all_by1s(self) -> List[str]:
        return list(self.products)

    def delete_by_parent_id(self, parent_id: str) -> None:
        self.deleted.append(parent_id)

    def add_product_with_edesc_list(
        self, product_name: str, edesc_list: List[str], embedding_func: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        embedding_func(edesc_list)
        parent_id = f"parent-{product_name}"
        self.products[product_name] = {
            "by1": product_name,
            "parent_id": parent_id,
            "edesc_list": edesc_list,
            "edesc_count": len(edesc_list),
            "metadata": metadata or {},
        }
        return parent_id


def make_service() -> EDescService:
    return EDescService(store=FakeStore(), embedder=FakeEmbedder(), repo=FakeRepo())


def test_search_by_edesc_raw_standardizes_and_adds_customer_specs(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "STANDARD DESC")
    service = make_service()
    service._spec_rules = {"D371X4": {"ACME": ["DN100"]}}

    results = service.search_by_edesc_raw("raw desc", top_k=10, customer="ACME")

    assert results[0]["productName"] == "D371X4"
    assert results[0]["matched_specs"] == ["DN100"]


def test_add_edesc_detects_duplicate(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "STANDARD DESC")

    result = make_service().add_edesc("D371X4", "raw desc")

    assert result["success"] is False
    assert result["is_duplicate"] is True
    assert result["existing_edesc_count"] == 1


def test_add_edesc_appends_new_standardized_description(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: "NEW DESC")
    service = make_service()

    result = service.add_edesc("D371X4", "new desc", metadata={"source": "unit"})

    assert result["success"] is True
    assert result["action"] == "appended"
    assert result["new_edesc_count"] == 2


def test_batch_import_isolates_per_item_results(monkeypatch) -> None:
    monkeypatch.setattr(edesc_module, "_standardize", lambda text: text)

    result = make_service().batch_import(["D371X9", "D371X4"])

    assert result["total"] == 2
    assert result["success_count"] == 1
    assert result["fail_count"] == 1
    assert result["details"][0]["success"] is True
    assert result["details"][1]["success"] is False
```

- [ ] **Step 2: Run service tests and record current failures**

Run:

```powershell
pytest tests/unit/test_edesc_service.py -q
```

Expected: failures caused by service typing, unreadable messages, or the current fake-repo compatibility points.

- [ ] **Step 3: Tighten service type annotations**

In `H:\zhhm_bge_db\service\edesc_service.py`, use these signatures:

```python
def _standardize(edesc: str) -> str:

def search_by_edesc_raw(
    self,
    query: str,
    top_k: int = 10,
    score_threshold: Optional[float] = None,
    customer: Optional[str] = None,
) -> List[Dict[str, Any]]:

def add_edesc(
    self,
    by1: str,
    edesc: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

def batch_import(
    self,
    by1_list: List[str],
    strategy: str = "most_references",
) -> Dict[str, Any]:

def _import_single(self, new_by1: str) -> Dict[str, Any]:

def _add_product_with_embedding(
    self,
    product_name: str,
    edesc_list: List[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:

def get_stats(self) -> Dict[str, Any]:
```

- [ ] **Step 4: Rewrite service messages as readable Chinese or English**

Use stable messages like these:

```python
"message": f"Description already exists for by1={by1}"
"message": f"Appended description for by1={by1}"
"message": f"Created product by1={by1}"
"message": f"by1={new_by1} already exists"
"message": f"No prefix candidates found for {new_by1}"
"message": "No candidate details could be loaded"
"message": f"Imported {new_by1} from {selected.by1}"
```

Do not change result keys used by existing API callers: keep `success`, `message`, `is_duplicate`, `action`, `parent_id`, `original`, `standardized`, `old_edesc_count`, `new_edesc_count`, `total`, `success_count`, `fail_count`, and `details`.

- [ ] **Step 5: Keep raw Qdrant point construction out of service**

Confirm `EDescService._add_product_with_embedding()` only delegates:

```python
return self.repo.add_product_with_edesc_list(
    product_name=product_name,
    edesc_list=edesc_list,
    embedding_func=self.embedder.encode,
    metadata=metadata,
)
```

If point construction appears in `service/edesc_service.py`, move it to `repo/qdrant_repo.py`.

- [ ] **Step 6: Make repository methods typed and message-free**

In `H:\zhhm_bge_db\repo\qdrant_repo.py`, use these public signatures:

```python
def add_product_with_edesc_list(
    self,
    product_name: str,
    edesc_list: List[str],
    embedding_func: Any,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:

def search(
    self,
    query_vector: List[float],
    top_k: int = 10,
    score_threshold: Optional[float] = None,
) -> List[Dict[str, Any]]:

def delete_by_parent_id(self, parent_id: str) -> None:

def get_by_by1(self, by1: str) -> Optional[Dict[str, Any]]:

def get_all_by1s(self, limit: int = 10000) -> List[str]:
```

Repository log messages should describe infrastructure events only:

```python
logger.info("Added product %s with %s descriptions", product_name, len(edesc_list))
logger.error("Vector search failed: %s", exc)
logger.debug("Deleted parent and children: %s", parent_id)
```

- [ ] **Step 7: Run service and strategy tests**

Run:

```powershell
pytest tests/unit/test_edesc_service.py tests/unit/test_import_strategy.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Compile service and repo modules**

Run:

```powershell
python -m py_compile service\edesc_service.py repo\qdrant_repo.py
```

Expected: command exits with code 0.

- [ ] **Step 9: Commit service orchestration cleanup**

Run:

```powershell
git add -- service/edesc_service.py repo/qdrant_repo.py tests/unit/test_edesc_service.py
git commit -m "refactor: tighten edesc service orchestration"
```

Expected: commit succeeds with only the listed files staged.

---

### Task 5: Add Integration Gate, Clean CLI Text, And Run Final Verification

**Files:**
- Create: `H:\zhhm_bge_db\tests\integration\test_qdrant_repo_contract.py`
- Modify: `H:\zhhm_bge_db\main.py`
- Modify: `H:\zhhm_bge_db\api.py`
- Modify: `H:\zhhm_bge_db\tests\unit\test_api_models.py`

**Interfaces:**
- Consumes: Cleaned service/repo/embedder/store interfaces from Tasks 2-4.
- Produces: Optional integration-test gate, readable CLI output, final route coverage, and full compile/default pytest verification.

- [ ] **Step 1: Add gated integration test skeleton**

Add this file at `H:\zhhm_bge_db\tests\integration\test_qdrant_repo_contract.py`:

```python
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Set RUN_INTEGRATION_TESTS=1 to run live Qdrant contract tests.",
)


def test_integration_gate_is_enabled_explicitly() -> None:
    assert os.getenv("RUN_INTEGRATION_TESTS") == "1"
```

- [ ] **Step 2: Verify integration test is skipped by default**

Run:

```powershell
pytest tests/integration/test_qdrant_repo_contract.py -q
```

Expected: one skipped test.

- [ ] **Step 3: Clean CLI output and keep commands unchanged**

In `H:\zhhm_bge_db\main.py`, keep these commands:

```python
import
clear
rebuild
```

Replace mojibake user-facing strings with readable output:

```python
print("Initializing product search maintenance engine")
print(f"  [OK] Embedding service is healthy ({EMBEDDING_MODEL}, {EMBEDDING_DIM} dims)")
print(f"  [OK] Qdrant connected ({QDRANT_URL})")
print("Usage:")
print("  python main.py import <csv_file>  # import standardized CSV data")
print("  python main.py clear              # clear all collection data")
print("  python main.py rebuild            # rebuild collections")
```

Keep method names:

```python
ProductSearchEngine.import_from_csv(self, csv_file: str) -> None
ProductSearchEngine.clear_all(self) -> None
ProductSearchEngine.rebuild_collections(self) -> None
```

- [ ] **Step 4: Add API route behavior tests with dependency override by monkeypatch**

Append to `H:\zhhm_bge_db\tests\unit\test_api_models.py`:

```python
from fastapi.testclient import TestClient

import api


class FakeEDescService:
    def search_by_edesc_raw(self, query, top_k=10, customer=None):
        return [{"productName": "D371X4", "score": 0.95}]

    def add_edesc(self, by1, edesc, metadata=None):
        return {"success": True, "message": "ok", "action": "created", "parent_id": "p1"}

    def batch_import(self, by1_list, strategy="most_references"):
        return {"total": len(by1_list), "success_count": len(by1_list), "fail_count": 0, "details": []}


class FakeValveService:
    def parse_with_normalized(self, model):
        return {
            "type": "butterfly valve",
            "driveMode": "manual",
            "connectMode": "lug",
            "form": "centerline",
            "material": "rubber",
            "standardizedProduct": "D371X",
        }


def test_api_routes_delegate_to_services(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_service", lambda: FakeEDescService())
    monkeypatch.setattr(api, "get_variety_type_service", lambda: FakeValveService())
    client = TestClient(api.app)

    assert client.post("/edesc/search", json={"query": "desc"}).status_code == 200
    assert client.post("/edesc/add", json={"by1": "D371X4", "edesc": "desc"}).status_code == 200
    assert client.post("/edesc/batch-import", json={"by1_list": ["D371X4"]}).status_code == 200
    assert client.post("/valve/parse", json={"model": "D371X4"}).status_code == 200
```

- [ ] **Step 5: Run full default pytest**

Run:

```powershell
pytest -q
```

Expected: unit tests pass and the integration contract test is skipped.

- [ ] **Step 6: Run full compile verification**

Run:

```powershell
python -m py_compile api.py config.py main.py qdrant_store.py repo\qdrant_repo.py service\edesc_service.py service\variety_type.py strategy\import_strategy.py strategy\__init__.py embedder\base.py embedder\bge_embedder.py embedder\__init__.py
```

Expected: command exits with code 0.

- [ ] **Step 7: Check retained source for mojibake markers**

Run:

```powershell
Select-String -Path api.py,config.py,main.py,qdrant_store.py,repo\qdrant_repo.py,service\edesc_service.py,service\variety_type.py,strategy\import_strategy.py,embedder\base.py,embedder\bge_embedder.py -Pattern '�|鏍|绱|涓|闃|鎵|鍚|瀵|妫|璐|榾'
```

Expected: no output for retained source files.

- [ ] **Step 8: Confirm API route list**

Run:

```powershell
@'
from api import app
for route in app.routes:
    methods = getattr(route, "methods", None)
    if methods and route.path in {"/edesc/search", "/edesc/add", "/edesc/batch-import", "/valve/parse"}:
        print(sorted(methods), route.path)
'@ | python -
```

Expected output includes:

```text
['POST'] /edesc/search
['POST'] /edesc/add
['POST'] /edesc/batch-import
['POST'] /valve/parse
```

- [ ] **Step 9: Commit final verification cleanup**

Run:

```powershell
git add -- main.py api.py tests/integration/test_qdrant_repo_contract.py tests/unit/test_api_models.py
git commit -m "test: add integration gate and final api checks"
```

Expected: commit succeeds with only the listed files staged.

---

## Self-Review

Spec coverage:

- API route preservation is covered by Tasks 1 and 5.
- Offline default tests are covered by Tasks 1, 4, and 5.
- Mojibake cleanup is covered by Tasks 2, 4, and 5.
- Typing and public docstrings are covered by Tasks 2 and 4.
- Strategy/repo/service boundary separation is covered by Tasks 3 and 4.
- Optional integration testing is covered by Task 5.
- Existing unrelated working-tree changes are protected by each task staging only its listed files.

Red-flag scan:

- No plan step uses unresolved vague markers.
- Every code-changing step includes concrete code or exact signatures.
- Every verification step includes an exact command and expected result.

Type consistency:

- `EDescService` method signatures in Task 4 match the API usage in Tasks 1 and 5.
- `rank_prefix_matches()` output keys match the existing `_import_single()` candidate-building logic.
- `standardizedProduct` is asserted in tests and produced by `VarietyTypeService`.
