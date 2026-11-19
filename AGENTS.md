# AGENTS.md — coding agent entry point

Read this first. It says what the project is, how to run it, who owns what, what
is frozen, and how we check work before it merges.

## What this is

CS5351 group project. We vendored **TradingAgents** (TauricResearch) as our code
baseline and are changing it against a frozen set of requirements.

- Baseline: upstream commit `9fa1196` — details and the retrieval record in
  [BASELINE.md](BASELINE.md); the pristine upstream README is at
  [docs/upstream/README-9fa1196.md](docs/upstream/README-9fa1196.md).
- Our own README is [README.md](README.md).
- Requirements: [docs/req/requirements.yaml](docs/req/requirements.yaml).
- Status, frozen values and measurements: [docs/status.md](docs/status.md).

## Layout

```
src/tradingagents/          the package (agents/, graph/, dataflows/, llm_clients/, memory/)
src/tradingagents/dataflows/   the only place third-party data vendors may be imported
src/tradingagents/graph/setup.py   graph wiring — owned by C (see Ownership)
src/cli/                    the "tradingagents" CLI; entry point src/cli/main.py
src/main.py                 thin launcher
test/offline/               the suite we run on every change
test/live/                  tests that need real API keys/network (integration marker)
test/conftest.py            shared fixtures, also the network-blocking fixture
docs/req/requirements.yaml  10 requirement ids: FR-01..05, INV-01..03, COST-01, GOV-01
BASELINE.md                 provenance of the vendored code
```

`test/conftest.py` blocks the network for every test without the `integration`
marker, so most tests need no credentials.

## Run it

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # editable install from src/ (pyproject: package-dir = src)
cp .env.example .env        # then fill in the keys you need
tradingagents               # the CLI
```

Requires Python >= 3.11. Some providers need extras: `pip install -e ".[bedrock]"`.

## Tests

```sh
pytest test/offline         # what we run before committing (offline, no keys)
```

`pyproject.toml` sets `testpaths = ["test"]` and `-m "not integration"`, so a
bare `pytest` is offline too. `test/live/` holds tests marked `integration`
(real DeepSeek key); they are skipped by default and are not part of our gate.

## Requirements

Ten ids, frozen — never renumbered, never reused:
**FR-01..05, INV-01..03, COST-01, GOV-01**. Statements and fit criteria live in
[docs/req/requirements.yaml](docs/req/requirements.yaml). Additions get new ids.

A fit criterion is how work is judged: read the one you are implementing before
you write code, and make the change that satisfies it, not the one that is easiest
to test.

## Ownership

| Area | Owner |
|---|---|
| `src/tradingagents/graph/setup.py` (graph wiring) | C |
| The safety guard (deterministic pre-action checks), plain code | D |
| Everything else | whoever is leading that workstream — ask before editing |

D adds the safety guard but **does not edit `src/tradingagents/graph/setup.py`**.
D tells C what node/edge/state change the guard needs; C makes it. If you are
unsure who owns a file, stop and ask.

## Invariants you must not break

- **Third-party imports only in `src/tradingagents/dataflows/`.** Vendor calls
  belong there, where failures become `VendorError` subclasses rather than
  looking like facts about the market. `test/offline/test_layering.py` enforces
  this (`yfinance` today); do not weaken, skip or narrow that test.
- **`final_rating` is one of** `Buy`, `Overweight`, `Hold`, `Underweight`,
  `Sell`, or `REVIEW`. `REVIEW` means the decision was unusable and **must not be
  traded**; see `src/tradingagents/agents/rating.py`.
- **The safety guard is plain code.** No LLM calls inside it — it must be
  deterministic and testable offline.
- **COST-01 config is `8 / 8 / 3`**: `max_tool_rounds = 8`,
  `news_article_limit = 8`, three `global_news_queries` entries. Do not change
  those numbers to make a test pass. (The baseline still reads 20 / 20 / 5; the
  change to 8 / 8 / 3 is the work, not a given.)
- **`REVIEW` is not a tradeable position** — code that turns a rating into an
  action must handle it.

## Frozen — do not edit

For everyone, unless the team agrees otherwise in the open:

- `test/offline/` — the suite is the referee; change it only as part of a
  reviewed change that says why.
- `docs/req/requirements.yaml` — requirement ids and criteria.
- `BASELINE.md` — the vendored baseline record.
- `transcripts/` — meeting and session records.
- The vendored source itself is the baseline: keep changes deliberate and small.
  Never reformat, reorder imports, or delete "unused" files as part of another
  change.

## How we check work

1. Plan first and **wait for approval before writing code** — list the files you
   will change and why.
2. Make the change; keep it to the files you listed.
3. Run `pytest test/offline` and read the output — do not commit on failures
   without saying so.
4. Commit on a branch, push the branch, and say what you changed. Only the
   maintainer merges to `main`.

## Later

`docs/architecture/`, `.opencode/`, `.agent/` and `Prompt.md` are not written yet.
They are planned, not linked here — do not treat them as missing or invent them.
