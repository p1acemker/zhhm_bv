# zhhm_bv

阀门货描维护、品种/规格推荐和标准货描设计服务。

三类阀门货描标准化、业务字典维护、Qdrant 模板构建和人工金标验收说明见
[`docs/valve-description-design.md`](docs/valve-description-design.md)。

## By1 template inference

Build the time-safe template index from the historical workbook:

```powershell
python tools\build_by1_template_index.py --input history_orders.xlsx --train-before 2024-04-28 --output data\by1_template_index.json
```

Run the chronological evaluation with prepared prediction rows:

```powershell
python tools\evaluate_by1_template_inference.py --input evaluation_rows.json --index data\by1_template_index.json --train-before 2024-04-28 --validation-before 2024-09-01 --output outputs\by1_template_inference\metrics.json
```

Set `BY1_TEMPLATE_MODE=shadow` to calculate template evidence without changing the existing response. Set it to `on` only after the by1, specification, joint-accuracy, coverage, and high-confidence gates pass. Missing template assets and retrieval failures fall back to historical/vector recommendation.
