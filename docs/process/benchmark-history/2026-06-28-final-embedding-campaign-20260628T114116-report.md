# Final Embedding Campaign Report: 20260628T114116

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-28-final-embedding-campaign-20260628T114116-report.md`
(SHA-256 `451f533a704855d715f7bda434e9a5df104a0efe2ade4c9513a09b1a296e5d69`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/final-embedding-model-campaign/20260627T201446` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260628T114116` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/embedding/uv-backed-repos.local.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.
- `benchmarks/uv-backed-repos.local.json` → `benchmarks/embedding/uv-backed-repos.local.json`.


Date: 2026-06-28

Compared campaigns:

- New: `.artifacts/final-embedding-model-campaign/20260628T114116`
- Previous: `.artifacts/final-embedding-model-campaign/20260627T201446`

## Executive Summary

The new campaign completed the same benchmark matrix as the previous campaign: 6 model configurations, 2 storage backends, 4 repositories, 5 hyperfine runs, 1 warmup, and 48 successful checkpoints. All failure summaries report zero failures.

The most important result is that the post-fix code is materially faster than the preceding campaign on the same command surface. On the three stable target repositories (`fontshow`, `chatops`, `sanikey`), average deltas are:

| Metric | Previous | New | New / previous | Change |
| --- | ---: | ---: | ---: | --- |
| Full index hyperfine | 4.452s | 3.223s | 0.724x | 27.6% faster |
| Warm index | 0.688s | 0.402s | 0.584x | 41.6% faster |
| `ctx` | 6.089s | 3.560s | 0.585x | 41.5% faster |
| `emb` | 3.630s | 3.233s | 0.891x | 10.9% faster |
| Instrumented total | 117.194s | 113.595s | 0.969x | 3.1% faster |
| Instrumented embeddings | 113.299s | 109.851s | 0.970x | 3.0% faster |
| Instrumented indexing | 1.445s | 0.573s | 0.397x | 60.3% faster |

Interpretation: the fixes mostly removed Python/plugin/config/backend overhead. They did not substantially change model inference cost: instrumented embedding time moved only about 3%.

The best current default remains `bge-small-en-v1.5-onnx + sqlite`: it is the best interactive `ctx`/`emb` choice, has modest memory, and avoids the 768-dimensional indexing cost. `current-minilm-sentence-transformers + sqlite` remains the cheapest full-index baseline, but its interactive query latency is much worse.

DuckDB improved in absolute time, but it is still not competitive with SQLite for this workload. On the stable repos, DuckDB is now about 1.99x slower than SQLite for full-index hyperfine, 1.17x slower for warm index, 1.11x slower for `ctx`, and 1.15x slower for `emb`.

## Parity Checks

| Field | Previous | New |
| --- | --- | --- |
| Repository manifest | `benchmarks/embedding/uv-backed-repos.local.json` | `benchmarks/embedding/uv-backed-repos.local.json` |
| Model manifest | `benchmarks/embedding/model-candidates.json` | `benchmarks/embedding/model-candidates.json` |
| Backend mode | `both` | `both` |
| Backends | `sqlite`, `duckdb` | `sqlite`, `duckdb` |
| Runs / warmup | 5 / 1 | 5 / 1 |
| Codira version in phase metadata | `1.44.6.post1.dev40` | `1.44.6.post1.dev45` |
| Completed checkpoints | 48 | 48 |
| Failure summaries | 0 failures | 0 failures |

Repository commit parity:

| Repo | Previous indexed commit | New indexed commit |
| --- | --- | --- |
| `codira` | `f40e324ee0aeb316b6e63409455d78e4b3e4726d` | `06c3bf151dc53eb83f23af943de8c6145963825d,20dcd1405085c6ce79d41597034bd2b8c5214fef` |
| `fontshow` | `b034de78880c2eb1a447a53cfcededb9559affe5` | `b034de78880c2eb1a447a53cfcededb9559affe5` |
| `chatops` | `0ce32108e109711531c65c8585bd86b0bf05f888` | `0ce32108e109711531c65c8585bd86b0bf05f888` |
| `sanikey` | `b57b75ae0bfbcab3c6eeb737ca288e2c738e8934` | `b57b75ae0bfbcab3c6eeb737ca288e2c738e8934` |

Caveat: the Codira repository itself changed while the new campaign was running; its rows span commits `06c3bf1` and `20dcd14`. The cleanest before/after evidence is therefore the `fontshow`, `chatops`, and `sanikey` subset, whose indexed commits are unchanged.

## Backend Comparison

Average across all six models on the stable repositories:

| Campaign | Backend | Full index | Warm index | `ctx` | `emb` | Phase indexing |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Previous | sqlite | 3.265s | 0.657s | 5.919s | 3.420s | 1.155s |
| Previous | duckdb | 5.639s | 0.719s | 6.260s | 3.840s | 1.735s |
| New | sqlite | 2.159s | 0.370s | 3.370s | 3.005s | 0.284s |
| New | duckdb | 4.287s | 0.434s | 3.750s | 3.460s | 0.863s |

DuckDB / SQLite ratios on stable repositories:

| Campaign | Full index | Warm index | `ctx` | `emb` | Phase indexing |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous | 1.727x | 1.095x | 1.058x | 1.123x | 1.502x |
| New | 1.986x | 1.174x | 1.113x | 1.151x | 3.038x |

Interpretation: DuckDB absolute performance improved, but SQLite improved more for full indexes. DuckDB still has room for write-path optimization before it can be treated as a near-1.1x alternative for full-index workloads.

## Model And Engine Results

New campaign averages across both backends on the stable repositories:

| Model | Full index | `ctx` | `emb` | Max index RSS | Max `ctx` RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bge-small-en-v1.5-sentence-transformers` | 2.910s | 4.851s | 4.487s | 569 MiB | 1042 MiB |
| `current-minilm-sentence-transformers` | 3.027s | 4.688s | 4.454s | 581 MiB | 995 MiB |
| `bge-small-en-v1.5-onnx` | 3.033s | 1.196s | 0.929s | 554 MiB | 554 MiB |
| `nomic-embed-text-v1.5-sentence-transformers` | 3.442s | 6.366s | 5.991s | 816 MiB | 1944 MiB |
| `nomic-embed-text-v1.5-onnx` | 3.453s | 1.988s | 1.696s | 816 MiB | 1037 MiB |
| `jina-embeddings-v2-base-code-onnx` | 3.472s | 2.272s | 1.838s | 820 MiB | 994 MiB |

