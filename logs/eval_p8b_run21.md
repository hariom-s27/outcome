# DEV eval (baseline)

Run `fc5e6f1` · 2026-11-08T05:42:04Z · pipeline `baseline-v1` · model `anthropic/claude-haiku-5.5` · p8b-old-box-r21

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | SUCCESS | True | 0.100 | 1/10 | 0 | 0 | 0 | 0/9 | 0.00440 | 0.00440 | 24.5 |  flags=truncated_output |

**Mean score 0.100 over n = 1 DEV docs** · paid $0.00440 (computed $0.00440) · uncached $0.00440 · **$0.00440/doc uncached** · p50 latency 24.5 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| boxscore_001 | date | 1 | 0 | 0 | 0 |
| boxscore_001 | number | 16 | 0 | 0 | 0 |
| boxscore_001 | text | 3 | 0 | 0 | 0 |

## Per-field scores (field names only)

### boxscore_001 (0.100)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| property_name | 0.10 | 0 | 0 | 0 |
| date | 0.10 | 0 | 0 | 0 |
| code | 0.10 | 0 | 0 | 0 |
| name | 0.10 | 0 | 0 | 0 |
| avg_sq_ft | 0.10 | 0 | 0 | 0 |
| avg_rent | 0.10 | 0 | 0 | 0 |
| units | 0.10 | 0 | 0 | 0 |
| occ_no_notice | 0.10 | 0 | 0 | 0 |
| vacant_rented | 0.10 | 0 | 0 | 0 |
| vacant_unrented | 0.10 | 0 | 0 | 0 |
| notice_rented | 0.10 | 0 | 0 | 0 |
| notice_unrented | 0.10 | 0 | 0 | 0 |
| avail | 0.10 | 0 | 0 | 0 |
| model | 0.10 | 0 | 0 | 0 |
| down | 0.10 | 0 | 0 | 0 |
| admin | 0.10 | 0 | 0 | 0 |
| percent_occupied | 0.10 | 0 | 0 | 0 |
| p_occ_wornonrev | 0.10 | 0 | 0 | 0 |
| percent_leased | 0.10 | 0 | 0 | 0 |
| p_trend | 0.10 | 0 | 0 | 0 |

