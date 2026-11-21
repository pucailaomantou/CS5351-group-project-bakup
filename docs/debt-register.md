# Debt register

Known technical debt, recorded so it is tracked rather than silently carried.
Add a row when a shortcut or deferred fix is accepted; do not delete resolved
rows — mark them resolved and date the change.

## Open

| id | area | description | deferred to | recorded |
|---|---|---|---|---|
| DEBT-01 | CI / lint | The static-analysis gate runs `ruff check src/` only. Legacy code outside `src/` (tests, evidence scripts) carries **46 unresolved ruff errors** and is not gated. Within `src/`, **9 pre-existing ruff errors** remain (I001 import sorting, UP035/UP037 typing modernisation, one F401 unused import), all auto-fixable and in vendored/fixture code, none introduced by the D3 work. Scoped down in the sprint of 2026-11-21 to avoid blocking all PRs on pre-existing debt. | next sprint | 2026-11-21 |

## Resolved

_(none yet)_
