# Query-daemon repeated-read measurement — 2026-08-09

This non-gating Slice 9 report measures repeated JSON reads on the Codira
checkout. It is evidence for the optional warm service, not a timing assertion.

## Method

- Commit: `e9347c79d20e893819a31a698ac8c0b385c64909`
- Backend: SQLite; embedding engine: ONNX on CPU
- Workload: `ctx`, `emb`, `plugins`, and `caps` with query `query daemon`
- Samples: three direct and three warm invocations per command
- Warm process: one repository-fixed IPC daemon at generation 27
- Peak process RSS: 292,488 KiB
- `hyperfine` was unavailable; the committed benchmark script used
  `perf_counter` and saved raw JSON outside the repository worktree.

## Results

| Command | Direct mean (ms) | Warm mean (ms) | Improvement |
| --- | ---: | ---: | ---: |
| `ctx` | 883.373 | 709.320 | 1.25x |
| `emb` | 194.581 | 22.407 | 8.68x |
| `plugins` | 359.586 | 2.577 | 139.54x |
| `caps` | 1007.862 | 31.694 | 31.80x |

The warm-session shutdown path resets embedding runtime caches. No unbounded
growth was observed within this three-run campaign; that is not a long-duration
leak proof.

## Decision and reproduction

The repeated-read benefit is material for embedding search, plugin diagnostics,
and capabilities, and positive for context retrieval. Enable the service for
repeated SQLite reads when the documented local-process memory footprint is
acceptable; direct execution remains deterministic and is retried after IPC
failure. DuckDB replacement/reopen behavior is covered by parameterized
warm-runtime tests, but operators should repeat this campaign under their
DuckDB configuration before generalizing these SQLite timings.

```bash
uv run codira index
uv run python scripts/benchmark_query_daemon.py --runs 10
```

The script refuses to overlap an existing endpoint and writes a timestamped
artifact to `.artifacts/benchmarks/` unless `--output` is supplied.
