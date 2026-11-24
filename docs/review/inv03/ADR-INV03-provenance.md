# ADR — INV-03 point-in-time input provenance (Proposed, for B review)

> Status: Proposed. For B review; not yet accepted.
> Target on acceptance: docs/architecture/adr/ (B owns docs/architecture/).
> This ADR accompanies the safety-critical `graph/setup.py` change (.agent/rules.md §4).

## Status
Proposed.

## Context
INV-03 requires D's deterministic guard to judge per-input freshness at the
decision layer, reading provenance from `AgentState`. Two structural facts force a
`graph/setup.py` change:
- Each analyst is a private subgraph `StateGraph(AgentState, output_schema=output)`;
  only keys listed in `output` cross to the parent, so a provenance key written in
  a node is dropped unless added to `output_schema`.
- Analysts run in parallel; their provenance must not overwrite each other.

Vendor tools return formatted strings (not structured metadata), so the real data
cutoff must be extracted deterministically from the tool result text.

## Decision
1. `AgentState.input_provenance: Annotated[list[InputProvenance], reducer]`, all
   keys required (a malformed entry raises rather than being defaulted valid).
2. Add `input_provenance` to each analyst subgraph `output_schema` so it reaches the
   parent graph.
3. Reducer is a pure function: idempotent, commutative, associative, non-mutating,
   keeps every distinct fact version (N); derived fields joined conservatively
   (`time_reliable` AND; a `conflict_kept_all` marker always forces
   `time_reliable=False`); output sorted over all differing fields.
4. `create_initial_state` seeds a fresh empty list per run (cross-run isolation).
5. Phase records only inputs that actually reached the analyst:
   - `market_close` ← verified snapshot's real "Latest trading row used" date
     (validated calendar date; never the requested date).
   - `fundamentals` ← profile (no vintage → null); balance sheet / cashflow /
     income statement each keep one entry per real period (`semantics=period_end`).
     Parsed deterministically across the three real vendor shapes: yfinance CSV
     (`DataFrame.to_csv()` with empty / `Date` / `Unnamed: 0` first header, or a
     `Date` column), SEC EDGAR (`Period` rows, multi-span `<end> (N months)` kept
     distinct per `period_id`), and Alpha Vantage JSON (`annualReports` /
     `quarterlyReports[].fiscalDateEnding`). No filing date is exposed in the
     visible text; the "filed on or before X" bound is NOT a filing date.
   - Distinguish success / ToolMessage error / DATA_UNAVAILABLE / NO_DATA_AVAILABLE /
     **withheld_point_in_time** (a `date_window` withhold notice is a refusal, not
     data; its request date is never used) / no-reliable-date via `available` +
     `missing_reason`. Success-but-no-time is kept distinct from withheld.

## Alternatives rejected
- Node-local variable / side channel: never reaches the guard; lost at the subgraph.
- Single scalar "latest as-of": collapses inputs/classes, hides older inputs.
- First-writer-wins append: order-dependent, loses conflicts, can pass an unreliable
  time.
- Infer provenance from analyst free text: non-deterministic; violates "from tool
  results, not self-report".

## Failure mode prevented
A fresh request returning stale underlying data would look fresh to the guard
without the real cutoff; parallel analysts could silently overwrite provenance.

## Consequences
- `setup.py` (safety-critical) needs this ADR + human approval every merge.
- Phase is additive and behaviour-neutral for report generation (no new LLM calls,
  no change to prompts / tool rounds / 8-8-3 / RM).
- prediction / insider and other classes remain follow-ups (see open items).

## Out of scope
The guard and thresholds (D); window-based inputs (news/global/macro FRED/stock/
indicators/sentiment — out of INV-03 by the date-window clamp); prediction and
insider classes until D/B confirm their class, criticality and time semantics.
