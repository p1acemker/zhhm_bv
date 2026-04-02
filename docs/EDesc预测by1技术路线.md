# EDesc 预测 by1 技术路线

## 1. 问题定义

**目标**: 输入蝶阀产品的英文描述（EDesc），自动预测其产品编码（by1）。

**本质**: by1 编码遵循《产品命名规则.md》的 5 位编码体系，是由 EDesc 中的多个维度特征组合而成的结构化编码。因此这不是一个黑盒分类问题，而是一个**基于规则的编码组装问题** + **少量需要 AI 辅助的特征抽取问题**。

### by1 编码结构

```
[X] D [Pos2] [Pos3] [Pos4] [Pos5] [变体后缀]
 │   │    │      │      │      │       │
 │   │    │      │      │      │       └─ L=凸耳, K=长颈, V=高位手柄, E=可锁定...
 │   │    │      │      │      └─ X=EPDM/NBR/Viton, F=PTFE, H=Cr13不锈钢
 │   │    │      │      └─ 1=中线垂直板, 2=双偏心, 3=三偏心
 │   │    │      └─ 7=对夹, 8=卡箍/沟槽, 4=法兰, 1=内螺纹
 │   │    └─ 省略(手动) 或 3=蜗轮
 │   └─ D=蝶阀
 └─ X=带信号接收器 (开关/监控/反馈信号)
```

---

## 2. 技术路线：规则引擎 + Top-10 候选预测

### 整体架构

```
EDesc 输入
    │
    ▼
┌──────────────────────┐
│  Stage 1: 文本预处理   │  统一大写、修正拼写、规范分隔符
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Stage 2: 特征抽取     │  从 EDesc 中抽取结构化特征
│  (规则 + 关键词匹配)    │  XD=信号接收器, 非消防认证
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────┐
│  Stage 3: 基础码变体 + 后缀展开 (Top-10) │
│  生成多个候选, 综合评分排序                │
│  · 基础码变体: XD↔D切换, Pos2伴随,       │
│    连接方式/操作方式替代                   │
│  · 后缀展开: 跨基础码共享, KNOWN_BY1补充   │
│  · 评分: 特征匹配分 + 频率分 + 置信度分   │
└──────────┬───────────────────────────┘
           │
           ▼
    Top-10 候选 [by1_1, by1_2, ..., by1_10]
    越靠前的越正确 (Top-1: 59.3%, Top-10: 90.4%)
```

---

## 3. 各阶段详细设计

### Stage 1: 文本预处理

```python
def preprocess(edesc: str) -> str:
    text = edesc.upper()
    # 拼写修正
    text = text.replace('ENCENTRIC', 'ECCENTRIC')
    text = text.replace('THEREADED', 'THREADED')
    text = text.replace('WAFER BUTTERF.V.', 'WAFER BFV')
    # 统一缩写
    text = text.replace('BUNA-N', 'NBR')
    text = text.replace('BUTTERFLY VALVE', 'BFV')
    text = text.replace('BUTTERFLY', 'BF')  # BFLY → BF
    # 清理
    text = re.sub(r'\s+', ' ', text).strip()
    return text
```

### Stage 2: 特征抽取（核心）

从预处理后的 EDesc 中抽取 8 个特征维度：

#### 2.1 信号接收器 (has_signal) — 决定 X 前缀

| 判定条件 | 值 |
|----------|-----|
| 含 `TAMPER SWITCH` / `W/SWITCHES` / `FLYING LEAD` / `NORMAL CLOSE` / `GEAR-OP` | `True` → 前缀加 `X` |
| 含 `BVW-`/`BVT-`/`GBV-`/`BFV-`/`D48638`/`FIG 215`/`FIG 216`/`SPF`/`NEW TURBINE` | `True` → 前缀加 `X` |
| 含 `FIRE RISER` | `True` → 前缀加 `X` (84%实际带信号,少数例外由Top-10覆盖) |
| 含 `BVG-`/`UL/FM` 等弱信号词 | 仅生成XD变体,不作为主预测 |

