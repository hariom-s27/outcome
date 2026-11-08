# P9e report: E5 scanned docs, every page as an image (Z-53..Z-58)

Branch `lab`. Stack: lab defaults, E0 on, grid on, cleanup on, `LAB_MODE=1`, `LLM_CACHE_MODE=off`,
`SCAN_PAGE_METHOD=all`. Worker start line (both replicas): `scan_pages=all, cache_mode=off,
lab_mode=on, e0_robust=on, pdf_table=grid, table_cleanup=on`. Code at `662f00a`.

## PLAIN SUMMARY

- **What changed.** Before, a scanned PDF sent only its first 8 page images. With
  `SCAN_PAGE_METHOD=all`, a scan with more than 8 page images sends every page, up to 40. It is
  still one call with the same prompt and the same model (Haiku).
  - Code puts a tag `PAGE n of N` in front of each image.
  - Code sets `page_numbers` from the citation's `[Page n]`, and only for pages that were
    actually sent.
- **Result.** 3 live runs per doc:

  | doc | before (runs 104–106) | after (runs 171–173) | missed fields per run |
  |---|---|---|---|
  | lease_001 | 0.642 | 0.867 | 7.7 → 0 |
  | syn_lease_scan | 0.150 | 0.925 | 33.0 → 0 |

  - 0 hallucinations, all VALID, no provider errors (every call HTTP 200, `stop`).
- **Gate (Z-56): PASS.** All 7 checks passed. Pooled latency p50 was 21.0 s against a 23.1 s
  limit, so it also passes.
  - lease_001's own latency p50 went from 13.1 s to 30.0 s (×2.3). See Decision.
- **Must-not-error full run 174: PASS.** 14/14 SUCCESS + VALID, $0.03035.
- **Decision.** `SCAN_PAGE_METHOD=all` is now the default on lab: `app/config.py`,
  `compose.yaml` and the shipped-config test. `first` turns it off (v1.0).
- **Cost.** $0.0067 per lease_001 job (it was $0.0031) and $0.0056 per syn_lease_scan job (it
  was $0.0030).
- **Spend.** P9e $0.06722 of the $0.15 cap. Project **$1.122552**. Lab ≈ **$0.5557** of $3.

## Part 0 facts (code + metadata, $0)

1. **v1.0 scan path.**
   - The reader renders every scan page: grayscale JPEG, 1600 px long side, quality 80, no OCR.
   - The prompt builder keeps the first `MAX_IMAGES = 8` images (R13).
   - One call. Each image comes after `[Page n] (no text layer; page image follows)`.
2. **Real image tokens are w×h/750, with no provider downscale.**
   - Ledger, n = 8 calls per doc at 8 images: 19,106 and 23,746 tokens in. That is 16,640 /
     21,111 image tokens + ~2.5K text.
   - Per page: lease_001 (975×1600) ≈ 2,080 tokens; syn_lease_scan (1237×1600) ≈ 2,639 tokens.
   - DR24's ~1,568 tokens per page does not hold at our render size.
3. **Limits.**
   - Haiku's price tier starts at 100K prompt tokens. 40 letter pages at 1600 px ≈ 105.6K tokens,
     so Z-54's cap of 40 on its own would not stay under the tier.
   - v1.0's `INPUT_TOKEN_CAP` = 60K applies first. It uses the same w×h/750 rule, so no request
     can reach the tier (see "Where it fails").
   - Our gateway's images-per-request limit is unmeasured. This phase sent at most 25, accepted.
   - R13's ~8 MB rule is our own, not a provider limit.
   - HTTP timeout 120 s per attempt.
4. **Under `all` (dry run).**

   | doc | pages sent | builder est. | fuse est. | real tokens in (live) |
   |---|---|---|---|---|
   | lease_001 | 25/25 | 57,667 | 81,667 | 54,235 |
   | syn_lease_scan | 15/15 | 45,237 | 51,314 | 42,315 |

5. **Tesseract:** not in the worker image (no binary, no pytesseract). Z-57 would need it added.

## Build (Part A, committed as 44245f1, 518c85f, 662f00a)

- **Worker.** Passes `scan_all=True` to the baseline only for `SCAN_PAGE_METHOD=all` with a
  single-value field list. E0 keeps working on this path.
- **Which docs.** Only docs with more than 8 page images take the new path. Others send the same
  request as v1.0 (tested).
- **Caps.** At most 40 images. The 60K input cap and the $ fuse are unchanged.
- **Metadata `scan_pages`:** `{method, pages_total, image_pages, pages_sent, cap, capped,
  page_numbers_set, page_numbers_dropped}`. The log line carries counts only.
- **Scripts.** `dry_run.py --scan-pages all`. `eval_dev` labels these docs `all:<sent>/<pages>`.

