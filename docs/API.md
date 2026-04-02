# 货描维护系统 API 文档

## 概述

货描维护系统提供 CLI 和 REST API 两种访问方式，用于管理基配品种(by1)的货物描述(EDesc)。

## CLI 接口

### 查询操作

#### `get <by1>`
查询指定 by1 的货描

```bash
python edesc_maintenance.py get D71X4
```

输出示例:
```json
{
  "by1": "D71X4",
  "parent_id": "abc123...",
  "productName": "D71X4",
  "EDesc": "Wafer Butterfly Valve, EPDM Seat...",
  "edesc_count": 1
}
```

#### `list [limit]`
列出所有 by1

```bash
python edesc_maintenance.py list 100
```

输出示例:
```
共 100 个基配品种:
  - D71X4: Wafer Butterfly Valve, EPDM Seat... (1条)
  - D71X5: Lug Butterfly Valve, NBR Seat... (2条)
```

#### `search "<text>"`
根据货描文本搜索 by1（向量搜索）

```bash
python edesc_maintenance.py search "Wafer Butterfly Valve"
```

输出示例:
```
查询: Wafer Butterfly Valve

[1] by1: D71X4
    相似度: 0.9234
    匹配片段: Wafer Butterfly Valve, EPDM Seat, DI Body...
```

### 智能导入操作

#### `preview <by1>`
预览前缀匹配的候选品种

```bash
python edesc_maintenance.py preview XD371X210
```

输出示例:
```
=== 与 XD371X210 前缀匹配的品种 ===
共找到 3 个候选

[1] XD371X208 [推荐]
    前缀匹配: 7位 (87.50%)
    货描引用数: 5
    货描预览: Wafer Butterfly Valve, Gear Operator...
```

#### `import <by1> [strategy]`
智能导入新 by1

```bash
# 使用默认策略 (most_references)
python edesc_maintenance.py import XD371X210

# 使用最高匹配度策略
python edesc_maintenance.py import XD371X210 highest_score

# 使用综合评分策略
python edesc_maintenance.py import XD371X210 combined
```

**策略说明:**
- `most_references`: 选择货描引用次数最多的候选（默认）
- `highest_score`: 选择前缀匹配度最高的候选
- `combined`: 综合评分 = 匹配度*0.4 + 标准化引用数*0.6

#### `batch-import <by1> <by2> ...`
批量智能导入

```bash
python edesc_maintenance.py batch-import XD371X210 XD371X211 XD371X212
```

### 增删改操作

#### `add <by1> "<edesc>"`
添加货描（自动去重）

```bash
python edesc_maintenance.py add D71X4 "New description text"
```

逻辑说明:
- 如果 by1 已存在: 检查货描是否重复，重复则跳过，不重复则追加
- 如果 by1 不存在: 创建新记录

#### `update <by1> "<edesc>" [--append]`
更新货描

```bash
# 替换模式
python edesc_maintenance.py update D71X4 "New description"

# 追加模式
python edesc_maintenance.py update D71X4 "Additional description" --append
```

#### `delete <by1>`
删除 by1 及其货描

```bash
python edesc_maintenance.py delete TEST001
```

---

## REST API 接口

### 启动服务

```bash
python api.py
```

服务启动后访问:
- API 文档: http://localhost:8000/docs
- 交互文档: http://localhost:8000/redoc

### 健康检查

#### `GET /health`
健康检查

```bash
curl http://localhost:8000/health
```

响应:
```json
{
  "status": "healthy",
  "parent_count": 100,
  "child_count": 500
}
```

### 查询接口

#### `GET /edesc/{by1}`
查询指定 by1 的货描

```bash
curl http://localhost:8000/edesc/D71X4
```

响应:
```json
{
  "by1": "D71X4",
  "parent_id": "abc123...",
  "productName": "D71X4",
  "EDesc": "Wafer Butterfly Valve...",
  "edesc_count": 1,
  "metadata": {}
}
```

#### `GET /edesc`
列出所有 by1

```bash
curl "http://localhost:8000/edesc?limit=100"
```

#### `POST /edesc/search`
根据货描文本搜索

```bash
curl -X POST http://localhost:8000/edesc/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Butterfly Valve", "top_k": 10}'
```

#### `GET /edesc/prefix-search/{by1}`
前缀匹配搜索

```bash
curl "http://localhost:8000/edesc/prefix-search/XD371X?top_k=10"
```

### 智能导入接口

#### `GET /edesc/preview/{by1}`
预览导入候选

```bash
curl "http://localhost:8000/edesc/preview/XD371X210?top_k=5"
```

#### `POST /edesc/import`
智能导入

```bash
curl -X POST http://localhost:8000/edesc/import \
  -H "Content-Type: application/json" \
  -d '{"by1": "XD371X210", "strategy": "most_references", "top_k": 5}'
```

#### `POST /edesc/batch-import`
批量导入

```bash
curl -X POST http://localhost:8000/edesc/batch-import \
  -H "Content-Type: application/json" \
  -d '{"by1_list": ["XD371X210", "XD371X211"], "strategy": "most_references"}'
```

### 增删改接口

#### `POST /edesc/add`
添加货描

```bash
curl -X POST http://localhost:8000/edesc/add \
  -H "Content-Type: application/json" \
  -d '{"by1": "D71X4", "edesc": "New description"}'
```

#### `PUT /edesc/update`
更新货描

```bash
curl -X PUT http://localhost:8000/edesc/update \
  -H "Content-Type: application/json" \
  -d '{"by1": "D71X4", "edesc": "Updated description", "append": false}'
```

#### `DELETE /edesc/{by1}`
删除 by1

```bash
curl -X DELETE http://localhost:8000/edesc/D71X4
```

### 导出接口

#### `GET /edesc/export/json`
导出 JSON

```bash
curl http://localhost:8000/edesc/export/json
```

#### `GET /edesc/export/csv`
导出 CSV

```bash
curl http://localhost:8000/edesc/export/csv
```

### 统计接口

#### `GET /stats`
获取统计信息

```bash
curl http://localhost:8000/stats
```

---

## 项目结构

```
F:\zhhm_bge_db\
├── config.py                    # 配置
├── main.py                      # 主入口CLI
├── api.py                       # FastAPI接口
├── edesc_maintenance.py         # CLI兼容层
│
├── service/
│   └── edesc_service.py         # 业务逻辑层
│
├── repo/
│   └── qdrant_repo.py           # 数据访问层
│
├── embedder/
│   ├── base.py                  # Embedder接口
│   └── bge_embedder.py          # BGE-M3实现
│
├── strategy/
│   └── import_strategy.py       # 导入策略
│
├── utils/
│   ├── text_utils.py            # 文本处理
│   └── id_utils.py              # ID生成
│
├── qdrant_store.py              # 向量存储
├── embedding_client.py          # 兼容层
├── data_processor.py            # 数据处理
│
└── tests/                       # 单元测试
    ├── test_utils.py
    ├── test_strategy.py
    └── test_service.py
```

## 环境变量

- `LOG_LEVEL`: 日志级别 (DEBUG, INFO, WARNING, ERROR)，默认 INFO

```bash
export LOG_LEVEL=DEBUG
python api.py
```

## 运行测试

```bash
python -m pytest tests/ -v
```
