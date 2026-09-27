# Benchmark and artifact retention review — 2026-09-27

## Scope and method

Read-only inventory of `benchmarks/` and `.artifacts/`. No artifact was moved,
renamed, or deleted. Sizes are approximate filesystem usage from `du`; separate
directory totals can overlap when files are hard-linked, so they should not be
added together as a reclaimed-space estimate.

## Findings

- `.artifacts/` uses about 222 GiB; `.artifacts/ae/` accounts for about 219 GiB.
- Nineteen completed agent-efficiency attempt environments contain
  `agent/.benchmark/uv-cache/` trees. Their combined `du` total is about 152 GiB.
  The runner copies a prewarmed cache into the attempt environment, then uses
  `uv sync --offline --frozen`; this cache is dependency-install machinery, not
  task output. The cache should be reconstructible from the matching prepared
  image's fixture-environment material.
- Twenty-four agent-efficiency `.venv` trees account for about 82 GiB when
  measured separately. Keep these for now: they record the installed runtime
  used by each attempt and support direct forensic inspection. Cache and
  environment trees may share hard-linked files, so actual free space after a
  cache cleanup can be less than the cache `du` total.
- `.artifacts/benchmarks/` contains 1,281 files. Its 616 `*.log` files total
  about 3.6 MB. The logs are small and can contain diagnostics not captured by
  structured results, so retain them with their `.exit` files.
- Dated performance runs include campaign plans, selection data, Hyperfine
  traces, phase timings, profile summaries, and profiler outputs. Keep these
  together: summaries alone do not retain the detailed comparison and
  reproduction evidence.
- The `semantic-pipeline-*` groups distinguish corrected runs, recovery, and
  reruns. Their distinct identities are useful provenance; do not consolidate
  them based only on similar names.
- `benchmarks/` already groups the agent-efficiency controls by campaign
  specification, schema, fixture, task, oracle, and protected probe. The other
  benchmark manifests have established paths used by code and documentation;
  preserve those paths until every consumer and local-only configuration can
  be migrated together.

## Cleanup decision table

| Group | Recommendation | Reason and replacement summary |
| --- | --- | --- |
| `.artifacts/ae/**/agent/.benchmark/uv-cache/` (19 trees, about 152 GiB by `du`) | Candidate for removal only after explicit approval and verification that each matching prepared image still contains the offline fixture cache | Recreated by copying the prepared fixture cache and running frozen offline dependency sync. The tracked record should retain only the aggregate count/size, campaign identities, and the cache-rebuild source. Exact recovered disk space must be measured after removal because of hard links. |
| `.artifacts/ae/**/agent/.venv/` (24 trees, about 82 GiB by separate `du`) | Keep for now | Installed environment from the actual attempt; useful for direct forensic examination and repeatability. |
| `.artifacts/ae/**/state/attempt-work/` other than the cache candidate | Keep | Contains task workspaces, events, state, provider response evidence, protected baselines, and run records. These are primary experiment evidence. |
| `.artifacts/benchmarks/**/logs/` and root gate logs/exits | Keep | Only about 3.6 MB for benchmark logs; preserve diagnostics and paired terminal exit state. |
| Hyperfine, phase timing, profile summary, selection, campaign-plan, and profiler files | Keep | Needed for detailed comparison, provenance, or future profiling; a prose summary cannot replace them. |
| `.artifacts/semantic-pipeline-*`, retrieval-quality, and dated campaign roots | Keep for now | Distinct historical identities and recovery/correction provenance have not been proven redundant. |
| `.artifacts/worktrees/` | Keep until checked | Currently empty by size inspection; verify worktree registrations before removing the directory. |
| `benchmarks/*.local.json` | Keep in place, untracked where ignored | Operator-local inputs may contain machine-specific paths and existing commands use these paths. Do not commit or relocate them as part of cleanup. |

The only recommended deletion candidate at this stage is the per-attempt
`uv-cache` tree, and even that requires confirming the corresponding prepared
image/cache material. No deletion is authorized or performed by this review.

## Candidate cleanup scope

The proposed scope is limited to the nineteen directories matching
`.artifacts/ae/**/agent/.benchmark/uv-cache/` in completed attempts. Preserve
all sibling files and directories, especially `.venv`, campaign manifests,
logs, response bodies, records, workspaces, and exit status. Before execution,
verify the matching prepared image/cache source; after approval and cleanup,
record the actual reclaimed space and affected run identities here. This
document is the proposed summary that would preserve the aggregate cache
inventory; it does not replace experiment results or provider evidence.

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

The matching prepared image/cache source has not yet been verified as present,
so the cache candidate is not ready for execution. Approval should cover this
exact set only, conditional on confirming the source cache is available. If it
is unavailable, leave these directories untouched and report that condition.

## Privacy review

This report uses repository-relative paths and aggregate counts only. It omits
machine paths, user names, credentials, provider payloads, and local dataset
contents.
