"""Side-channel market evidence capture for Before runs (experiment layer).

Why
---
The Before (upstream 9fa1196) runner keeps NO raw market response and does not use
provider fixtures. The only artefact was a 1254-row *cache* file, which is NOT the
response the tool actually returned for the run's own request. To prove a Before
sample's market completeness independently we must capture, from the REAL graph run:

  * each ``get_stock_data`` tool call's actual arguments (request range);
  * the full raw tool return that answered that exact ``tool_call_id``;
  * the parsed CSV, row count, first/last date;
  * SHA256 of the saved response file (and of the parsed CSV) plus the run_id.

How (no behaviour change)
-------------------------
We pass a ``graph_factory`` wrapper to the existing ``run_once``. It builds the
REAL ``TradingAgentsGraph`` unchanged, then wraps ONLY its ``stream_run`` generator
to tee the yielded messages into a collector. We never mutate messages, tool args,
returns, model input, callbacks or usage metering. After the run, the collector
pairs each ``AIMessage.tool_calls`` entry (name/args/id) with the ``ToolMessage``
that has the matching ``tool_call_id``.

We deliberately do NOT read the on-disk cache, the analyst report, or re-query
Yahoo: a recording that is not the tool response for the run's own call would be a
fabrication (the exact failure mode this module exists to avoid).

Offline-testable: ``pair_stock_calls`` and ``parse_stock_response`` are pure.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

STOCK_TOOL = "get_stock_data"

_HEADER_RE = re.compile(
    r"^# Stock data for (?P<label>.*?) from (?P<start>\d{4}-\d{2}-\d{2}) to (?P<end>\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)
_RECORDS_RE = re.compile(r"^# Total records:\s*(?P<n>\d+)\s*$", re.MULTILINE)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _tool_result_text(message) -> str | None:
    if type(message).__name__ != "ToolMessage":
        return None
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return " ".join(str(p) for p in content)
    return str(content)


def pair_stock_calls(messages: list) -> list[dict]:
    """Pair get_stock_data AIMessage tool_calls with their ToolMessage responses.

    Returns one dict per stock call (in first-seen order), each with the request
    args, tool_call_id, and the raw response text (or None if unanswered).
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for m in messages or []:
        for tc in (getattr(m, "tool_calls", None) or []):
            if tc.get("name") != STOCK_TOOL:
                continue
            cid = tc.get("id")
            if cid in calls:
                continue
            calls[cid] = {"tool_call_id": cid, "args": dict(tc.get("args") or {}),
                          "response_text": None, "response_seen": False}
            order.append(cid)
    for m in messages or []:
        text = _tool_result_text(m)
        if text is None:
            continue
        cid = getattr(m, "tool_call_id", None)
        if cid in calls and not calls[cid]["response_seen"]:
            calls[cid]["response_text"] = text
            calls[cid]["response_seen"] = True
    return [calls[cid] for cid in order]


def parse_stock_response(text: str) -> dict:
    """Parse the market tool's formatted text: header range + '# Total records' + CSV."""
    if not text:
        return {"header_start": None, "header_end": None, "label": None,
                "total_records": None, "csv_rows": None, "first_date": None,
                "last_date": None, "csv_sha256": None, "parse_ok": False}
    hm = _HEADER_RE.search(text)
    rm = _RECORDS_RE.search(text)
    total = int(rm.group("n")) if rm else None
    # CSV follows the first blank line after the header block.
    parts = text.split("\n\n", 1)
    csv_body = parts[1] if len(parts) == 2 else ""
    lines = [ln for ln in csv_body.splitlines() if ln.strip()]
    csv_rows = None
    first_date = last_date = None
    if lines and not lines[0].startswith("#"):
        # First line is the CSV header; data rows = len(lines)-1.
        csv_rows = len(lines) - 1
        data_lines = lines[1:]
        if data_lines:
            first_date = data_lines[0].split(",", 1)[0][:10] or None
            last_date = data_lines[-1].split(",", 1)[0][:10] or None
    return {
        "header_start": hm.group("start") if hm else None,
        "header_end": hm.group("end") if hm else None,
        "label": hm.group("label") if hm else None,
        "total_records": total,
        "csv_rows": csv_rows,
        "first_date": first_date,
        "last_date": last_date,
        "csv_sha256": _sha256_bytes(csv_body.encode("utf-8")) if csv_body else None,
        "parse_ok": hm is not None and total is not None and csv_rows is not None,
    }