**注意**: XD 前缀表示**带信号接收器**（开关/监控/反馈信号），不是消防认证(FM/UL)。但在实际数据中，消防立管(FIRE RISER)系统强制要求信号监控，因此 FIRE RISER 是 X 前缀的强关联指标。少数 FIRE RISER 产品实际无 XD 前缀（约49条），由 Top-10 候选列表覆盖。

#### 2.2 连接方式 (connection) — 决定 Pos3

| 关键词匹配 | Pos3 值 | 说明 |
|------------|---------|------|
| `WAFER` (不含 LUG) | `7` | 对夹 |
| `LUG` + `WAFER` | `7` + 后缀 `L` | 凸耳对夹 |
| 仅 `LUG` | `7` + 后缀 `L` | 凸耳 |
| `GRVD` / `GROOVED` / `GRV` / `Grv` | `8` | 沟槽/卡箍 |
| `FLGD` / `FLANGE` / `Flange` | `4` | 法兰 |
| `THD` / `THREADED` / `BSP` | `3` | 螺纹 → 归入机械接头 |

**规则优先级**: `THREADED` > `FLANGED` > `GROOVED` > `LUG` > `WAFER`

#### 2.3 阀门结构 (valve_structure) — 决定 Pos4

| 关键词匹配 | Pos4 值 |
|------------|---------|
| 含 `DOUBLE ECCENTRIC` / `HIGH PERFORMANCE` | `2` |
| 含 `TRIPLE ECCENTRIC` / `3 ECCENTRIC` / `3 ENCENTRIC` | `3` |
| 无偏心标注（默认中线） | `1` |

#### 2.4 密封材料 (seat_material) — 决定 Pos5

| 关键词匹配 | Pos5 值 |
|------------|---------|
| `EPDM` | `X` (橡胶类) |
| `NBR` | `X` |
| `VTON` / `VITON` | `X` |
| `PTFE` / `TEFLON` | `F` (氟塑料) |
| `CS SEAT` (金属密封) | `H` (Cr13系) |
| `SS` + `SEAT` | `H` |
| 无密封标注 + DI 阀体 | `X` (默认EPDM) |

#### 2.5 操作方式 (actuation) — 决定 Pos2 和后缀

| 关键词匹配 | Pos2 | 后缀影响 |
|------------|------|---------|
| 含 `LEVER` (无 GEAR) | 省略 | — |
| 含 `GEAR` / `GEARBOX` / `TURBINE` | 省略(手动蜗轮) | 加 `V` 或特殊标记 |
| `NO DRIVE` / `WITHOUT GEAR BOX` / `BARE` | 省略 | — |
| `MOTORIZED` / `ACTUATOR` | 省略 | — |
| 无标注 | 省略 | 由连接方式推断 |

> **说明**: 当前数据中 Pos2 全部省略（手动/蜗轮驱动不标注），实际不需要预测 Pos2。

#### 2.6 阀板材料 (disc_material) — 影响后缀中的数字

| 关键词 | 后缀数字 |
|--------|---------|
| `SS316 DISC` / `316 DISC` | `4` |
| `SS304 DISC` / `304 DISC` | `4` |
| `DI+EPDM DISC` | `4` |
| `DI+NBR DISC` | `4` (但加 `-BL`) |
| `DI DISC` | `K` 或无 |
| `CS DISC` | — |

#### 2.7 特殊结构 (special) — 影响后缀字母

| 关键词 | 后缀 |
|--------|------|
| `LONG NECK` | `K` |
| `LUG` | `L` |
| `LOCKABLE LEVER` | `E` |
| `TAMPER SWITCH` / `w/switches` | (由消防前缀XD覆盖) |

#### 2.8 口径 (size) — 不影响 by1 编码（by1 不含口径）

口径仅用于数据校验和辅助判定，不参与 by1 编码生成。

---

### Stage 3: 编码组装（纯规则）

