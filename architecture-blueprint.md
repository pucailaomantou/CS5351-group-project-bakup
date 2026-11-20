# Architecture blueprint

Describes commit `786671f`: upstream `9fa1196`, sources under `src/`, contents
unchanged. Requirements are the ten frozen ids in `docs/req/requirements.yaml`.

## 1. Runtime pipeline
analyst phase market and news analysts fetch data through tool calls
|
research debate bull <-> bear, adjudicated by research_manager
|
trader trader proposes an action
|
risk debate aggressive / neutral / conservative
|
portfolio manager emits final_trade_decision and final_rating
|
consumers src/cli/display.py, src/tradingagents/reporting.py, src/tradingagents/report_html.py, src/tradingagents/memory/log.py, src/tradingagents/portfolio.py

The last row is what this blueprint is organised around: five consumers, and no
single point all of them pass through.

## 2. Module map

| area | modules | responsibility |
|---|---|---|
| orchestration | `src/tradingagents/graph/setup.py`, `src/tradingagents/graph/trading_graph.py`, `src/tradingagents/graph/conditional_logic.py`, `src/tradingagents/graph/propagation.py`, `src/tradingagents/graph/analyst_execution.py` | wire the agents, own the loop and its termination conditions |
| agents | `src/tradingagents/agents/analysts/*`, `src/tradingagents/agents/researchers/*`, `src/tradingagents/agents/risk_mgmt/*`, `src/tradingagents/agents/trader/trader.py`, `src/tradingagents/agents/managers/*` | one node each; prompt in, structured output out |
| contract | `src/tradingagents/agents/state.py`, `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/rating.py`, `src/tradingagents/agents/structured.py` | the shapes that cross a node boundary, and the enum guarding the final rating |
| data | `src/tradingagents/dataflows/router.py`, `src/tradingagents/dataflows/date_window.py`, `src/tradingagents/dataflows/vendors/*` | vendor dispatch, date clamping, per-vendor fetch |
| cost | `src/tradingagents/default_config.py`, `src/tradingagents/agents/tools.py` | the configured limits, and the tool functions the model calls directly |
| provenance | `src/tradingagents/memory/log.py`, `src/tradingagents/memory/settlement.py` | the decision record |
| surface | `src/cli/*`, `src/tradingagents/reporting.py`, `src/tradingagents/report_html.py` | display and export |

## 3. Requirement to touchpoint

| id | touchpoint | kind of change |
|---|---|---|
| FR-01 | `src/tradingagents/agents/researchers/bull_researcher.py`, `src/tradingagents/agents/researchers/bear_researcher.py`, `src/tradingagents/agents/managers/research_manager.py`, `src/tradingagents/agents/state.py` | idea-card schema added to the debate state; prompts rewritten; manager adjudicates from cards |
| FR-02 | `src/tradingagents/graph/conditional_logic.py`, `src/tradingagents/graph/setup.py`, `src/tradingagents/agents/state.py` | record termination reason and convergence rounds on exit; convergence detection deferred |
| FR-03 | `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/managers/portfolio_manager.py` | four required fields; a validator that rejects a partial record |
| FR-04 | `src/tradingagents/llm_clients/*`, `src/cli/stats_handler.py`, new exporter | usage accounting exists only in the CLI callback (`tokens_in`/`tokens_out` off `AIMessage.usage_metadata`); the core package never reads usage, so an aggregate has to be lifted out of the callback and exposed programmatically |
| FR-05 | new `src/tradingagents/safety/guard.py`, wired in `src/tradingagents/graph/setup.py` | deterministic gate on the only path from decision to consumer |
| INV-01 | `src/tradingagents/agents/rating.py`, `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/state.py` | the enum exists; add the REVIEW-is-not-tradeable rule where a rating becomes a position |
| INV-02 | `src/tradingagents/agents/schemas.py`, `src/tradingagents/safety/guard.py` | position_sizing is free text today; parse to a percentage, apply the cap, unparseable resolves to REVIEW |
| INV-03 | `src/tradingagents/dataflows/date_window.py`, `src/tradingagents/agents/state.py` | `as_of` clamps future data only; a stale-input check belongs at the decision layer |
| COST-01 | `src/tradingagents/default_config.py`, `src/tradingagents/agents/tools.py` | three config values; the current implementation is config tightening plus measurement, and the tool-call budget proposed in ADR 001 is not yet in the code |
| GOV-01 | `src/tradingagents/memory/log.py`, `src/tradingagents/agents/state.py` | four provenance fields written in the same commit as the decision |

