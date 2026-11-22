# 001 — Bound cost at the tool-call boundary, not at the round boundary

- Status: Proposed — not yet implemented
- Date: 2026-11-19
- Supersedes: the mechanism assumed by COST-01 as first written
- Related: COST-01, `architecture-blueprint.md`

## Context

COST-01 was written assuming that lowering `max_tool_rounds` from 20 to 8 would
reduce token usage. The baseline measurement contradicts that assumption.

Ten valid runs on NVDA / 2026-11-18 (`9fa1196`, temperature 0.0, analysts
market+news, one research round, one risk round):

| quantity | observed | configured | binds? |
|---|---|---|---|
| tool_rounds | 3-5 in every run | 20, target 8 | no |
| tool_calls | 20-28, mean 24.2 | no limit | — |
| global news articles | 30 or 70 | 10 per query × 5 queries | not shown to bind (superseded — see Addendum, 2026-11-20) |

Three correlations measured on the 2026-11-18 batch, whose run records are not in this repo:

- `r(tool_calls, total_tokens) = 0.79` — call count tracks cost.
- `r(input_tokens, total_tokens) = 0.9981` — cost is context size, and context grows with each
  tool result appended. This figure is Workstream C's recomputation from the run records; the
  index ships with C's review material (PR #9). An earlier draft of this ADR quoted 0.9995 here.
  That figure was measured on the withdrawn 2026-09-01 batch, not on this one.
  with each tool result appended.
- `r(global_articles, total_tokens) = -0.19` — article count does not predict cost;

One correlation in this ADR is checkable from a clone. Over the ten valid Before runs in
`docs/evidence/cost01-2026-11-19/records/before/`, `r(input_tokens, total_tokens) = 0.9874`.
Same relationship, lower figure, and the records ship with the repo, so a reader can recompute it
rather than take it on trust.
  the three 70-article runs averaged 158516 tokens, below the 165826 averaged by the
  seven 30-article runs.

A round is not a unit of cost. The loop allows several tool calls inside one round,
so a cap on rounds cannot bound the thing that actually grows the context. Reducing
the article count per fetch also fails to bind, because the model compensates by
issuing more calls.

The code shape constrains where a fix can go. `src/tradingagents/agents/tools.py` defines twelve
independent tool functions that the model calls directly; there is no dispatcher to
decrement a counter in. The only place tool usage is visible is `state["messages"]`,
and the only code that already reads it for cost purposes is the conditional edge in
`src/tradingagents/graph/setup.py`, which returns `wrap_up` once `rounds(state["messages"])` reaches
`max_tool_rounds`. That edge is also where the analyst loop closes, and all tool
calls happen in the analyst phase — the debate and risk phases call no tools.

## Decision

Enforce the cost budget on **tool calls**, at the one place that already observes
them, and demote `max_tool_rounds` to a coarse backstop.

- `max_tool_calls` is added to `src/tradingagents/default_config.py`, next to `max_tool_rounds`.
- The conditional edge in `src/tradingagents/graph/setup.py` counts tool calls across the analyst's
  messages instead of rounds, and routes to `wrap_up` when either limit is reached.
- The wrap-up instruction tells the agent how many calls it has left before the last
  round, so it can prioritise rather than discover the wall.
- `max_tool_rounds` stays at 8 as a backstop expected never to fire.
- `max_tool_calls` is validated against `max_recur_limit` in `src/tradingagents/graph/trading_graph.py`, where
  `max_tool_rounds` is already checked today (`2 * max + 2 >= max_recur_limit` raises).

## Consequences

Positive:
- The budget binds on the first run, so COST-01 becomes falsifiable rather than
  decorative. A run that exhausts it produces a visible, countable event.
- The check lives in an edge that already exists, so no new dispatch layer and no
  change to the twelve tool functions.
- It also caps pathological loops, which is what the round cap was meant to do.

Negative:
- **The budget can only act between rounds, not inside one.** Once the model emits a
  batch of parallel tool calls, that batch completes. So the limit is a ceiling on the
  next batch, not on the current one, and the overshoot is bounded by the largest
  batch observed, not by zero.
- Exhausting the budget degrades the analysis, and the resulting decision may rest on
  less data. That trade must stay visible, so `budget_exhausted` is written into the
  decision record alongside GOV-01's provenance fields rather than swallowed.
- The value has to be chosen against a measured baseline, so it inherits that
  baseline's instability.

To re-measure: the same ten-run protocol, recording `tool_calls`, `tool_rounds`,
`budget_exhausted` and the token total per run.

## Alternatives considered

- **Lower `max_tool_rounds` further, to 3.** Rejected: rounds are 3-5 today, so 3 would bind in
  some runs by accident, and it would truncate the analysts' tool use, not the debate. The debate
  is bounded by `max_debate_rounds`, which is a separate control on a separate loop, so tightening
  the tool-round cap to steer cost couples the analyst loop to a knob that does not govern it.
- **Cap article counts harder.** Rejected: the measured correlation between article
  count and cost is negative, so the mechanism is unsupported.
- **Cap context size at the LLM client.** Rejected for now: it is the most direct
  control, but it sits below the point where the system can tell an agent to
  prioritise, so the model would be truncated without warning.

## Evidence

- `docs/req/requirements.yaml`, COST-01 `baseline_observations` — the batch aggregate and the
  validity rules. Since the 2026-11-19 migration this entry no longer carries the per-run
  correlations quoted in Context, and it never carried the run records themselves.
- `docs/evidence/cost01-2026-11-19/` — both 2026-11-19 batches, twelve Before and twelve After
  raw records, so the 160315.8, 147754.2 and 0.9874 figures in this ADR can be recomputed from a
  clone. The 2026-11-18 batch is not committed: its records remain Workstream C local, so the
  0.79, 0.9981 and -0.19 correlations and the 163633.2 baseline cannot be verified this way.
- PR #3, #4 and #5 discussion

## Addendum, 2026-11-20

The 2026-11-19 comparison measures 20/20/5 against 8/8/3 under a single protocol and
finds a 7.84% drop in mean total tokens (160315.8 to 147754.2), with input tokens falling
8.9% and output tokens 1.8%. That contradicts the Context table above, which recorded the
article and query limits as "not shown to bind".

The revision is partial, not a refutation of the decision:

- The drop is input-side, consistent with fewer global news queries (5 to 3) returning
  fewer articles and therefore a shorter context. It is not evidence that
  `max_tool_rounds` binds; rounds stayed at 3-5 in every run of both batches.
- The 2026-11-18 measurement could not separate the article axis, but not because that
  measurement was defective. All ten runs in it completed with `data_fetch.complete = true`,
  non-empty ticker and global news, and `market_rows = 252`, so it is a valid measurement. What
  it lacked was a per-run article count that could be joined to the token totals, and the counts
  it did report split 30 against 70 under a constant five-query configuration, so the article
  limit was not binding in a way that could be isolated. The fetch failure on that date belongs
  to a different run: the **After** attempt, whose quote feed returned only items dated after
  `as_of`. That is a fetch failure in the After run, not a distortion of the Before measurement.
  The 2026-11-19 protocol anchors the news window and removes the fetch failure.
- What survives is the narrower claim: a round cap does not bound cost. The call budget in
  the Decision remains the control that acts on the quantity observed to move.

For the record: "not shown to bind" was a statement about one batch's data, written as if
it were a statement about the mechanism. It should have been scoped to that batch.
