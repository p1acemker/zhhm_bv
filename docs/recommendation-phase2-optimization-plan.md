# 推荐系统 Phase 2/3 优化方案

## 1. 当前状态

Phase 0/1 已完成，现有 `POST /edesc/search` 执行顺序为：

1. 使用本地历史索引匹配 `英文描述 + form_code + customer`。
2. 返回 by1 Top-5，并同时推断规格。
3. 历史索引没有 by1 候选时，回退到现有 BGE/Qdrant 搜索。

当前历史索引包含 24,236 行订单、3,360 条聚合记录、384 个 by1、
90 个 form_code 和 14 条成熟规格规则。

Phase 2A 已实现：

- 未知阀座/阀板不再默认补为 EPDM/DI DISC。
- 已生成去尺寸的 `semantic_description`。
- 已建立 `recommendation_parent_v1`（384 点）和
  `recommendation_child_v1`（3,360 点）。
- `/edesc/search` 的历史未命中请求已接入 `vector_full_index`。
- 默认 child candidate pool 根据盲测从 100 调整为 300。

时间安全向量盲测结果：

| 指标 | 结果 |
| --- | ---: |
| 全部订单向量 Top-5 | 97.47% |
| 全部订单 recall@50 | 98.46% |
| 已知标签向量 Top-5 | 98.85% |
| 已知标签 recall@50 | 99.86% |
| 历史未命中且标签已知的 recall@50 | 95.83% |

盲测中有 31 行 by1 在训练期从未出现；这些冷启动标签不计入
known-label recall@50，但必须单独报告覆盖率。

时间盲测基线：

| 指标 | 按行结果 | 去重结果 |
| --- | ---: | ---: |
| by1 Top-5 总体准确率 | 93.27% | 92.97% |
| by1 回答覆盖率 | 95.84% | 95.37% |
| by1 已回答准确率 | 97.31% | 97.49% |
| 规格 Top-1 总体准确率 | 93.90% | 93.13% |
| 规格回答覆盖率 | 94.49% | 93.83% |
| 规格已回答准确率 | 99.38% | 99.26% |

现有向量回退仍使用 `products_tests/products_test_child`，只包含 61 个
父级 by1 和 1,489 条描述。下一阶段的主要目标不是替换 BGE-M3，而是让
向量层覆盖完整标签，并对低置信度候选进行 form-aware 重排。

## 2. Phase 2 目标

在不新增 API、不改变高置信度历史结果的前提下：

- 将 by1 Top-5 总体准确率提高到至少 95%。
- 将 by1 覆盖率提高到至少 98%。
- 将规格 Top-1 总体准确率提高到至少 95%。
- 将规格覆盖率提高到至少 97%。
- 对 embedding、Qdrant 或 reranker 故障提供确定性降级。
- 所有新权重和阈值只能使用验证集调参，盲测集只用于最终验收。

## 3. 不变约束

- 继续使用 `POST /edesc/search`，不增加 `/recommend`。
- `form_code` 与旧 `form/by1` 保持独立语义。
- 精确历史高置信度结果优先，不进入向量重排。
- `form_code` 不能单独产生 by1 或规格结论。
- 非标准规格不能由简单的 `prefix + size` 规则生成。
- 客户名只保存哈希，不进入明文向量 payload。

## 4. 目标检索流程

```text
请求
  -> 规范化描述、form_code、customer
  -> 精确历史匹配
       -> 高置信度：直接返回
       -> 无匹配/低置信度：进入混合召回
  -> BGE-M3 全量候选召回（child top 300）
  -> 按 by1 聚合为候选 top 50
  -> form/customer/属性先验重排
  -> bge-reranker-v2-m3 精排 top 20
  -> 置信度校准与 Top-5 输出
  -> 联合规格推断
  -> 低置信度时返回候选或 null
```

### 4.1 进入向量层的条件

满足任一条件才调用 BGE/Qdrant：

- 没有精确 `description + form_code` 记录。
- by1 第一候选历史占比低于 0.70。
- 第一、第二候选差值低于 0.15。
- 历史支持少于 2 行。
- 规格候选冲突且无法由成熟规则解决。

阈值先作为初始值，必须通过验证集网格搜索和置信度校准后固化。

## 5. 全量向量索引

### 5.1 新集合

使用版本化集合，不复用测试集合：

```text
recommendation_parent_v1
recommendation_child_v1
```

完成验证后使用 Qdrant alias 切换，保留旧版本用于快速回滚。

