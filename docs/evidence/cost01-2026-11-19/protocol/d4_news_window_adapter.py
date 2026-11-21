"""Experiment-window adapter for ``get_news`` (D4) — OUTSIDE the source trees.

Problem it solves
----------------
The research date may be *newer* than the window the model asks for (e.g. the
model calls ``get_news(2026-11-05, 2026-11-12)`` while the run's trade_date is
2026-11-19). The upstream tool only clamps *future* dates (``as_of_window`` keeps
a wholly-past window unchanged), so the call hits Yahoo with an old window and
Yahoo answers "only serves recent items" -> 0 articles -> run marked failed.

What this adapter does
----------------------
For ``get_news`` ONLY, it re-anchors the requested window to the run's trade_date:

    effective_end   = trade_date
    effective_start = trade_date - 7 days

The ORIGINAL news implementation is still called (same Yahoo path, same
fetch/date-filter/return contract). We do NOT silently mutate the window: the
returned string is prefixed with an explicit notice stating the requested window
and the effective window actually used, and out-of-window articles are never
injected (the original date filter still runs).

Rules are identical for Before (upstream) and After (c-cost-work); the adapter is
applied by patching the shared tool object in-process before the graph imports.

Provenance: ``ADAPTER_ID`` / ``WINDOW_DAYS`` / ``describe_protocol()`` let a runner
record exactly which adapter+rule produced a record.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta

ADAPTER_ID = "d4-news-window-adapter-v1"
WINDOW_DAYS = 7
logger = logging.getLogger(__name__)

_INSTALLED = False
_ORIG_FUNC = None


def _self_sha256() -> str:
    try:
        with open(__file__, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "unavailable"


def effective_window(trade_date: str) -> tuple[str, str]:
    """(start, end) for a trade_date: end=trade_date, start=trade_date-7d."""
    end = datetime.strptime(str(trade_date), "%Y-%m-%d")
    start = end - timedelta(days=WINDOW_DAYS)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def describe_protocol() -> dict:
    return {
        "adapter_id": ADAPTER_ID,
        "adapter_sha256": _self_sha256(),
        "applies_to": "get_news only",
        "rule": "effective_end=trade_date; effective_start=trade_date-7days",
        "window_days": WINDOW_DAYS,
        "tells_model": True,
        "out_of_window_injected": False,
    }


def _wrapped_get_news(*args, **kwargs):
    """Wrap the original tool ``.func`` to re-anchor the window and annotate it.

    The original tool signature is
        get_news(ticker, start_date, end_date, trade_date="")
    called positionally by the ToolNode as (ticker, start, end) with trade_date
    injected via LangGraph (InjectedState). We rewrite start/end using the
    injected trade_date when present; otherwise call through unchanged.
    """
    # Bind loosely: positional (ticker, start, end) + trade_date kwarg.
    def _get(i, name, default=None):
        if i < len(args):
            return args[i]
        return kwargs.get(name, default)

    req_start = _get(1, "start_date")
    req_end = _get(2, "end_date")
    trade_date = kwargs.get("trade_date") or _get(3, "trade_date", "")

    if trade_date and str(trade_date).strip():
        eff_start, eff_end = effective_window(trade_date)
        adjusted = (str(req_start), str(req_end)) != (eff_start, eff_end)
        notice = ""
        if adjusted:
            notice = (
                f"[news window adapter] requested get_news window "
                f"{req_start}..{req_end} was re-anchored to the analysis date: "
                f"using {eff_start}..{eff_end} (trade_date={trade_date}, "
                f"window={WINDOW_DAYS}d). Articles outside this effective window are "
                f"not included.\n\n"
            )
        # Call the ORIGINAL implementation with the effective window.
        call_args = list(args)
        if len(call_args) >= 3:
            call_args[1] = eff_start
            call_args[2] = eff_end
        else:
            kwargs["start_date"] = eff_start
            kwargs["end_date"] = eff_end
        result = _ORIG_FUNC(*call_args, **kwargs)
        return (notice + result) if notice else result

    return _ORIG_FUNC(*args, **kwargs)


def install() -> dict:
    """Patch ``tradingagents.agents.tools.get_news`` in-process (idempotent).

    Must be called BEFORE ``tradingagents.graph`` / analyst specs are imported so
    the graph's ToolNode captures the wrapped tool. Returns provenance.
    """
    global _INSTALLED, _ORIG_FUNC
    if _INSTALLED:
        return describe_protocol()

    import tradingagents.agents.tools as tools
    import tradingagents.agents.analysts.news_analyst as na
    from langchain_core.tools import StructuredTool

    orig = tools.get_news
    _ORIG_FUNC = orig.func
    wrapped = StructuredTool.from_function(
        func=_wrapped_get_news,
        name=orig.name,
        description=orig.description,
        args_schema=orig.args_schema,
    )
    tools.get_news = wrapped
    # Rebuild the module-level TOOLS tuple so the analyst offers the wrapped tool.
    na.TOOLS = tuple(wrapped if (getattr(t, "name", None) == "get_news") else t
                     for t in na.TOOLS)
    _INSTALLED = True
    logger.info("news window adapter installed (%s, sha=%s)", ADAPTER_ID, _self_sha256()[:12])
    return describe_protocol()
