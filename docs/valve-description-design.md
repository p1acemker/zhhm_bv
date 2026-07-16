# 三类阀门货描标准化

当前版本支持蝶阀、止回阀和闸阀。源订单表只读，附件、备件及其他产品保留原始行，但不生成阀门本体货描。

## 数据资产

- `data/edesc_business_dictionary.xlsx`：业务人员维护的唯一字典源。
- `data/edesc_business_dictionary.json`：由 Excel 编译的运行时字典，不应手工修改。
- `data/edesc_template_index.json`：用于构建 Qdrant 模板集合的版本化索引。
- `outputs/edesc_standardization_v1/standardized_orders.xlsx`：保留原始列并追加标准化结果。
- `outputs/edesc_standardization_v1/edesc_gold_review.xlsx`：600 条分层人工复核样本。

## 重新构建

```powershell
python tools\build_description_assets.py `
  --input "22年-24年海外阀门订单货描明细表.xlsx" `
  --output-dir "outputs\edesc_standardization_v1" `
  --dictionary-source "data\edesc_business_dictionary.xlsx" `
  --dictionary-version "2026.07.15-v1"
```

审核并更新 Excel 字典后，重新运行构建命令，再将通过审核的字典和模板索引同步到 `data`。Qdrant 使用新的物理集合并在点数验证后原子切换别名：

```powershell
python tools\build_template_qdrant.py `
  --index "data\edesc_template_index.json"
```

当前运行时别名为 `edesc_templates_current`。构建脚本不会删除现有推荐集合，也不会覆盖同名物理集合，除非显式提供 `--recreate`。

## API 开关

`POST /edesc/search` 的请求和原响应字段保持不变。通过环境变量控制新增结果：

- `EDESC_DESIGN_MODE=off`：不初始化货描设计服务。
- `EDESC_DESIGN_MODE=shadow`：计算并记录结果，但不改变响应。
- `EDESC_DESIGN_MODE=on`：响应中增加 `description_design`。

主结果只采用原文明示字段、产品编码字段和通过时间验证的成熟规则。Qdrant 模板用于候选召回；候选与原文明示字段冲突时会被淘汰，查询中的尺寸始终覆盖历史模板样例尺寸。

## 人工验收

在 `edesc_gold_review.xlsx` 中填写 `approved`；不通过时填写对应的 `corrected_*` 列。完成复核后运行：

```powershell
python tools\evaluate_description_design.py `
  --gold "outputs\edesc_standardization_v1\edesc_gold_review.xlsx" `
  --output "outputs\edesc_standardization_v1\edesc_gold_metrics.json"
```

在 600 条样本完成复核前，报告状态保持 `pending_human_review`，不得将自动一致性指标表述为业务准确率。
