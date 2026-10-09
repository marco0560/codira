# Issue #59 automatic known-target benchmark implementation

Date: 2026-10-08. Branch:
`feat/issue-059-embedding-retrieval-quality-benchmark`.

The operator approved automatic source-derived grading in place of the issue's
original manual pooling workflow. This implementation measures retrieval of
known targets, not exhaustive semantic relevance or successful agent tasks.
See the [benchmark guide](../benchmarks/known-target-quality.md).

## Delivered plan

1. **Automatic cases:** pinned Git blobs supply definition names, module and
   definition docstrings, Markdown headings outside correctly matched code
   fences, and literal error messages. The versioned public bank contains 75
   cases across three repositories. The ignored full local bank contains 100
   cases across four repositories, with five cases for every repository/intent
   cell. All source witnesses were regenerated and verified; private cases
   remain untracked.
2. **Resumable execution:** the existing benchmark entry point accepts
   `--known-target`. Sources are archived and indexed through isolated Git
   indexes. Model groups use SQLite, exact similarity search, fixed text
   limits, separate state and disabled daemons. The campaign identity binds
   dataset, model controls, local model assets, runtime and harness digests.
   Numbered raw attempts, successful checkpoints, response validation,
   timeouts and exclusive campaign locks protect interruption/resume.
3. **Automatic scoring and reports:** known-target Hit@1, Recall@5, MRR@5/10,
   requested additional cutoffs, repository/intent breakdowns and macro/micro
   averages are emitted in Markdown and JSON. Every planned slot remains in
   metric denominators. Primary retrieval and separate `ctx` timing probes,
   indexing wall time and sampled process-tree RSS support cost comparisons.
   Reports retain incomplete-label and sampled-memory limitations and never
   change installed defaults.

## Validation and retained evidence

- Focused benchmark tests: **38 passed**. Coverage includes source provenance,
  balanced generation, invalid/duplicate controls, literal error ownership,
  fence parsing, exact locations, duplicate rank handling, macro/micro weighting,
  missing slots, matched two-model controls, raw-output tampering, retry/resume,
  timeouts, concurrent writers and current configuration schema/text limits.
- The workflow preflight passed lint, formatting, core/package typing, custom
  Semgrep and fresh-index docstring auditing.
- The full repository gate passed with exit **0**: **1,431 passed, 3 skipped**,
  **86% coverage**. It ran in `issue059-repo-gate-20261008-0939` with separate
  log/exit records; those temporary gate records were examined before cleanup.
- Strict MkDocs build passed. Documentation explains prerequisites, exact
  commands, recovery, private-data handling and interpretation limits.
- The full local bank is retained under
  `.artifacts/benchmarks/retrieval-quality/datasets/known-target-20261008-v1/`.
  Its ignored locator manifest and source receipts remain with its cases.
- Real runtime qualification is retained under
  `.artifacts/benchmarks/retrieval-quality/runs/known-target-smoke-20261008-v5/`:
  two installed ONNX models, one tiny pinned source fixture, five cases per
  model, two indexing operations, ten primary retrievals and ten `ctx` probes.
  All commands completed with zero primary/`ctx` failures. All known targets
  were retrieved at rank one on this deliberately small fixture.
- `replay-receipt.json` confirms resume and rescore exit **0**, identical
  summaries, and **22 unchanged measurements with no new attempts**.

Earlier smoke identities remain intact. They exposed the historical renderer's
obsolete configuration schema and dimension-dependent text limits, empty
archive discovery through the surrounding Git checkout, and the current
`ctx` contract envelope. These were harness integration defects, corrected and
covered by regression tests; their unsuccessful records are not counted as
qualified runs.

The tiny runtime smoke qualifies the runner path, persistence and automatic
scoring. It does **not** establish a model ranking on the 100-case bank. No full
multi-repository comparison, manual review or paid provider campaign was run.
Future comparisons use the documented controls and new immutable identities.
