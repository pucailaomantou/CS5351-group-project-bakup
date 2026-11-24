# Debt register

Known technical debt, recorded so it is tracked rather than silently carried.
Add a row when a shortcut or deferred fix is accepted; do not delete resolved
rows — mark them resolved and date the change.

## Open

| id | area | description | deferred to | recorded |
|---|---|---|---|---|
| DEBT-02 | CI / lint | Legacy code **outside `src/`** (tests and evidence scripts) still carries **37 unresolved ruff errors** and is not gated, because the static-analysis gate runs `ruff check src/` only. | next sprint | 2026-11-21 |

## Resolved

| id | area | description | resolved |
|---|---|---|---|
| DEBT-01 | CI / lint | Fixed by PR #17 (commit 32e02b0): the 9 pre-existing style errors in five vendored files (2×I001, 3×UP035, 3×UP037, 1×F401) are gone; `ruff check src/` now exits 0. | 2026-11-23 |