## Per doc and job (n = 3 candidate runs; run 174 shown separately)

| run | doc | score | wrong / missed / halluc | pages sent / total | tokens in | tokens out | $ | latency s | provider |
|---|---|---|---|---|---|---|---|---|---|
| 171 | lease_001 | 0.850 | 6 / 0 / 0 | 25/25 | 54,235 | 2,541 | 0.00669 | 33.2 | 200 stop |
| 172 | lease_001 | 0.900 | 4 / 0 / 0 | 25/25 | 54,235 | 2,684 | 0.00677 | 30.0 | 200 stop |
| 173 | lease_001 | 0.850 | 6 / 0 / 0 | 25/25 | 54,235 | 2,601 | 0.00672 | 24.2 | 200 stop |
| 171 | syn_lease_scan | 0.950 | 2 / 0 / 0 | 15/15 | 42,315 | 2,635 | 0.00555 | 17.8 | 200 stop |
| 172 | syn_lease_scan | 0.900 | 4 / 0 / 0 | 15/15 | 42,315 | 2,681 | 0.00557 | 16.2 | 200 stop |
| 173 | syn_lease_scan | 0.925 | 3 / 0 / 0 | 15/15 | 42,315 | 2,661 | 0.00556 | 15.6 | 200 stop |
| 174 | lease_001 | 0.825 | 7 / 0 / 0 | 25/25 | 54,235 | 2,688 | 0.00677 | 22.0 | 200 stop |
| 174 | syn_lease_scan | 0.925 | 3 / 0 / 0 | 15/15 | 42,315 | 2,659 | 0.00556 | 16.0 | 200 stop |

- **Request size.** The service does not log it. Computed from the same JPEGs (Part 0
  measurement): lease_001 ≈ 10.0 MB of base64 images; syn_lease_scan ≈ 4.0 MB. Every request was
  accepted. No 413, no size error, no retry. Ledger: all 43 calls in the hour of runs 171–173
  were `ok` / HTTP 200.
- **Per-type error buckets** (runs 171–173, cells per run):
  - Hallucinated: 0 on both docs in every run.
  - Missed: 0 on both docs in every run.
  - Wrong, lease_001: 4–6, all `text`. The fields are the long clause summaries:
    base_rent_escalation, expense_structure, electricity_provision, right_to_sublet, late_fee,
    holdover_rent.
  - Wrong, syn_lease_scan: 2–4 (1 `number`, 1–3 `text`).
- **Base, for comparison** (runs 104–106):
  - lease_001: wrong 8, missed 7–8.
  - syn_lease_scan: wrong 1, missed 33 per run. Its form pages were never seen.
- **$/doc, mean of 3 runs.** lease_001 0.00673 (base 0.00307). syn_lease_scan 0.00556 (base
  0.00302).
- **Latency.**

  | | base p50 / p95 | candidate p50 / p95 |
  |---|---|---|
  | lease_001 (n=3) | 13.1 / 16.8 s | 30.0 / 33.2 s |
  | syn_lease_scan (n=3) | 9.7 / 10.6 s | 16.2 / 17.8 s |
  | pooled (n=6) | 11.55 / 16.8 s | 21.0 / 33.2 s |

  p95 is the nearest rank, which is the maximum at this n.

## Gate arithmetic (Z-24 + Z-50 + Z-39, declared docs lease_001 + syn_lease_scan)

`compare_runs.py --base 104 105 106 --cand 171 172 173 --docs lease_001 syn_lease_scan`:

| check | result |
|---|---|
| mean ≥ base + 0.025 | pass: 0.8958 vs 0.3958 (+0.5000) |
| no DEV doc drop > 0.05 | pass: lease_001 +0.225 |
| hallucinations ≤ base (paired cells) | pass: 0.0 vs 0.0 |
| $/doc ≤ $0.01 | pass: $0.00614 |
| all VALID | pass: 0 invalid |
| collapses ≤ base | pass: 0 vs 0 |
| p50 ≤ 2 × base p50 (Z-39, pooled over declared-doc jobs as in P9b §5.3) | pass: 21.0 s vs 23.1 s limit |
| **verdict** | **PASS** |

Per doc, which Z-39 does not require: lease_001 30.0 / 13.1 = ×2.29 (over 2×), syn_lease_scan
16.2 / 9.7 = ×1.67.

**Must-not-error run 174 (`--set all`, 14 docs):**
- 14/14 SUCCESS, all VALID, mean 0.906, $0.03035 ($0.00217/doc), p50 5.5 s.
- Only the two scans took the `all` path. Every other doc reports `scan_pages=first`, since it has
  no page images or ≤ 8 of them.