## 4. State contract for FR-02

Two fields are added to `InvestDebateState`, not to the top-level `AgentState`, because
they describe the investment debate only. The risk debate is not changed in this
deliverable.

| field | type | written by | read by | allowed values |
|---|---|---|---|---|
| `count` (existing) | int | incremented by the debate loop per speaker turn | the termination check in `src/tradingagents/graph/conditional_logic.py` | 0 .. 2 x `max_debate_rounds` |
| `convergence_rounds` (new) | `int \| None` | `src/tradingagents/graph/conditional_logic.py`, at the exit point | the decision record in `src/tradingagents/memory/log.py`; the FR-02 test | `None`, or the round at which convergence was detected |
| `termination_reason` (new) | str | same point, same write | same | `"converged"` or `"max_rounds"` |

Three constraints:

- **`count` is speaker turns, not rounds.** Each round has a bull turn and a bear turn, so
  `count` runs at twice the round count. Any code that reports a round number must divide.
- **`convergence_rounds` is `None` when the debate did not converge.** It is not a copy of
  the number of rounds run: a run that hit the cap reports `None`, and the round count is
  recovered from `count`. Reporting the rounds run in this field would carry no information
  the state does not already hold, and would make the field unassertable as evidence of
  convergence.
- **`termination_reason` is written in the same place as the routing decision, and both
  fields are written together.** A reader must never see the debate finished with a reason
  but no convergence round, or the reverse.

### Why convergence is not claimed

The research manager runs once, after the debate, rather than once per round. There is
therefore no per-round verdict to compare, and no deterministic signal in
`InvestDebateState` that indicates agreement. Convergence detection is deferred: in every
run of this deliverable `convergence_rounds` is `None` and `termination_reason` is
`"max_rounds"`, and the FR-02 test asserts exactly that. A rule that reads the debate text
and judges whether the participants agreed cannot be tested, and would leave FR-02 as
unfalsifiable as COST-01 was before its first amendment; if detection is added later it
needs its own detector and its own criterion.

## 5. Seams

A seam is a place where a change is allowed to cross a module boundary. There are
four, and every requirement above lands on one of them.

1. **Decision boundary.** Everything a consumer may read passes `src/tradingagents/safety/guard.py`.
   No consumer keeps a bypass. This is what makes FR-05, INV-01, INV-02 and INV-03
   checkable by one assertion instead of four.
2. **Tool-usage boundary.** There is no dispatcher to hook: `src/tradingagents/agents/tools.py` defines
   twelve tool functions that the model calls directly, and the only place tool usage
   is observable is the message history. The conditional edge in `src/tradingagents/graph/setup.py`
   already reads it to choose between another round and `wrap_up`, so a call budget
   belongs there. Measured rounds 3-5 against 20-28 calls, so the round count is the
   wrong unit. All tool calls happen in the analyst phase, so the limit is scoped
   there and not to the debate or risk phases.
3. **Date boundary.** `src/tradingagents/dataflows/date_window.py` is the only place a window is
   computed. `as_of` clamps future data but does not detect stale data, so INV-03
   needs an added check rather than a change here.
4. **Record boundary.** `src/tradingagents/memory/log.py` is the only writer of the decision log, so
   GOV-01's four fields go there rather than into each consumer.

5. **Context boundary.** Of the five context layers, only one is compactable: the tool
   results in `messages`, which the `add_messages` reducer inherited from `MessagesState`
   makes append-only. The check sits at the conditional edge in
   `src/tradingagents/graph/setup.py` that already reads the history. The other four layers
   are pinned because a criterion or a downstream agent reads them directly — FR-02 reads
   `count` and the debate state, and the manager agents read the report fields. Compaction
   therefore cannot invalidate a criterion. See ADR 002.

## 6. Out of scope

- The vendor layer, beyond the news-window change already made. No other requirement needs
  an edit under `src/tradingagents/dataflows/vendors/*`, and the rest stays as vendored.
- The LLM client layer, except reading usage out of it.
- The risk debate. FR-02's two fields are added to `InvestDebateState` only; `RiskDebateState`
  keeps its current shape in this deliverable.

## 7. How this is verified

`test/offline/` covers everything deterministic: the guard, the rating enum, the
position parser, the date check, the config values. `test/live/` covers the pipeline
running against the real endpoint, which is the only place token accounting and the
tool-call budget can be observed. COST-01 and FR-04 are the two requirements that
cannot be verified offline.
