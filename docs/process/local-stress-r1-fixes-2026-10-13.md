# Local stress r1 correction ledger

The dedicated `fix/stress-benchmark-findings` branch starts at `46a1134`, the
validated findings branch. Its own environment and structural index are isolated
from the running `local-stress-20261010-r1` campaign. Main and campaign evidence
remain unchanged. Six new commits correspond to the six approved corrections.

| Correction | Scope | State |
| --- | --- | --- |
| 1 | Shared CLI/MCP/daemon/family coverage classification | Implemented; focused tests and quality preflight pass |
| 2 | Clear terminal outcomes and timestamped progress | Pending |
| 3 | Explicit renderer and outer architecture timeout controls | Pending |
| 4 | Actual FAISS SIMD provenance and retained, quieter diagnostics | Pending |
| 5 | Embedding phase attribution and interruption recovery | Pending |
| 6 | Integration, package/catalog/documentation alignment and full validation | Pending |

## Coverage classification

The original MCP classifier checked failed selected files (`partial`) but omitted
broader incomplete coverage (`complete=false`). Thus usable indexes with zero
failed files could enter the complete-index cohort despite known coverage gaps.
CLI and MCP now share the predicate; ready daemon generation records also account
for `coverage_complete=false`. MCP/family aggregation checks all tool responses,
so a later complete response cannot erase an earlier incomplete member.

Operational errors and unusable indexes retain precedence. Empty query responses
remain distinct from partial coverage and do not prove repository-wide absence.
Timing eligibility is explicit for complete, partial and unusable outcomes.
Resume regressions include failure-free coverage gaps as well as failed files.

The first focused validation passed 59 tests. Reclassification of 22 retained
MCP observations changed 19 original `passed` outcomes to `partial`; three were
already partial. This is a diagnostic replay, not a replacement campaign result.
Original receipts and timings were never overwritten. The replay with source
receipt digests is in the dedicated worktree's ignored
`.artifacts/validation/stress-findings-20261013/coverage-reclassification.json`.
The final quality preflight passes lint, formatting, typing, Semgrep, refreshed
indexing and docstring checks; initial typing failure evidence is retained.

Integration onto main and operator-run measurement campaigns follow completion
of the current stress run. Existing malformed fixtures remain evidence; the
runner does not add exclusions or retry deterministic failures automatically.
