# 基于标准化描述模板的 by1 与规格联合推断设计

## 1. 背景与目标

当前系统已经具备历史精确匹配、BGE 向量召回、form_code 规则和规格推断能力，但历史英文描述存在缩写、词序、符号、尺寸写法和字段缺失等噪声。仅直接对原始描述做向量检索，会使表面写法差异影响召回；仅生成一个全局模板，又可能把不同产品结构或同一 by1 下的多个变体过早合并。

本设计的目标是：

1. 提升 `by1` 候选召回和 Top-5 准确率；
2. 同时输出可审计的规格推断结果；
3. 允许一个 `by1` 对应多个结构模板簇；
4. 让模板成为召回和重排证据，而不是不可解释的最终真值；
5. 在时间切分下避免模板、规格画像和规则的数据泄漏。

本设计不以替换 BGE-M3、自动改写所有历史描述或生成不存在的规格为目标。

## 2. 核心决策

### 2.1 先标准化，再聚类，但保留多视图

历史记录不压缩为单一字符串，而是同时保留：

- `raw_description`：原始描述，用于审计和最终证据；
- `structural_description`：用于 by1 推断，统一同义词、缩写、词序和格式，弱化或移除尺寸；
- `full_description`：用于规格推断，保留 DN、英寸、外径、压力、后缀和特殊尺寸信息；
- `attribute_evidence`：结构化属性及其来源、置信度和文本证据。

标准化只做可验证的归一化，不为缺失字段填充默认值。未知的阀座、阀板、材料或驱动必须保持 `unknown` 或缺失，不能把历史经验默认值当作当前描述中的事实。

### 2.2 模板簇以 `(by1, template_cluster)` 为粒度

聚类先按已知历史 `by1` 分组，再在同一个 `by1` 内对结构化描述聚类。一个 `by1` 可以拥有多个模板簇，例如：

```text
D71XLV99 / WAFER + EPDM + GEAR
D71XLV99 / GROOVED + EPDM + GEAR
```

不做全局无约束聚类，避免文字相似但 `by1` 不同的产品被合并。模板代表描述必须来自真实历史记录，不能由模型凭空生成。

### 2.3 模板负责结构，规格画像负责规格

模板簇描述产品结构和使用场景；规格画像描述该模板在不同 `form_code`、尺寸和历史条件下对应的规格分布。规格不作为模板簇的唯一划分依据，因此同一结构模板可以覆盖多个尺寸规格。

规格推断仍然依赖完整描述、尺寸解析、form_code 规则和历史映射。模板相似度不能单独生成非标准规格。

### 2.4 推断结果同时包含 by1 和规格

公共推断结果包含：

```json
{
  "by1_candidates": [],
  "inferred_spec": "D100",
  "spec_confidence": "high",
  "spec_confidence_score": 0.98,
  "spec_alternatives": [],
  "match_level": "template_form_size",
  "evidence": {}
}
```

低置信度时 `inferred_spec` 可以为 `null`，但仍返回排序后的规格候选和证据。

## 3. 数据模型

### 3.1 历史成员记录

每个聚合后的历史描述记录至少包含：

```text
point_id
raw_description
normalized_description
structural_description
full_description
by1
form_code
spec
parsed_size
family
body_material
connection
structure
seat_material
closure_material
actuation
pressure
certification
attribute_evidence
contract_date
support
```

每个属性的证据结构为：

```json
{
  "value": "EPDM",
  "source": "query | mature_rule | unknown",
  "confidence": 1.0,
  "evidence": "EPDM SEAT"
}
```

`mature_rule` 只能使用经过时间切分验证的稳定规则；它不能覆盖描述中已经明确出现的冲突字段。

### 3.2 模板簇记录

```text
template_id
by1
cluster_id
structural_signature
representative_description
representative_point_id
supported_form_codes
attribute_profile
spec_profile
support
member_count
cohesion
outlier_count
template_status
```

`structural_signature` 由产品族、连接、结构、阀座、阀板、驱动、压力和认证等已知字段组成，不包含尺寸作为唯一身份字段。

### 3.3 规格画像

```text
template_id
form_code
spec_distribution
size_to_spec_distribution
nonstandard_specs
support
date_min
date_max
```

规格画像保存历史分布，不把最高频规格强行视为所有输入的正确规格。对于非标准规格、后缀规格或历史例外，必须保留原始历史映射。

## 4. 构建流程

### 4.1 数据清洗与分类

先识别阀门、附件和备件。附件和备件保留原始记录，但不进入阀门模板簇。无法确认产品族的记录进入隔离集，并记录原因。

### 4.2 保真标准化

使用统一的词典、边界匹配、尺寸解析和属性抽取逻辑生成三种描述视图。标准化规则应具备版本号；每次模板构建记录词典版本、规则版本、输入时间范围和源数据哈希。

### 4.3 模板聚类

在每个 `by1` 内：

