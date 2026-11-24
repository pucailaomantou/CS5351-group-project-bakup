import re
from datetime import date

from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.turn import take_turn
from tradingagents.agents.context import get_instrument_context_from_state, get_language_instruction
from tradingagents.agents.state import InputProvenance
from tradingagents.agents.tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_insider_transactions,
)

# The tools this analyst is offered; its tool node is built from the same tuple.
TOOLS = (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_insider_transactions,
)

# Statement tools return multi-period data; one provenance entry is kept per
# period so a newer period never hides older inputs. Vendor-visible text carries
# no filing/publication date (SEC EDGAR states only "filed on or before <request
# bound>", which is NOT the filing date; Alpha Vantage / Yahoo expose only the
# fiscal period), so the real cutoff is the period end, tagged ``period_end``.
# Per D's confirmed contract: actual filing/publication date wins if present,
# else the real fiscal period (``semantics="period_end"``), else as_of=None and
# time_reliable=False.
_STATEMENT_TOOLS = {
    "get_balance_sheet": "balance_sheet",
    "get_cashflow": "cashflow",
    "get_income_statement": "income_statement",
}
_DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
_NO_DATA_AVAILABLE = "NO_DATA_AVAILABLE"
# date_window.withhold_* notices (profile / statement); these are NOT data.
_WITHHELD_MARKER = "withheld for this date"
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_ISO_DATE_FULL = re.compile(r"\d{4}-\d{2}-\d{2}")


def _valid_calendar_date(value: str | None) -> str | None:
    """Return ``value`` as YYYY-MM-DD only when it is a real calendar date, else None."""
    if not value:
        return None
    match = _ISO_DATE_RE.fullmatch(value.strip()) or _ISO_DATE_RE.search(value)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def _classify_availability(message: ToolMessage) -> tuple[bool, str]:
    """(available, missing_reason) for a fundamental ToolMessage.

    A withheld notice is a refusal to serve data, not data: it is unavailable.
    """
    content = message.content if isinstance(message.content, str) else str(message.content)
    if getattr(message, "status", None) == "error":
        return False, "tool_error"
    if _WITHHELD_MARKER in content:
        return False, "withheld_point_in_time"
    if _DATA_UNAVAILABLE in content:
        return False, "vendor_unavailable"
    if _NO_DATA_AVAILABLE in content:
        return False, "no_data_available"
    return True, ""


def _period_from_cell(cell: str) -> tuple[str, str | None]:
    """(period_id, period_end) from a statement 'Period'/'Date' cell.

    The period_id keeps the full cell (so distinct spans of the same end date are
    not merged), while period_end is the calendar date portion when real.
    """
    cell = cell.strip()
    return cell, _valid_calendar_date(cell)


def _parse_csv_periods(content: str) -> list[tuple[str, str | None]]:
    """Periods from a yfinance statement CSV via the standard csv module.

    Handles the real ``DataFrame.to_csv()`` shapes: the first column is the row
    index ``Date`` with an empty/``Unnamed: 0``/``Date`` header, and the period
    dates live across the header row (columns) OR down a ``Date`` column. All
    periods are kept, real or not (invalid ones keep their raw id, period_end
    None), so a bad period is never silently dropped.
    """
    import csv
    import io

    lines = [ln for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return []
    try:
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
    except csv.Error:
        return []
    if not rows:
        return []
    header = rows[0]
    # Case 1: dates run across the header columns (yfinance transpose layout).
    # Select period columns by ISO SHAPE so an impossible-but-real period is kept
    # (with period_end None), not silently dropped.
    date_cols = [i for i, h in enumerate(header) if _ISO_DATE_FULL.search(h.strip())]
    if date_cols:
        out = []
        for i in date_cols:
            out.append(_period_from_cell(header[i]))
        return out
    # Case 2: a 'Date' column runs down the rows; other cells are values.
    # Prefer an explicit 'Date' header over an empty/'Unnamed: 0' index column,
    # which is the row-number index, not the period. Select rows by ISO SHAPE so
    # an impossible-but-real period keeps its raw period_id (as_of None), never
    # silently dropped.
    date_idx = next((i for i, h in enumerate(header) if h.strip().lower() == "date"), None)
    if date_idx is None:
        date_idx = next((i for i, h in enumerate(header) if h.strip() == ""), None)
    out = []
    if date_idx is not None:
        for row in rows[1:]:
            if date_idx < len(row) and _ISO_DATE_FULL.search(row[date_idx].strip()):
                out.append(_period_from_cell(row[date_idx]))
    return out


def _parse_edgar_periods(content: str) -> list[tuple[str, str | None]]:
    """Periods from a SEC EDGAR statement table (one data row per period label).

    ``Period`` cell is ``<end>[ (N months)]``; the full label is the period_id so
    the quarterly / 6-month / 9-month spans sharing one end date stay distinct.
    """
    import csv
    import io

    lines = [ln for ln in content.splitlines() if ln.strip() and not ln.startswith("#")]
    out: list[tuple[str, str | None]] = []
    started = False
    for ln in lines:
        try:
            first = next(csv.reader(io.StringIO(ln)))[0] if ln else ""
        except (csv.Error, StopIteration):
            first = ln.split(",", 1)[0]
        if first.strip().lower() == "period":
            started = True
            continue
        if started and first.strip():
            out.append(_period_from_cell(first))
    return out


def _parse_alpha_vantage_periods(content: str) -> list[tuple[str, str | None]]:
    """Periods from an Alpha Vantage statement JSON (annualReports/quarterlyReports)."""
    import json

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, str | None]] = []
    for key in ("annualReports", "quarterlyReports"):
        for row in data.get(key) or []:
            ending = row.get("fiscalDateEnding") if isinstance(row, dict) else None
            if ending:
                out.append(_period_from_cell(str(ending)))
    return out