Same-family Torch vs ONNX in the new campaign on stable repositories:

| Family | Backend | Full index ONNX/Torch | `ctx` ONNX/Torch | `emb` ONNX/Torch |
| --- | --- | ---: | ---: | ---: |
| BGE | sqlite | 1.070x | 0.221x | 0.176x |
| BGE | duckdb | 1.028x | 0.271x | 0.236x |
| Nomic | sqlite | 0.927x | 0.290x | 0.252x |
| Nomic | duckdb | 1.043x | 0.333x | 0.311x |

Interpretation: ONNX is the clear interactive winner. BGE ONNX is roughly similar to BGE Torch for full-index hyperfine and dramatically faster for `ctx`/`emb`. Nomic ONNX beats Nomic Torch on the measured dimensions, but the Nomic family is still too expensive and memory-heavy to beat BGE ONNX as a default.

## Before/After By Model

New / previous ratios on stable repositories; lower is better:

### Full index

| Model | New / previous |
| --- | ---: |
| `bge-small-en-v1.5-onnx` | 0.669x |
| `bge-small-en-v1.5-sentence-transformers` | 0.704x |
| `current-minilm-sentence-transformers` | 0.723x |
| `jina-embeddings-v2-base-code-onnx` | 0.717x |
| `nomic-embed-text-v1.5-onnx` | 0.780x |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.750x |

### `ctx`

| Model | New / previous |
| --- | ---: |
| `bge-small-en-v1.5-onnx` | 0.321x |
| `bge-small-en-v1.5-sentence-transformers` | 0.640x |
| `current-minilm-sentence-transformers` | 0.632x |
| `jina-embeddings-v2-base-code-onnx` | 0.530x |
| `nomic-embed-text-v1.5-onnx` | 0.439x |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.708x |

### `emb`

| Model | New / previous |
| --- | ---: |
| `bge-small-en-v1.5-onnx` | 0.782x |
| `bge-small-en-v1.5-sentence-transformers` | 0.874x |
| `current-minilm-sentence-transformers` | 0.904x |
| `jina-embeddings-v2-base-code-onnx` | 0.871x |
| `nomic-embed-text-v1.5-onnx` | 0.869x |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.926x |

## Profile Evidence

The phase timing files explain why the hyperfine improvements are larger than the embedding improvements:

- Instrumented embedding time on stable repos moved from 113.299s to 109.851s on average, only 3.0% faster.
- Instrumented indexing time moved from 1.445s to 0.574s on average, 60.3% faster.
- Warm/query command latencies improved strongly, which is consistent with cached configuration/plugin discovery and less per-command startup overhead.
- Full-index hyperfine improved more than phase total because hyperfine includes process/runtime overhead that the phase `timings.total` file does not isolate in the same way.

## Decisions

- Keep `bge-small-en-v1.5-onnx + sqlite` as the best measured production default for this machine.
- Do not switch default storage to DuckDB yet. The absolute DuckDB regression is controlled, but the backend is still about 2x SQLite for full-index hyperfine on the stable repo subset.
- Keep the split-engine experiment separate from this campaign. This campaign used one configured embedding engine per model cell; it does not exercise Torch for indexing plus ONNX for interactive `ctx`/`emb`.
- Use the new split-engine and ONNX sweep scripts for the next question: whether a Torch-index / ONNX-query split improves lifecycle cost without semantic drift.

## Validation

- Parsed 48 hyperfine files and 48 index phase files for each compared campaign.
- Confirmed both campaigns have identical manifest path, model manifest path, backend mode, concrete backend set, run count, and warmup count.
- Confirmed all 96 compared failure summaries report zero failures.
- Used stable-repository subset for before/after conclusions because the Codira target repository changed during the new campaign.