### 5.2 Parent payload

```text
by1
description_count
form_codes
specifications
material_classes
date_min/date_max
index_version
```

### 5.3 Child payload

每条聚合历史描述作为一个 child：

```text
parent_id
by1
raw_description
normalized_description
semantic_description
form_code
specification
spec_prefix
spec_size
material
surface
support
date_min/date_max
customer_hashes
```

### 5.4 双描述表示

为同一记录保留两个文本版本：

- `semantic_description`：去掉规格尺寸，用于 by1 召回，避免 DN 差异主导相似度。
- `normalized_description`：保留尺寸、压力和型号，用于 reranker 与规格判断。

当前标准化器在缺少证据时会默认补入 `EPDM` 和 `DI DISC`。Phase 2 必须
改为“未知则不写入”，避免制造不存在的材料相似性。

## 6. 候选召回与聚合

### 6.1 广召回

- BGE-M3 child 检索初始取 300 条；时间盲测表明 100 条不足以达到
  已知标签的 recall@50 目标。
- 聚合后至少保留 50 个不同 by1，用于计算 candidate recall@50。
- by1 聚合使用最高相似度、前 3 条描述均值和历史支持三个信号。
- 精确历史候选与向量候选取并集，不能被向量层删除。

### 6.2 结构化重排特征

候选特征包括：

- BGE 相似度和命中描述数量。
- `P(by1 | form_code)`，使用平滑后的训练期统计。
- customer/by1 历史兼容度，仅作为弱信号。
- 连接方式、阀门类型、阀座、阀板、驱动、压力和认证匹配。
- 描述支持量、最近订单时间和候选稳定性。
- 规格尺寸是否与描述中的 DN/mm/英寸一致。

`form_code` 先验只能调整已有候选排序，不能凭空创建候选。

### 6.3 初始融合分数

第一版使用可解释加权分数，权重在验证集调整：

```text
0.45 * reranker_score
+ 0.25 * vector_score
+ 0.15 * form_compatibility
+ 0.05 * attribute_compatibility
+ 0.05 * customer_compatibility
+ 0.05 * support_recency
```

若 reranker 服务不可用，则重新归一化其余特征并继续返回结果。

## 7. Reranker 接入

使用现有 `bge-reranker-v2-m3` 服务，只精排聚合后的前 20 个 by1：

- query：原始描述 + 独立 form_code。
- document：候选 by1 最相关的 1～3 条完整历史描述。
- 同一 by1 取最高 reranker 分数，并保留对应证据描述。
- 每次请求的 reranker 文档数量设置硬上限，避免长尾延迟。
- 失败、超时或返回数量不一致时自动降级到结构化重排。

## 8. 规格联合推断

保持当前高精度顺序：

1. 精确 `description + form_code + customer` 历史。
2. 精确 `description + form_code` 历史。
3. 14 条成熟 form_code 规则 + 尺寸解析。
4. 精确 description 历史。
5. by1 Top-5 候选对应的 `(by1, form_code, size)` 历史分布。
6. 向量最近描述的规格分布。

新增约束：

- 标准规格必须满足前缀、尺寸和候选 by1 历史兼容性。
- 沟槽、CTS、英寸/mm 冲突继续使用现有成熟尺寸规则。
- `N89K10`、`N125X1220` 等非标准规格只允许历史检索，不允许生成。
- by1 候选分歧较大时，规格置信度不得标记为 high。

## 9. 置信度校准

使用验证集训练一个轻量校准器，不需要微调 BGE：

```text
exact_match
historical_support
top1_score
top1_top2_margin
reranker_score
form_compatibility
attribute_match_count
size_consistency
candidate_entropy
```

输出 `high / medium / low`：

- high：目标准确率至少 99%。
- medium：可返回结果，但必须包含 alternatives 和证据。
- low：规格返回 null；by1 可保留候选列表但标记低置信度。

校准器参数保存为版本化 JSON，不在运行时代码中散落魔法数字。

## 10. 代码改动建议

### 新增

```text
service/candidate_retriever.py
service/candidate_reranker.py
service/confidence_calibrator.py
tools/build_recommendation_vectors.py
tools/evaluate_hybrid_recommendation.py
data/recommendation_calibration.json
```

### 修改

