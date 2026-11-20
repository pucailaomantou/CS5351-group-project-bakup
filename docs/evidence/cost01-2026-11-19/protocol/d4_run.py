"""D4 Before/After runner (experiment layer, OUTSIDE all source trees).

Sides
-----
  before : tradingagents-upstream @ 9fa1196      (runner: c-baseline-work/baseline_runner.py)
  after  : c-round2-src-migration/src            (runner: c-round2-src-migration/scripts/round2_runner.py)

The news-window adapter (``d4_news_window_adapter``) is installed BEFORE the graph
is imported, so the graph's ToolNode uses the wrapped ``get_news`` on BOTH sides.

Design points fixed after review
--------------------------------
- Both sides are driven ONLY through their common ``run_once(ticker, date, *,
  analysts, overrides, record_dir, graph_factory)`` signature; no side-specific
  extra kwargs are passed.
- Before has no ``write_log`` -> this layer writes the Before LOG itself. After
  (round2) provides ``write_record`` + ``write_log``; both use exclusive-create
  (no overwrite).
- Each record is SAVED FIRST, then gated on the record's own ``valid`` /
  ``invalid_reasons`` (which already encode status + usage + data_fetch.complete +
  news-delivered>0) plus import-tree identity. Any failure stops the batch.
- The output directory must be NEW/empty; a non-empty dir is refused.
- Adapter SHA, runner SHA, news.py SHA and effective config are recorded per run.

This module does not modify any source tree. It only writes into ``--out``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import d4_news_window_adapter as ADAPTER  # noqa: E402

BEFORE_ROOT = Path("/Users/administrator/CityU/CS5351/c-baseline-work")
AFTER_ROOT_REPO = Path("/Users/administrator/CityU/CS5351/c-round2-src-migration")
AFTER_SRC = AFTER_ROOT_REPO / "src"
AFTER_RUNNER_DIR = AFTER_ROOT_REPO / "scripts"

EXPECTED_NEWS_SHA = "0233bb76019e6425b0f90a2bfa150a49d22dd84822d489296cd2ee6be047edef"
BEFORE_NEWS_REL = Path("tradingagents/dataflows/vendors/yahoo/news.py")
AFTER_NEWS = AFTER_SRC / BEFORE_NEWS_REL
# C-optimization files whose SHA must be frozen/recorded in formal measurement.
AFTER_BEAR = AFTER_SRC / "tradingagents/agents/researchers/bear_researcher.py"
AFTER_RM = AFTER_SRC / "tradingagents/agents/managers/research_manager.py"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _file_sha(path: Path) -> str:
    return _sha256(path) or "unavailable"


def _duration(rec: dict) -> float | None:
    try:
        a = datetime.fromisoformat(rec["finished_at"])
        b = datetime.fromisoformat(rec["started_at"])
        return round((a - b).total_seconds(), 1)
    except Exception:
        return None


def _build_overrides() -> dict:
    base_url = os.environ.get("CITYUCS_LLM_BASE_URL", "https://llm.cs.cityu.edu.hk/v1")
    model = os.environ.get("CITYU_BASELINE_MODEL", "CS5351/DeepSeek-V4-Flash")
    # Do not pin max_tool_rounds / news_article_limit / global_news_queries:
    # each tree keeps its own defaults (Before 20/20/5, After 8/8/3).
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
    """Before has no write_log; write an experiment-layer log (exclusive create)."""
    path = out / f"{record['run_id']}.log"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("D4 Before run log (experiment layer)\n")
        f.write(f"Run ID      : {record['run_id']}\n")
        f.write(f"Ticker/Date : {record['ticker']} / {record['date']}\n")
        f.write(f"Package     : {record.get('imported_package_path')}\n")
        f.write(f"Commit      : {record.get('actual_commit')} (matches={record.get('commit_matches')})\n")
        f.write(f"status={record.get('status')} valid={record.get('valid')} reasons={record.get('invalid_reasons')}\n")
        f.write(f"usage_complete={record.get('usage_complete')} total_tokens={(record.get('usage') or {}).get('total_tokens')}\n")
        f.write(f"data_fetch.complete={(record.get('data_fetch') or {}).get('complete')}\n")
        f.write(f"error={record.get('error')}\n")
    return path


def _require_runner(side: str):
    """Import the correct runner (adapter already installed), verifying the tree."""
    import tradingagents
    pkg = str(Path(tradingagents.__file__).resolve())
    if side == "before":
        if "tradingagents-upstream" not in pkg:
            raise RuntimeError(f"Before must import tradingagents-upstream, got {pkg!r}")
        if str(BEFORE_ROOT) not in sys.path:
            sys.path.insert(0, str(BEFORE_ROOT))
        import baseline_runner as runner
        runner.assert_before_tree()
        return runner, pkg, "before"
    else:
        if "c-round2-src-migration" not in pkg:
            raise RuntimeError(f"After must import c-round2-src-migration/src, got {pkg!r}")
        if str(AFTER_RUNNER_DIR) not in sys.path:
            sys.path.insert(0, str(AFTER_RUNNER_DIR))
        import round2_runner as runner
        runner.assert_round2_tree()
        return runner, pkg, "after"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="D4 Before/After runner (news-window adapter).")
    p.add_argument("--side", choices=["before", "after"], required=True)
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--ticker", default="NVDA")
    p.add_argument("--date", default="2026-11-19")
    p.add_argument("--out", required=True)
    p.add_argument("--interval", type=float, default=0.0)
    args = p.parse_args(argv)

    key = os.environ.get("CITYUCS_LLM_API_KEY")
    if not key:
        print("ERROR: CITYUCS_LLM_API_KEY not set.", file=sys.stderr)
        return 2
    os.environ["OPENAI_COMPATIBLE_API_KEY"] = key  # child env only, never printed

    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"ERROR: output dir {out} is not empty; refusing to reuse it.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    # Verify the After tree's news.py SHA matches the expected review value.
    if args.side == "after":
        actual = _sha256(AFTER_NEWS)
        if actual != EXPECTED_NEWS_SHA:
            print(f"ERROR: After news.py sha256={actual!r} != expected {EXPECTED_NEWS_SHA}.", file=sys.stderr)
            return 2

    # Install adapter BEFORE importing the graph.
    proto = ADAPTER.install()

    runner, pkg, side = _require_runner(args.side)

    news_path = (Path("/Users/administrator/CityU/CS5351/tradingagents-upstream") / BEFORE_NEWS_REL) \
        if side == "before" else AFTER_NEWS
    env_prov = {
        "side": side,
        "imported_package_path": pkg,
        "runner_file_sha256": _file_sha(Path(runner.__file__)),
        "news_py_path": str(news_path),
        "news_py_sha256": _sha256(news_path),
        "adapter": dict(proto),
        "adapter_trade_date": args.date,
        "effective_window": "%s..%s" % ADAPTER.effective_window(args.date),
    }
    if side == "after":
        # Freeze the C-optimization files used by the After measurement.
        env_prov["after_bear_researcher_sha256"] = _sha256(AFTER_BEAR)
        env_prov["after_research_manager_sha256"] = _sha256(AFTER_RM)
    overrides = _build_overrides()
    completed = []
    for i in range(1, args.runs + 1):
        print(f"--- {side} run {i}/{args.runs} ({args.ticker}/{args.date}) ---", flush=True)
        if side == "after":
            # Record raw provider responses (fixtures) so they can be replayed;
            # Before keeps its unchanged behaviour and does NOT use fixtures.
            run_kwargs = {"fixtures_dir": out / "_fixtures"}
        else:
            run_kwargs = {}
        rec = runner.run_once(args.ticker, args.date, analysts=("market", "news"),
                              overrides=overrides, record_dir=out, **run_kwargs)
        rec["duration_s"] = _duration(rec)
        rec["provenance"] = env_prov
        # SAVE FIRST (both runners write JSON exclusively; After also has write_log).
        runner.write_record(rec, out)
        if hasattr(runner, "write_log"):
            try:
                runner.write_log(rec, out)
            except Exception:
                pass
        else:
            _write_before_log(rec, out)

        # INVALID-stops: use the record's OWN validity + tree identity.
        valid = rec.get("valid")
        reasons = rec.get("invalid_reasons")
        tree_ok = ("tradingagents-upstream" in pkg) if side == "before" else ("c-round2-src-migration" in pkg)
        df = rec.get("data_fetch") or {}
        print(f"  run_id={rec['run_id']} status={rec['status']} valid={valid} reasons={reasons} "
              f"usage_ok={rec.get('usage_complete')} data_fetch.complete={df.get('complete')} "
              f"news={rec.get('news_delivered_count')} tok={(rec.get('usage') or {}).get('total_tokens')} "
              f"dur={rec['duration_s']}", flush=True)
        completed.append(rec)

        if not tree_ok:
            print(f"STOP: import-tree mismatch ({pkg!r}).", flush=True)
            break
        if not valid:
            print(f"STOP: invalid record (reasons={reasons}). Saved then stopped.", flush=True)
            break
        if args.interval and i < args.runs:
            import time
            time.sleep(args.interval)

    print(f"DONE attempted={len(completed)} side={side} valid={sum(1 for r in completed if r.get('valid'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
