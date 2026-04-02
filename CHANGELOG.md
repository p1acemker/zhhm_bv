# 更新日志

## [2.0.0] - 2026-03-05

### 重构说明

本次重构实现了分层架构，使代码更清晰、可维护、可测试，同时保持了 CLI 和 API 的对外行为不变。

### 架构变更

#### 新增模块

- **`service/edesc_service.py`**: 业务逻辑层，封装所有业务逻辑
- **`repo/qdrant_repo.py`**: 数据访问层，封装 Qdrant 操作
- **`embedder/base.py`**: Embedder 抽象基类
- **`embedder/bge_embedder.py`**: BGE-M3 Embedder 实现
- **`strategy/import_strategy.py`**: 导入策略模块（most_references/highest_score/combined）
- **`utils/text_utils.py`**: 文本处理工具（分割/去重/清洗）
- **`utils/id_utils.py`**: ID 生成工具

#### 修改文件

- **`api.py`**: 重构为只做参数解析和响应格式化，业务逻辑委托给 Service
- **`edesc_maintenance.py`**: 重构为兼容层，包装 Service 保持原有接口
- **`config.py`**: 添加日志配置，支持 LOG_LEVEL 环境变量
- **`qdrant_store.py`**: 使用 utils 模块的 ID 生成函数，添加 embedding 维度校验

#### 保留文件（兼容）

- **`embedding_client.py`**: 保留作为兼容层
- **`data_processor.py`**: 保留数据处理功能
- **`main.py`**: 保留原有导入功能

### 新增功能

1. **日志系统**
   - 支持 `LOG_LEVEL` 环境变量
   - 替换 print 为 logging

2. **Embedding 维度校验**
   - 在 `qdrant_store.py` 和 `BGEEmbedder` 中添加维度校验
   - 维度不匹配时抛出明确异常

3. **导入策略模块化**
   - `most_references`: 选择引用数最多的
   - `highest_score`: 选择匹配度最高的
   - `combined`: 综合评分 (score*0.4 + count/max_count*0.6)

### 测试覆盖

- **`tests/test_utils.py`**: 文本工具和 ID 生成测试
- **`tests/test_strategy.py`**: 导入策略测试
- **`tests/test_service.py`**: 业务逻辑层测试（使用 Mock）

### 文档

- **`docs/API.md`**: CLI 和 REST API 完整文档
- **`scripts/demo_import_and_search.py`**: 可运行的演示脚本

### 迁移指南

#### 使用 Service 层（推荐）

```python
from qdrant_store import QdrantVectorStore
from embedder import BGEEmbedder
from repo import QdrantRepo
from service import EDescService

store = QdrantVectorStore()
store.init_collections()
embedder = BGEEmbedder()
repo = QdrantRepo(store.client, store.parent_collection, store.child_collection)
service = EDescService(store, embedder, repo)

# 使用 Service
result = service.add_edesc("D71X4", "Test description")
```

#### 使用兼容层（保持原有代码不变）

```python
from edesc_maintenance import EDescMaintenance

maintenance = EDescMaintenance()
result = maintenance.add_edesc_for_by1("D71X4", "Test description")
```

### 验证清单

- [x] CLI 命令都能运行（同样输出结构/语义）
- [x] FastAPI /docs 可打开
- [x] 示例 curl 能跑
- [x] demo 脚本能跑通导入与搜索
- [x] tests 通过
