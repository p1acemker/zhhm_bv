# Recommendation System Improvement Plan

## 1. Objective

Refactor the current recommendation service around two explicit outputs:

1. Recommend `by1` candidates from `English description + form_code`, with
   Top-5 accuracy substantially above the current production baseline.
2. Infer a specification from the same inputs, with at least 90% overall
   accuracy on a chronological holdout and explicit abstention for weak cases.

`by1` and `form_code` must remain separate fields. The existing `/spec/infer`
request currently uses `form` as if it were `by1`; that contract must not be
extended to the newly extracted form code.

Phase 0/1 is now implemented in the working tree: the product-code parser is in
`service/product_code.py`, the deterministic service is in
`service/recommendation.py`, the generated runtime index is
`data/recommendation_index.json`, and the public endpoint is the existing
`POST /edesc/search`.
Rebuild the index with:

```powershell
python tools\build_recommendation_index.py --input history_orders.xlsx
```

## 2. Product Code Parsing

For standard product codes, parse:

```text
<business_prefix><by1>_<specification>_<form_code><material><surface>
```

Example:

```text
LD71XLV99_D100_90FQ11L50
| |         |    |  |   |
| D71XLV99  D100 90F Q11 L50
business prefix = L
```

Workbook findings:

- 24,338 total rows
- 24,220 standard three-segment product codes (99.52%)
- 23,491 usable rows with standard specification, description, by1, and form
- 365 by1 labels, 157 standard specifications, 87 form codes
- 1,976 normalized English descriptions
- all successfully parsed first segments follow `one business prefix + by1`
- 118 nonstandard numeric/legacy codes are mainly accessories, spare parts, or
  incomplete rows and should enter a separate quarantine path

The parser must validate extracted values against the existing by1,
specification, and material-classification columns during index construction.
Invalid rows must be reported, not silently forced into the standard valve model.

## 3. Measured Baselines

### Current BGE/Qdrant service

The configured collections contain only 61 parent by1 labels and 1,489 child
descriptions. On orders from 2024-09-01 onward:

| Metric | Result |
| --- | ---: |
| Holdout rows | 2,217 |
| Ground-truth by1 present in current collection | 55.12% |
| Current by1 Top-1, all rows | 28.06% |
| Current by1 Top-5, all rows | 46.50% |
| Current by1 Top-5, known-label rows only | 84.37% |

The first bottleneck is incomplete index coverage, followed by insufficient
candidate recall and the absence of form-aware reranking. Replacing BGE alone
will not solve the largest error source.

### Chronological historical baseline

Training and validation use orders before 2024-09-01; the untouched holdout
contains 2,179 standard-specification rows.

| Predictor | Coverage | Answered accuracy | Overall accuracy |
| --- | ---: | ---: | ---: |
| by1 Top-5: exact description + form, then description | 95.87% | 97.32% | 93.30% |
| Specification Top-1: exact description + form, then description | 95.87% | 98.13% | 94.08% |

After deduplicating by `order number + product code + English description`, the
holdout still produces:

| Predictor | Coverage | Answered accuracy | Overall accuracy |
| --- | ---: | ---: | ---: |
| by1 Top-5 | 95.69% | 97.61% | 93.40% |
| Specification Top-1 | 95.69% | 97.99% | 93.76% |

These results demonstrate that both requested targets are feasible before any
new model training. They must be treated as retrieval/rule baselines, not as a
final production model score.

`form_code` alone is not a safe fallback: its observed by1 Top-5 accuracy is
27.5%, and specification Top-1 accuracy is 6.25%. The service must abstain when
description evidence is absent.

## 4. Target Architecture

### 4.1 Versioned training dataset

Create one row-level dataset with these normalized fields:

```text
contract_date, order_number, customer, raw_description,
normalized_description, semantic_description_without_size,
product_code, business_prefix, by1, specification,
spec_prefix, spec_size, form_code, material, surface
```

Keep row counts for priors, but also create a deduplicated evaluation view.
Persist parser failures and nonstandard specifications in separate tables.

### 4.2 by1 recommendation

Use a staged pipeline:

1. Exact historical lookup by `normalized_description + form_code`.
2. Exact description-only fallback when its historical candidate distribution
   is sufficiently concentrated.
3. Retrieve a broad candidate pool from a complete BGE-M3 child index containing
   all training-time by1 labels.
4. Rerank candidates using the available `bge-reranker-v2-m3` model plus
   structured compatibility features:
   - form_code/by1 historical compatibility
   - connection type, valve structure, seat, disc, drive, pressure, certification
   - optional customer compatibility
   - label support and recency
5. Aggregate child hits by by1 and return five distinct candidates with evidence.
6. Abstain or flag low confidence when candidate margin and calibrated confidence
   are below threshold.

