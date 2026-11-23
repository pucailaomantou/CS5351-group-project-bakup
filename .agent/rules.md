# .agent/rules.md — project covenant

The standing agreement between the humans and the agents on this project. It is
human-owned: agents propose changes to it, humans merge them.

## 1. Abstraction limit

Build to the abstraction the requirement needs, and not one layer more. Introduce a
new module, class, base type or plugin seam only when a second concrete caller
exists or a requirement names the extension point. A single-use abstraction is
debt, not design. If you find yourself writing a factory for a factory, stop and
justify it in the PR.

## 2. Dependency constraint

No new third-party dependency without an explicit, approved reason recorded in the
PR — what it replaces, why the standard library or an existing dependency cannot do
it, and its licence. Third-party vendor code stays behind
`src/tradingagents/dataflows/`; everything else uses the routed interface. Vendoring
a dependency is a baseline change and needs the same approval as the code baseline.

## 3. One negative test per feature

Every feature ships with at least one **negative** test: the case that must not
work. For this project that means, per feature, a test proving the failure path
behaves — an unreadable rating becomes `REVIEW` and is not traded, a vendor outage
is reported as unavailable rather than as absent data, a guard rejects a decision
rather than passing it. A feature with only happy-path tests is not finished.

Negative tests live with the rest of the offline suite and never reach the network.

## 4. Safety-critical code

Changing safety-critical code (`src/tradingagents/safety/`,
`src/tradingagents/agents/rating.py`, `src/tradingagents/agents/schemas.py`,
`src/tradingagents/agents/post_screen.py`,
`src/tradingagents/graph/setup.py`) requires:

1. an **ADR** in `docs/architecture/adr/` recording the decision, the alternatives
   rejected and the failure mode being prevented; and
2. **human approval** before merge, every time — not a blanket approval once.

The guard stays plain code with zero LLM calls. An ADR that proposes an LLM inside
the guard is out of order and must be rejected.

## 5. Rules stay current

When `docs/req/requirements.yaml` changes, the rules here, `.opencode/rules.md`
and `AGENTS.md` are reviewed and refreshed **within one sprint**. A rule that
contradicts the requirements is a defect: the tests would enforce one thing while
the written rules say another. Record the refresh in `docs/status.md`.

## 6. How disagreements are settled

The requirement wins over the rule, the rule wins over the implementation, and the
human wins over all three. Where they conflict, raise it rather than choosing
silently.
