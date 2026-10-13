# Local stress r1 correction ledger

The dedicated `fix/stress-benchmark-findings` branch starts at `46a1134`, the
validated findings branch. Its own environment and structural index are isolated
from the running `local-stress-20261010-r1` campaign. Main and campaign evidence
remain unchanged. Six new commits correspond to the six approved corrections. A separately
authorized seventh commit fixes silent conditional progress omissions.

| Correction | Scope | State |
| --- | --- | --- |
| 1 | Shared CLI/MCP/daemon/family coverage classification | Implemented; focused tests and quality preflight pass |
| 2 | Clear terminal outcomes and timestamped progress | Implemented; 69 focused tests and quality preflight pass |
| 3 | Explicit renderer and outer architecture timeout controls | Implemented; 75 focused tests and quality preflight pass |
| 4 | Actual FAISS SIMD provenance and retained, quieter diagnostics | Implemented; 91 focused tests and quality preflight pass |
| 5 | Embedding phase attribution and interruption recovery | Implemented; 96 focused tests and final quality preflight pass |
| 6 | Integration, package/catalog/documentation alignment and full validation | Implemented; full gate passes: 1673 tests, 3 skips, 86% coverage |
| 7 | Explicit conditional skips without ordinal or resume fabrication | Implemented; 80 focused tests, quality preflight and full gate pass |

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


## Terminal reporting

Timestamp behavior from `eee8bef` is incorporated into this correction without
altering the original branch. Stage ordinals and pending counts still exclude
retained resume checkpoints. Machine statuses remain unchanged; terminal text
explains partial coverage, known failed-file/coverage-issue counts, no matches,
real command failures and optional SVG warnings. Unknown counts are not invented.
An embedding-only response's empty issue list does not erase structural gaps.
Plain-text workspace reads receive coverage annotation before printing, so the
terminal and persisted receipts agree. The shared implementation covers both
local suites; successful protocol requests do not imply semantic completeness.


## Architecture budgets

The runner previously imposed a 300-second outer deadline while silently using
Codira's 60-second SVG default. Both suites now pass an explicit inner Graphviz
limit, defaulting to the findings branch's 180 seconds. The outer default remains
300 seconds and includes extraction, report writing and rendering. Independent
zero values disable only their respective limit; shorter outer limits remain
valid operator controls and can interrupt rendering earlier. Both controls are
printed in the dry plan and stored in immutable identity, so changing either
requires a new run identity. Explicit per-command renderer arguments are retained.

Each successful repeated command preserves its renderer manifest beside raw
stdout/stderr. Mandatory reports and optional SVG availability/timings are separate
receipt fields; an optional timeout is shown prominently without being promoted
to a command failure. Outer timeouts still terminate only the owned process group.


## Native acceleration and MCP diagnostics

FAISS diagnostics record its version, binding module, compile options and, when
available, dynamic dispatch and active SIMD level. A generic binding name does
not imply generic execution: the inspected FAISS 1.15.0 wheel reports dynamic
dispatch and active AVX2 despite lacking a separate AVX2 Python module. Reading
these diagnostics never changes dispatch. Older wheels report unknown optional
fields rather than guessing. The plugin distribution advances to 2.0.1 and the
FAISS optional official bundle pin follows it in bundle 2.0.12.

Both benchmark suites retain MCP server stderr in each attempt's `mcp.stderr`,
referenced by its result receipt. Routine SDK/FAISS INFO messages no longer
interleave progress output. Actual tool errors still classify the attempt as
failed and name the affected tools; responses and attempt history remain intact.
The transport tests simulate the SDK boundary; native diagnostic tests inspect
the installed library. Neither is a corpus campaign or retrieval-quality claim.


## Embedding population and interruption recovery

Both backends previously fetched the entire pending queue, performed inference
for all selected texts, and committed structural pending removals only at the end.
They now select bounded segments using the existing embedding work-size control
and commit completed segments only for owned connections. Failed active segments
roll back; borrowed transactions remain caller-owned. Explicit embeddings-only
recovery also rebuilds similarity artifacts for an empty queue, closing the gap
between vector persistence and interrupted publication. No schema or vector
format changes are needed. SQLite advances to 2.0.3, DuckDB to 2.0.5 and their
official bundle pins follow in 2.0.13.

Opt-in shared profiling separates queue selection, cache lookup, inference,
serialization, persistence and commits, retaining interrupted phase evidence,
throughput and correctly scoped lifetime RSS. Native database regressions use
simulated inference; they verify both owned checkpoint recovery and borrowed
rollback, plus explicit empty-queue publication and unavailable profiling.
The [population recovery guide](../benchmarks/pending-embedding-recovery.md)
documents commands, units, transaction limits and measurement scope. Original
campaign timings do not isolate the slow phase; no whole-campaign improvement
is claimed from the focused persistence probe.


## Integration and final validation

The worktree inherits the validated findings at `46a1134`, including canonical
method inventories/graph aliases, C++ header routing and measured DuckDB inventory
query repair. Timestamp changes are incorporated by correction 2. The final
package pins and generated installer catalog are aligned; README developer
possibilities link the benchmark and embedding recovery procedures. Rejected
DuckDB performance candidates remain reverted. Prior native measurements do not
qualify the original campaign or these new runtime/runner controls.

Corrections 1–5 have their focused tests and quality preflights. Correction 6
passed the combined full repository gate in a named tmux session before
delivery: 1673 tests passed, 3 skipped, 86% coverage, including the seventh progress omission
correction. That source patch is tested in the combined working tree and will
be recorded after correction 6, preserving one commit per approved problem.
Main, the original running checkout and campaign artifacts remain unchanged.


## Conditional progress omissions

`StageProgress.omit` previously removed conditional stages silently. MCP probes
without a discovered identity could remove `mcp/cli-evidence`, making the pending
count jump with no corresponding terminal outcome. Newly omitted exact stages
and grouped children now each print one timestamped `skip` with their reason.
They decrement pending once and never advance measured-test ordinals. Repeated
omissions and retained resume checkpoints remain silent. No child measurement
receipt is fabricated for an omitted evidence probe.

Missing identities and embedding/concurrency prerequisites are exclusions; an
actual MCP failure remains a failed measured probe and its dependent evidence
is explicitly excluded. Both suites use this shared behavior, including final
orchestration cleanup. Focused tests cover missing MCP identity, true tool errors,
group counts, repeated omissions and retained partial checkpoint resume.
The seventh commit follows the original six. Original campaign artifacts remain
unchanged.
