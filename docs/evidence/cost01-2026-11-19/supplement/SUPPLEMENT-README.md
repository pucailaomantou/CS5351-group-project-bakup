# Before supplement — market evidence capture (analysis date 2026-11-19)

Candidate experiment, pending B/E. No source tree, model, requirement or historical
experiment was modified. Everything here is experiment-layer.

## What this supplement does
Re-runs exactly two TRUE Before analyses for the FIXED analysis date **2026-11-19**
(never auto-changed to today), replacing the two 141-row Before samples that B/E
excluded for lack of independent market evidence. Each re-run additionally captures a
side-channel market-evidence manifest proving the request range and the verbatim tool
response.

## Versions (verified this supplement)
- Before: `tradingagents-upstream @ 9fa1196` (cleaner than dirty; import path verified),
  `news.py` sha `9f56dcc58bae002a4e7c19e0f659504fabfb7132aef535e248bc7d080b30b7eb`.
- Config: 20/20/5, DeepSeek-V4-Flash, temperature 0.0, analysts market+news,
  debate/risk rounds 1/1; independent memory/cache/results.
- Same `d4_news_window_adapter` (7-day ticker window anchored to trade_date=11-19)
  as the original batch. Adapter SHA recorded per run.

## Cross-UTC-day fact (comparability limit)
- Analysis date (fixed): **2026-11-19**.
- Actual UTC execution date: **2026-11-20** (batch start 2026-11-20T03:41:50Z;
  runs began UTC 11:42). So these two samples are a **cross-UTC-day supplement**.
- Recorded per run as `provenance.cross_utc_day_supplement=true`,
  `run_started_utc_date=2026-11-20`, `analysis_date=2026-11-19`.
- Implication: the different execution time may affect the news obtainable within the
  window and the market closing/last values; the size of the difference is not
  quantified. The analysis date and the news filter window remain fixed at 11-19. This
  is a stated limitation for B/E, not hidden.

## Supplement runs (both valid, both with market evidence)
| run_id | valid | market_rows | request range | header range | rows | ticker/global news | total |
|---|---|---|---|---|---|---|---|
| 20261120_114222_f2932b46 | True | 252 | 2025-11-19..2026-11-19 | 2025-11-19..2026-11-19 | 252 | 6 / 70 | 173115 |
| 20261120_114441_2a33e022 | True | 264 | 2025-11-01..2026-11-19 | 2025-11-01..2026-11-19 | 264 (2025-11-03..2026-11-19) | 6 / 70 | 164203 |

Market evidence per run: `market_evidence/<run_id>_market_evidence.json` +
`market_evidence/<run_id>_stock_0.txt` (verbatim ToolMessage text, SHA256 recorded).
The request args are the model's actual `get_stock_data` call; the response is the
exact `ToolMessage` of the matching `tool_call_id` tee'd from the graph's own stream
(not the cache, not the analyst report, not a re-query).

## Evidence gap (Before)
- Before still keeps NO provider fixtures for news/other tools (only market evidence
  was side-captured here). Before inputs are therefore NOT fully replayable; only the
  market get_stock_data request→response for these two runs is proven.

## Revised Before statistics (n=10: original 8 kept + these 2)
- total: mean **160315.8**, median **159615.0**, min 145545, max 174399, sum 1603158.
- input mean 136602.4; output mean 23713.4.
- The old values (153510.4 / 154416.5) and the old delta percentage are NOT used.

## Comparison with the retained After (n=10 valid, not re-run)
- After total: mean **147754.2**, median **148087.0**.
- After mean < Before mean (147754.2 < 160315.8): **True** (−7.84%).
- After median < Before median (148087.0 < 159615.0): **True** (−7.22%).

## Exclusion of the two 141-row records (unchanged originals)
`20261120_032135_28a781b6`, `20261120_032332_fe83feb4` are marked
**excluded_per_BE** in `SAMPLE-LIST-REVISED.csv`; their original JSON and `valid`
field are untouched. They are preserved, not deleted.

## Files
- supplement runs + evidence: `docs/evidence/cost01-2026-11-19/`
- summary: `docs/evidence/cost01-2026-11-19/review/summary_revised.json`
- sample list: `docs/evidence/cost01-2026-11-19/review/SAMPLE-LIST-REVISED.csv`
- market evidence rows appended to `docs/evidence/cost01-2026-11-19/review/MARKET-EVIDENCE.csv`
