# Debt register

Known technical debt, recorded so it is tracked rather than silently carried.
Add a row when a shortcut or deferred fix is accepted; do not delete resolved
rows — mark them resolved and date the change.

## Open

| id | area | description | deferred to | recorded |
|---|---|---|---|---|
| DEBT-02 | CI / lint | Legacy code **outside `src/`** (tests and evidence scripts) still carries **37 unresolved ruff errors** and is not gated, because the static-analysis gate runs `ruff check src/` only. `src/` itself is now clean (see DEBT-01). | next sprint | 2026-11-21 |

## Resolved

| id | area | description | resolved |
|---|---|---|---|
| DEBT-01 | CI / lint | The static-analysis gate runs `ruff check src/` only. The 9 pre-existing ruff errors within `src/` (I001 import sorting, UP035/UP037 typing modernisation, one F401 unused import; all in vendored/fixture code) were auto-fixed, so `ruff check src/` now exits 0 and the gate is green. The remaining lint debt is outside `src/` and tracked as DEBT-02. | 2026-11-21 |