- Context, not a gate (n = 1 each): t12_001 0.548 is its usual level (run 144: 0.5485).
  Hallucinations 45 = run 157 (44 rentroll_001 + 1 lease_002), none on the scans.

## Decision

- As pre-registered: the gate passed and run 174 passed, so **`SCAN_PAGE_METHOD=all` is the lab
  default**.
  - `app/config.py`: field default + `from_env` default.
  - `compose.yaml`: `${SCAN_PAGE_METHOD:-all}`.
  - `tests/test_shipped_config.py`, `tests/test_p8b.py`, `tests/test_p9e.py` updated.
  - `SCAN_PAGE_METHOD=first` reproduces v1.0, which the default-call tests prove.
- **For Hariom.** lease_001's own job latency roughly doubles (p50 13.1 → 30.0 s). This is
  allowed by the pooled rule but worth weighing against the load marks.
  - Long scans are rare in a mixed load, and run 174's overall p50 stayed 5.5 s.
  - A 25-page scan job now takes about 22–33 s.
- **Not changed.**
  - `dry_run.py` and `eval_dev`'s dry-run gate still plan `first` unless given `--scan-pages all`.
  - `scripts/render_docs.py` still describes `SCAN_PAGE_METHOD=first` as shipped. That is docs
    work for P9f.

## Where it fails

- **The 60K input cap limits a scan to about 21–27 pages, not 40.**
  - Real image tokens are w×h/750, about 2.1K per page at 1600 px for lease_001's page shape and
    about 2.6K for US letter.
  - So the v1.0 cap (60K estimated input) is reached at about 21 letter pages, or about 27 pages
    of lease_001's shape.
  - Later pages are dropped (`pages_dropped` in metadata), so the hole moves later but stays.
- **Scans over 40 pages:** first 40 only, if they fit the 60K cap, which at 1600 px they don't.
  `capped` is set in metadata.
- **Request size grows about 0.3–0.4 MB per page.** 25 pages ≈ 10 MB was accepted. The gateway's
  real ceiling is unmeasured, and so is its images-per-request limit beyond 25.
- **Latency grows with the page count:** about 1–1.5 s per page on Haiku here (15 pages p50
  16.2 s, 25 pages p50 30.0 s).
- **Handwriting, stamps, strike-throughs:** not measured; the SYN scan is typed.
- **Values a VLM may "correct"** (typos, odd spellings, inconsistent totals): not measured. Our
  docs have no such traps that we know of.
- **Scanned table field lists** do not take this path. They keep v1.0 (Z-48).
- **Wrong long-text fields remain** on lease_001: 4–6 clause summaries per run. That is wording,
  not missing pages.

## Spend

| item | $ |
|---|---|
| Part 0 + Part A | 0 |
| run 171 | 0.01224 |
| run 172 | 0.01234 |
| run 173 | 0.01229 |
| run 174 (full set) | 0.03035 |
| **P9e total** | **0.06722** (cap $0.15) |
| project running total | 1.055332 → **1.122552** |
| lab running total | ≈ 0.4885 → **≈ 0.5557** (cap $3) |

## Deviations

- Image size stays 1600 px long side, not ~1568. The renderer is shared with `first`, and
  changing it would change v1.0.
- The `all` path runs only when a doc has more than 8 page images. Shorter scans already send
  every page, and they keep the v1.0 request byte for byte.
- Z-39 was applied pooled over the declared-doc jobs, as in P9b §5.3. Per-doc figures are given
  above.
- `tests/test_e0.py`: the E0 worker-wiring test checks the exact kwargs, so it now pins
  `scan_page_method="first"`. With `all` the default, the worker also passes `scan_all` for
  single-value lists (a no-op on docs with ≤ 8 page images). Verified after the default change:
  pytest 752 passed, ruff clean, pre-commit 7/7.
- Part 0 used the DB `llm_calls` ledger (numeric columns only) to get real tokens per call.
- **Disclosure.** In Part 0, a `find` for run folders printed two directory names under
  `cache/`. Nothing was opened there.

## SELF-AUDIT

- [x] Default `first` reproduces v1.0 and the shipped-config test proves it. That held while
      `first` was the default (Part A). Now `all` is the lab default, and `first` still gives the
      v1.0 request (default-call tests).
- [x] Page tags and page numbers come from code. Invalid page numbers are dropped (tested).
- [x] Cap respected. No request near the price tier: the largest was 54,235 tokens in.
- [x] Gate as pre-registered, latency included. No held-out run or read.
- [x] Spend within cap ($0.06722 of $0.15). Running totals reported.
- [x] No commits, no stack restarts or env changes by the agent. No `.env`, answer files,
      held-out docs or `cache/` contents opened. Scratch only in `.scratch/`. No sample values in
      this report.
