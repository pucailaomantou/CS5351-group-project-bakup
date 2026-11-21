# CS5351 group project — status

Last updated: 2026-11-21

This is the single place to check what is done, what is frozen, and what is still open.
Update it when you merge something.

## Frozen

| what | value | set on |
|---|---|---|
| requirement id set | 10 ids: FR-01..05, INV-01..03, COST-01, GOV-01. Additions get new ids; existing ids are never renumbered. | 2026-11-17 |
| baseline commit | `9fa1196fffbcfd9de5146d2dd2869df84ab99838` | 2026-11-17 |
| upstream | https://github.com/tauricresearch/tradingagents | 2026-11-17 |
| source layout | `src/tradingagents/` (package), `src/cli/` and `src/main.py` beside it, `test/offline/`, `test/live/`. Upstream contents unmodified; see `BASELINE.md`. | 2026-11-19 |
| cost measurement point (superseded 2026-11-20) | NVDA / 2026-09-01, analysts market+news, research 1 round / risk 1 round, temperature 0.0, CS5351/DeepSeek-V4-Flash | 2026-11-18 |
| cost measurement point (superseded 2026-11-21) | NVDA / 2026-11-18, analysts market+news, research 1 round / risk 1 round, temperature 0.0, CS5351/DeepSeek-V4-Flash; ten valid runs, mean 163633.2, median 160664 | 2026-11-19 |
| cost measurement point (on main) | NVDA / 2026-11-19, analysts market+news, research 1 round / risk 1 round, temperature 0.0, CS5351/DeepSeek-V4-Flash, seven-day ticker news window anchored to the analysis date; 20/20/5; ten valid runs, mean 160315.8, median 159615; evidence `docs/evidence/cost01-2026-11-19/` | 2026-11-21 |
| after measurement (not a baseline) | NVDA / 2026-11-19, same protocol as the baseline, 8/8/3; ten valid runs, mean 147754.2, median 148087 | 2026-11-21 |
| effective cost config | `max_tool_rounds` 8, `news_article_limit` 8, `global_news_queries` 3 items, `global_news_article_limit` 10 | 2026-11-20 |

## Changes so far

| PR | what changed | why |
|---|---|---|
| #1 | `docs/req/requirements.yaml` (10 ids), `notes/three-changes.md`, `transcripts/60211808-袁舞扬.md` | D1 baseline |
| #2 | COST-01 `baseline` field filled with the measured ten-run mean | Workstream C measurement |
| #3 (superseded by #4) | COST-01 `fit_criterion` rewritten; `baseline_median` and `baseline_observations` added; `amended` records both revisions | the measurement invalidated the original criterion |
| #4 | COST-01 amendment merged to main | the measurement invalidated the original criterion |
| direct merge by A (no PR) | `BASELINE.md`; sources relocated under `src/`, tests under `test/` | vendoring: upstream version fixed, contents unmodified |
| #5 (merged) | `architecture-blueprint.md`; `docs/architecture/adr/001-bound-cost-at-tool-calls.md`; ADR 002 on context layers; FR-02 state contract | D2 architecture deliverable |
| #6 (merged) | COST-01 baseline migrated from 2026-09-01 to 2026-11-18; ten valid runs, mean 163633.2, median 160664; the two 141-row records excluded and retained | the 09-01 batch lacked data-integrity evidence, so the baseline was re-measured |
| #8 (merged) | `docs/evidence/cost01-2026-11-19/` — 40 files: 12 Before and 12 After raw records, protocol scripts, `SHA256SUMS.txt`, review tables | C's evidence package, so the 2026-11-19 figures can be recomputed from a clone |
| #9 (open) | `docs/report/`, `docs/evidence/c-debate-2026-11-19/`, `transcripts/`, `docs/review/` | C's report material, debate evidence, transcripts, and the cross-review memo for B |
| #10 (merged) | `test/offline/test_config_cost.py`, `test_debate_termination.py`, `test_rating_invariants.py` | E's verification work: adds offline tests for COST-01 (8/8/3), FR-02 (termination + convergence), and INV-01 (rating). All 25 tests passed. |
## Measurements on record

Two ten-run batches on NVDA / 2026-11-19 under one protocol, ten valid runs on each side,
temperature 0.0, analysts market+news, one research round, one risk round:

- Before: mean 160315.8, median 159615, min 145545, max 174399, CV 6.4%
- After: mean 147754.2, median 148087, min 132330, max 160591, CV 5.9%
- mean −7.84%, median −7.22%
- input −8.9% (136602.4 to 124466.1); output −1.8% (23713.4 to 23288.1)
- both sides carry five 252-row and five 264-row request ranges, so row count is not confounded
  with the comparison: 252 rows −10.54%, 264 rows −5.05%
- two Before records excluded (141-row market responses whose request range could not be
  independently evidenced), two After records excluded (one market timeout, one ssl_error). All
  four are retained and listed, not dropped.
- CV fell from 11.4% on the 2026-11-18 batch to 6.4% here, which measures the protocol, not the
  token level

This batch is the 2026-11-19 protocol measured twice: 20/20/5 before the tightening, 8/8/3 after. The 20/20/5 batch is the baseline now on main, at mean 160315.8; the 8/8/3 batch is the after measurement at 147754.2. The 2026-11-18 baseline (163633.2) and the 2026-09-01 batch (108901) are both superseded. The three are never mixed.

## Open questions

1. **Article counts are still not recorded per run.** The 2026-11-19 protocol anchors the news
   window, which removes the date distortion, but no per-run article count is captured, so the
   article axis still cannot be separated from the query axis. The input-side drop is consistent
   with both and isolates neither.
2. **Which lever binds, and through what.** `max_tool_rounds` did not bind at measurement time
   (observed rounds 3-5 against a cap of 20; the cap is now 8). The 8/8/3 tightening did move the total by 7.84%, and it
   moved on the input side only, so the levers do bind — but through query count, then article
   volume, then context length, not through the article limit acting directly on the total.
3. **The per-query article limit is still unverified.** `global_news_queries` is now a configured
   list of three queries and is read by the adapter, so the query axis is fixed rather than left to
   the model. `global_news_article_limit` remains 10 and no per-run article count is recorded, so
   whether that ceiling binds is still open.
4. **Convergence requires structured output, and the fallback rate is not measured.** The rule
   compares the stance signatures of successive rounds' idea cards, so a run whose structured
   output fell back to prose can never report `"converged"`. How often that happens is not
   recorded, so the share of runs structurally unable to converge is unknown.

## Rule for this file

When a PR merges, add one row to *Changes so far*. When something becomes fixed, add it to
*Frozen*. Do not delete rows; a status file that gets rewritten loses the record of why things
are the way they are.