```python
def assemble_by1(features: dict) -> str:
    code = ""

    # 1. 消防前缀
    if features['fire_cert']:
        code += "X"

    # 2. 阀门类型
    code += "D"

    # 3. Pos2 驱动方式 — 当前数据全部省略

    # 4. Pos3 连接方式
    code += features['connection']  # '7', '8', '4', '3'

    # 5. Pos4 结构形式
    code += features['valve_structure']  # '1', '2', '3'

    # 6. Pos5 密封材料
    code += features['seat_material']  # 'X', 'F', 'H'

    # 7. 变体后缀
    suffix = ""
    if features.get('is_lug'):
        suffix += "L"
    if features.get('is_long_neck'):
        suffix += "K"
    if features.get('is_lockable'):
        suffix += "E"
    if features.get('has_stainless_disc'):
        suffix += "4"
    elif features.get('has_nbr_disc'):
        suffix += "4-BL"
    elif features.get('disc_material') == 'DI' and not features.get('is_lug'):
        suffix += "K"

    code += suffix
    return code
```

### 组装规则映射表（基于实际数据验证）

| EDesc 特征组合 | by1 基础码 | 后缀 | 完整 by1 |
|---------------|-----------|------|---------|
| WAFER + 中线 + EPDM + SS316 DISC + LEVER | D71X | 4 | D71X4 |
| WAFER + 中线 + EPDM + DI DISC + LEVER | D71X | K | D71XK |
| WAFER + 中线 + EPDM + DI DISC + GEAR | D71X | KL | D71XKL |
| LUG WAFER + 中线 + EPDM + SS316 DISC + LEVER | D71X | L4 | D71XL4 |
| LUG WAFER + 中线 + EPDM + SS316 DISC + HIGHER LEVER | D71X | LV4 | D71XLV4 |
| LUG WAFER + 中线 + EPDM + DI DISC + LEVER | D71X | LK | D71XLK |
| WAFER + 中线 + EPDM + 304 DISC | D71X | S4 | D71XS4 |
| GROOVED + 中线 + EPDM + DI+EPDM DISC + LEVER | D81X | 4 | D81X4 |
| GROOVED + 中线 + EPDM + DI+EPDM DISC + LOCKABLE LEVER | D81X | E | D81XE |
| GROOVED + 中线 + EPDM + DI+NBR DISC + LEVER | D81X | 4-BL | D81X4-BL |
| FLANGED + 双偏心 + EPDM | D342X | — | D342X |
| FLANGED + 双偏心 + EPDM + SS316 | D342X | 4 | D342X4 |
| FLANGED + 中线 + EPDM + SS316 + LEVER | D41X | 4 | D41X4 |
| XD + WAFER + 中线 + EPDM + DI EPDM DISC + GEAR + TAMPER | XD371X | — | XD371X |
| XD + WAFER + LUG + EPDM + GEAR + TAMPER | XD371X | L | XD371XL |
| XD + WAFER + LUG + EPDM + GEAR + TAMPER + SS304 | XD371X | LV4 | XD371XLV4 |
| XD + GROOVED + 中线 + EPDM + DI+EPDM DISC | XD381X | — | XD381X |
| XD + GROOVED + 中线 + EPDM + DI+EPDM + 300PSI | XD381X | G | XD381XG |
| XD + GROOVED + 中线 + EPDM + NEW TURBINE | XD381X | E | XD381XE |

---

### Stage 4: 校验与纠错

```
1. 基础码校验: 生成的基础码必须在 60 个已知 by1 中出现（或能拆分为已知前缀+合法后缀）
2. 特征交叉校验:
   - GROOVED(Pos3=8) + FLANGED 矛盾
   - 消防认证(X前缀) + 无 TAMPER/FIRE 关键词 → 标记 LOW 置信度
   - 双偏心(Pos4=2) + LEVER → 标记警告（双偏心通常为 GEAR）
3. 后缀合法性: 后缀字母必须是 L/K/V/E/G/S/C 的合法组合
4. 置信度评估:
   - HIGH: 所有关键词明确匹配，无歧义
   - MEDIUM: 部分字段需默认推断（如密封材料默认EPDM）
   - LOW: 多个特征缺失或存在矛盾
```

