# .opencode/rules.md — always-on behavioural rules

These apply to every session, every agent, every task. They are not suggestions.

## 1. The safety guard is plain code

Everything under `src/tradingagents/safety/` is deterministic code with **zero LLM
calls**. No model decides whether a decision is safe, whether a rating is
tradeable, or whether a run may proceed. If a rule needs judgement, it belongs
outside the guard.

## 2. Ratings

`final_rating` is exactly one of: `Buy`, `Overweight`, `Hold`, `Underweight`,
`Sell`, `REVIEW`. **`REVIEW` is never tradeable** — it means the decision could
not be read, and code that turns a rating into an action must treat it as "do
nothing", not as "hold".

## 3. COST-01 is 8 / 8 / 3

`max_tool_rounds = 8`, `news_article_limit = 8`, three global news queries. These
numbers are the requirement. Do not change them to make a test pass, to speed up a
run, or because a measurement suggests something else. Changing them is a
requirement change, not an implementation detail.

## 4. Vendor imports live in one place

Third-party data vendors are imported only under
`src/tradingagents/dataflows/`. Everywhere else uses the routed interface, so a
vendor failure surfaces as a `VendorError` instead of looking like a fact about the
market. `test/offline/test_layering.py` enforces this; never weaken it.

## 5. Every change cites a requirement

Every commit, PR and plan names the requirement IDs it serves (FR-01..05,
INV-01..03, COST-01, GOV-01). If you cannot name one, the change is out of scope
unless the human says otherwise.

## 6. Never cheat the tests

Never skip, xfail, delete, narrow or weaken a test to make a suite pass. A failing
test is a finding: report it. If the test is wrong, say why and get approval before
changing it.

## 7. Vendored source is untouched by style

No reformatting, no import reordering, no "cleanup" of the vendored packages under
`src/tradingagents/` and `src/cli/`. Changes are deliberate and small, and belong to
the owner of the file. Lint fixes are their own reviewed change.

## 8. Boundaries and approvals

- `BASELINE.md`, `transcripts/` and `docs/upstream/` are frozen for everyone.
- Changing `src/tradingagents/safety/`, `src/tradingagents/graph/setup.py`,
  `src/tradingagents/default_config.py`, `docs/req/` or `test/offline/` requires
  human approval every time.
- D never edits `src/tradingagents/graph/setup.py`; D tells C what to add.

## 9. Ask when unsure

If a rule, a path or an owner is unclear, stop and ask. Guessing at ownership is
how a frozen file gets edited by the wrong person.
