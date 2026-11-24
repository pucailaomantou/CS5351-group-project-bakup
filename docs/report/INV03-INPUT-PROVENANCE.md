# INV-03 provenance — interface handoff (for D, and E/B)

## Field structure (AgentState.input_provenance: list[InputProvenance])
Each entry (all keys required; malformed raises):
```
analyst:str        # "market" | "fundamentals" (future: news/social)
tool:str           # tool name, e.g. get_verified_market_snapshot
call_id:str        # LangGraph tool_call_id
input_class:str    # INV-03 class: "market_close" | "fundamentals" (macro_latest not produced)
period_id:str      # period date for statements; "" when not period-scoped
as_of:str|null     # real data cutoff ISO; null when unknowable (never backfilled)
precision:str      # "date" | "datetime" | "unknown"
semantics:str      # "latest_trading_row" | "period_end" | "unknown" (future: filing_date, market_implied_probability)
evidence:str       # normalized source fragment/tag
available:bool     # data actually returned & entered analyst context
time_reliable:bool # time source reliable (NOT a freshness verdict)
missing_reason:str # "" | tool_error | vendor_unavailable | no_data_available | no_vintage | no_reliable_date | conflict_kept_all
```

## Example JSON entries
```json
{"analyst":"market","tool":"get_verified_market_snapshot","call_id":"s1",
 "input_class":"market_close","period_id":"","as_of":"2026-11-18","precision":"date",
 "semantics":"latest_trading_row","evidence":"Latest trading row used: 2026-11-18",
 "available":true,"time_reliable":true,"missing_reason":""}

{"analyst":"fundamentals","tool":"get_balance_sheet","call_id":"b1",
 "input_class":"fundamentals","period_id":"2026-09-30","as_of":"2026-09-30","precision":"date",
 "semantics":"period_end","evidence":"get_balance_sheet: period 2026-09-30",
 "available":true,"time_reliable":true,"missing_reason":""}

{"analyst":"fundamentals","tool":"get_fundamentals","call_id":"f1",
 "input_class":"fundamentals","period_id":"","as_of":null,"precision":"unknown",
 "semantics":"unknown","evidence":"Company Fundamentals (profile, no filing date in output)",
 "available":true,"time_reliable":false,"missing_reason":"no_vintage"}
```

## Tool → class / semantics map
| tool | window/PIT | class | as_of source | phase |
|---|---|---|---|---|
| get_verified_market_snapshot | PIT | market_close | Latest trading row used (validated date) | done |
| get_fundamentals (profile) | PIT | fundamentals | none → null/no_vintage | done |
| get_balance_sheet/cashflow/income_statement | PIT | fundamentals | period_end (per period; yfinance CSV empty/Date header or Date column, SEC EDGAR multi-span, Alpha Vantage annual/quarterlyReports.fiscalDateEnding) | done |
| get_insider_transactions | PIT candidate | **UNRESOLVED** | trade date (no filing date) | deferred (D/B) |
| get_prediction_markets | PIT candidate | **UNRESOLVED** | implied prob (live) | deferred |
| get_news / get_global_news | window | — | n/a | out of scope |
| get_macro_indicators (FRED) | window (range + realtime) | — | n/a | out of scope |
| get_stock_data / get_indicators | window | — | n/a | out of scope |
| sentiment prefetch (news/StockTwits/Reddit) | window | — | n/a | out of scope |

## Unknown / conflict handling
- No reliable time → `as_of=null, precision="unknown", time_reliable=false` with a
  `missing_reason`; NEVER backfilled with trade_date/now/request/grab time.
- Unavailable (error/DATA_UNAVAILABLE/NO_DATA_AVAILABLE) → `available=false`, never usable.
- Multi-period → one entry per period (no "latest hides history").
- Conflicts (same identity, differing facts) → keep all N versions, all
  `time_reliable=false`; `conflict_kept_all` marker is never cleared and always
  forces unreliable.

## Open items for D/B
1. **get_prediction_markets**: needs confirmed `input_class`, criticality and
   freshness scope; is the cutoff the implied-probability timestamp or the market's
   last update? Until confirmed, no formal provenance entry is produced (not
   silently treated as window).
2. **get_insider_transactions**: transaction date vs filing date; class/criticality.
3. **fundamentals freshness basis**: C records `period_end` (real filing date not in
   the visible text). If D wants filing-date freshness, dataflows must expose it
   (frozen → separate approved change).
4. **macro_latest class**: FRED is window-based in the current contract; if D wants
   macro freshness, a different PIT macro source/time is needed.

## Note
Tests (E) and this ADR (B) are follow-ups. The targeted/parent-graph checks live
outside the repo until E lands them; "candidate tests pass" is NOT "added to the
official suite".


## Withheld / unavailable notice handling (date_window)
Vendor withheld notices ("… is/are withheld for this date", `DATA_UNAVAILABLE`,
`NO_DATA_AVAILABLE`, or `ToolMessage.status=error`) are recorded as
`available=false` with a specific `missing_reason`
(`withheld_point_in_time` / `vendor_unavailable` / `no_data_available` / `tool_error`)
and `as_of=null`. The request date inside a notice is **never** used as the data time.
This is kept distinct from "success but no time" (`available=true`,
`missing_reason="no_vintage"`).

## Period identity
`period_id` keeps the full period label so distinct spans/periods of one end date do
not merge: EDGAR `2026-09-30`, `2026-09-30 (6 months)`, `2026-09-30 (9 months)` are
three entries (each `period_end=2026-09-30`); distinct invalid dates keep their raw
label with `as_of=null`. Only exact repeated labels collapse.

## Publication status (PR #21)
All INV-03 C-side code and this interface doc are included in PR #21
(`feat/inv03-provenance`):
- `src/tradingagents/agents/state.py` — `InputProvenance` + reducer + `AgentState.input_provenance`
- `src/tradingagents/graph/propagation.py` — per-run init
- `src/tradingagents/graph/setup.py` — subgraph output_schema carries provenance
- `src/tradingagents/agents/analysts/market_analyst.py` — snapshot/market_close
- `src/tradingagents/agents/analysts/fundamentals_analyst.py` — profile + balance/cashflow/income (yfinance CSV / SEC EDGAR / Alpha Vantage), withheld handling, per-period retention
- `docs/report/INV03-INPUT-PROVENANCE.md` — this interface handoff (for D)

Review materials in this PR (candidates; not yet in the official suites):
- [E] pytest test candidate — [docs/review/inv03/test_inv03_provenance.py](../review/inv03/test_inv03_provenance.py);
  target on acceptance `test/offline/test_inv03_provenance.py` (E owns test/offline).
- [B] ADR (Proposed) — [docs/review/inv03/ADR-INV03-provenance.md](../review/inv03/ADR-INV03-provenance.md);
  target on acceptance `docs/architecture/adr/` (B owns docs/architecture/).