---

## 4. 难点与处理策略

### 4.1 难点：描述格式多样性

**问题**: 三种格式（逗号分隔/空格分隔/自然语言）需要不同的解析策略。

**方案**: 先识别格式类型，再分策略提取。

```python
def detect_format(text):
    comma_count = text.count(',')
    if comma_count >= 3:
        return 'COMMA_SEPARATED'   # ~65%
    elif comma_count <= 1 and any(kw in text.upper() for kw in ['GRV', 'WAF', 'FLG']):
        return 'COMPACT_SPACE'     # ~19%
    else:
        return 'NATURAL_LANGUAGE'  # ~16%
```

### 4.2 难点：后缀变体组合复杂

**问题**: 同一基础码 D71X 有 12 种后缀变体，后缀由多个特征交叉决定。

**方案**: 后缀拆分为独立特征位，按优先级叠加。

```
后缀 = [L(凸耳)] + [K(长颈)] + [V(带齿轮箱)] + [4/-BL(阀板)] + [E(特殊认证)]
```

优先级: L > K > V > 阀板标记 > E

### 4.3 难点：特征缺失与歧义

**问题**: 约 46% 的描述未明确操作方式，部分描述连接方式不明确。

**方案**: 默认值 + 上下文推断。

| 缺失字段 | 默认策略 |
|----------|---------|
| 密封材料 | 默认 EPDM(X) |
| 操作方式 | WAFER/GROOVED 默认 LEVER；FLANGED 默认 GEAR |
| 阀板材料 | DI+EPDM(消防) / DI(普通) |
| 阀门结构 | 默认中线(1) |

### 4.4 难点：特殊编码

**问题**: 少量 by1 编码包含非标准后缀（如 `D341X3-16QB1`、`XD371X243`）。

**方案**: 维护一个特殊编码映射表，规则引擎无法覆盖时查表。

---

## 5. 实现路径

### Phase 1: 规则引擎 — 单值预测 (准确率 58%)

```
输入: edesc_by1_filtered.csv (1999条)
  │
  ├─ 实现 Stage 1-4 全流程
  ├─ 逐条对比预测结果与真实 by1
  ├─ 统计覆盖率/准确率
  └─ 输出: 错误案例清单 → 用于 Phase 1.5 改进
```

**关键模块**:
- `preprocess()`: 文本预处理
- `extract_features()`: 特征抽取（关键词匹配 + 正则）
- `assemble_by1()`: 编码组装
- `validate()`: 校验纠错

**局限**: by1 是产品目录编码，不是纯粹特征驱动——相同特征可能对应不同编码（如 D71X4 vs D371X4），单值预测上限约 60%。

### Phase 1.5: Top-10 候选预测 (当前版本, 准确率 90.4%)

从单值预测升级为返回前 10 个候选编码，核心思路是：**对不确定特征生成变体，综合评分排序**。

