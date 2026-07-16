# -*- coding: utf-8 -*-
"""Runtime configuration for the four supported API workflows."""

import logging
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)
logger.info("Logging configured with level: %s", LOG_LEVEL)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QDRANT_URL = "http://10.0.8.238:6333"
EMBEDDING_API_URL = "http://10.0.12.12:9997/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024
PARENT_COLLECTION = "products_tests"
CHILD_COLLECTION = "products_test_child"
DEFAULT_TOP_K = 10
DEFAULT_SCORE_THRESHOLD = 0.5
SPEC_INFERENCE_INDEX_PATH = os.getenv(
    "SPEC_INFERENCE_INDEX_PATH",
    os.path.join(BASE_DIR, "data", "spec_inference_index.json"),
)
SPEC_INFERENCE_RULES_PATH = os.getenv(
    "SPEC_INFERENCE_RULES_PATH",
    os.path.join(BASE_DIR, "data", "spec_inference_rules.json"),
)
RECOMMENDATION_INDEX_PATH = os.getenv(
    "RECOMMENDATION_INDEX_PATH",
    os.path.join(BASE_DIR, "data", "recommendation_index.json"),
)
RECOMMENDATION_MODE = os.getenv("RECOMMENDATION_MODE", "hybrid").lower()
RECOMMENDATION_PARENT_COLLECTION = os.getenv(
    "RECOMMENDATION_PARENT_COLLECTION",
    "recommendation_parent_v1",
)
RECOMMENDATION_CHILD_COLLECTION = os.getenv(
    "RECOMMENDATION_CHILD_COLLECTION",
    "recommendation_child_v1",
)
RECOMMENDATION_VECTOR_CANDIDATES = int(
    os.getenv("RECOMMENDATION_VECTOR_CANDIDATES", "300")
)
RERANKER_URL = os.getenv(
    "RERANKER_URL",
    "http://10.0.12.12:9997/v1/rerank",
)
RERANKER_TIMEOUT = float(os.getenv("RERANKER_TIMEOUT", "3"))
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "bge-reranker-v2-m3")
EDESC_DESIGN_MODE = os.getenv("EDESC_DESIGN_MODE", "off").lower()
EDESC_DICTIONARY_JSON_PATH = os.getenv(
    "EDESC_DICTIONARY_JSON_PATH",
    os.path.join(BASE_DIR, "data", "edesc_business_dictionary.json"),
)
EDESC_TEMPLATE_ALIAS = os.getenv(
    "EDESC_TEMPLATE_ALIAS",
    "edesc_templates_current",
)
EDESC_TEMPLATE_CANDIDATES = int(os.getenv("EDESC_TEMPLATE_CANDIDATES", "100"))
BY1_TEMPLATE_MODE = os.getenv("BY1_TEMPLATE_MODE", "off").lower()
BY1_TEMPLATE_INDEX_PATH = os.getenv(
    "BY1_TEMPLATE_INDEX_PATH",
    os.path.join(BASE_DIR, "data", "by1_template_index.json"),
)
BY1_TEMPLATE_COLLECTION = os.getenv("BY1_TEMPLATE_COLLECTION", "by1_templates_v1")
BY1_TEMPLATE_CANDIDATES = int(os.getenv("BY1_TEMPLATE_CANDIDATES", "100"))
