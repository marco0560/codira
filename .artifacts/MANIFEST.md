# Generated artifact directory manifest

This directory contains ignored run output and local runtime state. Except for
this manifest and explicitly approved summaries, its contents stay untracked.
Do not move or delete files in an experiment identity without explicit operator
approval. See the [retention review](../docs/process/artifact-retention-review-2026-09-27.md)
for the completed cache cleanup and keep-versus-summarize decisions.

## Current groups

| Path or naming pattern | Contents | Default handling |
| --- | --- | --- |
| `ae/<identity>/` | Agent-efficiency factory output, receipts, attempt state, fixture copies, records, provider responses, and attempt workspaces | Preserve as immutable evidence. Do not rewrite, merge, or retry an identity. |
| `agent-efficiency/` | Campaign-generation and execution artifacts, gates, and handoffs | Preserve manifests, receipts, logs, response evidence, records, and terminal status. |
| `*T*Z-bk-*/` | Dated backend performance campaigns | Preserve campaign plans, selection data, Hyperfine JSON, phase timings, summaries, profiles, and logs. |
| `semantic-pipeline-*/` | Semantic pipeline campaign inputs, measurements, corrections, recovery attempts, and reruns | Keep separate by run identity; do not collapse corrected or recovery runs into one directory. |
| `retrieval-quality/` | Retrieval-quality benchmark datasets and run evidence | Preserve source manifests and measured results; inspect privacy and provenance before sharing. |
| `validation/`, `*-gate-*.log`, `*-gate-*.exit` | Repository validation output and terminal statuses | Keep recent and failed gate evidence; the log and exit file form one record. |
| `analysis/`, `callgraphs/` | Derived investigations and generated graphs | Retain while referenced by a report or active work; otherwise review as a group before cleanup. |
| `worktrees/` | Temporary worktree storage | Check Git worktree registrations and active processes before considering cleanup. |

Names are intentionally listed as patterns because each run directory is an
immutable identity. Use the dated retention review before proposing removal.

## Rules

- Keep raw result JSON, manifests, exact provider-response evidence, terminal
  records, failure evidence, task records, and source profiles. A short summary
  does not replace these audit records by default.
- Keep logs with their exit-status file. The logs are small relative to the
  dataset and may contain the cause of a failed or unusual run.
- The reviewed per-attempt `uv-cache` directories were removed after explicit
  approval and confirmation that their prepared image caches remain available.
  Keep the image caches and all other attempt evidence; review any different
  cache group separately before proposing cleanup.
- Keep this directory ignored. Only this manifest and approved, sanitized
  summaries may be tracked; do not unignore raw runtime trees.
