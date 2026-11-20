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
| contract | `src/tradingagents/agents/state.py`, `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/rating.py`, `src/tradingagents/agents/structured.py`, `src/tradingagents/agents/researchers/debate.py`, `src/tradingagents/agents/researchers/debate_schemas.py` | the shapes that cross a node boundary, and the enum guarding the final rating |
| data | `src/tradingagents/dataflows/router.py`, `src/tradingagents/dataflows/date_window.py`, `src/tradingagents/dataflows/vendors/*` | vendor dispatch, date clamping, per-vendor fetch |
| cost | `src/tradingagents/default_config.py`, `src/tradingagents/agents/tools.py` | the configured limits, and the tool functions the model calls directly |
| provenance | `src/tradingagents/memory/log.py`, `src/tradingagents/memory/settlement.py` | the decision record |
| surface | `src/cli/*`, `src/tradingagents/reporting.py`, `src/tradingagents/report_html.py` | display and export |

## 3. Requirement to touchpoint

| id | touchpoint | kind of change |
|---|---|---|
| FR-01 | `src/tradingagents/agents/researchers/bull_researcher.py`, `src/tradingagents/agents/researchers/bear_researcher.py`, `src/tradingagents/agents/managers/research_manager.py`, `src/tradingagents/agents/state.py` | idea-card schema added to the debate state; prompts rewritten; manager adjudicates from cards |
| FR-02 | `src/tradingagents/agents/researchers/debate.py`, `src/tradingagents/agents/researchers/bear_researcher.py`, `src/tradingagents/agents/managers/research_manager.py`, `src/tradingagents/agents/state.py` | record why the debate stopped and after how many rounds; convergence is decided structurally from the idea cards, so the reason is never a model opinion |
| FR-03 | `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/managers/portfolio_manager.py` | four required fields; a validator that rejects a partial record |
| FR-04 | `src/tradingagents/llm_clients/*`, `src/cli/stats_handler.py`, new exporter | usage accounting exists only in the CLI callback (`tokens_in`/`tokens_out` off `AIMessage.usage_metadata`); the core package never reads usage, so an aggregate has to be lifted out of the callback and exposed programmatically |
| FR-05 | new `src/tradingagents/safety/guard.py`, wired in `src/tradingagents/graph/setup.py` | deterministic gate on the only path from decision to consumer |
| INV-01 | `src/tradingagents/agents/rating.py`, `src/tradingagents/agents/schemas.py`, `src/tradingagents/agents/state.py` | the enum exists; add the REVIEW-is-not-tradeable rule where a rating becomes a position |
| INV-02 | `src/tradingagents/agents/schemas.py`, `src/tradingagents/safety/guard.py` | position_sizing is free text today; parse to a percentage, apply the cap, unparseable resolves to REVIEW |
| INV-03 | `src/tradingagents/dataflows/date_window.py`, `src/tradingagents/agents/state.py` | `as_of` clamps future data only; a stale-input check belongs at the decision layer |
| COST-01 | `src/tradingagents/default_config.py`, `src/tradingagents/agents/tools.py` | the three config values are set to 8 / 8 / 3 in `src/tradingagents/default_config.py`; the tool-call budget proposed in ADR 001 is still not implemented |
| GOV-01 | `src/tradingagents/memory/log.py`, `src/tradingagents/agents/state.py` | four provenance fields written in the same commit as the decision |

## 4. State contract for FR-02

The debate's outcome lives on `InvestDebateState`, written by the researchers rather than by
the routing edge. The bear speaks second in each round, so its node closes the round and
records the outcome; `src/tradingagents/graph/conditional_logic.py` only reads `count` to
decide whether another round starts.

| field | type | written by | read by | allowed values |
|---|---|---|---|---|
| `count` (existing) | int | each researcher node, once per turn | the continuation check in `src/tradingagents/graph/conditional_logic.py` | 0 .. 2 x `max_debate_rounds` |
| `debate_rounds` | list | `src/tradingagents/agents/researchers/bear_researcher.py`, at round close | the record builder in `src/tradingagents/agents/researchers/debate.py` | one entry per completed round |
| `convergence_rounds` | `int \| None` | same point | the decision record; the FR-02 test | the round index at which convergence held, or `None` |
| `termination_reason` | str | same point | same | `"converged"` or `"max_rounds"` |

### How convergence is decided

The rule is structural and needs no model call, so the termination reason is never a model's
opinion. A round converges when each side's newly added cards carry the same stance signature
as the cards that side added in the previous round: the participants are still speaking, but
they are no longer saying anything new. Both sides must agree before the round counts.

The empty case is excluded by construction. A side that produced no cards — which happens when
structured output is unavailable and the turn falls back to prose — is not evidence that its
position settled, so a round in which either side added nothing is never converged. Without
that guard two empty sets would compare equal and every fallback run would report a convergence
it did not have.

`convergence_rounds` is the round index at which the comparison first held, and is `None` when
the debate instead ran to `max_debate_rounds`. The two fields are written together, in the same
node, from the same evaluation, so a reader never sees a reason without a round or the reverse.
The debate record also carries `convergence_method` as a verbatim string, so a later change to
the rule is visible in the data rather than inferred from a version number.

Three constraints:

- **`count` is speaker turns, not rounds.** Each round is one bull turn and one bear turn, so
  `count` runs at twice the round count. `convergence_rounds` is the round index the node
  recorded, not a value a reader derives from `count`.
- **`"converged"` requires cards on both sides in both rounds.** A run that lost structured
  output to the fallback cannot report convergence and reports `"max_rounds"` instead, which is
  correct: it stopped because the cap was reached, not because the positions settled.
- **The research manager validates rather than recomputes.**
  `src/tradingagents/agents/managers/research_manager.py` checks that the reason is one of the
  two legal values and falls back to `("max_rounds", None)` otherwise, so a malformed state
  degrades to the cap instead of to an unlabelled finish.

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