class _Collector:
    def __init__(self) -> None:
        self.messages: list = []

    def tee(self, messages):
        """Append messages (cumulative stream is later de-duped by pairing)."""
        if messages:
            self.messages.extend(messages)


def make_capturing_factory(real_factory, run_id_holder: dict):
    """Return a graph_factory that builds the real graph but tees stream_run messages.

    ``run_id_holder`` is filled by the caller after run_once returns; we only need
    a stable id to name evidence files, so we accept a mutable dict and read
    ``run_id_holder['run_id']`` lazily, or fall back to a timestamp.
    """
    def factory(*args, **kwargs):
        graph = real_factory(*args, **kwargs)
        collector = _Collector()
        real_stream = graph.stream_run

        def stream_run(*sargs, **skwargs):
            for item in real_stream(*sargs, **skwargs):
                # item is (messages, state); tee the messages only, yield unchanged.
                try:
                    msgs = item[0] if isinstance(item, (tuple, list)) and item else None
                except Exception:
                    msgs = None
                collector.tee(msgs)
                yield item

        graph.stream_run = stream_run  # instance-level wrap; class untouched
        factory._collector = collector
        return graph

    return factory


def write_market_evidence(messages: list, out_dir: Path, run_id: str, side: str = "before") -> dict:
    """Pair stock calls, save each raw response, and return an evidence summary."""
    ev_dir = Path(out_dir) / "market_evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    pairs = pair_stock_calls(messages)
    records = []
    for i, p in enumerate(pairs):
        parsed = parse_stock_response(p["response_text"] or "")
        raw_bytes = (p["response_text"] or "").encode("utf-8")
        resp_sha = _sha256_bytes(raw_bytes) if p["response_seen"] else None
        resp_file = None
        if p["response_seen"]:
            resp_file = ev_dir / f"{run_id}_stock_{i}.txt"
            resp_file.write_bytes(raw_bytes)
            # verify the just-written file hashes to what we recorded
            assert _sha256_bytes(resp_file.read_bytes()) == resp_sha
        records.append({
            "run_id": run_id,
            "side": side,
            "tool_call_index": i,
            "tool_call_id": p["tool_call_id"],
            "request_args": p["args"],
            "request_symbol": p["args"].get("symbol"),
            "request_start": p["args"].get("start_date"),
            "request_end": p["args"].get("end_date"),
            "response_seen": p["response_seen"],
            "response_file": str(resp_file) if resp_file else None,
            "response_sha256": resp_sha,
            "header_start": parsed["header_start"],
            "header_end": parsed["header_end"],
            "total_records": parsed["total_records"],
            "csv_rows": parsed["csv_rows"],
            "first_date": parsed["first_date"],
            "last_date": parsed["last_date"],
            "csv_sha256": parsed["csv_sha256"],
            "parse_ok": parsed["parse_ok"],
        })
    summary = {
        "run_id": run_id, "side": side, "captured_at": _now_iso(),
        "stock_calls": len(records), "records": records,
        "note": ("Captured from the graph's own stream: each get_stock_data call's "
                 "args paired with the ToolMessage of matching tool_call_id. Raw "
                 "response text saved verbatim. NOT from cache/report/re-query."),
    }
    man_path = ev_dir / f"{run_id}_market_evidence.json"
    man_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["manifest_file"] = str(man_path)
    summary["manifest_sha256"] = _sha256_bytes(man_path.read_bytes())
    return summary
