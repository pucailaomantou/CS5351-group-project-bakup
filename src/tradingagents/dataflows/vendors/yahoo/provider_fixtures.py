"""Record / replay of raw Yahoo provider responses for the C experiments (Round 2).

Goal: an experiment run can save the RAW responses it received from Yahoo
(market OHLCV as CSV, news/search payloads as JSON), each with a SHA256, and a
later run can REPLAY those exact responses offline — with no Yahoo call — so two
configurations can be compared on identical DATA input.

Scope and honesty:
  * This replays the DATA-acquisition layer only (market rows, ticker news,
    per-query global news). It does NOT and cannot replay non-deterministic LLM
    output.
  * Recording is a pure observation of the value the vendor already got back;
    replay serves that value in place of a live call. With fixtures OFF (the
    default everywhere, including normal CLI runs and existing tests) every hook
    is a no-op and behaviour is byte-identical to before.
  * Only public Yahoo payloads are stored. API keys / credentials are never part
    of these responses and are never written here.

A fixture is addressed by ``(kind, key)``:
  kind = "market"  -> key = symbol (e.g. "NVDA")          -> CSV of the frame
  kind = "news"    -> key = f"{symbol}"                    -> JSON list
  kind = "search"  -> key = f"{query}|{symbol}|{news_count}" -> JSON list (.news)
Files land under ``<root>/<kind>/<safe(key)>.{csv,json}`` with a sibling
``.sha256``; ``manifest()`` lists every file's relative path and hash.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_active: ContextVar[FixtureStore | None] = ContextVar("provider_fixtures", default=None)


def _safe_key(key: str) -> str:
    """A filesystem-safe token for a fixture key (no path traversal, bounded)."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key)[:120]
    return safe or "anonymous"


class SearchResult:
    """Minimal replay stand-in for ``yf.Search`` exposing just what callers read."""

    def __init__(self, news: list | None = None, quotes: list | None = None) -> None:
        self.news = news or []
        self.quotes = quotes or []


