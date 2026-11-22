# 002 — Layer the context, compact only tool results, re-inject a fixed set

- Status: Proposed — not yet implemented, except the cross-run re-injection in Decision 4,
  which already exists
- Date: 2026-11-20
- Related: COST-01, FR-04, `architecture-blueprint.md`, ADR 001

## Context

A run's context is not one thing. It is five things with different lifetimes, and only one
of them grows without a bound.

| layer | what it holds | where it lives | grows during a run? |
|---|---|---|---|
| system prompts | each agent's role and output contract | the agent modules | no, fixed |
| analyst reports | four structured reports, written once each | `AgentState` fields (`market_report`, `sentiment_report`, `news_report`, `fundamentals_report`) | no, one write per analyst |
| tool results | the raw return of every tool call, appended to the message history | `messages`, via the `add_messages` reducer inherited from `MessagesState` | **yes, unbounded** |
| debate history | bull and bear turns, counted by `count` | `investment_debate_state` | yes, bounded by `2 x max_debate_rounds` |
| cross-run memory | lessons from settled past decisions, 2-4 sentences | `memory_note`, loaded at run start | no, fixed size |

The growth is structural, not incidental. `AgentState` inherits `MessagesState`, so `messages`
is append-only: every tool result stays in the history for the rest of the run, and every
subsequent model call in that agent's phase re-reads it. The cost measurement supports this:
over the ten valid Before runs of the 2026-11-19 baseline, measured at 20/20/5,
`r(input_tokens, total_tokens) = 0.9874`; over the After batch measured at 8/8/3, input is 124k
of the 147k mean total. In both batches cost is dominated by what the model re-reads rather than
what it writes.

There is exactly one bound today, and it is the wrong unit. `max_recur_limit: 100`
(`src/tradingagents/default_config.py`) is passed to LangGraph as `recursion_limit`
(`src/tradingagents/graph/propagation.py`), which counts super-steps, not tokens. A single
tool call that returns 30,000 tokens consumes one step. A step count cannot bound a size.

Re-injection is not missing, it is narrow. `Reflector.reflect_on_final_decision`
(`src/tradingagents/memory/reflection.py`) asks the model for 2-4 sentences explicitly
"compact enough to be re-injected into future agent prompts without bloating the context
window", and `_memory_step` (`src/tradingagents/graph/trading_graph.py`) loads those lessons
through `get_past_context(company, as_of=...)` into `memory_note`. So the pattern exists
across runs. Nothing applies it inside a run.

## Decision

**1. Classify the layers, and compact only the tool results.** The other four are pinned. The
analyst reports and the debate history are not eligible for compaction because other
requirements read them directly: FR-02 reads `count` and the debate state, and the manager
agents read the report fields. Compacting a value that a criterion asserts on would make the
criterion untestable. Tool results are the only layer that is both unbounded and unread by
any criterion.

**2. Trigger on a token threshold at the analyst loop boundary, not on steps.** The check
belongs at the conditional edge in `src/tradingagents/graph/setup.py` that already inspects
the message history to decide between another round and wrap-up; that is the only point where
the loop is between rounds and the history is readable.

The threshold is a ratio of the model's declared context window rather than a fixed token
count, because a hardcoded number drifts the moment the model changes and cannot be justified
against a window the configuration does not record. The live context is estimated rather than
counted. The default estimator is `ceil(characters / 4)` over the concatenated message content:
an approximation whose error is small on prose and worse on markdown tables, and deliberately a
pure function of the text so that it can be exercised offline and replaced by a real tokeniser
without touching the threshold logic. The estimator is injected, not called directly, so the
offline test supplies an exact counter and asserts the trigger fires at the boundary. If no
estimator is configured, the check fails closed rather than assuming a window size.

**3. Compact by deterministic digest, not by asking a model to summarise.** The digest is
built mechanically from fields the tool already returns, in two tiers:

| tier | fields | applies to |
|---|---|---|
| mandatory | tool name, the arguments it was called with (ticker, requested date range, limit), response length in characters | every tool |
| tabular | row count, first and last timestamp in the payload | tools that declare a tabular shape, such as the price and indicator tools |

