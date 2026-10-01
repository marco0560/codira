# Generated artifact directory manifest

This directory contains ignored run output and local runtime state. Keep its
contents untracked except for this manifest and explicitly approved summaries.
Do not move or delete files in an experiment identity without explicit operator
approval. See the [retention review](../docs/process/artifact-retention-review-2026-09-27.md)
for the completed cache cleanup and detailed keep-versus-summarize decisions.

## Directory map

| Path | Contents | Default handling |
| --- | --- | --- |
| `agent-efficiency/attempts/<identity>/` | Attempt workspaces, records, responses, receipts, and fixture state; moved here from the former `ae/` group | Preserve as immutable evidence. Do not rewrite, merge, or retry an identity. |
| `agent-efficiency/campaigns/<campaign-id>/` | Factory-generated campaign manifests and launch plans | Preserve each generated identity. |
| `agent-efficiency/executions/<record-id>/` | Execution logs, receipts, preflights, source-preparation records, and fixture copies; existing suffixes distinguish execution, rerun, and source records | Preserve each record identity with related campaign and attempt evidence. |
| `agent-efficiency/environment-images/`, `gates/`, `reviewer-evaluation/` | Prepared image evidence, validation runs, and reviewer evaluations | Keep records grouped by purpose; retain log/exit pairs. |
| `benchmarks/backend/<run-id>/` | Dated backend campaigns and Hyperfine, phase, profile, and selection artifacts | Preserve each run and its detailed measurement files. |
| `benchmarks/campaigns/<run-id>/` | Output from the generic benchmark campaign runner | Keep the run plan, result data, and logs together. |
| `benchmarks/experiments/` | Issue 55 concurrency runs and vector-store authority investigation | Keep each named experiment together. |
| `benchmarks/embedding/runs/` | Default output destination, created when an embedding campaign runs | Keep generated configs, measurements, and reports together by timestamp. |
| `benchmarks/retrieval-quality/runs/<dataset-id>/<timestamp>/` | Retrieval-quality campaign outputs grouped by dataset and timestamp | Preserve dataset provenance and measured results. |
| `benchmarks/release/` | Default destination for the release-oriented Hyperfine trace | Keep the trace with release review records. |
| `benchmarks/semantic-pipeline/<run-id>/` | Semantic-pipeline campaigns, corrections, recovery, and reruns | Preserve separate run identities; do not consolidate similar runs. |
| `validation/repo-gates/` | Repository-gate logs and exit statuses | Keep each log with its terminal status. |
| `analysis/`, `callgraphs/`, `worktrees/` | Derived investigations, generated graphs, and temporary worktrees | Retain while referenced; check active worktree registrations before cleanup. |

Historical generated receipts and campaign manifests retain path values from
when each run occurred. Current scripts and documentation use the grouped paths
above; do not rewrite immutable run contents to change historical provenance.

## Rules

- Keep raw result JSON, manifests, exact provider-response evidence, terminal
  records, failure evidence, task records, and source profiles. A short summary
  does not replace these audit records by default.
- Keep logs with their exit-status file. The logs are small relative to the
  dataset and may contain the cause of a failed or unusual run.
- The reviewed per-attempt `uv-cache` copies were removed after approval and
  confirmation that the prepared image caches remain available. Keep those
  image caches and all other attempt evidence. Review any different cache group
  separately before proposing cleanup.
- Keep this directory ignored. Only this manifest and approved, sanitized
  summaries may be tracked; do not unignore raw runtime trees.

## Product/harness qualification evidence

Retain per-campaign runtime qualification receipts and complete stdout/stderr,
protected oracle traces, blinded quality packets, append-only adjudications and
example replay manifests/streams alongside attempt evidence. These may contain
complete answers and repository-local runtime paths; keep them ignored. Offline
retrieval receipts belong in `analysis/` under a fresh investigation identity.
Summaries must distinguish offline qualification from paid task efficacy.
