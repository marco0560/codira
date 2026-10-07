# Final embedding campaign report: 20260626T023243

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-27-final-embedding-campaign-20260626T023243-report.md`
(SHA-256 `3eabb4e4aa6b2a542ee6757057752fa8961a8773a1289a46794d8cdb3e347635`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-hyperfine.json` | available pattern |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-index-phases.json` | available pattern |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/campaign-plan.json` | available |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/failure-summary.json` | available |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/*-hyperfine.json` | available pattern |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/*-index-phases.json` | available pattern |
| `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/campaign-plan.json` | available |
| `.artifacts/final-embedding-model-campaign/20260626T023243` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/...current-minilm` | illustrative path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/README.md` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-hyperfine.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-index-phases.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/failure-summary.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/checkpoints/index.tsv` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/checkpoints/labels.txt` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/configs/*.toml` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/logs/*.log` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/metadata/environment.txt` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/embedding/uv-backed-repos.local.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.
- `.artifacts/20260618T095148Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb`.
- `.artifacts/20260618T095148Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite`.
- `benchmarks/uv-backed-repos.local.json` → `benchmarks/embedding/uv-backed-repos.local.json`.


Date: 2026-06-27

Campaign root:

```text
.artifacts/final-embedding-model-campaign/20260626T023243
```

This report replaces the earlier incorrect analysis that used the incomplete
retry campaign `20260627T201446`.

## Executive Summary

Campaign `20260626T023243` is the completed DuckDB embedding-model campaign.
It ran all 6 configured embedding models across all 4 repositories, producing
24 successful checkpoints and 0 failure-summary entries.

Top-level result:

- Best average full-index Hyperfine time: `bge-small-en-v1.5-onnx`, 263.277s.
- Best average instrumented full-index phase wall time: `current-minilm-sentence-transformers`, 584.137s.
- Best average `ctx`: `bge-small-en-v1.5-onnx`, 3.701s.
- Best average `emb`: `bge-small-en-v1.5-onnx`, 1.468s.
- ONNX is clearly faster than SentenceTransformers for query-time `ctx` and
  `emb` in the paired BGE and Nomic comparisons.
- Full-index time does not show the same clean ONNX advantage; for BGE the ONNX
  phase timings are slower than SentenceTransformers despite similar Hyperfine
  full-index means, while for Nomic ONNX is slightly better than
  SentenceTransformers in instrumented full-index phase time.

For real interactive use, `bge-small-en-v1.5-onnx` is the strongest result in
this campaign because it combines the fastest `ctx`, fastest `emb`, and best
average full-index Hyperfine time. For repeated full indexing only,
`current-minilm-sentence-transformers` remains attractive because its
instrumented full-index phase wall time and embedding diagnostic time are the
lowest.

## Campaign Identity

Launch surface recorded by the campaign:

```text
Repository manifest: benchmarks/embedding/uv-backed-repos.local.json
Model manifest: benchmarks/embedding/model-candidates.json
Backend mode: duckdb
Runs: 5
Warmup: 1
```

Environment:

```text
BACKEND_MODE=duckdb
RUNS=5
WARMUP=1
STAMP=20260626T023243
PYTHON=.venv/bin/python
CODIRA=.venv/bin/codira
```

Artifact parity:

```text
checkpoints/labels.txt: 24 rows
checkpoints/index.tsv: 24 data rows plus header
failure-summary.json files: 24
failure_count: 0 for every campaign subrun
backend: duckdb for every checkpoint
git_commit: 50ce7784cb636c540aa7af1a2e515d865eb56a0c for every subrun
codira_version: 1.44.6.post1.dev37 for every subrun
```

Relevant plugin versions captured in the artifacts:

```text
codira-backend-duckdb: 1.49.1
codira-backend-sqlite: 1.45.0
codira-embedding-onnx: 1.0.1
codira-embedding-sentence-transformers: 1.0.1
codira-vector-store-duckdb: 1.0.1
codira-vector-store-sqlite: 1.0.1
```

## Frozen Model Configs

All models used DuckDB for both structural backend and vector store.

| Model id | Engine | Dimension | Batch size | max_text_chars | ONNX max_tokens | ONNX threads |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| current-minilm-sentence-transformers | sentence-transformers | 384 | 32 | 0 | 512 | 0/0 |
| bge-small-en-v1.5-sentence-transformers | sentence-transformers | 384 | 32 | 0 | 512 | 0/0 |
| bge-small-en-v1.5-onnx | onnx | 384 | 8 | 0 | 512 | 0/0 |
| nomic-embed-text-v1.5-sentence-transformers | sentence-transformers | 768 | 1 | 2000 | 512 | 4/1 |
| nomic-embed-text-v1.5-onnx | onnx | 768 | 1 | 2000 | 512 | 4/1 |
| jina-embeddings-v2-base-code-onnx | onnx | 768 | 1 | 2000 | 512 | 4/1 |

The 768-dimensional models used the conservative memory-safe campaign settings:
`batch_size = 1`, `max_text_chars = 2000`, and ONNX `intra_op_num_threads = 4`,
`inter_op_num_threads = 1`.

## Average Results by Model

Hyperfine means and instrumented phase timings, averaged over the 4 repositories.
Seconds unless otherwise noted.

| Model | Full index | Warm index | ctx | emb | Phase total | Phase embeddings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bge-small-en-v1.5-onnx | 263.277 | 0.710 | 3.701 | 1.468 | 677.275 | 114.792 |
| current-minilm-sentence-transformers | 263.551 | 0.697 | 8.811 | 5.116 | 584.137 | 35.700 |
| bge-small-en-v1.5-sentence-transformers | 264.887 | 0.696 | 7.313 | 5.150 | 635.170 | 79.676 |
| nomic-embed-text-v1.5-sentence-transformers | 470.014 | 0.722 | 9.072 | 6.863 | 1311.704 | 284.108 |
| nomic-embed-text-v1.5-onnx | 470.427 | 0.729 | 4.687 | 2.347 | 1263.179 | 270.234 |
| jina-embeddings-v2-base-code-onnx | 474.944 | 0.729 | 4.504 | 2.489 | 1251.365 | 247.670 |

Interpretation:

- Warm structural indexing is effectively flat across models, around
  0.70-0.73s, because it is mostly not embedding-bound.
- 384-dimensional models are far cheaper to fully index than 768-dimensional
  models.
- ONNX materially improves query-time embedding commands (`ctx`, `emb`).
- MiniLM has the lowest instrumented embedding diagnostic time, but its `ctx`
  and `emb` latency are much worse than ONNX.

## Per-Repository Top-Line Results

Hyperfine means by model and repository. Seconds.

### codira

| Model | Full index | Warm index | ctx | emb |
| --- | ---: | ---: | ---: | ---: |
| current-minilm-sentence-transformers | 423.276 | 0.706 | 13.043 | 5.459 |
| bge-small-en-v1.5-sentence-transformers | 423.009 | 0.707 | 6.965 | 5.477 |
| bge-small-en-v1.5-onnx | 422.188 | 0.722 | 3.366 | 1.802 |
| nomic-embed-text-v1.5-sentence-transformers | 752.492 | 0.715 | 8.631 | 7.129 |
| nomic-embed-text-v1.5-onnx | 757.945 | 0.743 | 4.335 | 2.682 |
| jina-embeddings-v2-base-code-onnx | 762.135 | 0.740 | 4.470 | 2.812 |

### fontshow

| Model | Full index | Warm index | ctx | emb |
| --- | ---: | ---: | ---: | ---: |
| current-minilm-sentence-transformers | 392.003 | 0.736 | 8.283 | 5.183 |
| bge-small-en-v1.5-sentence-transformers | 395.828 | 0.734 | 8.310 | 5.213 |
| bge-small-en-v1.5-onnx | 392.702 | 0.739 | 4.717 | 1.522 |
| nomic-embed-text-v1.5-sentence-transformers | 697.064 | 0.795 | 10.246 | 7.117 |
| nomic-embed-text-v1.5-onnx | 693.920 | 0.759 | 5.776 | 2.414 |
| jina-embeddings-v2-base-code-onnx | 709.729 | 0.770 | 6.065 | 2.558 |

### chatops

| Model | Full index | Warm index | ctx | emb |
| --- | ---: | ---: | ---: | ---: |
| current-minilm-sentence-transformers | 121.729 | 0.678 | 6.781 | 4.949 |
| bge-small-en-v1.5-sentence-transformers | 121.241 | 0.678 | 6.789 | 5.009 |
| bge-small-en-v1.5-onnx | 121.214 | 0.688 | 3.149 | 1.318 |
| nomic-embed-text-v1.5-sentence-transformers | 218.292 | 0.694 | 8.563 | 6.668 |
| nomic-embed-text-v1.5-onnx | 219.525 | 0.713 | 4.141 | 2.193 |
| jina-embeddings-v2-base-code-onnx | 217.455 | 0.704 | 3.901 | 2.336 |

### sanikey

| Model | Full index | Warm index | ctx | emb |
| --- | ---: | ---: | ---: | ---: |
| current-minilm-sentence-transformers | 117.197 | 0.669 | 7.138 | 4.872 |
| bge-small-en-v1.5-sentence-transformers | 119.471 | 0.666 | 7.188 | 4.900 |
| bge-small-en-v1.5-onnx | 117.006 | 0.693 | 3.572 | 1.229 |
| nomic-embed-text-v1.5-sentence-transformers | 212.208 | 0.683 | 8.849 | 6.540 |
| nomic-embed-text-v1.5-onnx | 210.317 | 0.702 | 4.495 | 2.100 |
| jina-embeddings-v2-base-code-onnx | 210.456 | 0.702 | 3.581 | 2.250 |

## ONNX versus SentenceTransformers

### BGE small, 384-dimensional

| Metric | SentenceTransformers | ONNX | ONNX / ST |
| --- | ---: | ---: | ---: |
| Full index | 264.887 | 263.277 | 0.994 |
| ctx | 7.313 | 3.701 | 0.506 |
| emb | 5.150 | 1.468 | 0.285 |
| Phase total | 635.170 | 677.275 | 1.066 |
| Phase embeddings | 79.676 | 114.792 | 1.441 |

BGE ONNX is effectively tied for full-index Hyperfine mean, much faster for
interactive query-time embedding commands, but worse in the instrumented
embedding diagnostic phase. That split suggests ONNX startup/runtime behavior
helps query commands, while full-index instrumentation and batching still need
careful interpretation.

### Nomic 768-dimensional

| Metric | SentenceTransformers | ONNX | ONNX / ST |
| --- | ---: | ---: | ---: |
| Full index | 470.014 | 470.427 | 1.001 |
| ctx | 9.072 | 4.687 | 0.517 |
| emb | 6.863 | 2.347 | 0.342 |
| Phase total | 1311.704 | 1263.179 | 0.963 |
| Phase embeddings | 284.108 | 270.234 | 0.951 |

For Nomic, ONNX preserves full-index performance, slightly improves
instrumented full-index phase timings, and roughly halves `ctx` while cutting
`emb` latency by about two thirds.

## Runtime Cost Shape

Average full-index Hyperfine time separates mainly by dimensionality:

| Family | Average full-index range |
| --- | ---: |
| 384-dimensional MiniLM/BGE | 263-265s |
| 768-dimensional Nomic/Jina | 470-475s |

Average query-time embedding separates mainly by engine:

| Engine/model class | Average emb range |
| --- | ---: |
| 384-dimensional ONNX BGE | 1.468s |
| 768-dimensional ONNX Nomic/Jina | 2.347-2.489s |
| 384-dimensional SentenceTransformers | 5.116-5.150s |
| 768-dimensional SentenceTransformers Nomic | 6.863s |

Average `ctx` shows the same pattern:

| Model | Average ctx |
| --- | ---: |
| bge-small-en-v1.5-onnx | 3.701s |
| jina-embeddings-v2-base-code-onnx | 4.504s |
| nomic-embed-text-v1.5-onnx | 4.687s |
| bge-small-en-v1.5-sentence-transformers | 7.313s |
| current-minilm-sentence-transformers | 8.811s |
| nomic-embed-text-v1.5-sentence-transformers | 9.072s |

## Operational Elapsed Time

The outer phase logs confirm the campaign was long but stable. Representative
totals:

| Model | codira | fontshow | chatops | sanikey |
| --- | ---: | ---: | ---: | ---: |
| current-minilm-sentence-transformers | 1h 52m 14s | 1h 38m 53s | 32m 22s | 31m 26s |
| bge-small-en-v1.5-sentence-transformers | 1h 49m 50s | 1h 41m 41s | 32m 45s | 32m 01s |
| bge-small-en-v1.5-onnx | 1h 50m 04s | 1h 42m 44s | 31m 46s | 30m 43s |
| nomic-embed-text-v1.5-sentence-transformers | 3h 29m 06s | 3h 10m 03s | 1h 00m 22s | 59m 11s |
| nomic-embed-text-v1.5-onnx | 3h 26m 15s | 3h 05m 34s | 57m 59s | 56m 20s |
| jina-embeddings-v2-base-code-onnx | 3h 26m 11s | 3h 05m 17s | 57m 21s | 56m 07s |

This agrees with the measured cost shape: 768-dimensional models roughly double
the campaign cost versus the 384-dimensional group.

## Profile Evidence and Caveats

Profile summaries exist for every subrun. The same broad pattern appears across
the campaign:

- Full-index cost is dominated by embedding generation and vector persistence.
- Query-time `ctx` includes both embedding lookup work and recurring config /
  plugin/backend resolution costs.
- The campaign is DuckDB-only, so no SQLite-vs-DuckDB conclusion can be drawn
  from this artifact alone.
- The campaign predates the later vector-store DuckDB `executemany` fix and the
  later `--backend both` phase-visibility/config-generation fix. Do not use this
  run to validate those newer changes.

The phase-timing JSON exposes `timings.total` and `timings.embeddings`.
`timings.total` is wall-clock for the instrumented index pass.
`timings.embeddings` is a diagnostic hook total. These values must not be added
together.

## Comparison with Preceding Comparable Campaigns

The directly comparable non-final campaign fragment is:

```text
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb
```

Manifest check:

- `20260618T095148Z-bk-cpp-duckdb` contains exactly the four repositories used
  by the final embedding campaign: `codira`, `fontshow`, `chatops`, `sanikey`.
- Earlier broad `bk-cpp` campaigns contain only partial overlap with the final
  campaign, usually `codira` and `fontshow`, and were skipped for this
  comparison.
- The sibling `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite` campaign has the
  same four repositories and is useful as context, but the direct comparison
  below uses DuckDB-to-DuckDB.

Parity and drift:

| Field | 20260618 predecessor | 20260626 final MiniLM slice |
| --- | --- | --- |
| Artifact | `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb` | `.artifacts/final-embedding-model-campaign/20260626T023243/...current-minilm...` |
| Backend | DuckDB | DuckDB |
| Repositories | codira, fontshow, chatops, sanikey | codira, fontshow, chatops, sanikey |
| Codira commit | `7df2d1925f46754fe6c64cd9421f220c0c1d96fb` | `50ce7784cb636c540aa7af1a2e515d865eb56a0c` |
| Codira version | `1.44.4.post1.dev1` | `1.44.6.post1.dev37` |
| DuckDB backend package | `1.48.0` | `1.49.1` |
| Embedding plugins | not separated plugin packages | `codira-embedding-* 1.0.1` |
| Vector store plugins | absent | `codira-vector-store-duckdb 1.0.1` |
| Batch size metadata | 128 | 32 |

Only the final MiniLM slice is used here because it is the closest model match
to the predecessor run. The final campaign additionally measures BGE, Nomic,
and Jina variants, but those have no direct predecessor-model counterpart.

### MiniLM DuckDB Regression Table

Mean timings, seconds. Ratios are final / predecessor.

| Repo | Metric | 20260618 DuckDB | 20260626 MiniLM DuckDB | Ratio |
| --- | --- | ---: | ---: | ---: |
| codira | full index | 5.594 | 423.276 | 75.67x |
| codira | warm index | 0.458 | 0.706 | 1.54x |
| codira | ctx | 7.066 | 13.043 | 1.85x |
| codira | emb | 4.323 | 5.459 | 1.26x |
| codira | phase total | 69.524 | 944.494 | 13.59x |
| codira | phase embeddings | 64.793 | 67.954 | 1.05x |
| fontshow | full index | 5.054 | 392.003 | 77.57x |
| fontshow | warm index | 0.479 | 0.736 | 1.54x |
| fontshow | ctx | 5.815 | 8.283 | 1.42x |
| fontshow | emb | 4.321 | 5.183 | 1.20x |
| fontshow | phase total | 53.746 | 871.272 | 16.21x |
| fontshow | phase embeddings | 49.741 | 51.425 | 1.03x |
| chatops | full index | 2.577 | 121.729 | 47.23x |
| chatops | warm index | 0.419 | 0.678 | 1.62x |
| chatops | ctx | 5.201 | 6.781 | 1.30x |
| chatops | emb | 4.283 | 4.949 | 1.16x |
| chatops | phase total | 14.259 | 262.024 | 18.38x |
| chatops | phase embeddings | 11.739 | 11.903 | 1.01x |
| sanikey | full index | 2.079 | 117.197 | 56.36x |
| sanikey | warm index | 0.412 | 0.669 | 1.62x |
| sanikey | ctx | 5.255 | 7.138 | 1.36x |
| sanikey | emb | 4.330 | 4.872 | 1.12x |
| sanikey | phase total | 14.371 | 258.760 | 18.01x |
| sanikey | phase embeddings | 12.191 | 11.518 | 0.94x |

Average across the four common repositories:

| Metric | 20260618 DuckDB | 20260626 MiniLM DuckDB | Ratio |
| --- | ---: | ---: | ---: |
| full index | 3.826 | 263.551 | 68.89x |
| warm index | 0.442 | 0.697 | 1.58x |
| ctx | 5.835 | 8.811 | 1.51x |
| emb | 4.314 | 5.116 | 1.19x |
| phase total | 37.975 | 584.137 | 15.38x |
| phase embeddings | 34.616 | 35.700 | 1.03x |
| embedding rows | 2,608.5 | 2,755.25 | 1.06x |

The important asymmetry is that embedding diagnostic time barely moved:
`phase_embeddings` increased only 3.1% on average. Hyperfine full-index time
increased 68.9x, and instrumented phase wall time increased 15.4x. That means
the regression is not explained by the MiniLM model or by the small increase in
embedded rows.

### Likely Cause of the Regression

The most plausible code-path change between these campaigns is the separated
embedding/vector-store architecture:

- The predecessor metadata has no first-party embedding or vector-store plugin
  packages.
- The final campaign metadata includes `codira-embedding-sentence-transformers`
  and `codira-vector-store-duckdb`.
- The final frozen config writes vectors to `vector_store = "duckdb"`.
- The final campaign predates the later DuckDB vector-store batching fix; it
  used `codira-vector-store-duckdb 1.0.1`.

The numbers match that hypothesis. Embedding computation time is almost flat,
but wall-clock full-index time explodes. In the instrumented final `codira`
MiniLM run, `timings.total` is 944.494s while `timings.embeddings` is only
67.954s. The unaccounted wall-clock cost is consistent with slow vector-store
materialization / persistence outside the embedding hook timing. This is the
same area later fixed by replacing row-wise DuckDB vector-store writes with a
batched Arrow-table path.

The predecessor SQLite sibling is also useful context. On the same four-repo
manifest, `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite` averaged:

| Metric | 20260618 SQLite average |
| --- | ---: |
| full index | 2.331s |
| warm index | 0.362s |
| ctx | 5.499s |
| emb | 4.223s |
| phase total | 36.705s |
| phase embeddings | 34.204s |

That context reinforces that the final campaign's multi-minute full-index times
are not normal for this four-repo workload with MiniLM-like embeddings.

### What the Predecessor Comparison Says About Software Evolution

Costs introduced:

- Full-index rebuilds became dramatically slower in the final campaign's code
  path.
- Warm structural operations also slowed, but much less severely: about 1.6x
  for warm index and 1.2-1.5x for embedding/query commands.
- The new plugin/vector-store architecture adds extra runtime surfaces and
  persistence work that the old campaign did not exercise.

Advantages introduced:

- The final campaign can compare multiple embedding engines and model families
  in a controlled matrix.
- It records explicit frozen model configs, embedding plugin versions, vector
  store plugin versions, and per-model backend configuration.
- ONNX query-time latency is much better than SentenceTransformers once the new
  plugin architecture is available.

Net conclusion:

The architecture evolution enabled the model/engine comparison and exposed a
clear ONNX advantage for interactive queries, but it also introduced a severe
DuckDB vector-store full-index performance regression in the measured
`50ce7784...` code path. The later DuckDB vector-store batching fix is therefore
not cosmetic; it targets the dominant regression surfaced by this predecessor
comparison. A new post-fix campaign is required before choosing final defaults.

## Recommendations

1. Use `bge-small-en-v1.5-onnx` as the leading candidate when interactive
   `ctx`/`emb` latency matters.
2. Keep `current-minilm-sentence-transformers` as the conservative baseline for
   cheapest full-index phase behavior, but do not prefer it for interactive
   embedding query latency.
3. Treat 768-dimensional models as significantly more expensive to index.
   Nomic ONNX is better than Nomic SentenceTransformers for query latency, but
   its full-index cost is still in the expensive 768-dimensional class.
4. Re-run a smaller confirmatory campaign after the DuckDB vector-store write
   fix if the goal is to choose the final production default. This campaign is
   complete and useful, but it predates that performance-sensitive code change.
5. For a backend comparison, use a newer `--backend both` campaign after the
   backend phase split fix; this run is DuckDB-only.

## Source Artifacts

Primary files inspected:

```text
.artifacts/final-embedding-model-campaign/20260626T023243/README.md
.artifacts/final-embedding-model-campaign/20260626T023243/metadata/environment.txt
.artifacts/final-embedding-model-campaign/20260626T023243/checkpoints/index.tsv
.artifacts/final-embedding-model-campaign/20260626T023243/checkpoints/labels.txt
.artifacts/final-embedding-model-campaign/20260626T023243/configs/*.toml
.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-hyperfine.json
.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-index-phases.json
.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/failure-summary.json
.artifacts/final-embedding-model-campaign/20260626T023243/logs/*.log
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/campaign-plan.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-hyperfine.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-index-phases.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/failure-summary.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/campaign-plan.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/*-hyperfine.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-sqlite/*-index-phases.json
```