For by1 retrieval, size tokens should be removed from one semantic representation
so that DN differences do not dominate product-variety similarity. Retain a
second full representation for specification inference.

The current standardizer also fills missing seat/disc evidence with `EPDM` and
`DI DISC`. Unknown attributes should instead remain absent; invented defaults
create false similarity between underspecified queries and specific products.

The child candidate pool should be at least 100 hits before parent aggregation;
the current `top_k * 5` pool is too narrow for reliable parent Top-5 recall.

### 4.3 Specification inference

Use this evidence order:

1. Exact `description + form_code` historical specification distribution.
2. Mature deterministic rule: stable form-code prefix plus parsed size.
3. Exact description-only history when unambiguous.
4. Joint inference from the by1 candidate set, historical
   `(by1, form_code, size)` compatibility, and nearest descriptions.
5. Return alternatives or `null` when confidence is insufficient.

Fourteen form-code prefix rules passed all of these gates:

- at least 20 parseable training rows
- at least 5 parseable validation rows
- zero prefix and complete-spec conflicts in both windows

The rules are:

```text
907:D, 90F:D, 90Q:D, 90S:D, 913:D, 916:D, 91Q:D,
91X:D, 92N:B, 931:B, 935:B, 93J:B, 93X:B, 96Q:B
```

On the untouched holdout, the complete rule path answered 101 orders (4.64%)
with 100% accuracy. It is a high-confidence supplement, not a universal
fallback. Existing grooved OD, CTS, suitable-range, decimal-mm, and explicit
exception handling should remain in the size parser.

Nonstandard specifications such as extension sizes or suffix-bearing codes must
use exact/nearest historical evidence rather than generated `prefix + size`.

### 4.4 API contract

Extend the existing search request with an explicit `form_code`; do not add a
separate recommendation endpoint:

```json
{
  "query": "DI LUG WAFER BV ... 4\"/DN100",
  "form_code": "90F",
  "customer": "optional",
  "top_k": 5
}
```

The response should contain:

```text
by1_candidates, inferred_specification, specification_alternatives,
confidence, confidence_score, match_level, evidence, model_version
```

Evidence should identify exact history, vector retrieval, reranker score,
form compatibility, parsed size rule, support, and candidate margin.

## 5. Delivery Phases

### Phase 0: Data contract and parser

- implement `ProductCodeParser`
- rename internal request context to `by1` and `form_code`
- generate parser quality and quarantine reports
- add row-level and deduplicated chronological fixtures

### Phase 1: Complete index and deterministic baseline

- rebuild versioned parent/child collections from pre-cutoff history
- include all eligible by1 labels and structured payload fields
- implement exact description/form lookup and confidence-aware abstention
- add mature form-code specification rules

This phase alone is expected to exceed 90% overall on both measured objectives.

### Phase 2: Hybrid retrieval and reranking

Detailed implementation and rollout gates are defined in
`docs/recommendation-phase2-optimization-plan.md`.

- retrieve at least 100 child candidates
- add form-aware priors and parsed attribute compatibility
- integrate the existing BGE reranker service
- calibrate confidence on validation data only
- evaluate new descriptions, rare labels, and nonstandard specifications separately

### Phase 3: Shadow deployment

- deploy to versioned collections and keep the current endpoint unchanged
- log recommendations, evidence, latency, and later-confirmed labels
- compare old/new results in shadow mode
- switch the collection alias only after acceptance gates pass

## 6. Acceptance Gates

Use chronological splits: training before 2024-04-28, validation through
2024-08-31, and blind holdout from 2024-09-01 onward. Report both row-weighted
and deduplicated metrics.

Required gates:

| Metric | Minimum |
| --- | ---: |
| by1 candidate recall at 50 | 99% |
| by1 Top-5 overall accuracy | 93% |
| by1 Top-5 answered accuracy | 97% |
| by1 answer coverage | 95% |
| Specification Top-1 overall accuracy | 92% |
| Specification Top-1 answered accuracy | 95% |
| Specification answer coverage | 95% |
| High-confidence specification accuracy | 98% |

Also publish segmented metrics for known/unseen descriptions, known/unseen by1,
form code, customer, standard/nonstandard specification, and parser status.

## 7. Recommended Priority

1. Fix field semantics and build the product-code parser.
2. Rebuild the complete, time-safe index; this addresses the largest measured gap.
3. Add exact history and mature specification rules.
4. Increase candidate recall and add form-aware reranking.
5. Calibrate confidence and deploy in shadow mode.

Do not begin with fine-tuning or replacing BGE-M3. The available evidence shows
that data/index completeness and structured reranking offer the largest and
lowest-risk improvement first.
