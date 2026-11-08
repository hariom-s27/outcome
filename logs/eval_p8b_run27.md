# DEV eval (baseline)

Run `fc5e6f1-dirty` · 2026-11-08T05:46:25Z · pipeline `table-spec-v1` · model `anthropic/claude-haiku-5.5` · p8b-spec-t12-r27

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| t12_001 | SUCCESS | True | 0.157 | 140/119 | 0 | 1067 | 0 | 21/0 | 0.00126 | 0.00126 | 4.1 |  |

**Mean score 0.157 over n = 1 DEV docs** · paid $0.00126 (computed $0.00126) · uncached $0.00126 · **$0.00126/doc uncached** · p50 latency 4.1 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| t12_001 | date | 0 | 0 | 238 | 0 |
| t12_001 | number | 0 | 0 | 476 | 0 |
| t12_001 | text | 242 | 0 | 353 | 0 |

## Per-field scores (field names only)

### t12_001 (0.157)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.00 | 0 | 119 | 0 |
| period_start | 0.00 | 0 | 119 | 0 |
| period_end | 0.00 | 0 | 119 | 0 |
| amount_total | 0.00 | 0 | 119 | 0 |
| amount_first_month | 0.00 | 0 | 119 | 0 |
| amount_last_month | 0.00 | 0 | 119 | 0 |
| months_with_activity | 0.00 | 0 | 119 | 0 |
| section | 0.01 | 0 | 117 | 0 |
| category | 0.01 | 0 | 117 | 0 |
| gl_code | 0.85 | 0 | 0 | 0 |
| line_item | 0.85 | 0 | 0 | 0 |

