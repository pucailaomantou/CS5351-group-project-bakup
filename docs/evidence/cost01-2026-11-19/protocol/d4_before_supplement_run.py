"""Before supplement driver (experiment layer) — capture market evidence, 2026-11-19.

Runs ONE OR TWO additional true-Before analyses for the FIXED analysis date
2026-11-19, using the same upstream tree, news-window adapter and runner as the
original candidate batch, and additionally captures a side-channel market-evidence
manifest for each run (see ``d4_market_evidence``).

Fixes:
  - analysis date is HARD-PINNED to 2026-11-19 (never auto-changes to today).
  - it RECORDS that execution happens on the actual UTC date (which may be
    2026-11-20 -> a cross-UTC-day supplement) into every record's provenance.
  - Before: tradingagents-upstream @ 9fa1196, 20/20/5, DeepSeek-V4-Flash, temp 0.
  - independent memory/cache/results (run_once handles isolated dirs).
  - saves record + market evidence; stops on invalid or missing evidence.
  - does NOT force market_rows to 252, does NOT change model request params.

This module edits no source tree; it only writes into --out.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d4_market_evidence as ME  # noqa: E402
import d4_news_window_adapter as ADAPTER  # noqa: E402

BEFORE_ROOT = Path("/Users/administrator/CityU/CS5351/c-baseline-work")
PINNED_DATE = "2026-11-19"
EXPECTED_BEFORE_NEWS_SHA = "9f56dcc58bae002a4e7c19e0f659504fabfb7132aef535e248bc7d080b30b7eb"
BEFORE_NEWS_REL = Path("tradingagents/dataflows/vendors/yahoo/news.py")


def _sha256(path: Path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _file_sha(path: Path) -> str:
    return _sha256(path) or "unavailable"


def _duration(rec: dict):
    try:
        a = datetime.fromisoformat(rec["finished_at"])
        b = datetime.fromisoformat(rec["started_at"])
        return round((a - b).total_seconds(), 1)
    except Exception:
        return None


def _build_overrides() -> dict:
    base_url = os.environ.get("CITYUCS_LLM_BASE_URL", "https://llm.cs.cityu.edu.hk/v1")
    model = os.environ.get("CITYU_BASELINE_MODEL", "CS5351/DeepSeek-V4-Flash")
    return {
        "llm_provider": "openai_compatible",
        "backend_url": base_url,
        "deep_think_llm": model,
        "quick_think_llm": model,
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "temperature": 0.0,
        "checkpoint_enabled": False,
    }


def _write_before_log(record: dict, out: Path) -> Path:
    path = out / f"{record['run_id']}.log"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("D4 Before SUPPLEMENT run log (experiment layer)\n")
        fh.write(f"Run ID      : {record['run_id']}\n")
        fh.write(f"Ticker/Date : {record['ticker']} / {record['date']}\n")
        fh.write(f"Package     : {record.get('imported_package_path')}\n")
        fh.write(f"Commit      : {record.get('actual_commit')} (matches={record.get('commit_matches')})\n")
        fh.write(f"status={record.get('status')} valid={record.get('valid')} reasons={record.get('invalid_reasons')}\n")
        fh.write(f"usage_complete={record.get('usage_complete')} total={(record.get('usage') or {}).get('total_tokens')}\n")
        fh.write(f"data_fetch.complete={(record.get('data_fetch') or {}).get('complete')}\n")
        fh.write(f"market_rows={record.get('market_rows')} news={record.get('news_delivered_count')}\n")
    return path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Before supplement runs with market evidence (11-19).")
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--ticker", default="NVDA")
    p.add_argument("--date", default=PINNED_DATE)
    p.add_argument("--out", required=True)
    p.add_argument("--interval", type=float, default=0.0)
    args = p.parse_args(argv)

    if args.date != PINNED_DATE:
        print(f"ERROR: analysis date is pinned to {PINNED_DATE}; refusing {args.date}.", file=sys.stderr)
        return 2

    key = os.environ.get("CITYUCS_LLM_API_KEY")
    if not key:
        print("ERROR: CITYUCS_LLM_API_KEY not set.", file=sys.stderr)
        return 2
    os.environ["OPENAI_COMPATIBLE_API_KEY"] = key  # process-local; never printed

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"ERROR: output dir {out} is not empty; refusing to reuse it.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    # Import upstream first, verify identity + news SHA.
    import tradingagents
    pkg = str(Path(tradingagents.__file__).resolve())
    if "tradingagents-upstream" not in pkg:
        print(f"ERROR: Before must import tradingagents-upstream, got {pkg!r}.", file=sys.stderr)
        return 2
    before_news = Path("/Users/administrator/CityU/CS5351/tradingagents-upstream") / BEFORE_NEWS_REL
    if _sha256(before_news) != EXPECTED_BEFORE_NEWS_SHA:
        print("ERROR: Before news.py SHA mismatch; refusing.", file=sys.stderr)
        return 2

    # Install the SAME news-window adapter as the original batch, BEFORE runner import.
    adapter_proto = ADAPTER.install()

    if str(BEFORE_ROOT) not in sys.path:
        sys.path.insert(0, str(BEFORE_ROOT))
    import baseline_runner as runner
    runner.assert_before_tree()
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    utc_now = datetime.now(timezone.utc)
    env_prov = {
        "side": "before",
        "imported_package_path": pkg,
        "runner_file_sha256": _file_sha(Path(runner.__file__)),
        "news_py_path": str(before_news),
        "news_py_sha256": _sha256(before_news),
        "adapter": dict(adapter_proto),
        "adapter_trade_date": args.date,
        "effective_window": "%s..%s" % ADAPTER.effective_window(args.date),
        "run_started_utc_date": utc_now.strftime("%Y-%m-%d"),
        "cross_utc_day_supplement": utc_now.strftime("%Y-%m-%d") != args.date,
        "analysis_date": args.date,
    }
    overrides = _build_overrides()
    completed = []
    for i in range(1, args.runs + 1):
        print(f"--- before SUPPLEMENT run {i}/{args.runs} ({args.ticker}/{args.date}) UTC={utc_now:%Y-%m-%d} ---", flush=True)
        holder = {}
        capturing_factory = ME.make_capturing_factory(TradingAgentsGraph, holder)
        rec = runner.run_once(args.ticker, args.date, analysts=("market", "news"),
                              overrides=overrides, record_dir=out, graph_factory=capturing_factory)
        rec["duration_s"] = _duration(rec)
        rec["provenance"] = env_prov
        run_id = rec["run_id"]
        holder["run_id"] = run_id

        # Save record + log FIRST (exclusive create via runner).
        runner.write_record(rec, out)
        _write_before_log(rec, out)

        # Capture market evidence from the captured messages.
        collector = capturing_factory._collector
        # De-dupe cumulative stream before pairing (messages repeat each step).
        seen = set(); deduped = []
        for m in collector.messages:
            mid = getattr(m, "id", None) or id(m)
            if mid in seen:
                continue
            seen.add(mid); deduped.append(m)
        evidence = ME.write_market_evidence(deduped, out, run_id, side="before")
        rec["market_evidence"] = {
            "stock_calls": evidence["stock_calls"],
            "manifest_file": evidence["manifest_file"],
            "manifest_sha256": evidence["manifest_sha256"],
            "records": evidence["records"],
        }
        # Persist the augmented record under a distinct name (do not overwrite).
        aug = out / f"{run_id}.withmarket.json"
        if not aug.exists():
            aug.write_text(__import__("json").dumps(rec, indent=2, ensure_ascii=False))

        df = rec.get("data_fetch") or {}
        print(f"  run_id={run_id} status={rec['status']} valid={rec.get('valid')} "
              f"reasons={rec.get('invalid_reasons')} market_rows={rec.get('market_rows')} "
              f"stock_calls={evidence['stock_calls']} news={rec.get('news_delivered_count')} "
              f"tok={(rec.get('usage') or {}).get('total_tokens')}", flush=True)
        completed.append((rec, evidence))

        # Gating: valid AND at least one stock call WITH a captured response.
        tree_ok = "tradingagents-upstream" in pkg
        have_evidence = evidence["stock_calls"] >= 1 and any(r["response_seen"] for r in evidence["records"])
        if not tree_ok:
            print("STOP: import-tree mismatch.", flush=True); break
        if not rec.get("valid"):
            print(f"STOP: invalid record (reasons={rec.get('invalid_reasons')}).", flush=True); break
        if not have_evidence:
            print("STOP: market evidence missing (no stock call/response captured).", flush=True); break
        if args.interval and i < args.runs:
            import time; time.sleep(args.interval)

    print(f"DONE attempted={len(completed)} side=before valid={sum(1 for r,_ in completed if r.get('valid'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
