# COST-01 evidence — NVDA / 2026-11-19 cost comparison (candidate)

This directory lets team members **independently recompute the latest statistics and
inspect sample selection and supplement evidence** from files stored in the
repository. It is an evidence delivery, not a requirement change.

> **Status:** candidate evidence, pending B/E confirmation. This PR does **not**
> declare the `requirements.yaml` active baseline migrated, and does **not** declare
> final COST-01 acceptance. The core implementation is already in `main` via **PR #7**.
> Formal baseline/criterion updates remain with B/E.

## Protocol

- **Analysis date: 2026-11-19** (fixed), US market trading day, intraday collection
  permitted. The date was NOT auto-changed to the last-closed day.
- **Shared 7-day ticker news window** on both sides: **2026-11-12 .. 2026-11-19**,
  via a shared, explicit news-window adapter (`protocol/d4_news_window_adapter.py`,
  sha256 `4fb6cab37adc075aa51f5457653371a0959d14a834688f464eef7b67aacf91ca`). The
  adapter re-anchors `get_news` to `[trade_date-7d, trade_date]` and states the
  requested vs effective window in the tool return. It is **archived here for the
  record and is NOT wired into the application / not a production default.**
- **Before** — true upstream `tradingagents-upstream @ 9fa1196`,
  `max_tool_rounds/news_article_limit/global_news_queries = 20/20/5`.
- **After** — the measured version that was merged in PR #7, `8/8/3`; frozen 16-file
  `d2d3_file_sha256` in each After record match that measurement (news.py frozen sha
  `0233bb76019e6425b0f90a2bfa150a49d22dd84822d489296cd2ee6be047edef`).
- **Model:** course DeepSeek API `CS5351/DeepSeek-V4-Flash`, `temperature=0.0`,
  analysts `market+news`, research/risk rounds `1/1`.
- Data layer: **live Yahoo** on both sides (fixed-news adapter NOT used).

## Sample selection (fixed; do not re-select)

Selection is defined by [`review/SAMPLE-LIST-REVISED.csv`](review/SAMPLE-LIST-REVISED.csv)
(24 rows, unique run_ids). Records are under [`records/`](records/); every record is a
**verbatim copy** of the original run JSON (byte-identical; SHA checked in
[`index/record-locations.json`](index/record-locations.json)).

Accounting:
- **Before — 12 records**: 10 included (8 original + 2 supplement) + 2 `excluded_per_BE`.
  - excluded: `20261120_032135_28a781b6`, `20261120_032332_fe83feb4` (141 market rows;
    original JSON and its `valid` field are unchanged — exclusion is a selection
    decision, not an edit).
  - supplement: `20261120_114222_f2932b46`, `20261120_114441_2a33e022`.
- **After — 12 records**: 10 included + 2 failed (kept):
  - failed: `20261120_035236_01461635` (`market_data_incomplete`, `timeout`),
    `20261120_040304_484e3073` (`news_data_incomplete`, `ssl_error`).
- Selection is by run_id, **not** by token value.

## Statistics (independently recomputed from the records in this directory)

| set | n | sum | mean | median |
|---|---|---|---|---|
| Before (included) | 10 | **1603158** | **160315.8** | **159615** |
| After (included) | 10 | **1477542** | **147754.2** | **148087** |

- Mean reduction **≈ 7.84%**, median reduction **≈ 7.22%** (After both lower).
- **After attempted total = 1729316 across 12 attempts**; the two failed After runs
  are reported as **failed-run overhead, listed separately, and NOT summed with the
  10 valid Before samples** for the primary comparison.
- The earlier Before values 153510.4 / 154416.5 (and their delta) are **superseded and
  not used**.

Source of truth for the numbers: [`review/summary_revised.json`](review/summary_revised.json).

## How to recompute

From the repository root, with the project Python:

