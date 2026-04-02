# -*- coding: utf-8 -*-
"""
货描维护 FastAPI 接口
提供 REST API 访问货描维护功能

重构说明：
- API 层只做参数解析和响应格式化
- 业务逻辑集中在 service/edesc_service.py
"""

from fastapi import FastAPI, HTTPException, Query, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import uvicorn
from datetime import datetime
import logging

# 配置日志
from config import LOG_LEVEL

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI(
    title="货描维护接口", description="基配品种by1货物描述维护API", version="2.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service 单例
_service = None
_variety_type_service = None


def get_service():
    """获取 Service 实例（延迟初始化）"""
    global _service
    if _service is None:
        logger.info("Initializing EDescService...")
        from qdrant_store import QdrantVectorStore
        from embedder import BGEEmbedder
        from repo import QdrantRepo
        from service import EDescService
        from config import CHUNK_SIZE, CHUNK_OVERLAP

        store = QdrantVectorStore()
        store.init_collections()
        embedder = BGEEmbedder()
        repo = QdrantRepo(
            client=store.client,
            parent_collection=store.parent_collection,
            child_collection=store.child_collection,
        )
        _service = EDescService(
            store=store,
            embedder=embedder,
            repo=repo,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        logger.info("EDescService initialized")
    return _service


def get_variety_type_service():
    """获取 VarietyTypeService 实例（延迟初始化）"""
    global _variety_type_service
    if _variety_type_service is None:
        logger.info("Initializing VarietyTypeService...")
        from service import VarietyTypeService

        _variety_type_service = VarietyTypeService()
        logger.info("VarietyTypeService initialized")
    return _variety_type_service


# ==================== 请求模型 ====================


class AddEDescRequest(BaseModel):
    """添加货描请求"""

    by1: str
    edesc: str
    metadata: Optional[dict] = None


class UpdateEDescRequest(BaseModel):
    """更新货描请求"""

    by1: str
    edesc: str
    append: bool = False
    metadata: Optional[dict] = None


class ImportRequest(BaseModel):
    """智能导入请求"""

    by1: str
    strategy: str = "most_references"
    top_k: int = 5


class BatchImportRequest(BaseModel):
    """批量导入请求"""

    by1_list: List[str]
    strategy: str = "most_references"


class SearchRequest(BaseModel):
    """搜索请求"""

    query: str
    top_k: int = 10


class BatchSearchRequest(BaseModel):
    """批量搜索请求"""

    queries: List[str]
    top_k: int = 10
    score_threshold: Optional[float] = None
    max_concurrent: int = 10


class BatchSearchResponse(BaseModel):
    """批量搜索响应"""

    total_queries: int
    elapsed_seconds: float
    results: List[dict]


# ==================== 阀门型号解析请求模型 ====================


class ValveParseRequest(BaseModel):
    """阀门型号解析请求"""

    model: str = Field(..., description="原始品种字符串")


class ValveBatchParseRequest(BaseModel):
    """批量解析请求"""

    models: List[str] = Field(..., description="原始品种字符串列表")


class ValveParseResult(BaseModel):
    """解析结果"""

    品种: str
    驱动: Optional[str] = None
    连接: Optional[str] = None
    结构: Optional[str] = None
    密封材质: Optional[str] = None
    标准化品种: str = Field(..., description="标准化后的品种（已截断到材质位）")


class ValveBatchParseItem(BaseModel):
    """批量解析单项"""

    input: str
    ok: bool
    result: Optional[ValveParseResult] = None
    error: Optional[str] = None


class ValveBatchParseResponse(BaseModel):
    """批量解析响应"""

    items: List[ValveBatchParseItem]


# ==================== 健康检查 ====================


@app.get("/", tags=["系统"])
async def root():
    """API根路径"""
    return {"message": "货描维护接口", "version": "2.0.0", "docs": "/docs"}


@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查"""
    try:
        service = get_service()
        stats = service.get_stats()
        return {
            "status": "healthy",
            "parent_count": stats["parent_collection"]["points_count"],
            "child_count": stats["child_collection"]["points_count"],
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


# ==================== 查询接口 ====================


@app.get("/edesc/{by1}", tags=["查询操作"])
async def get_edesc(by1: str):
    """
    查询指定by1的货描

    - **by1**: 基配品种编码
    """
    service = get_service()
    result = service.get_by1(by1)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到 by1={by1}")
    return result


@app.get("/edesc", tags=["查询操作"])
async def list_edesc(
    limit: int = Query(default=100, ge=1, le=10000), by1: Optional[str] = None
):
    """
    列出所有by1及货描摘要

    - **limit**: 返回数量限制
    - **by1**: 可选，模糊搜索by1
    """
    service = get_service()
    results = service.list_by1(limit=limit)

    if by1:
        results = [r for r in results if by1.lower() in r["by1"].lower()]

    return {"total": len(results), "data": results}


@app.post("/edesc/search", tags=["查询操作"])
async def search_edesc(request: SearchRequest):
    """
    根据货描文本搜索匹配的by1 (向量搜索)

    - **query**: 货描查询文本
    - **top_k**: 返回结果数量
    """
    service = get_service()
    results = service.search_by_edesc(request.query, top_k=request.top_k)
    return {"query": request.query, "total": len(results), "data": results}


@app.post("/edesc/batch-search", tags=["查询操作"])
async def batch_search_edesc(request: BatchSearchRequest):
    """
    批量搜索 - 高并发支持

    一次请求处理多个查询，支持并行处理

    - **queries**: 货描查询文本列表
    - **top_k**: 每个查询返回结果数量
    - **score_threshold**: 相似度阈值（可选，暂不支持）
    - **max_concurrent**: 最大并发数

    示例请求:
    ```json
    {
        "queries": ["Butterfly Valve", "Gate Valve", "Check Valve"],
        "top_k": 5,
        "max_concurrent": 10
    }
    ```
    """
    import asyncio
    from datetime import datetime
    from concurrent.futures import ThreadPoolExecutor

    start_time = datetime.now()

    try:
        # 使用线程池并行处理
        service = get_service()

        def search_single(query: str):
            return service.search_by_edesc(query, top_k=request.top_k)

        # 并行执行所有查询
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=request.max_concurrent) as executor:
            futures = [
                loop.run_in_executor(executor, search_single, query)
                for query in request.queries
            ]
            results = await asyncio.gather(*futures)

        elapsed = (datetime.now() - start_time).total_seconds()

        return {
            "total_queries": len(request.queries),
            "elapsed_seconds": round(elapsed, 3),
            "queries_per_second": (
                round(len(request.queries) / elapsed, 2) if elapsed > 0 else 0
            ),
            "results": [
                {"query": query, "total": len(result), "data": result}
                for query, result in zip(request.queries, results)
            ],
        }

    except Exception as e:
        logger.error(f"Batch search failed: {e}")
        raise HTTPException(status_code=500, detail=f"批量搜索失败: {str(e)}")


@app.get("/edesc/prefix-search/{by1}", tags=["查询操作"])
async def prefix_search_edesc(by1: str, top_k: int = Query(default=10, ge=1, le=50)):
    """
    根据by1前缀匹配搜索相似的品种

    前几位编码越相同，相似度越高

    - **by1**: 基配品种编码
    - **top_k**: 返回结果数量
    """
    service = get_service()
    results = service.search_by_prefix(by1, top_k=top_k)
    return {"query_by1": by1, "total": len(results), "data": results}


# ==================== 智能导入接口 ====================


@app.get("/edesc/preview/{by1}", tags=["智能导入"])
async def preview_similar(by1: str, top_k: int = Query(default=5, ge=1, le=20)):
    """
    预览与by1前缀匹配的品种及其货描

    基于by1编码前缀匹配，前几位越相同相似度越高

    - **by1**: 新研发的基配品种编码
    - **top_k**: 返回候选数量
    """
    service = get_service()
    result = service.preview_import(by1, top_k=top_k)
    return result


@app.post("/edesc/import", tags=["智能导入"])
async def import_edesc(request: ImportRequest):
    """
    智能导入新by1 (前缀匹配)

    根据by1前缀匹配找到相似品种，选择最标准的货描并导入

    匹配逻辑：前几位编码越相同，相似度越高

    - **by1**: 新研发的基配品种编码
    - **strategy**: 选择策略 (most_references/highest_score/combined)
    - **top_k**: 搜索候选数量
    """
    service = get_service()
    result = service.import_by1(
        new_by1=request.by1, top_k=request.top_k, strategy=request.strategy
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.post("/edesc/batch-import", tags=["智能导入"])
async def batch_import_edesc(request: BatchImportRequest):
    """
    批量智能导入

    - **by1_list**: 新品种编码列表
    - **strategy**: 选择策略
    """
    service = get_service()
    return service.batch_import(request.by1_list, strategy=request.strategy)


# ==================== 增删改接口 ====================


@app.post("/edesc/add", tags=["增删改操作"])
async def add_edesc(request: AddEDescRequest):
    """
    添加货描到指定by1

    逻辑：
    1. 如果by1已存在：
       - 检查EDesc是否重复
       - 重复则不添加，返回提示
       - 不重复则追加到现有货描
    2. 如果by1不存在：
       - 创建新记录，metadata中包含by1

    - **by1**: 基配品种编码
    - **edesc**: 货物描述
    - **metadata**: 可选元数据
    """
    service = get_service()
    result = service.add_edesc(
        by1=request.by1, edesc=request.edesc, metadata=request.metadata
    )
    # 重复不算错误，正常返回
    if not result["success"] and not result.get("is_duplicate"):
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.put("/edesc/update", tags=["增删改操作"])
async def update_edesc(request: UpdateEDescRequest):
    """
    更新by1的货描

    - **by1**: 基配品种编码
    - **edesc**: 新货物描述
    - **append**: 是否追加模式
    - **metadata**: 可选元数据
    """
    service = get_service()
    result = service.update_edesc(
        by1=request.by1,
        new_edesc=request.edesc,
        append=request.append,
        metadata=request.metadata,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@app.delete("/edesc/{by1}", tags=["增删改操作"])
async def delete_edesc(by1: str):
    """
    删除by1及其货描

    - **by1**: 基配品种编码
    """
    service = get_service()
    result = service.delete_by1(by1)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result


# ==================== 导出接口 ====================


@app.get("/edesc/export/json", tags=["导出操作"])
async def export_json():
    """导出向量库数据为JSON格式"""
    service = get_service()
    data = service.export_all()

    return {
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_count": len(data),
        "data": data,
    }


@app.get("/edesc/export/csv", tags=["导出操作"])
async def export_csv():
    """导出向量库数据为CSV格式（返回JSON，可下载为CSV）"""
    service = get_service()
    data = service.export_all()

    # 简化数据用于 CSV
    csv_data = [
        {
            "by1": d["by1"],
            "edesc_count": d["edesc_count"],
            "source_by1": d["source_by1"],
            "source_score": d["source_score"],
            "import_strategy": d["import_strategy"],
            "EDesc": d["EDesc"],
        }
        for d in data
    ]

    return {
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_count": len(csv_data),
        "data": csv_data,
    }


# ==================== 统计接口 ====================


@app.get("/stats", tags=["系统"])
async def get_stats():
    """获取向量库统计信息"""
    service = get_service()
    stats = service.get_stats()
    return {
        "parent_collection": {
            "name": stats["parent_collection"]["name"],
            "count": stats["parent_collection"]["points_count"],
        },
        "child_collection": {
            "name": stats["child_collection"]["name"],
            "count": stats["child_collection"]["points_count"],
        },
    }


# ==================== 阀门型号解析接口 ====================


@app.post("/valve/parse", tags=["阀门型号解析"])
async def parse_valve_model(request: ValveParseRequest):
    """
    解析单个阀门型号

    先标准化（截断到材质位Pos6），再按前几位推断返回：
    - 品种
    - 驱动方式
    - 连接形式
    - 结构形式
    - 密封材质
    - 标准化品种

    - **model**: 原始品种字符串（如 Z941H-16C DN50）
    """
    service = get_variety_type_service()
    try:
        result = service.parse_with_normalized(request.model)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/valve/parse/batch", tags=["阀门型号解析"], response_model=ValveBatchParseResponse
)
async def parse_valve_models_batch(request: ValveBatchParseRequest):
    """
    批量解析阀门型号

    一次请求处理多个阀门型号解析

    - **models**: 原始品种字符串列表

    示例请求:
    ```json
    {
        "models": ["Z941H-16C", "D371F-16", "H44H-25"]
    }
    ```
    """
    service = get_variety_type_service()
    items = service.batch_parse(request.models)
    return ValveBatchParseResponse(items=items)


@app.post("/valve/normalize", tags=["阀门型号解析"])
async def normalize_valve_model(request: ValveParseRequest):
    """
    标准化阀门型号

    清洗并截断到材质位（Pos6）

    - **model**: 原始品种字符串
    """
    service = get_variety_type_service()
    try:
        normalized = service.normalize_model(request.model)
        return {"input": request.model, "normalized": normalized}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 启动服务 ====================

if __name__ == "__main__":
    print("=" * 50)
    print("货描维护 API 服务 v2.0.0")
    print("=" * 50)
    print("API文档: http://localhost:8000/docs")
    print("交互文档: http://localhost:8000/redoc")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8000)
