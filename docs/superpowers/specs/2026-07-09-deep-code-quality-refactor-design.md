# Deep Code Quality Refactor Design

Date: 2026-07-09
Project: zhhm_bge_db

## Goal

Perform a deep code-quality refactor without changing the four supported business API entry points:

- `POST /edesc/search`
- `POST /edesc/add`
- `POST /edesc/batch-import`
- `POST /valve/parse`

The refactor should improve module boundaries, readability, typing, dead-code hygiene, and test structure. It should preserve current behavior where practical, and any unavoidable contract changes must be called out before implementation.

## Non-Goals

- Do not add new product features.
- Do not replace Qdrant or the embedding provider.
- Do not change collection names or default configuration values unless the existing code is internally inconsistent.
- Do not make default tests depend on live Qdrant or embedding services.
- Do not continue destructive feature removal beyond code that is confirmed unused by the four supported API call chains.

## Current Context

The project is a Python FastAPI service backed by Qdrant and a BGE embedding HTTP API. The working tree already contains a large in-progress slimming refactor. Core Python files currently compile, but many comments and docstrings are mojibake, tests have mostly been removed, and several modules still mix responsibilities.

The refactor should treat the current working tree as the starting point and must not revert unrelated existing changes.

## Target Boundaries

### API Layer

`api.py` should own:

- FastAPI app setup.
- Pydantic request and response models.
- Dependency construction through `get_service()` and `get_variety_type_service()`.
- HTTP exception mapping.

It should not own:

- Qdrant point construction.
- Embedding calls.
- Candidate selection.
- Business wording beyond API-level errors.

### EDesc Service Layer

`service/edesc_service.py` should own orchestration for:

- Standardizing descriptions.
- Searching by description.
- Adding one description to a product.
- Batch-importing product descriptions.
- Translating repository results into service results.

It may contain business-specific decisions such as duplicate detection and per-item batch failure handling. It should not construct raw Qdrant points or know Qdrant collection internals.

### Repository Layer

`repo/qdrant_repo.py` should own Qdrant data access:

- Creating or replacing a product with its description children.
- Searching child vectors and returning grouped parent matches.
- Fetching product details needed by the service.
- Deleting/replacing records only where required by current add behavior.

It should not own:

- Prefix strategy scoring.
- Business messages.
- API response shapes.

If prefix lookup is still required for `batch_import`, keep the Qdrant fetching in the repo and move scoring/selection to `strategy`.

### Store Layer

`qdrant_store.py` should own infrastructure:

- Qdrant client construction.
- Collection initialization.
- Collection clearing.
- Collection stats.

It should not implement business search or import behavior.

### Embedder Layer

`embedder/` should own the embedding protocol:

- `BaseEmbedder` interface.
- `BGEEmbedder` HTTP implementation.
- Public exports in `embedder/__init__.py`.

The public interface should be small and typed. If both single-text and batch embedding are needed by the current behavior, keep both and document them clearly.

### Strategy Layer

`strategy/import_strategy.py` should own import candidate ranking and selection. It should expose deterministic, easily tested functions and data models. It should not call Qdrant or embedding services directly.

### Valve Parser

`service/variety_type.py` should remain an independent parser service for `POST /valve/parse`. Parsing helpers should be private where possible, typed, and covered by unit tests with representative model strings.

## Target Directory Layout

```text
H:\zhhm_bge_db
  api.py
  config.py
  main.py
  qdrant_store.py

  embedder/
    __init__.py
    base.py
    bge_embedder.py

  repo/
    __init__.py
    qdrant_repo.py

  service/
    __init__.py
    edesc_service.py
    variety_type.py

  strategy/
    __init__.py
    import_strategy.py

  tests/
    unit/
      test_edesc_service.py
      test_import_strategy.py
      test_variety_type.py
      test_api_models.py
    integration/
      test_qdrant_repo_contract.py
    fixtures/
      edesc_samples.py
```

Large CSV files under `tests/` should be treated as data assets, not default unit-test inputs. They may be moved under `tests/fixtures/data/` only if implementation needs it and the move is explicit.

## Data Flow

```text
HTTP request
  -> api.py request model
  -> service layer
  -> standardizer / parser / strategy as needed
  -> repo layer
  -> qdrant_store and embedder
  -> service result
  -> api.py HTTP response
```

The API paths and main request fields should remain compatible with the current app. Internal service and repository return types may be tightened as long as API responses remain stable or changes are explicitly approved before implementation.

## Error Handling

- The repo layer should return empty results or raise infrastructure exceptions. It should not generate business-facing Chinese messages.
- The service layer should translate duplicate descriptions, missing candidates, embedding failures, and per-item batch failures into explicit service results or service exceptions.
- `api.py` should translate service exceptions into HTTP status codes.
- Embedding and Qdrant failures should be logged and surfaced; they should not be silently swallowed when the caller needs to know the operation failed.
- `batch_import` should keep per-item failure isolation: one failed item should not abort the entire batch.

## Typing And Documentation

- Public classes and methods in retained modules should have type hints.
- Core public methods should have concise Google-style docstrings.
- Mojibake comments, docstrings, log messages, and API metadata should be rewritten in clear Chinese or English.
- Comments should explain non-obvious behavior only; remove decorative section banners if they add noise.

## Dead Code Policy

Code can be removed when both are true:

- It is not reachable from the four supported API call chains or retained CLI maintenance commands.
- It is not required by tests, configuration loading, or the planned integration-test contract.

When reachability is unclear, keep the code in the first implementation pass and add a targeted test or note rather than guessing.

## Test Strategy

Default tests must be offline and deterministic.

Unit tests:

- `tests/unit/test_edesc_service.py`: fake repo and fake embedder for `search_by_edesc_raw`, `add_edesc`, and `batch_import`.
- `tests/unit/test_import_strategy.py`: fixed candidates to verify deterministic selection.
- `tests/unit/test_variety_type.py`: representative valve model parsing examples.
- `tests/unit/test_api_models.py`: Pydantic defaults and field compatibility.

Integration tests:

- `tests/integration/test_qdrant_repo_contract.py`: optional repo contract tests.
- Skip unless `RUN_INTEGRATION_TESTS=1` is set.
- Do not run by default in normal `pytest`.

## Acceptance Criteria

- `python -m py_compile` passes for retained Python modules.
- Default `pytest` passes without network access.
- The four supported API routes still exist.
- No obvious mojibake remains in retained source comments, docstrings, log messages, or FastAPI metadata.
- Public retained methods have meaningful type hints.
- Repository, service, strategy, embedder, and API responsibilities are separated according to this design.
- Existing unrelated working-tree changes are not reverted.

## Implementation Notes

Implementation should proceed in small, verifiable steps:

1. Establish tests and fakes around current behavior.
2. Clean readable metadata, docstrings, and type hints.
3. Move business logic out of repo and infrastructure details out of service.
4. Re-run compile and unit tests after each meaningful boundary change.
5. Add optional integration-test scaffolding last.