```sh
python - <<'PY'
import csv, json, statistics
B = "docs/evidence/cost01-2026-11-19"
rows = list(csv.DictReader(open(f"{B}/review/SAMPLE-LIST-REVISED.csv")))
def tok(r):
    d = "before" if r["side"] in ("before","before_supplement") else "after"
    return json.load(open(f"{B}/records/{d}/{r['run_id']}.json"))["usage"]["total_tokens"]
before = [tok(r) for r in rows if r["side"] in ("before","before_supplement") and r["status"]=="included"]
after  = [tok(r) for r in rows if r["side"]=="after" and r["status"]=="included"]
after_all = [tok(r) for r in rows if r["side"]=="after"]
for name,v in (("before",before),("after",after)):
    print(name, "n",len(v),"sum",sum(v),"mean",round(statistics.mean(v),1),"median",statistics.median(v))
print("after attempted sum (12):", sum(after_all))
print("mean delta %", round((statistics.mean(after)-statistics.mean(before))/statistics.mean(before)*100,2))
print("median delta %", round((statistics.median(after)-statistics.median(before))/statistics.median(before)*100,2))
PY
```

Expected: Before `1603158 / 160315.8 / 159615`; After `1477542 / 147754.2 / 148087`;
after attempted sum `1729316`; deltas `-7.84` / `-7.22`.

## Supplement (Before re-runs with market evidence)

- Records: `records/before/20261120_1142*.json` and `..._114441_*.json`.
- Market evidence: [`supplement/market_evidence/`](supplement/market_evidence/) — for
  each run a manifest JSON (request args, header range, row count, first/last date,
  response sha256) plus the **verbatim raw tool response** `.txt`. These were captured
  from the graph's own message stream (each `get_stock_data` call paired with the
  `ToolMessage` of matching `tool_call_id`) — not from cache/report/re-query.
- The two supplement runs executed on **UTC 2026-11-20** (see limitations).

## Limitations (state these when citing)

- **Cross-UTC-day supplement:** the two Before re-runs ran on UTC 2026-11-20 though the
  analysis date is fixed 2026-11-19. The different execution time may affect the news
  obtainable within the window and the market closing/last values; the size of the
  difference is not quantified. Analysis date and news filter window remain fixed at 11-19.
- **Inputs are not fully fixed.** Before does not record provider fixtures for news/
  other tools, so **Before is not fully replayable**; only the two supplement runs'
  market request→response is proven.
- **The other 8 Before samples lack direct request-range evidence** (only their run
  records are shipped; the original local cache path is not in the repo). This
  supplement does not retro-fix them.
- **252 vs 264 market rows** correspond to different requested start ranges, not data
  loss; completeness is judged from the request/response, not from row count or
  first/last date alone.
- The original **2026-11-18** experiment is preserved separately and is **not** mixed
  into these numbers.

## Directory map

- `review/` — the four latest review materials (paths rewritten to repo-relative;
  content otherwise preserved). `summary_revised.json`, `SAMPLE-LIST-REVISED.csv`,
  `MARKET-EVIDENCE.csv` (24 rows), `CANDIDATE-REVIEW-REVISED.md`.
- `records/before/` — 12 Before run JSONs (10 included + 2 excluded), verbatim.
- `records/after/` — 12 After run JSONs (10 valid + 2 failed), verbatim.
- `supplement/market_evidence/` — supplement market manifests + verbatim raw `.txt`.
- `supplement/SUPPLEMENT-README.md` — supplement narrative.
- `protocol/` — archived experiment-layer code (news-window adapter + drivers + market
  evidence capture). **Not connected to the application.**
- `index/record-locations.json` — repo-relative locator + record sha256 (documents the
  original absolute local paths for provenance).
- `SHA256SUMS.txt` — checksums of every delivered file (excludes itself).

## What this evidence does NOT claim

- Not the ADR's old-batch `r=0.9995` (that figure's source is not in this set; no new
  correlation or causal explanation is asserted here).
- Not a declared migration of the active baseline nor a passed COST-01 assessment.
