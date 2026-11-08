| Scenario | Workers | n | Terminal | Lost | Dup | VALID % | p50 s | p95 s | max s | jobs/min | POST max s | POST 429 | 5xx | slot > 60 s | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1 | 1 | 20 | 20 | 0 | 0 | 100.0 | 59.17 | 71.47 | 75.34 | 8.51 | 0.64 | 0 | 0 | 0 | PASS |

Per doc (submit -> terminal seconds, client clock, 2 s poll):

| Scenario | Workers | Doc | Kind | n | p50 s | p95 s | max s |
|---|---|---|---|---|---|---|---|
| L1 | 1 | boxscore_001 | csv | 4 | 37.84 | 69.45 | 71.27 |
| L1 | 1 | lease_001 | pdf | 4 | 64.54 | 73.88 | 75.34 |
| L1 | 1 | lease_002 | docx | 3 | 47.19 | 50.45 | 50.81 |
| L1 | 1 | om_001 | pdf | 3 | 59.19 | 59.47 | 59.5 |
| L1 | 1 | rentroll_001 | xlsx | 3 | 69.28 | 69.28 | 69.28 |
| L1 | 1 | t12_001 | xlsx | 3 | 65.28 | 67.0 | 67.19 |

Criteria:

- L1 w=1: all passed (statuses {'SUCCESS': 20})