class FixtureStore:
    """Records provider responses to disk, or replays them, for one run.

    Storage is content-addressed for de-duplication (Minimum Sufficient Evidence):
      objects/<sha256>.<ext>      the raw payload, stored once per unique content
      <kind>/<safe(key)>.ref      JSON pointer {"sha256", "ext"} for one request
    Identical content from different requests (e.g. the same range fetched twice,
    or two queries returning identical news) shares ONE object. The manifest
    resolves each request to its object's sha256 so a run's actual fixtures are
    traceable. No unrelated fields, no caches, no credentials are stored.
    """

    def __init__(self, root: Path, mode: str) -> None:
        assert mode in ("record", "replay")
        self.root = Path(root)
        self.mode = mode
        # replay only: per-(kind,key) call cursor so repeated requests are served
        # in their recorded order.
        self._cursor: dict[tuple[str, str], int] = {}

    # --- pointer / object paths --------------------------------------------
    def _ref_path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{_safe_key(key)}.ref"

    def _object_path(self, sha: str, ext: str) -> Path:
        return self.root / "objects" / f"{sha}.{ext}"

    def manifest(self) -> list[dict]:
        """Each recorded REQUEST occurrence -> its object path + sha256.

        A key can be requested more than once in a run. Every occurrence is
        listed (in recorded order) so a reviewer sees exactly which objects were
        produced and in what order; identical consecutive content is collapsed
        to one entry (see ``_save``), differing content yields several.
        """
        out = []
        for ref in sorted(self.root.glob("*/*.ref")):
            kind = ref.parent.name
            entries = self._read_entries(ref)
            for idx, e in enumerate(entries):
                sha, ext = e.get("sha256"), e.get("ext")
                obj = self._object_path(sha, ext)
                out.append({
                    "kind": kind,
                    "key": ref.stem,
                    "occurrence": idx,
                    "path": str(obj.relative_to(self.root)),
                    "sha256": sha,
                    "exists": obj.exists(),
                })
        return out

    # --- ref pointer file (ordered entries) --------------------------------
    @staticmethod
    def _read_entries(ref: Path) -> list[dict]:
        try:
            data = json.loads(ref.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict) and "entries" in data:
            return list(data.get("entries") or [])
        # Backward-compat with the earlier single-pointer form {"sha256","ext"}.
        if isinstance(data, dict) and data.get("sha256"):
            return [{"sha256": data["sha256"], "ext": data.get("ext")}]
        return []

    def _append_entry(self, kind: str, key: str, sha: str, ext: str) -> None:
        """Atomically append one {sha256,ext} to the key's ordered entry list.

        Idempotent for identical consecutive content (same sha as the current
        last entry): that call does not create a second entry. Different content
        is appended, preserving call order for replay. The write is atomic
        (temp file + os.replace), never O_EXCL, so repeated calls never fail.
        """
        import os
        import tempfile
        ref = self._ref_path(kind, key)
        ref.parent.mkdir(parents=True, exist_ok=True)
        entries = self._read_entries(ref)
        last = entries[-1] if entries else None
        if last and last.get("sha256") == sha and last.get("ext") == ext:
            return  # identical consecutive request: idempotent, no new entry
        entries.append({"sha256": sha, "ext": ext})
        fd, tmp = tempfile.mkstemp(dir=str(ref.parent), suffix=".ref.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"entries": entries}, fh)
            os.replace(tmp, ref)  # atomic overwrite
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # --- record -------------------------------------------------------------
    def _save(self, kind: str, key: str, ext: str, write: Callable[[Any], None]) -> Path:
        # Write the payload to a temp content file, hash it, then move into the
        # content-addressed objects/ store (dedup: identical content stored once).
        import os
        import tempfile
        self._ref_path(kind, key).parent.mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.root / "objects", suffix="." + ext)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                write(fh)
            sha = _sha256(Path(tmp))
            obj = self._object_path(sha, ext)
            if not obj.exists():
                os.replace(tmp, obj)  # store once per unique content
            else:
                os.unlink(tmp)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._append_entry(kind, key, sha, ext)
        return obj

    def save_csv(self, kind: str, key: str, write: Callable[[Any], None]) -> Path:
        return self._save(kind, key, "csv", write)

    def save_json(self, kind: str, key: str, data: Any) -> Path:
        return self._save(kind, key, "json",
                          lambda fh: fh.write(json.dumps(data, ensure_ascii=False, indent=2)))

    # --- replay -------------------------------------------------------------
    def _load(self, kind: str, key: str, ext: str) -> Path:
        ref = self._ref_path(kind, key)
        if not ref.exists():
            raise FileNotFoundError(
                f"fixture missing for replay: kind={kind!r} key={key!r} -> {ref}")
        entries = self._read_entries(ref)
        # Serve entries in recorded call order via a per-key cursor. Replaying the
        # same number of calls the recording made returns the same responses in
        # the same order; more calls than recorded is a hard error (no live call).
        pos = self._cursor.get((kind, key), 0)
        if pos >= len(entries):
            raise FileNotFoundError(
                f"replay cursor exhausted: kind={kind!r} key={key!r} "
                f"recorded {len(entries)} call(s), replay asked for #{pos + 1}")
        entry = entries[pos]
        self._cursor[(kind, key)] = pos + 1
        sha, pext = entry.get("sha256"), entry.get("ext")
        if pext != ext:
            raise ValueError(f"fixture type mismatch for {ref}: expected {ext}, got {pext}")
        obj = self._object_path(sha, ext)
        if not obj.exists():
            raise FileNotFoundError(
                f"fixture object missing for replay: kind={kind!r} key={key!r} -> {obj}")
        got = _sha256(obj)
        if got != sha:
            raise ValueError(f"fixture SHA256 mismatch for {obj}: {sha} != {got}")
        return obj

    def load_csv(self, kind: str, key: str, read: Callable[[Path], Any]) -> Any:
        return read(self._load(kind, key, "csv"))

    def load_json(self, kind: str, key: str) -> Any:
        return json.loads(self._load(kind, key, "json").read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_history_csv(path: Path):
    """Rebuild a yfinance ``history()`` DataFrame from its recorded CSV.

    The live frame has a **tz-aware DatetimeIndex** (each row's local wall-clock
    date with its own UTC offset; the offset varies across a DST change, e.g.
    ``-05:00`` winter / ``-04:00`` summer as strings in the CSV). A naive
    ``pd.read_csv(..., parse_dates=True)`` cannot parse those mixed-offset
    strings into a DatetimeIndex — it yields a plain ``Index`` with no ``.tz``,
    which then breaks downstream code that reads ``df.index.tz``.

    Reconstruction that preserves meaning (NOT just to pass a ``.tz`` check):
      1. read the CSV with the first column as strings;
      2. parse to a single canonical, **UTC**-aware instants column;
      3. convert those instants back to the common exchange tz so each row's
         LOCAL wall-clock date and the row order are exactly what was recorded
         (DST-aware: winter dates come back at -05:00, summer at -04:00);
      4. drop the tz-naive duplicate and set the tz-aware DatetimeIndex.

    The resulting index, after the downstream ``tz_localize(None)`` in
    ``market.py``, yields the same local calendar dates in the same order as the
    original live frame. No synthetic/shifted dates are introduced.
    """
    import pandas as pd

    raw = pd.read_csv(path)
    # Identify the date column (the frame was written with its index first; a
    # named index becomes the leading column, e.g. "Date").
    date_col = raw.columns[0]
    instants = pd.to_datetime(raw[date_col], utc=True, errors="coerce", format="mixed")
    if getattr(instants.dt, "tz", None) is None:
        # Extremely defensive: no offset info in the CSV -> treat as naive local.
        idx = pd.DatetimeIndex(pd.to_datetime(raw[date_col]).values, name=date_col)
    else:
        # Convert all instants to one exchange tz so wall-clock dates are the
        # recorded local dates (America/New_York is Yahoo's tz; the offsets in
        # the CSV confirm this). This keeps a single tz-aware index.
        try:
            local = instants.dt.tz_convert("America/New_York")
        except Exception:
            local = instants
        idx = pd.DatetimeIndex(local, name=date_col)
    df = raw.drop(columns=[date_col]).copy()
    df.index = idx
    # Coerce numeric price columns the way the live path expects.
    for col in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@contextlib.contextmanager
def recording(root: Path) -> Iterator[FixtureStore]:
    store = FixtureStore(root, "record")
    token = _active.set(store)
    try:
        yield store
    finally:
        _active.reset(token)


@contextlib.contextmanager
def replaying(root: Path) -> Iterator[FixtureStore]:
    store = FixtureStore(root, "replay")
    token = _active.set(store)
    try:
        yield store
    finally:
        _active.reset(token)


def active() -> FixtureStore | None:
    return _active.get()


# --- type-aware helpers used at the vendor call sites -----------------------
# Each: when a store is active it records/replays; otherwise it just runs the
# thunk. This keeps the call sites a single-line change and guarantees identical
# behaviour when fixtures are off.

def history(key: str, thunk: Callable[[], Any]) -> Any:
    """``yf.Ticker(symbol).history(...)`` -> pandas DataFrame, recorded as CSV.

    ``key`` should uniquely identify the request (e.g. ``symbol|start|end``) so a
    replay serves the exact range the caller asked for.
    """
    store = _active.get()
    if store is None:
        return thunk()
    if store.mode == "replay":
        def _read(path: Path):
            return _read_history_csv(path)
        return store.load_csv("market", key, _read)
    data = thunk()
    if data is not None and hasattr(data, "to_csv"):
        store.save_csv("market", key, lambda fh: data.to_csv(fh))
    return data


def news_list(symbol: str, thunk: Callable[[], Any], *, count: Any = None) -> Any:
    """``yf.Ticker(symbol).get_news(count=...)`` -> list[dict], recorded as JSON.

    ``count`` (the requested article limit) is part of the key: the response
    depends on it, so two different limits must never share one fixture.
    """
    store = _active.get()
    if store is None:
        return thunk()
    key = f"{symbol}|{count}"
    if store.mode == "replay":
        return store.load_json("news", key)
    data = thunk()
    store.save_json("news", key, data)
    return data


def search_news(query: str, symbol: str, news_count: Any, thunk: Callable[[], Any]) -> Any:
    """``yf.Search(query, news_count=...)`` -> object with ``.news``, as JSON."""
    store = _active.get()
    if store is None:
        return thunk()
    key = f"{query}|{symbol}|{news_count}"
    if store.mode == "replay":
        payload = store.load_json("search", key)
        return SearchResult(news=payload.get("news"), quotes=payload.get("quotes"))
    obj = thunk()
    store.save_json("search", key, {
        "news": list(getattr(obj, "news", []) or []),
        "quotes": list(getattr(obj, "quotes", []) or []),
    })
    return obj

def search_news_list(query: str, symbol: str, news_count: Any, thunk: Callable[[], Any]) -> Any:
    """Per-query global search that yields the ``.news`` list (as the vendor does).

    ``thunk`` must return the ``.news`` list itself (i.e. it already does
    ``yf.Search(...).news``), so the no-store path is byte-identical to before
    and any exception (rate limit/timeout) still propagates through ``yf_retry``
    inside the thunk. When recording, the list is stored per query; when
    replaying it is served from the fixture with no Yahoo call.
    """
    store = _active.get()
    if store is None:
        return thunk()
    key = f"{query}|{symbol}|{news_count}"
    if store.mode == "replay":
        return store.load_json("search", key)
    found = thunk()
    store.save_json("search", key, list(found or []))
    return found

def tool_text(kind: str, key: str, thunk: Callable[[], Any]) -> str:
    """Record/replay the FINAL text a data tool returns to the analyst.

    Used for tools whose response is a formatted string assembled by the vendor
    (e.g. Polymarket prediction markets, FRED macro). The exact string the analyst
    would receive is stored (as JSON ``{"text": ...}``) and, on replay, served
    verbatim with NO vendor/network call. A sentinel such as FRED's
    "DATA_UNAVAILABLE ..." is stored as-is (we do not fabricate data that did not
    exist). Missing fixture / SHA256 mismatch raise; there is no live fallback.
    """
    store = _active.get()
    if store is None:
        return thunk()
    if store.mode == "replay":
        return store.load_json(kind, key).get("text", "")
    text = thunk()
    store.save_json(kind, key, {"text": text})
    return text