```
EDesc 输入
    │
    ▼
┌──────────────────────────┐
│  Stage 1: 文本预处理       │  统一大写、修正拼写、规范分隔符
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  Stage 2: 特征抽取         │  从 EDesc 中抽取结构化特征
│  (规则 + 关键词匹配)       │  注意: XD 前缀 = 带信号接收器
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│  Stage 3: 基础码变体生成 (核心创新点)                    │
│                                                      │
│  ① 主预测: 根据特征生成最可能的基础码 (得分=50)        │
│  ② 连接方式变体: conn=UNKNOWN 时尝试 WAFER/GROOVED/    │
│     LUG/FLANGED (得分=15)                              │
│  ③ 操作方式变体: act=UNKNOWN 时尝试 GEAR/手动 (得分=10) │
│  ④ 信号前缀切换: XD↔D 互换 (得分=35)                   │
│  ⑤ Pos2 伴随: D71X↔D371X (得分=原分×0.6)              │
│                                                      │
│  输出: 4~16 个基础码变体及其得分                        │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│  Stage 4: 后缀展开与评分 (核心创新点)                    │
│                                                      │
│  ① 跨基础码后缀共享:                                 │
│     D71X/D371X/XD71X/XD371X 的后缀互相应用            │
│     (因为 SUFFIX_LOOKUP 可能只在一个基础码下有记录)    │
│                                                      │
│  ② KNOWN_BY1 补充: 从60个已知编码中提取特殊后缀        │
│     (如 105, 243, 76, G 等)                           │
│                                                      │
│  ③ 300PSI 特殊处理: 生成 G 后缀                        │
│                                                      │
│  ④ 评分公式:                                          │
│     total = base_score × mult                        │
│           + match_score (特征匹配分, 0~36)            │
│           + freq_score (频率分, 0~10)                 │
│                                                      │
│  ⑤ mult 乘数:                                        │
│     - 基础码本身: 1.0                                  │
│     - 伴随码: 0.5                                     │
└──────────┬───────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────┐
│  Stage 5: 合并去重 + Top-10 排序                      │
│                                                      │
│  所有基础码变体的后缀展开结果合并到同一个候选池           │
│  按得分降序排列, 取前 10 个作为最终候选                  │
└───────────────────────────────────────────────────┘
           │
           ▼
    [候选1, 候选2, ..., 候选10]
     越靠前的越正确
```

#### 信号接收器 (XD 前缀) 判定逻辑

XD 前缀表示蝶阀带有信号接收器（开关/监控/反馈信号），与消防认证(FM/UL)不同。

| 关键词层级 | 关键词 | 说明 |
|------------|--------|------|
| 强信号 | `TAMPER SWITCH`, `W/SWITCHES`, `FLYING LEAD` | 明确提到开关/信号 |
| 强信号 | `NORMAL CLOSE`, `GEAR-OP` | 信号控制相关 |
| 强信号 | `BVW-`, `BVT-`, `GBV-`, `BFV-` | 带信号蝶阀型号 |
| 强信号 | `D48638` (GD/WD/LD系列), `FIG 215/216` | 信号蝶阀型号 |
| 强信号 | `FIRE RISER` | 消防立管(84%带信号,少数例外) |
| 强信号 | `NEW TURBINE`, `SPF` | 新型信号涡轮/品牌 |
| 弱信号 | `BVG-`, `UL/FM` | 不确定,仅用于变体生成 |

#### 后缀查找表 (SUFFIX_LOOKUP)

从训练数据统计生成 (`generate_suffix_lookup.py`):
- 按 `(base_code, has_lug, is_higher_lever, is_lockable, disc_material, seat_name, actuation)` 分组
- 每组取众数后缀作为默认
- 同时生成 `SUFFIX_LOOKUP_BASE` 作为仅按基础码的回退

#### 基础码变体生成示例

| 场景 | 主预测 | 变体 | 得分 |
|------|--------|------|------|
| WAFER+中线+EPDM+GEAR | D71X | D71X(50), XD371X(35), D371X(30), XD71X(30) |
| GROOVED+中线+EPDM+LEVER | D81X | D81X(50), XD381X(35), D381X(30), XD81X(30) |
| WAFER+双偏心+FLANGED | D342X | D342X(50), XD342X(35) |

#### 后缀展开示例 (以 D71X 为例)

```
基础码: D71X (主), D371X, XD71X, XD371X (伴随)

伴随码后缀共享:
  D71X 的 SUFFIX_LOOKUP 条目: "", "4", "K", "L4", "LV4", "LK", "KL", "S4", "V4" ...
  → 全部应用到 D371X, XD71X, XD371X

结果:
  D71X,  D71X4,  D71XK,  D71XL4,  D71XLV4,  D71XLK,  D71XKL,  D71XS4,  D71XV4 ...
  D371X, D371X4, D371XK, D371XL4, D371XLV4, ...
  XD71X, XD71X4, ...
  XD371X, XD371X4, XD371XL, XD371XLV4, XD371XG, ...

最终按得分排序取 Top-10
```

