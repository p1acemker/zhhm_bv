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

QDRANT_URL = "http://10.0.8.238:6333"
EMBEDDING_API_URL = "http://10.0.12.12:9997/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024
PARENT_COLLECTION = "products_tests"
CHILD_COLLECTION = "products_test_child"
DEFAULT_TOP_K = 10
DEFAULT_SCORE_THRESHOLD = 0.5
