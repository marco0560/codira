# Worktree integration and evidence retention — 2026-10-16

All five linked worktrees were integrated into `main`, validated, and removed.
Their branch refs remain available. No remote push or branch deletion was
performed.

## Integrated histories

| Branch | Retained tip | Integration |
| --- | --- | --- |
| `fix/benchmark-findings` | `46a1134` | Ancestor of the stress findings and final-tail fixes |
| `fix/benchmark-progress-timestamps` | `eee8bef` | Merge `34573d8` |
| `fix/local-docs-release-gate` | `41c39ef` | Merge `297d8ed` |
| `fix/stress-benchmark-findings` | `9de487f` | Ancestor of the final-tail fixes |
| `fix/stress-final-tail` | `d887c2e` | Fast-forward from the previous main |

The progress branch conflicted with later benchmark runner changes. Resolution
kept the later runner, documentation, and tests: its timestamp behavior was
already incorporated. The merge records its ancestry without replacing the
later diagnostics. The documentation-gate branch merged cleanly.

## Validation

The full repository gate passed on `297d8ed`: **1,713 passed, 3 skipped**, with
**86% coverage**. The final index processed 780 files with zero failures and
zero docstring coverage issues. All eight workflow quality preflight checks
passed, including the strict documentation build. Frozen benchmark revisions
were present; no fetch was needed.

Two existing untracked reports were parked during validation because one draft
contains local artifact links that trigger strict documentation warnings. Both
are restored byte-for-byte after validation and remain untracked. This result
covers the integrated source tree with those drafts excluded.

## Retained evidence and cleanup

Ignored evidence remains under
`.artifacts/analysis/worktree-integration-20261016/retained/<worktree>/files/`.
The worktree names are `codira-benchmark-findings`, `codira-benchmark-progress`,
`codira-docs-ci`, `codira-stress-findings`, and `stress-final-tail`.
Original paths are relative to each `files/` directory. Historical paths inside
raw records retain their original provenance and were not rewritten.

Preservation retained 7,789 file or symlink entries, including every nested
artifact file, totaling 27,558,848,093 regular-file bytes. Each regular file was
SHA-256 verified against its original twice; symlink targets were checked.
Per-worktree `preservation.json` receipts record the complete inventories.
Root virtual environments and rebuildable code caches were removed with the
worktrees; installed package inventories and environment configuration remain
under each retained worktree's `environment/` directory.

Before removal, every worktree was clean, every tip was an ancestor of main,
and no process working directory was inside a retired worktree. The original
`local-stress-20261010-r1/summary.json` still matches its pre-integration hash.
The integration directory retains `pre-removal-verification.json`,
`original-campaign-verification.json`, and `full-gate-result.json`. Only the
main worktree remains registered after cleanup.
