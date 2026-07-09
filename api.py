# -*- coding: utf-8 -*-
"""EDesc maintenance FastAPI surface."""

import logging
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EDesc maintenance API",
    description="Maintains product descriptions and parses valve model codes.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_service = None
_variety_type_service = None


def get_service():
    """Return the lazily initialized EDesc service."""
    global _service
    if _service is None:
        logger.info("Initializing EDescService...")
        from embedder import BGEEmbedder
        from qdrant_store import QdrantVectorStore
        from repo import QdrantRepo
        from service import EDescService

        store = QdrantVectorStore()
        try:
            store.init_collections()
        except Exception as exc:
            logger.warning("init_collections skipped: %s", exc)
        embedder = BGEEmbedder()
        repo = QdrantRepo(
            client=store.client,
            parent_collection=store.parent_collection,
            child_collection=store.child_collection,
        )
        _service = EDescService(store=store, embedder=embedder, repo=repo)
        logger.info("EDescService initialized")
    return _service


def get_variety_type_service():
    """Return the lazily initialized valve parsing service."""
    global _variety_type_service
    if _variety_type_service is None:
        logger.info("Initializing VarietyTypeService...")
        from service import VarietyTypeService

        _variety_type_service = VarietyTypeService()
        logger.info("VarietyTypeService initialized")
    return _variety_type_service


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


@app.get("/health", tags=["system"])
async def health_check():
    """Return store health and collection counts."""
    try:
        service = get_service()
        stats = service.get_stats()
        return {
            "status": "healthy",
            "parent_count": stats["parent_collection"]["points_count"],
            "child_count": stats["child_collection"]["points_count"],
        }
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return {"status": "unhealthy", "error": str(exc)}


@app.post("/edesc/search", tags=["edesc"])
async def search_edesc(request: SearchRequest):
    """Search products by raw description text."""
    service = get_service()
    results = service.search_by_edesc_raw(
        request.query,
        top_k=request.top_k,
        customer=request.customer,
    )
    return {
        "query": request.query,
        "customer": request.customer,
        "total": len(results),
        "data": results,
    }


@app.post("/edesc/add", tags=["edesc"])
async def add_edesc(request: AddEDescRequest):
    """Add one description to one product."""
    service = get_service()
    result = service.add_edesc(
        by1=request.by1,
        edesc=request.edesc,
        metadata=request.metadata,
    )
    if not result["success"] and not result.get("is_duplicate"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/edesc/batch-import", tags=["edesc"])
async def batch_import_edesc(request: BatchImportRequest):
    """Import descriptions for multiple products."""
    service = get_service()
    return service.batch_import(request.by1_list, strategy=request.strategy)


@app.post("/valve/parse", tags=["valve"])
async def parse_valve_model(request: ValveParseRequest):
    """Parse a valve model code."""
    service = get_variety_type_service()
    try:
        return service.parse_with_normalized(request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    print("=" * 50)
    print("EDesc maintenance API service v3.0.0")
    print("=" * 50)
    print("API docs: http://localhost:8000/docs")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
