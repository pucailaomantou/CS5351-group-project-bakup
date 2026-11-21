# CS5351 group project — status

Last updated: 2026-11-19

This is the single place to check what is done, what is frozen, and what is still
open. Update it when you merge something.

## Frozen

| what | value | set on |
|---|---|---|
| requirement id set | 10 ids: FR-01..05, INV-01..03, COST-01, GOV-01. Additions get new ids; existing ids are never renumbered. | 2026-11-17 |
| baseline commit | `9fa1196fffbcfd9de5146d2dd2869df84ab99838` | 2026-11-17 |
| upstream | https://github.com/tauricresearch/tradingagents | 2026-11-17 |
| cost measurement point | NVDA / 2026-09-01, analysts market+news, research 1 round / risk 1 round, temperature 0.0, CS5351/DeepSeek-V4-Flash | 2026-11-18 |

## Changes so far

| PR | what changed | why |
|---|---|---|
| #1 | `docs/req/requirements.yaml` (10 ids), `notes/three-changes.md`, `transcripts/60211808-袁舞扬.md` | D1 baseline |
| #2 | COST-01 `baseline` field filled with the measured ten-run mean | Workstream C measurement |
| #3 (open) | COST-01 `fit_criterion` rewritten; `baseline_median` and `baseline_observations` added; `amended` records both revisions | the measurement invalidated the original criterion |
| \#4 (open) | E's verification work: 5 intentional red lights for COST-01 and FR-02, 17 passes for existing logic |  |

## Measurements on record

Ten runs at the baseline commit, all `succeeded`, `usage_complete = true`,
`commit_matches = true`:

- total tokens: mean 108901, median 92713, min 80968, max 167483
- tool_calls 12-25; tool_rounds 3-5 in every run
- r(tool_calls, total_tokens) = 0.90; r(input_tokens, total_tokens) = 0.9995
- tokens per tool call stayed at 4859-7613, so the call count moves, not the payload

Raw records live in `c-baseline-work/results/` (Workstream C, local, not in this
repo).

## Open questions

1. **Article counts for the baseline batch were never recorded.** A table of ten
   runs was circulated, but its run ids (`125350`, `133107`, ...) and clock times
   (12:53-14:19) do not match the evidence pack (`20261118_163055_da813fb3`,
   16:30-17:37), and none of those ids appear inside the pack, so the table
   appears to come from a different batch and cannot be joined. Until this is
   resolved, the effect of `news_article_limit` on the token target cannot be
   separated from the effect of the global query count.
2. **Two of COST-01's three levers may not bind.** `max_tool_rounds` is
   unreachable (observed rounds 3-5 against a configured cap of 20);
   `news_article_limit` is unconfirmed. Only `global_news_queries 5 -> 3` has a
   clear mechanism, and even that acts through article volume rather than
   directly on the token total.
3. **`global_news_article_limit` appears not to be enforced.** The configured
   ceiling is 10 articles per query over 5 queries, i.e. at most 50 articles, yet
   70 were reported for some runs. This needs a code read before it can become an
   ADR.

## Rule for this file

When a PR merges, add one row to *Changes so far*. When something becomes fixed,
add it to *Frozen*. Do not delete rows; a status file that gets rewritten loses
the record of why things are the way they are.