1. 先按已知结构属性生成确定性 signature 桶；
2. 对同一桶内的标准化描述使用归一化向量和余弦相似度聚类；
3. 低样本 `by1` 保留单模板并标记 `insufficient_sample`；
4. 选择真实成员作为 medoid；
5. 记录 cohesion、离群点和成员支持度；
6. 为 cluster id 做稳定、连续编号。

若属性证据冲突，优先保留多个模板候选或标记为冲突，不用聚类结果抹平冲突。聚类不使用规格或 form_code 作为语义特征，但它们可以作为模板解释和规格画像字段。

### 4.4 规格画像构建

对每个 `(by1, template_id, form_code)` 统计历史规格、解析尺寸和支持度，形成 `spec_distribution` 与 `size_to_spec_distribution`。form-code 前缀规则只有在训练窗口和验证窗口都满足成熟规则门槛后才能进入运行时规则表。

## 5. 在线联合推断

### 5.1 推断顺序

```text
输入 query + form_code + customer
    ↓
解析 composite query 与字段
    ↓
生成 structural_description、full_description 和属性证据
    ↓
精确历史匹配 description + form_code
    ↓
标准化描述精确匹配
    ↓
模板簇召回
    ↓
属性兼容性过滤和模板重排
    ↓
聚合为 by1 候选
    ↓
尺寸规则、规格画像和历史映射推断规格
    ↓
检查 by1 + template + form_code + spec 的历史兼容性
    ↓
返回联合结果与证据
```

精确历史匹配保持最高优先级。模板召回主要解决新写法、历史描述变体和低证据输入的候选覆盖问题。

### 5.2 by1 评分因素

候选 by1 分数应综合：

- 模板向量相似度；
- structural attribute 匹配比例；
- form_code 与模板的历史兼容性；
- customer 兼容性；
- 历史支持度；
- 最佳模板成员与原始描述的相似度；
- 候选之间的分数边际。

最终返回不同的 by1 候选，并保留命中的模板、代表描述、相似度和支持度。

### 5.3 规格推断因素

规格推断按以下证据顺序执行：

1. `description + customer + form_code` 历史分布；
2. `description + form_code` 历史分布；
3. 已验证的 `form_code + size → spec` 规则；
4. `description + customer` 或 description-only 历史分布；
5. 模板的规格画像和 `(by1, form_code, size, spec)` 历史兼容性；
6. 低置信度时返回 `null` 和 alternatives。

模板只能增强规格候选，不能绕过非标准规格保护，也不能在没有尺寸证据时凭模板默认生成规格。

### 5.4 兼容性约束

以下组合若历史中没有支持，应降低置信度：

```text
by1 + template_id + form_code + inferred_spec
```

若描述明确字段与模板冲突，应淘汰模板；若只是模板缺少该字段，不应视为冲突，而应降低匹配比例。

## 6. 评估与验收

### 6.1 对照实验

至少比较四个版本：

1. 原始描述 + 精确历史 + 向量召回；
2. 标准化描述 + 精确历史；
3. 标准化描述 + 模板簇召回；
4. 模板簇召回 + 原始描述重排 + 规格画像的联合方案。

### 6.2 时间切分与防泄漏

模板、代表描述、规格画像、成熟规则和置信度校准只能使用训练窗口数据。验证集用于调参，测试集只用于最终报告。

必须同时报告行加权和去重后的指标，并按已知/未知描述、已知/新 by1、有无 form_code、标准/非标准规格、阀门/附件/备件、高频/低频模板和尺寸是否明确进行分层。

### 6.3 核心指标

```text
by1 Top-1 / Top-5 accuracy
by1 candidate recall@50
by1 answer coverage
spec Top-1 accuracy
spec answered accuracy
by1 与 spec 同时正确的联合准确率
高置信度准确率
template purity
template cohesion
template coverage
spec consistency
```

模板方案只有在不降低规格准确率和覆盖率的前提下，才允许替换现有 by1 排序。若模板方案不能带来稳定收益，则保留为 shadow evidence。

## 7. 上线策略与失败处理

### 7.1 发布阶段

1. `off`：不加载模板推断服务；
2. `shadow`：计算并记录模板和规格结果，不改变 API 主结果；
3. `on`：只在通过验收门槛后加入模板增强结果。

运行时记录模板版本、词典版本、索引版本、召回来源、候选 margin、规格规则和延迟。

### 7.2 降级策略

- 模板索引不存在或加载失败：保留历史精确匹配和现有向量路径；
- 模板检索超时：返回原有 by1 候选；
- reranker 不可用：使用模板向量和结构化分数；
- 规格证据不足：`inferred_spec = null`，保留 alternatives；
- 描述被判定为附件或备件：不强行生成阀门模板。

## 8. 非目标

- 不自动覆盖或改写原始历史描述；
- 不把每个 by1 强制压缩成一个模板；
- 不用规格或 form_code 直接替代描述语义聚类；
- 不为未知材料、阀座、阀板或规格填充业务默认值；
- 不在没有时间切分验证的情况下宣称准确率提升；
- 不新增独立的推荐 API，继续扩展现有 `/edesc/search` 响应。

