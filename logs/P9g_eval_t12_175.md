# DEV eval (baseline)

Run `a544d9f` · 2026-11-08T18:54:57Z · pipeline `table-spec-v1` · model `-` · P9g t12 feedback on

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t12_001 | SUCCESS | True | 0.077 | 140/119 | 0 | 1190 | 0 | 21/0 | 0.00000 | 0.00000 | 1.5 |  |

**Mean score 0.077 over n = 1 DEV docs** · paid $0.00000 (computed $0.00000) · uncached $0.00000 · **$0.00000/doc uncached** · p50 latency 1.5 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| t12_001 | date | 0 | 0 | 238 | 0 |
| t12_001 | number | 0 | 0 | 476 | 0 |
| t12_001 | text | 119 | 0 | 476 | 0 |

## Per-field scores (field names only)

### t12_001 (0.077)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 0 | 119 | 0 |
| period_start | 0.00 | 0 | 119 | 0 |
| period_end | 0.00 | 0 | 119 | 0 |
| line_item | 0.00 | 0 | 119 | 0 |
| section | 0.00 | 0 | 119 | 0 |
| category | 0.00 | 0 | 119 | 0 |
| amount_total | 0.00 | 0 | 119 | 0 |
| amount_first_month | 0.00 | 0 | 119 | 0 |
| amount_last_month | 0.00 | 0 | 119 | 0 |
| months_with_activity | 0.00 | 0 | 119 | 0 |
| gl_code | 0.85 | 0 | 0 | 0 |

