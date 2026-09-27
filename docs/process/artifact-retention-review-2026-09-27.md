# Benchmark and artifact retention review — 2026-09-27

## Scope and method

Inventory, physical reorganization, and approved cleanup of `benchmarks/` and
`.artifacts/`. Existing experiment leaf names and contents were preserved while
their parent directories were grouped by benchmark family and artifact role.
Sizes are approximate filesystem usage from `du`; separate directory totals
can overlap when files are hard-linked, so they should not be added together as
a reclaimed-space estimate.

## Findings

- `.artifacts/` measured about 222 GiB before cleanup and about 86 GiB after it,
  a reduction of roughly 136 GiB by `du`.
- The nineteen completed agent-efficiency attempt environments originally had
  `agent/.benchmark/uv-cache/` trees with a combined `du` total of about 152
  GiB. The runner copies a prewarmed cache into the attempt environment, then
  uses frozen offline dependency sync; this cache is dependency-install
  machinery, not task output. The exact attempt-local copies were removed after
  approval. The prepared image copies remain available.
- Twenty-four agent-efficiency `.venv` trees account for about 82 GiB when
  measured separately. Keep these for now: they record the installed runtime
  used by each attempt and support direct forensic inspection. Cache and
  environment trees shared hard-linked files, so the measured reduction in
  `.artifacts/` was less than the cache directories' separate `du` total.
- `.artifacts/benchmarks/` contains 1,281 files. Its 616 `*.log` files total
  about 3.6 MB. The logs are small and can contain diagnostics not captured by
  structured results, so retain them with their `.exit` files.
- Dated performance runs include campaign plans, selection data, Hyperfine
  traces, phase timings, profile summaries, and profiler outputs. Keep these
  together: summaries alone do not retain the detailed comparison and
  reproduction evidence.
- Corrected, recovery, and rerun semantic-pipeline results now sit under
  `.artifacts/benchmarks/semantic-pipeline/`. Their distinct identities remain
  separate because they provide useful provenance.
- Benchmark inputs are grouped under `benchmarks/agent-efficiency/`,
  `benchmarks/embedding/`, `benchmarks/retrieval-quality/`,
  `benchmarks/performance/`, and `benchmarks/semantic-pipeline/`. Runtime
  outputs are grouped under `.artifacts/agent-efficiency/`,
  `.artifacts/benchmarks/`, and `.artifacts/validation/`. Code, documentation,
  tests, and local-only manifests were migrated to the new input paths.
- Existing run leaf names and evidence remain intact. Immutable generated
  receipts and manifests retain historical path values as provenance; current
  scripts and documentation use the grouped layout.

## Cleanup decision table

| Group | Recommendation | Reason and replacement summary |
| --- | --- | --- |
| `.artifacts/agent-efficiency/attempts/**/agent/.benchmark/uv-cache/` (19 trees, about 152 GiB by `du`) | Removed after explicit approval and image-cache verification | The three referenced fixture-image digests were present locally; no-network, read-only checks confirmed the embedded cache in each. Kept this aggregate inventory and the affected attempt identities here. |
| `.artifacts/agent-efficiency/attempts/**/agent/.venv/` (24 trees, about 82 GiB by separate `du`) | Keep for now | Installed environment from the actual attempt; useful for direct forensic examination and repeatability. |
| `.artifacts/agent-efficiency/attempts/**/state/attempt-work/` other than the cache candidate | Keep | Contains task workspaces, events, state, provider response evidence, protected baselines, and run records. These are primary experiment evidence. |
| `.artifacts/benchmarks/**/logs/` and `.artifacts/validation/repo-gates/` logs/exits | Keep | Only about 3.6 MB for benchmark logs; preserve diagnostics and paired terminal exit state. |
| Hyperfine, phase timing, profile summary, selection, campaign-plan, and profiler files | Keep | Needed for detailed comparison, provenance, or future profiling; a prose summary cannot replace them. |
| `.artifacts/benchmarks/semantic-pipeline/`, `retrieval-quality/`, backend, and dated campaign roots | Keep for now | Distinct historical identities and recovery/correction provenance have not been proven redundant. |
| `.artifacts/worktrees/` | Keep until checked | Currently empty by size inspection; verify worktree registrations before removing the directory. |
| `benchmarks/{performance,embedding,semantic-pipeline}/*.local.json` | Keep in place, untracked where ignored | Operator-local inputs may contain machine-specific paths. They were moved with their benchmark family and remain ignored. |

The approved cleanup removed only the per-attempt `uv-cache` trees. The
directory reorganization moved benchmark inputs and runtime-output groups into
the categories above. It did not delete or rewrite run evidence: prepared
images, `.venv` environments, campaign manifests, logs, response bodies,
records, workspaces, and exit statuses remain intact. Original run leaf names
were retained under their new parents.

## Completed cleanup scope

The approved scope was limited to the nineteen directories matching
`.artifacts/agent-efficiency/attempts/**/agent/.benchmark/uv-cache/` in
completed attempts. All sibling files and directories were preserved,
especially `.venv`, campaign manifests, logs, response bodies, records,
workspaces, and exit status. The aggregate before-and-after size and affected
run identities below summarize the removed caches without replacing experiment
results or provider evidence.

Affected attempt identities are:

- `007`: `patch-001-r01-codira-mcp`
- `008`: `symbols-001-r01-codira-mcp`
- `009`: `patch-001-r01-codira-mcp`
- `010`: `patch-001-r01-baseline`, `patch-001-r01-codira-mcp`,
  `symbols-001-r01-baseline`, and `symbols-001-r01-codira-mcp`
- `012`: `symbols-001-r01-baseline`
- `013` and `014`: `patch-001-r01-baseline`, `patch-001-r01-codira-mcp`,
  `symbols-001-r01-baseline`, and `symbols-001-r01-codira-mcp` in each run
- `c012a`: `patch-001-calibration-codira-mcp`
- `c013a`: `patch-001-calibration-codira-mcp`
- `e014a`: `patch-002-calibration-codira-mcp`

The campaign specs reference three distinct prepared fixture-image digests.
All three remained available locally. A no-network, read-only check confirmed
that each image contains the offline fixture cache before cleanup. A
post-cleanup inventory found zero attempt-local `uv-cache` directories and all
24 `.venv` directories still present.

## Privacy review

This report uses repository-relative paths and aggregate counts only. It omits
machine paths, user names, credentials, provider payloads, and local dataset
contents.