The tabular tier is not universal, and pretending otherwise would produce empty fields for the
news tools, whose payload is prose rather than rows. A news result therefore digests to its
query, its character length, and the earliest and latest publication date present in the
payload when a date is present at all. The rule is that the mandatory tier is always
satisfiable and the tabular tier is asserted only for tools that declare it, so the digest is
testable per tool class rather than only in aggregate.

**4. Re-inject a fixed set after compaction, and state it as a closed list.** What a later
agent must not lose is small: the analysis date and `as_of`, the resolved instrument context,
the analyst reports already written, and `memory_note`. The first three are already typed
state fields, so compacting `messages` does not touch them; that is why this design is safe
where a naive message-trimming approach would not be. The re-injection set is closed so that a
test can assert the post-compaction state contains all four, and the digest carries the tool
provenance that the raw results used to carry.

**5. Compact in place; never remove a message.** Compaction rewrites the `content` of the
`ToolMessage` and keeps the message, its `tool_call_id` and its position. The message list is
handed to the provider as-is, so deleting a tool result while the assistant turn that requested
it still carries the `tool_call` produces a request the provider rejects outright. Replacing
rather than deleting also keeps the history length stable, which makes the compaction event
observable as a content change instead of a disappearance.

## Consequences

Positive:

- The bound becomes a size, so it acts on the quantity that the measurement shows moves.
  Under ADR 001 the same reasoning applies to tool calls; this ADR applies it to bytes.
- Compaction is checkable in two independent ways: the digest can be verified against the raw
  response, and the re-injection set can be asserted as present.
- Because the compactable layer is disjoint from every field a criterion reads, adding
  compaction cannot invalidate COST-01, FR-02 or GOV-01.

Negative:

- **A digest is lossy, and the loss is not recoverable inside the run.** If a later agent
  needs a number that only the raw payload contained, the digest will not have it, and the
  agent will either re-fetch — raising cost, the opposite of the intent — or reason without it.
  This is the main risk and the reason the digest carries the requested range and row count:
  those are enough to detect that a re-fetch would return the same data.
- Compaction adds a state transition that did not exist, so it needs its own test and its own
  failure mode. A digest that is wrong is worse than no digest, because it is silently trusted.
- The threshold ratio is a judgement, not a measurement. Unlike COST-01 there is no baseline
  that says where it should sit, so the first value is a hypothesis to be revised by the same
  evidence discipline, not a derived result.

## Alternatives considered

- **`trim_messages` at the LLM client.** Rejected: it is the simplest control, but it drops
  messages without telling the agent, so the model is silently truncated mid-phase and cannot
  prioritise. It also cannot distinguish a tool result from a report.
- **Summarise with a model.** Rejected for now: it makes the compressor a second source of
  error, doubles the number of calls whose cost must be attributed under FR-04, and produces
  an artefact that cannot be asserted against the original.
- **Hard truncation of old messages.** Rejected: it deletes the tool provenance that GOV-01
  depends on and leaves no record that a truncation happened, so a degraded run would be
  indistinguishable from a clean one.
- **Lower `max_recur_limit`.** Rejected: it is a step count. Lowering it truncates the graph
  rather than the context, which is the same category error as bounding cost by rounds in
  ADR 001.

## Evidence

- `src/tradingagents/agents/state.py` — `AgentState(MessagesState)`, the four report fields,
  `InvestDebateState.count`
- `src/tradingagents/graph/propagation.py` — `max_recur_limit` passed as `recursion_limit`;
  `memory_note` initialised empty
- `src/tradingagents/default_config.py` — `max_recur_limit: 100`
- `src/tradingagents/graph/setup.py` — the conditional edge that already reads the history
- `src/tradingagents/memory/reflection.py` — the 2-4 sentence re-injection contract
- `src/tradingagents/graph/trading_graph.py` — `_memory_step`, `get_past_context(..., as_of=...)`
- COST-01 `baseline_observations` — the batch aggregate and the validity rules. It does not
  carry the per-run correlations cited above, and it never carried the run records.
- `docs/evidence/cost01-2026-11-19/` — the run records behind the 11-19 figures quoted in
  Context, committed, so they can be recomputed from a clone. The 2026-11-18 batch is not
  committed and the 0.9995 correlation quoted in Context belongs to the withdrawn 2026-09-01
  batch; neither can be checked from a clone.
