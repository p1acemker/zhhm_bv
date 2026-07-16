# Specification inference

## Request contract

`POST /spec/infer` accepts:

```json
{
  "query": "English product description",
  "top_k": 50,
  "customer": "optional customer name",
  "form": "optional product form or variety code"
}
```

The service also accepts a composite query in the form
`customer[SEP]description[SEP]form`. Explicit `customer` and `form` fields take
precedence over values parsed from the composite query.

## Historical evidence

The runtime index was built from `history_orders.xlsx`:

- 24,236 usable historical rows from 2021-08-11 through 2024-12-20
- 2,081 normalized English descriptions
- 384 product forms (`品种`)
- 246 specifications
- 96.4% of rows containing both a numeric specification and DN/mm text use a
  matching numeric size

A chronological holdout using orders before 2024-04-28 as training data and
later orders as evaluation data produced:

- 96.3% response coverage after low-confidence abstention
- 96.5% accuracy among answered requests
- 99.1% accuracy for high-confidence requests
- 83.5% accuracy for medium-confidence requests

Customer and form priors without description evidence were not reliable, so
they are not used alone. A form contributes a specification prefix only when
it passes the mature-rule validation described below.

Customer names are normalized and stored only as SHA-256 fingerprints in the
runtime index. Order numbers and row-level dates are not included.

## Mature deterministic rules

The rule layer infers only standard specifications shaped as
`alphabetic prefix + numeric size`.

Form-prefix rules are admitted only when all of these conditions hold:

- at least 20 parseable training orders before 2024-04-28
- at least 5 parseable validation orders from 2024-04-28 through 2024-08-31
- 100% prefix and complete-specification agreement in both windows
- no hard-coded customer names or customer-only priors

This produced 33 mature form rules. On the untouched 2024-09-01 through
2024-12-20 holdout (2,179 standard-specification orders), the rules covered
254 complete specifications (11.66%) with 100% accuracy. The generated rule
table records support counts and holdout metrics in
`data/spec_inference_rules.json`.

The deterministic size rules are:

1. Ordinary `DN100` descriptions infer size `100`.
2. Explicit decimal millimetres are rounded half up, for example `114.3MM`
   becomes `114`.
3. `SUITABLE FOR` / `SUIT FOR` ranges use the largest stated size.
4. Grooved steel-pipe sizes convert nominal DN/inches to outside diameter,
   for example `DN100` or `4"` becomes `114`.
5. When a grooved description contains both inches and mm, explicit mm wins
   only when it is within 3 mm of the validated outside diameter. Thus
   `6"/165MM` becomes `165`, while `3"/80MM` becomes `89`.
6. Grooved `CTS` / `COP` descriptions use copper-tube OD: nominal inches plus
   1/8 inch, converted to rounded millimetres.
7. The historically stable `GD48638N` series exceptions are `2.5" -> 73` and
   `5" -> 141`; an explicit nearby mm value still wins.

The rule layer abstains for a grooved description containing only a bare mm
value, an unvalidated form, an unparseable size, or a nonstandard specification
such as `N89K10` or `N125X1220`. These requests continue through historical
exact and fuzzy matching.

## Inference order

1. Normalize description, customer, and form.
2. Match exact `description + customer + form` history, preserving known
   customer-specific exceptions.
3. Apply a mature form-prefix rule plus a deterministic size rule.
4. Fall back to exact `description + form`, `description + customer`, or
   description-only history.
5. For unseen descriptions, retrieve similar historical descriptions using
   weighted token overlap.
6. Apply DN/mm consistency as a strong constraint.
7. Use customer and form matches as reranking signals.
8. Return `null` instead of a unique specification when confidence is low;
   ranked alternatives and evidence remain available.

With an index containing only orders before 2024-09-01, the later 2,217 usable
orders produced 96.62% answer coverage and 97.39% answered accuracy. The mature
rule stage handled 14 requests that were not resolved by stronger
customer-specific exact history and was correct on all 14.

The response includes `inferred_spec`, `confidence`, `confidence_score`,
`match_level`, `evidence`, and `alternatives`.

## Rebuilding the runtime index

The raw workbook is intentionally excluded from Git. Rebuild the compact,
tracked runtime index with:

```powershell
python tools\build_spec_index.py --input history_orders.xlsx
python tools\build_spec_rules.py --input history_orders.xlsx
```

The API reads `data/spec_inference_index.json` and
`data/spec_inference_rules.json`. Override their locations with the
`SPEC_INFERENCE_INDEX_PATH` and `SPEC_INFERENCE_RULES_PATH` environment
variables when needed.
