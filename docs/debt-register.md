# Debt register

Known technical debt, recorded so it is tracked rather than silently carried.
Add a row when a shortcut or deferred fix is accepted; do not delete resolved
rows — mark them resolved and date the change.

## Open

| id | area | description | deferred to | recorded |
|---|---|---|---|---|
| DEBT-01 | CI / lint | The static-analysis gate runs `ruff check src/`. This PR reverted `src/` to main; the 9 ruff errors will be fixed by C's separate PR. Until that fix merges, `ruff check src/` does not pass. (The 9 are: I001 import sorting ×3, UP035/UP037 typing modernisation ×4, F401 unused import ×1.) | C's separate PR | 2026-11-21 |
| DEBT-02 | CI / lint | Legacy code **outside `src/`** (tests and evidence scripts) still carries **37 unresolved ruff errors** and is not gated, because the static-analysis gate runs `ruff check src/` only. | next sprint | 2026-11-21 |

## Resolved

_(none yet)_

