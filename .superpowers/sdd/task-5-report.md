status: DONE

files changed:
- H:\zhhm_bge_db\main.py
- H:\zhhm_bge_db\tests\integration\test_qdrant_repo_contract.py
- H:\zhhm_bge_db\tests\unit\test_api_models.py

commits created:
- `886ab31` (`test: add integration gate and final api checks`)

commands run with outcomes:
- `pytest tests/integration/test_qdrant_repo_contract.py -q` -> PASS (`1 skipped`)
- `pytest tests/unit/test_api_models.py::test_api_routes_delegate_to_services -q` -> PASS (`1 passed`)
- `pytest -q` -> PASS (`17 passed, 1 skipped`)
- `python -m py_compile api.py config.py main.py qdrant_store.py repo\qdrant_repo.py service\edesc_service.py service\variety_type.py strategy\import_strategy.py strategy\__init__.py embedder\base.py embedder\bge_embedder.py embedder\__init__.py` -> PASS (exit code 0)
- `Select-String -Path api.py,config.py,main.py,qdrant_store.py,repo\qdrant_repo.py,service\edesc_service.py,service\variety_type.py,strategy\import_strategy.py,embedder\base.py,embedder\bge_embedder.py -Pattern '锟絴閺峾缁眧娑搢闂億閹祙閸殀鐎祙濡珅鐠恷姒?'` -> PASS (no output)
- route listing snippet from the brief -> PASS (`['POST'] /edesc/search`, `['POST'] /edesc/add`, `['POST'] /edesc/batch-import`, `['POST'] /valve/parse`)

concerns:
- `main.py` had pre-existing working-tree edits before Task 5. The cleanup preserved the current `import`, `clear`, and `rebuild` CLI flow rather than reverting to the older HEAD-era command surface.
- `api.py` already satisfied the route contract and monkeypatch-based delegation test, so no source change was required there.

fix notes:
- Routed `ProductSearchEngine.rebuild_collections()` through `QdrantVectorStore.rebuild_collections()` so the CLI keeps the same behavior while the store owns collection lifecycle management.
- The new store method deletes the parent and child collections only when present, then re-initializes them through `init_collections()`.
