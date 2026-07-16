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
    description="Maintains product descriptions and infers order specifications.",
    version="3.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_service = None
_spec_inference_service = None
_recommendation_service = None
_description_design_service = None
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
        store.init_collections()
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


def get_spec_inference_service():
    """Return the lazily initialized historical specification service."""
    global _spec_inference_service
    if _spec_inference_service is None:
        from config import SPEC_INFERENCE_INDEX_PATH, SPEC_INFERENCE_RULES_PATH
        from service import SpecInferenceService

        _spec_inference_service = SpecInferenceService(
            SPEC_INFERENCE_INDEX_PATH,
            SPEC_INFERENCE_RULES_PATH,
        )
        logger.info("SpecInferenceService initialized")
    return _spec_inference_service


def get_recommendation_service():
    """Return the lazily initialized by1/form-code recommendation service."""
    global _recommendation_service
    if _recommendation_service is None:
        from config import (
            BY1_TEMPLATE_MODE,
            RECOMMENDATION_INDEX_PATH,
            RECOMMENDATION_MODE,
        )
        from service import RecommendationService
        from service.candidate_retriever import CandidateRetriever
        from service.candidate_reranker import CandidateReranker, RerankerClient

        template_retriever = None
        if BY1_TEMPLATE_MODE in {"shadow", "on"}:
            try:
                from service.by1_template_retriever import By1TemplateRetriever

                template_retriever = By1TemplateRetriever.from_config()
            except Exception as exc:
                logger.warning("By1 template retriever unavailable: %s", exc)

        retriever = (
            CandidateRetriever.from_config()
            if RECOMMENDATION_MODE == "hybrid"
            else None
        )
        reranker_client = (
            RerankerClient.from_config()
            if RECOMMENDATION_MODE == "hybrid"
            else None
        )
        _recommendation_service = RecommendationService(
            RECOMMENDATION_INDEX_PATH,
            retriever=retriever,
            reranker=CandidateReranker(reranker_client)
            if reranker_client is not None
            else None,
            template_retriever=template_retriever,
        )
        logger.info("RecommendationService initialized")
    return _recommendation_service


def get_description_design_mode() -> str:
    """Return a validated description-design rollout mode."""
    from config import EDESC_DESIGN_MODE

    return EDESC_DESIGN_MODE if EDESC_DESIGN_MODE in {"off", "shadow", "on"} else "off"


def get_description_design_service():
    """Return the lazily initialized valve-description design service."""
    global _description_design_service
    if _description_design_service is None:
        from service.description_design import DescriptionDesignService

        _description_design_service = DescriptionDesignService.from_config()
        logger.info("DescriptionDesignService initialized")
    return _description_design_service


class SearchRequest(BaseModel):
    """Description search and integrated recommendation request."""

    query: str = Field(..., description="Raw product description text.")
    top_k: int = Field(5, ge=1, le=20, description="Maximum by1 results to return.")
    customer: str = Field("", description="Optional customer name.")
    form_code: str = Field("", description="Structured product-code form, such as 90F.")
    form: str = Field("", description="Deprecated alias for form_code.")


class SpecInferenceRequest(BaseModel):
    """Backward-compatible request for the legacy specification endpoint."""

    query: str = Field(..., description="Raw product description text.")
    top_k: int = Field(50, ge=1, le=100, description="Maximum alternatives to return.")
    customer: str = Field("", description="Optional customer name.")
    form: str = Field("", description="Legacy product variety/by1 context.")


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
    """Recommend by1 and specification, with vector search as fallback."""
    form_code = request.form_code or request.form
    try:
        recommendation = get_recommendation_service().recommend(
            query=request.query,
            form_code=form_code,
            customer=request.customer,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    candidates = recommendation["by1_candidates"]
    if candidates:
        results = [
            {**candidate, "productName": candidate["by1"]}
            for candidate in candidates
        ]
        by1_match_level = recommendation["by1_match_level"]
        recommendation_source = (
            "full_vector_index"
            if by1_match_level in {"vector_full_index", "vector_reranked"}
            else "historical_index"
        )
    else:
        service = get_service()
        results = service.search_by_edesc_raw(
            request.query,
            top_k=request.top_k,
            customer=request.customer or None,
        )
        recommendation_source = "vector_fallback"
        by1_match_level = "vector_description" if results else "none"
    response = {
        "query": request.query,
        "customer": request.customer,
        "form_code": form_code,
        "total": len(results),
        "data": results,
        "recommendation_source": recommendation_source,
        "by1_match_level": by1_match_level,
        "template_candidates": recommendation.get("template_candidates", []),
        "template_match_level": recommendation.get("template_match_level", "none"),
        "inferred_spec": recommendation["inferred_spec"],
        "spec_confidence": recommendation["spec_confidence"],
        "spec_confidence_score": recommendation["spec_confidence_score"],
        "spec_match_level": recommendation["spec_match_level"],
        "spec_alternatives": recommendation["spec_alternatives"],
        "evidence": recommendation["evidence"],
    }
    design_mode = get_description_design_mode()
    if design_mode in {"shadow", "on"}:
        try:
            description_design = get_description_design_service().design(
                request.query,
                by1_candidates=candidates or results,
                form_code=form_code,
            )
            if design_mode == "on":
                response["description_design"] = description_design
            else:
                logger.info(
                    "Description design shadow result: status=%s family=%s template=%s",
                    description_design.get("status"),
                    description_design.get("valve_family"),
                    description_design.get("template_id"),
                )
        except Exception as exc:
            logger.warning("Description design failed without affecting search: %s", exc)
            if design_mode == "on":
                response["description_design"] = {
                    "status": "partial",
                    "valve_family": None,
                    "product_role": "other",
                    "standardized_description": None,
                    "template_id": None,
                    "confidence": "low",
                    "confidence_score": 0.0,
                    "attributes": {},
                    "inferred_fields": [],
                    "warnings": ["description_design_unavailable"],
                    "alternatives": [],
                }
    return response


@app.post("/spec/infer", tags=["specification"])
async def infer_specification(request: SpecInferenceRequest):
    """Infer a specification from description, customer, and form context."""
    service = get_spec_inference_service()
    try:
        return service.infer(
            query=request.query,
            top_k=request.top_k,
            customer=request.customer,
            form=request.form,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
    print("EDesc maintenance API service v3.1.0")
    print("=" * 50)
    print("API docs: http://localhost:8000/docs")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
