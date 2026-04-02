# -*- coding: utf-8 -*-
"""
配置文件 - Qdrant 父子分段检索系统
"""

import logging
import os

# ==================== 日志配置 ====================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# 配置根日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)
logger.info(f"Logging configured with level: {LOG_LEVEL}")

# ==================== Qdrant 配置 ====================
QDRANT_URL = "http://10.0.8.238:6333"

# ==================== Embedding API 配置 ====================
EMBEDDING_API_URL = "http://10.0.12.12:9997/v1/embeddings"
EMBEDDING_MODEL = "bge-m3"
EMBEDDING_DIM = 1024

# ==================== 集合名称配置 ====================
PARENT_COLLECTION = "products_parent"   # 父集合：存储完整产品信息
CHILD_COLLECTION = "products_child"     # 子集合：存储分段向量

# ==================== 分段配置 ====================
CHUNK_SIZE = 500          # 每段文本长度
CHUNK_OVERLAP = 50        # 段间重叠长度

# ==================== 检索配置 ====================
DEFAULT_TOP_K = 10        # 默认返回结果数
DEFAULT_SCORE_THRESHOLD = 0.5  # 默认相似度阈值
