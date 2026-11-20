# C candidate review — REVISED (before supplement; analysis date 2026-11-19)

This supersedes the pre-supplement review narrative. The two excluded 141-row Before
records are replaced by two re-run Before samples that carry direct market evidence.
All source trees, models, requirements and historical experiments are unchanged.

## 1. Protocol
- Analysis date: **2026-11-19** (fixed). Live Yahoo, intraday permitted.
- The two Before re-runs executed on **UTC 2026-11-20** — a **cross-UTC-day
  supplement** (stated limitation; recorded in each run's provenance).
- Fixed news adapter NOT used; the 7-day ticker news window adapter IS used (same as
  the original batch). Before = upstream 9fa1196 20/20/5; After = current 8/8/3.
- Model DeepSeek-V4-Flash, temperature 0.0, analysts market+news, rounds 1/1.

## 2. Sample accounting
- Before attempted this supplement: 2; runner-valid: 2; both with market evidence.
- Before excluded per B/E: `20261120_032135_28a781b6`, `20261120_032332_fe83feb4`
  (141 rows; originals untouched, marked excluded_per_BE).
- Before final included: **10** = original 8 kept + 2 supplement.
- After: attempted 12, valid **10** (kept, NOT re-run), invalid 2
  (`20261120_035236_01461635` market timeout; `20261120_040304_484e3073` ssl_error).
- Deduplicated by run_id; selection is NOT by token value.

## 3. Market evidence (this supplement)
`MARKET-EVIDENCE.csv` holds 24 rows in total: the original 22 rows (which already
include the two After-failure records) plus the two appended Before supplement rows.
Each supplement row proves:
request args (model's call) → header range → row count → first/last date →
verbatim raw response file + SHA256. See supplement `market_evidence/`.

## 4. Revised statistics (valid only)
| | Before n=10 | After n=10 |
|---|---|---|
| total mean | **160315.8** | **147754.2** |
| total median | **159615.0** | **148087.0** |
| total min/max | 145545 / 174399 | 132330 / 160591 |

- After mean < Before mean: **True** (−7.84%).
- After median < Before median: **True** (−7.22%).
- Old Before 153510.4 / 154416.5 and the old delta are NOT used.

## 5. Evidence limitations requiring E confirmation
- Cross-UTC-day supplement: the two Before re-runs were executed UTC 2026-11-20, not
  11-19. The different execution time may affect the news obtainable within the window
  and the market closing/last values; the size of the difference is not quantified. The
  analysis date and the news filter window remain fixed at 11-19.
- Before news/other inputs are still not fixture-recorded → Before is not fully
  replayable; only the two suppliers' market request→response is proven here.
- The other 8 Before samples still lack direct request-range evidence (only market
  evidence CSV historical note); this supplement does not retro-fix them.

## 6. Files
- `MARKET-EVIDENCE.csv` (+2 supplement rows), `SHA256SUMS.pre-supplement.txt`,
  `SAMPLE-LIST-REVISED.csv`, `summary_revised.json`, this file.
- supplement evidence: `docs/evidence/cost01-2026-11-19/supplement/`