```text
service/recommendation.py
  - 保留精确历史逻辑
  - 注入 retriever/reranker/calibrator
  - 增加混合候选合并与降级路径

repo/qdrant_repo.py
  - 支持固定 child candidate pool
  - 返回 child payload 和 parent 聚合证据
  - 不在 repo 内决定最终业务分数

scripts/edesc_standardizer.py
  - 未知属性不再默认填 EPDM/DI DISC
  - 新增不含尺寸的 semantic_description

config.py
  - 增加版本化集合、reranker URL、超时和模式开关

api.py
  - 路径和请求体不变
  - response 增加 model_version、candidate_margin、degraded
```

## 11. 运行模式与降级

增加环境变量：

```text
RECOMMENDATION_MODE=historical|hybrid|shadow
RECOMMENDATION_PARENT_COLLECTION=recommendation_parent_v1
RECOMMENDATION_CHILD_COLLECTION=recommendation_child_v1
RECOMMENDATION_VECTOR_CANDIDATES=300
RECOMMENDATION_RERANK_CANDIDATES=20
RECOMMENDATION_RERANK_TIMEOUT=3
```

降级顺序：

```text
historical exact
  -> vector + reranker
  -> vector + structured rerank
  -> historical candidates/rules only
  -> null/empty candidates
```

任何外部服务故障都不能覆盖已有的高置信度历史结果。

## 12. 回测设计

固定三段时间切分：

- train：2024-04-28 之前。
- validation：2024-04-28 至 2024-08-31。
- holdout：2024-09-01 之后。

同时报告：

- 逐行指标。
- 按 `订单号 + 产品编码 + 英文描述` 去重指标。
- 已见/未见英文描述。
- 高频/低频/新 by1。
- 各 form_code。
- 标准/非标准规格。
- historical/vector/reranker/degraded 各阶段指标。

调参时禁止查看 holdout 分桶结果。

## 13. Phase 2 验收门槛

| 指标 | 当前基线 | Phase 2 门槛 |
| --- | ---: | ---: |
| candidate recall@50（已知标签） | 99.86% | >= 99% |
| by1 Top-5 总体准确率 | 93.27% | >= 95% |
| by1 Top-5 去重准确率 | 92.97% | >= 94.5% |
| by1 回答覆盖率 | 95.84% | >= 98% |
| by1 已回答准确率 | 97.31% | >= 97% |
| 规格 Top-1 总体准确率 | 93.90% | >= 95% |
| 规格 Top-1 去重准确率 | 93.13% | >= 94% |
| 规格回答覆盖率 | 94.49% | >= 97% |
| 规格已回答准确率 | 99.38% | >= 98.5% |
| high 规格准确率 | 未单列 | >= 99% |

不得出现以下回归：

- 精确历史命中的 by1 Top-5 下降。
- 当前 14 条成熟规格规则出现已知冲突。
- 外部服务故障导致 `/edesc/search` 返回 5xx。

## 14. 性能与可观测性

性能门槛：

- 精确历史路径 P95 < 100 ms。
- hybrid 路径 P95 < 1.5 s。
- reranker 超时 3 s 后必须降级。
- API 错误率 < 1%。

记录以下指标：

```text
request_count
historical_hit_rate
vector_fallback_rate
reranker_success_rate
degraded_rate
empty_result_rate
by1_candidate_margin
spec_confidence_distribution
embedding_latency
qdrant_latency
reranker_latency
model_version/index_version
```

日志中不记录客户明文和完整原始订单号。

## 15. Phase 3 影子发布

1. `historical` 模式作为生产基线。
2. `shadow` 模式并行计算 hybrid，但仍返回 historical 结果。
3. 比较至少一周的候选变化、延迟和确认标签。
4. 达到离线门槛且线上无明显回归后切换到 `hybrid`。
5. 使用 Qdrant alias 和环境变量支持分钟级回滚。

## 16. 实施顺序

### 2A：索引与召回（已完成）

- 修正标准化器的未知属性默认值。
- 生成双描述表示。
- 构建全量版本化 Qdrant 集合。
- 建立 candidate recall@50 基准。

### 2B：结构化重排

- 加入 form、属性、支持量和时间特征。
- 在 validation 上确定初始权重。
- 保证精确历史候选不丢失。

### 2C：Reranker 与规格联合

- 接入 reranker top 20。
- 加入 by1/spec 联合约束。
- 完成置信度校准。

### 3：影子发布与切换

- 部署 shadow 模式。
- 观察一周并出对比报告。
- 满足门槛后切换 alias 和运行模式。

建议下一次实现从 2A 开始，先交付可重复构建的全量向量索引和
candidate recall@50 回测；只有召回达到 99% 后，再投入 reranker 调权。