def _statement_periods(content: str) -> list[tuple[str, str | None]]:
    """All periods in a statement return, across the three vendor shapes.

    Tries EDGAR, yfinance CSV and Alpha Vantage JSON deterministically; returns
    the union in first-seen order. Each item is (period_id, period_end|None).
    """
    for parser in (_parse_alpha_vantage_periods, _parse_edgar_periods, _parse_csv_periods):
        periods = parser(content)
        if periods:
            return periods
    return []


def _fundamentals_input_provenance(messages) -> list[InputProvenance]:
    """Point-in-time provenance for the fundamental inputs the analyst received.

    Only ToolMessages that reached the analyst count ("actually used"). Profile
    (``get_fundamentals``) has no historical vintage -> one entry, ``as_of=None``
    with ``missing_reason="no_vintage"`` (or ``withheld_point_in_time`` when the
    vendor withheld it). Each statement keeps one entry per real period; distinct
    span labels sharing an end date are kept apart via ``period_id``. Withheld /
    unavailable responses are recorded as such and never as usable data. Entries
    are de-duplicated by tool + call_id + period_id.
    """
    entries: list[InputProvenance] = []
    seen: set[tuple[str, str]] = set()
    for message in messages or []:
        if not isinstance(message, ToolMessage):
            continue
        name = getattr(message, "name", None)
        call_id = getattr(message, "tool_call_id", "") or ""
        content = message.content if isinstance(message.content, str) else str(message.content)

        if name == "get_fundamentals":
            if (name, call_id) in seen:
                continue
            seen.add((name, call_id))
            available, missing_reason = _classify_availability(message)
            entries.append(InputProvenance(
                analyst="fundamentals", tool=name, call_id=call_id,
                input_class="fundamentals", period_id="",
                as_of=None, precision="unknown", semantics="unknown",
                evidence="Company Fundamentals (profile, no filing date in output)",
                available=available, time_reliable=False,
                missing_reason=missing_reason or "no_vintage",
            ))
            continue

        if name not in _STATEMENT_TOOLS:
            continue

        available, missing_reason = _classify_availability(message)
        if not available:
            if (name, call_id) in seen:
                continue
            seen.add((name, call_id))
            entries.append(InputProvenance(
                analyst="fundamentals", tool=name, call_id=call_id,
                input_class="fundamentals", period_id="",
                as_of=None, precision="unknown", semantics="unknown",
                evidence=f"{name}: unavailable",
                available=False, time_reliable=False, missing_reason=missing_reason,
            ))
            continue

        periods = _statement_periods(content)
        if not periods:
            if (name, call_id) in seen:
                continue
            seen.add((name, call_id))
            entries.append(InputProvenance(
                analyst="fundamentals", tool=name, call_id=call_id,
                input_class="fundamentals", period_id="",
                as_of=None, precision="unknown", semantics="unknown",
                evidence=f"{name}: no parseable period",
                available=True, time_reliable=False, missing_reason="no_reliable_date",
            ))
            continue

        for period_id, period_end in periods:
            # The raw period label keeps distinct spans/periods apart, so an
            # invalid date never collapses several distinct periods into one.
            key = (name, f"{call_id}|{period_id or '<blank>'}")
            if key in seen:
                continue
            seen.add(key)
            entries.append(InputProvenance(
                analyst="fundamentals", tool=name, call_id=call_id,
                input_class="fundamentals", period_id=period_id,
                as_of=period_end,
                precision="date" if period_end else "unknown",
                semantics="period_end" if period_end else "unknown",
                evidence=f"{name}: period {period_id or '(blank)'}",
                available=True,
                time_reliable=bool(period_end),
                missing_reason="" if period_end else "no_reliable_date",
            ))
    return entries


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        system_message = (
            "You are a researcher tasked with analyzing fundamental information over the past week about a company. Please write a comprehensive report of the company's fundamental information such as financial documents, company profile, basic company financials, and company financial history to gain a full view of the company's fundamental information to inform traders. Make sure to include as much detail as possible. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."
            + " Use the available tools: `get_fundamentals` for comprehensive company analysis, `get_balance_sheet`, `get_cashflow`, and `get_income_statement` for specific financial statements, and `get_insider_transactions` for recent insider buying and selling."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " Report what your tools support; another agent decides the trade."
                    " You have access to the following tools: {tool_names}."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}\n"
                    "{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in TOOLS]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        result, report = take_turn(prompt, llm, TOOLS, state["messages"])

        return {
            "messages": [result],
            "fundamentals_report": report,
            "input_provenance": _fundamentals_input_provenance(state["messages"]),
        }

    return fundamentals_analyst_node
