# DEV eval (baseline)

Run `fc5e6f1-dirty` · 2026-11-08T05:45:57Z · pipeline `table-spec-v1` · model `anthropic/claude-haiku-5.5` · p8b-spec-box-r24

Score = mean of per-field means (tools/validate.py `score()`), per document. Counts are cells; wrong / missed (wrongly null) / hallucinated (value where truth is null). Extra/missing rows score 0 on every field and are counted separately. $ paid = this run's spend (a dev-cache hit is $0); $ uncached = what the document costs with no cache (a hit is priced at the ledger cost of the call that filled it), the figure a grader pays and the one used for $/doc.

| doc | status | valid | score | rows pred/truth | wrong | missed | halluc. | extra/missing rows | $ paid | $ uncached | latency s | reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| boxscore_001 | SUCCESS | True | 0.950 | 10/10 | 0 | 10 | 0 | 0/0 | 0.00091 | 0.00091 | 3.8 |  |

**Mean score 0.950 over n = 1 DEV docs** · paid $0.00091 (computed $0.00091) · uncached $0.00091 · **$0.00091/doc uncached** · p50 latency 3.8 s · reasoning tokens 0

Gates: dry run `passed` · --allow-dirty used: `False`

## Errors by truth value type (cells in matched rows)

| doc | type | right | wrong | missed | halluc. |
|---|---|---|---|---|---|
| boxscore_001 | date | 0 | 0 | 10 | 0 |
| boxscore_001 | number | 160 | 0 | 0 | 0 |
| boxscore_001 | text | 30 | 0 | 0 | 0 |

## Per-field scores (field names only)

### boxscore_001 (0.950)

| field | score | wrong | missed | halluc. |
|---|---|---|---|---|
| date | 0.00 | 0 | 10 | 0 |
| property_name | 1.00 | 0 | 0 | 0 |
| code | 1.00 | 0 | 0 | 0 |
| name | 1.00 | 0 | 0 | 0 |
| avg_sq_ft | 1.00 | 0 | 0 | 0 |
| avg_rent | 1.00 | 0 | 0 | 0 |
| units | 1.00 | 0 | 0 | 0 |
| occ_no_notice | 1.00 | 0 | 0 | 0 |
| vacant_rented | 1.00 | 0 | 0 | 0 |
| vacant_unrented | 1.00 | 0 | 0 | 0 |
| notice_rented | 1.00 | 0 | 0 | 0 |
| notice_unrented | 1.00 | 0 | 0 | 0 |
| avail | 1.00 | 0 | 0 | 0 |
| model | 1.00 | 0 | 0 | 0 |
| down | 1.00 | 0 | 0 | 0 |
| admin | 1.00 | 0 | 0 | 0 |
| percent_occupied | 1.00 | 0 | 0 | 0 |
| p_occ_wornonrev | 1.00 | 0 | 0 | 0 |
| percent_leased | 1.00 | 0 | 0 | 0 |
| p_trend | 1.00 | 0 | 0 | 0 |