#### 评分公式详解

```
候选得分 = base_score × mult        # 基础码置信度 (0~50)
         + match_score               # 后缀特征匹配分 (0~36)
         + freq_score                # 训练集频率分 (0~10)

其中:
  base_score: 主预测=50, 信号切换=35, 连接替代=15, 操作替代=10, Pos2伴随=原分×0.6
  mult:       基础码本身=1.0, 伴随码=0.5
  match_score: has_lug匹配=8, disc匹配=10, act匹配=8, seat匹配=4,
               is_hl匹配=3, is_lock匹配=3, UNKNOWN容差=2~3
  freq_score: min(训练集出现次数, 20) × 0.5
```

### Phase 2: AI 辅助增强 (覆盖剩余 10%)

对 Phase 1.5 中 top-10 未命中的案例：

```
方案 A: LLM 辅助特征抽取
  - 将 EDesc + 提示词发给 LLM
  - LLM 返回结构化特征 JSON
  - 再走 Stage 3 编码组装

方案 B: Embedding 相似度匹配
  - 对历史数据计算 EDesc embedding
  - 新描述找最相似的历史 EDesc
  - 直接复用其 by1 编码
```

### Phase 3: 持续优化

```
- 新增产品数据持续加入训练集
- 规则引擎无法覆盖的案例自动归档
- 定期人工审核 LOW 置信度预测结果
```

---

## 6. 评估指标

| 指标 | Phase 1 单值 | Phase 1.5 Top-10 | 目标 |
|------|-------------|-----------------|------|
| 基础码准确率 | ~80% | — | > 95% |
| Top-1 完全匹配 | 59.3% | — | > 70% |
| Top-3 命中率 | — | 73.4% | > 80% |
| Top-5 命中率 | — | 81.2% | > 85% |
| **Top-10 命中率** | — | **90.4%** | **> 92%** |
| 完全未命中率 | — | 9.6% | < 5% |

---

## 7. 当前未命中分析 (192 条 / 9.6%)

| 类别 | 数量 | 原因 |
|------|------|------|
| G 后缀 (300PSI 未标注) | ~34 | EDesc 未提及 300PSI，但 by1 含 G |
| 数值后缀 (76/242/243) | ~20 | 特殊产品编码，无法从特征预测 |
| PTFE 密封 (F vs X) | ~13 | EDesc 未提及 PTFE，默认判为 EPDM(X) |
| 数据不一致 | ~20 | FIRE RISER 产品但 by1 无 X 前缀 |
| 连接/结构误判 | ~15 | 关键词歧义或缺失 |
| 其他 | ~90 | 多因素叠加 |

---

## 8. 文件清单

| 文件 | 说明 |
|------|------|
| `scripts/by1_rule_engine.py` | 主引擎：预处理、特征抽取、编码组装、Top-10 候选预测 |
| `scripts/generate_suffix_lookup.py` | 从训练数据统计生成后缀查找表 |
| `scripts/suffix_lookup_generated.py` | 自动生成的查找表 (110条 + 12条回退) |
| `zhhm_orders/edesc_by1_filtered.csv` | 训练数据 (1999条, 60个 by1 编码) |
| `docs/prediction_top10_misses.csv` | Top-10 未命中案例 (192条) |

---

## 9. 数据集划分建议

```
总数据: 1999 条 (60 个 by1 编码)

按 by1 分层划分:
  - 训练集: 70% (约 1400 条, 覆盖全部 60 个 by1)
  - 验证集: 15% (约 300 条)
  - 测试集: 15% (约 300 条)

划分原则:
  - 每个 by1 编码至少在训练集中出现 3 条
  - 低频 by1 (<10条) 全部保留在训练集
  - 按描述格式(COMMA/COMPACT/NATURAL)分层抽样
```
