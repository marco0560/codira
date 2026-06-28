# Embedding Performance Execution

## Purpose

This branch-local ledger records the executed steps for the batched embedding
performance workstream.

## Branch

The implementation branch for this work is:

```text
feat/batch-embedding-indexing
```

## Planned Phases

1. Branch bootstrap and execution ledger
2. ADR for batched embeddings and tunable runtime controls
3. Batched embedding backend implementation
4. Same-run payload deduplication in index persistence
5. Benchmark script and operator documentation
6. Validation, tuning review, and commit preparation

## Executed Steps

* [x] Created the dedicated implementation branch.
* [x] Added the branch-local execution ledger.
* [x] Added ADR-008 covering batching, same-run payload reuse, and explicit
  runtime controls.
* [x] Added a batched embedding API and environment-driven runtime settings.
* [x] Updated index persistence to batch recomputed embeddings and reuse
  identical payload vectors within one flush.
* [x] Added regression tests for batching and same-run payload reuse.
* [x] Added a benchmark script for phase timings and embedding batch metrics.
* [x] Ran the full validation surface:
  `ruff check src scripts tests`,
  `ruff format --check src scripts tests`,
  `mypy src scripts tests`,
  `pytest -q`.
* [x] Captured one instrumented full-index benchmark on this repository. The
  first sample showed `embed_texts` and `flush_embedding_rows` dominating wall
  time, which confirmed the optimization target.
* [x] Ran controlled embedding microbenchmarks after the first pass. On this
  host, constrained Torch threads and larger batches sometimes helped on the
  synthetic benchmark.
* [x] Kept runtime tuning operator-controlled after follow-up end-to-end
  measurements proved too noisy to justify hardcoded thread defaults in this
  branch.
* [x] Recovered the historical large-repository baseline for
  `Personalia/Progetti/Software/texlive-2026-source` under `codira 1.4.0`.
  The timed `codira index --full` run started at `21:30:18` on 02/04/2026
  and ended at `05:31:21` on 03/04/2026, for a total wall time of
  `8h01m03s`, with:
  `Indexed: 7933`,
  `Reused: 0`,
  `Deleted: 0`,
  `Failed: 0`,
  `Embeddings recomputed: 43732`,
  `Embeddings reused: 0`,
  `Coverage issues: 0`.
* [x] Captured a large-repository full-index benchmark on
  `Personalia/Progetti/Software/texlive-2026-source` after the 1.7.x
  performance and audit-policy updates. On 03/04/2026 the command
  `codira index --full` ran from `17:27:36` to `17:40:21`, for a total wall
  time of `12m45s`, with:
  `Indexed: 7933`,
  `Reused: 0`,
  `Deleted: 0`,
  `Failed: 0`,
  `Embeddings recomputed: 43732`,
  `Embeddings reused: 0`,
  `Coverage issues: 0`.
* [x] Recorded an apples-to-apples before/after comparison for the same large
  repository and the same full-index workload:
  `8h01m03s` on `codira 1.4.0` versus `12m45s` on the current 1.7.x line,
  which is roughly a `37.7x` speedup by wall clock.
* [x] Captured a local runtime-tuning baseline on 20/04/2026 for the
  `codira` repository on `verona` with 12 CPU cores and 48 GB RAM. With all
  Codira tuning variables unset, the effective baseline was:
  `CODIRA_EMBED_BATCH_SIZE=32`,
  `CODIRA_EMBED_DEVICE=cpu`,
  `CODIRA_TORCH_NUM_THREADS` unset,
  `CODIRA_TORCH_NUM_INTEROP_THREADS` unset,
  `torch.get_num_threads()=6`, and
  `torch.get_num_interop_threads()=6`.
* [x] Ran release Hyperfine benchmarks on the same host and repository with
  three tuning profiles:

  | Profile | `codira index --full` | `codira ctx --json` | `codira audit --json` |
  | --- | ---: | ---: | ---: |
  | `threads=6`, `interop=1`, `batch=32` | `31.158s +/- 0.354s` | `6.923s +/- 0.172s` | `200.6ms +/- 3.1ms` |
  | `threads=8`, `interop=1`, `batch=64` | `32.499s +/- 0.291s` | `6.924s +/- 0.166s` | `198.9ms +/- 0.8ms` |
  | `threads=10`, `interop=1`, `batch=128` | `29.451s +/- 0.152s` | `6.666s +/- 0.099s` | `196.7ms +/- 6.2ms` |

  A direct Hyperfine check with `.codira` removed before each run measured
  `threads=8`, `interop=1`, `batch=64` at `32.123s +/- 0.256s` for
  `codira index --full`, confirming that the release benchmark helper did not
  materially distort the indexing measurement.
* [x] Recorded the 20/04/2026 operator recommendation for this host and
  repository: use `CODIRA_TORCH_NUM_THREADS=10`,
  `CODIRA_TORCH_NUM_INTEROP_THREADS=1`, and `CODIRA_EMBED_BATCH_SIZE=128` for
  fastest measured full indexing at that time. This was a local operational
  baseline, not a universal default.
* [x] Superseded that recommendation on 28/05/2026 after the issue #30
  post-step4 campaign: a short controlled SQLite full-index matrix on `codira`
  measured the default PyTorch runtime with `CODIRA_EMBED_BATCH_SIZE=32` as the
  fastest tested profile. Keep `CODIRA_TORCH_*` unset for general campaign
  commands unless a fresh host-local Hyperfine matrix proves otherwise.
* [x] Added a read-only engine compatibility helper for the post-plugin
  benchmark workstream:
  `scripts/compare_embedding_engines.py`. Use it to compare fixed-corpus
  vectors for paired manifest entries before considering any mixed
  Torch-index/ONNX-query configuration. The helper records pass/fail gates for
  model identity, dimensions, and cosine similarity; it does not enable mixed
  production mode.
* [x] Added command-scoped effective-config and active-plugin instance caches
  around CLI, indexing, context retrieval, and embedding candidate hot paths.
  The cache avoids repeated TOML parsing and repeated backend/vector/embedding
  plugin instantiation during one command while resetting at command exit.
* [x] Added a DuckDB vector-store vector-set identity cache now that plugin
  instances are command-scoped. This removes repeated vector-set
  initialization and lookup work across cache/materialized/pending vector-store
  writes during one command.
* [x] Create the final branch commit.
