# Prompt.md — the static launch instruction

This file is the instruction the coding agent is launched with. It is fixed text,
not a conversation. Read it with AGENTS.md, which carries the project's rules.

## 1. Read first

Read `AGENTS.md` before anything else, then this file, then
`docs/req/requirements.yaml`. If they disagree, stop and report the disagreement.

## 2. Produce a plan and stop

Do not write code until you have produced a plan covering:

- **Traceability** — which requirement IDs the work serves (FR-01..05, INV-01..03,
  COST-01, GOV-01). Every change you propose cites at least one.
- **Interface contracts** — the functions, state fields, tool schemas or files you
  will add or change, and the exact shape of each.
- **Scope boundaries** — the files you will touch, and the files you will not.
  Name what is out of scope explicitly.
- **Testing strategy** — which offline tests prove each requirement clause, and how
  they fail before the change and pass after.
- **Steps** — the stages you will build in, in order.

Then **STOP and wait for the human's approval**. The plan is not a formality: an
unapproved plan is not permission to start.

## 3. Build in stages, gate each one

After approval, implement one stage at a time. At the end of each stage:

1. Run `pytest test/offline` and report the summary line.
2. Say what changed, and what you did not change.
3. **STOP for the human gate** before starting the next stage.

## 4. Never run to completion unattended

Do not chain stages, do not "finish the job while you are here", and do not treat a
passing test run as approval for the next stage. If a gate is not answered, stop and
say so. Unattended completion is a failure mode, not a goal.

## 5. Do not

- Weaken, skip or delete a test to make the suite pass.
- Change the COST-01 numbers (8 / 8 / 3).
- Put an LLM call inside the safety guard.
- Push to a branch whose PR is merged, or force-push any branch.
