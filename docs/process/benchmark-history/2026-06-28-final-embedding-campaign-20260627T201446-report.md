# Final Embedding Campaign Report: 20260627T201446

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-28-final-embedding-campaign-20260627T201446-report.md`
(SHA-256 `45e7e6be884a7840cf3acb9cd11cd9cabc4bd3a8b82be9cc4fe7c6bbb42c412e`).

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
| `.artifacts/final-embedding-model-campaign/20260626T023243` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-hyperfine.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-index-phases.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/README.md` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/*-hyperfine.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/*-index-phases.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/failure-summary.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/profile-summary.json` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446/checkpoints/index.tsv` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/checkpoints/labels.txt` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/configs/*.toml` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260627T201446/metadata/environment.txt` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/metadata/manifest-repositories.tsv` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260627T201446/metadata/model-manifest.json` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/embedding/uv-backed-repos.local.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.
- `.artifacts/20260618T095148Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb`.
- `benchmarks/uv-backed-repos.local.json` → `benchmarks/embedding/uv-backed-repos.local.json`.


Date: 2026-06-28

Campaign:

```text
.artifacts/final-embedding-model-campaign/20260627T201446
```

## Executive Summary

This campaign completed the full matrix:

- 6 embedding model configurations
- 2 backends: SQLite and DuckDB
- 4 repositories: `codira`, `fontshow`, `chatops`, `sanikey`
- 48 successful checkpoints
- 0 recorded benchmark failures

The best overall production default from this run is:

```text
bge-small-en-v1.5-onnx + sqlite
```

Reason:

- Best `ctx` latency: 3.517s average.
- Best `emb` latency: 0.993s average.
- Near-best full-index hyperfine time: 4.104s average.
- Much lower query memory than SentenceTransformers variants.
- Uses a 384-dimensional model, avoiding the much higher index-time cost of
  the 768-dimensional models.

The safest conservative baseline remains:

```text
current-minilm-sentence-transformers + sqlite
```

Reason:

- Best full-index hyperfine time: 3.953s average.
- Best instrumented full-index phase time: 38.707s average.
- Query latency is much worse than ONNX BGE.

DuckDB is now back under control after the vector-store batching fix, but it is
not faster than SQLite in this campaign. SQLite is consistently faster for
full-index and warm/query command overhead.

## Campaign Parity

The campaign metadata records:

| Field | Value |
| --- | --- |
| Repository manifest | `benchmarks/embedding/uv-backed-repos.local.json` |
| Model manifest | `benchmarks/embedding/model-candidates.json` |
| Backend mode | `both` |
| Concrete backends | `sqlite`, `duckdb` |
| Runs | 5 |
| Warmup | 1 |
| Codira version | `1.44.6.post1.dev40` |
| Git commit | `f40e324ee0aeb316b6e63409455d78e4b3e4726d` |
| DuckDB backend package | `codira-backend-duckdb 1.49.1` |
| SQLite backend package | `codira-backend-sqlite 1.45.0` |
| DuckDB vector store package | `codira-vector-store-duckdb 1.0.2` |
| SQLite vector store package | `codira-vector-store-sqlite 1.0.1` |
| Embedding plugins | `codira-embedding-onnx 1.0.1`, `codira-embedding-sentence-transformers 1.0.1` |

The checkpoint table contains all expected rows:

```text
6 models x 2 backends x 4 repos = 48 completed checkpoints
```

All `failure-summary.json` files report:

```text
"failure_count": 0
```

## Model Configurations

| Model id | Engine | Dimension | Batch size | Max text chars | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `current-minilm-sentence-transformers` | SentenceTransformers/Torch | 384 | 32 | 0 | Existing baseline |
| `bge-small-en-v1.5-sentence-transformers` | SentenceTransformers/Torch | 384 | 32 | 0 | BGE Torch path |
| `bge-small-en-v1.5-onnx` | ONNX | 384 | 8 | 0 | CPUExecutionProvider, max 512 tokens |
| `nomic-embed-text-v1.5-sentence-transformers` | SentenceTransformers/Torch | 768 | 1 | 2000 | `trust_remote_code = true` |
| `nomic-embed-text-v1.5-onnx` | ONNX | 768 | 1 | 2000 | CPUExecutionProvider, 4 intra-op threads |
| `jina-embeddings-v2-base-code-onnx` | ONNX | 768 | 1 | 2000 | CPUExecutionProvider, 4 intra-op threads |

The 768-dimensional models used the safer memory configuration that was
introduced after the previous memory-pressure runs: batch size 1 and
`max_text_chars = 2000`.

## Backend Comparison

Average across all models and repositories:

| Backend | Full index | Warm index | `ctx` | `emb` | Phase total | Phase embeddings | Full-index memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite | 4.217s | 0.660s | 6.094s | 3.445s | 178.780s | 175.278s | 96 MiB |
| DuckDB | 6.795s | 0.723s | 6.439s | 3.951s | 180.413s | 174.376s | 551 MiB |
| DuckDB / SQLite | 1.61x | 1.10x | 1.06x | 1.15x | 1.01x | 0.99x | 5.74x |

Interpretation:

- SQLite wins the user-visible command timings in this campaign.
- DuckDB full-index hyperfine time is about 61% slower than SQLite on average.
- DuckDB warm/query overhead is smaller but still consistently slower.
- Instrumented phase totals are almost equal; the larger hyperfine full-index
  gap appears to come from process-level/runtime overhead outside the measured
  embedding hook.
- DuckDB memory during full-index commands is much higher, especially for
  768-dimensional models.

Per-model DuckDB / SQLite ratios:

| Model | Full index | Warm index | `ctx` | `emb` | Phase total | Phase embeddings | Full-index memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `current-minilm-sentence-transformers` | 1.57x | 1.10x | 1.04x | 1.08x | 1.07x | 1.01x | 4.83x |
| `bge-small-en-v1.5-sentence-transformers` | 1.61x | 1.03x | 1.01x | 1.07x | 0.95x | 0.93x | 4.79x |
| `bge-small-en-v1.5-onnx` | 1.65x | 1.13x | 1.07x | 1.52x | 1.01x | 1.00x | 4.82x |
| `nomic-embed-text-v1.5-sentence-transformers` | 1.60x | 1.10x | 1.07x | 1.09x | 1.01x | 1.00x | 6.62x |
| `nomic-embed-text-v1.5-onnx` | 1.59x | 1.11x | 1.10x | 1.35x | 1.01x | 1.00x | 6.63x |
| `jina-embeddings-v2-base-code-onnx` | 1.64x | 1.11x | 1.10x | 1.32x | 1.02x | 1.00x | 6.62x |

Backend conclusion:

```text
Prefer SQLite for the current machine unless a non-benchmark workload proves a
DuckDB-specific advantage.
```

## Model Ranking

Average across both backends and all four repositories:

| Model | Full index | Warm index | `ctx` | `emb` | Phase total | Phase embeddings | `ctx` memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `current-minilm-sentence-transformers` | 5.086s | 0.682s | 8.817s | 4.997s | 39.985s | 35.550s | 986 MiB |
| `bge-small-en-v1.5-sentence-transformers` | 5.353s | 0.703s | 7.525s | 5.186s | 89.732s | 85.193s | 1025 MiB |
| `bge-small-en-v1.5-onnx` | 5.432s | 0.696s | 3.646s | 1.249s | 122.100s | 117.653s | 355 MiB |
| `nomic-embed-text-v1.5-onnx` | 5.475s | 0.692s | 4.434s | 2.022s | 277.233s | 272.241s | 973 MiB |
| `nomic-embed-text-v1.5-sentence-transformers` | 5.795s | 0.682s | 8.886s | 6.556s | 294.635s | 289.506s | 1924 MiB |
| `jina-embeddings-v2-base-code-onnx` | 5.896s | 0.695s | 4.290s | 2.177s | 253.892s | 248.819s | 950 MiB |

Best per metric:

| Metric | Best model/backend | Value |
| --- | --- | ---: |
| Full index | `current-minilm-sentence-transformers + sqlite` | 3.953s |
| Warm index | `nomic-embed-text-v1.5-sentence-transformers + sqlite` | 0.649s |
| `ctx` | `bge-small-en-v1.5-onnx + sqlite` | 3.517s |
| `emb` | `bge-small-en-v1.5-onnx + sqlite` | 0.993s |
| Phase total | `current-minilm-sentence-transformers + sqlite` | 38.707s |
| Phase embeddings | `current-minilm-sentence-transformers + sqlite` | 35.385s |
| `ctx` memory | `bge-small-en-v1.5-onnx + sqlite` | 256 MiB |

Model conclusion:

- `bge-small-en-v1.5-onnx` is the best interactive-query model.
- `current-minilm-sentence-transformers` is still the cheapest full-index
  model.
- The 768-dimensional models are significantly more expensive to index and do
  not beat BGE ONNX for interactive `ctx` or `emb` latency.

## Torch vs ONNX

In this campaign, "Torch" means the SentenceTransformers engine.

Only BGE and Nomic have direct Torch-vs-ONNX pairs for the same model family.
MiniLM is Torch-only in this matrix. Jina is ONNX-only.

### BGE

ONNX / Torch ratios:

| Backend | Full index | `ctx` | `emb` | Phase total | Phase embeddings | `ctx` memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite | 1.00x | 0.47x | 0.20x | 1.32x | 1.33x | 0.25x |
| DuckDB | 1.03x | 0.50x | 0.28x | 1.41x | 1.44x | 0.44x |

Interpretation:

- BGE ONNX is roughly equal for hyperfine full-index time.
- BGE ONNX is about 2x faster for `ctx`.
- BGE ONNX is about 3.6x to 5.0x faster for `emb`.
- BGE ONNX uses much less query memory.
- BGE ONNX has higher instrumented embedding phase time than BGE Torch.

This is the clearest ONNX win in the campaign because interactive query latency
improves strongly while full-index hyperfine time stays near the Torch path.

### Nomic

ONNX / Torch ratios:

| Backend | Full index | `ctx` | `emb` | Phase total | Phase embeddings | `ctx` memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite | 0.95x | 0.49x | 0.28x | 0.94x | 0.94x | 0.49x |
| DuckDB | 0.94x | 0.51x | 0.34x | 0.94x | 0.94x | 0.52x |

Interpretation:

- Nomic ONNX is better than Nomic Torch on every important metric here.
- Query latency is roughly 2x better for `ctx`.
- Embedding-query latency is roughly 3x to 3.6x better.
- Query memory is roughly half.
- Full-index and phase costs are also slightly better.

However, Nomic remains a 768-dimensional model and is much more expensive than
BGE ONNX for indexing.

### Engine Aggregate

Average by engine and backend:

| Engine | Backend | Full index | `ctx` | `emb` | Phase total | Phase embeddings | `ctx` memory |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SentenceTransformers/Torch | SQLite | 4.171s | 8.248s | 5.358s | 141.219s | 137.717s | 1298 MiB |
| ONNX | SQLite | 4.263s | 3.939s | 1.532s | 216.341s | 212.839s | 695 MiB |
| SentenceTransformers/Torch | DuckDB | 6.651s | 8.570s | 5.802s | 141.683s | 135.783s | 1326 MiB |
| ONNX | DuckDB | 6.939s | 4.308s | 2.100s | 219.142s | 212.970s | 823 MiB |

Engine conclusion:

```text
ONNX is strongly better for interactive ctx/emb latency and memory. Torch is
still cheaper for some full-index embedding phases, especially MiniLM.
```

## Dimensionality

Average by dimension and backend:

| Dimension | Backend | Full index | `ctx` | `emb` | Phase total | Phase embeddings | `ctx` memory |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 384 | SQLite | 4.055s | 6.555s | 3.601s | 83.979s | 80.557s | 748 MiB |
| 384 | DuckDB | 6.525s | 6.771s | 4.021s | 83.899s | 78.374s | 829 MiB |
| 768 | SQLite | 4.379s | 5.632s | 3.289s | 273.581s | 269.999s | 1245 MiB |
| 768 | DuckDB | 7.064s | 6.108s | 3.882s | 276.926s | 270.379s | 1320 MiB |

The 768-dimensional models have similar hyperfine full-index command time in
this fixed campaign, but the instrumented embedding phase is about 3.2x higher
than the 384-dimensional group.

The 768-dimensional models are not a good default on this machine unless their
retrieval quality is materially better in a relevance evaluation.

## Comparison with 20260626 DuckDB Campaign

The preceding completed final campaign was:

```text
.artifacts/final-embedding-model-campaign/20260626T023243
```

It was DuckDB-only and ran before the DuckDB vector-store batching fix. The new
campaign uses the same model set and same four repositories, but a newer commit
and the fixed vector-store package:

| Field | 20260626 | 20260627 |
| --- | --- | --- |
| Backend coverage | DuckDB only | SQLite and DuckDB |
| Codira version | `1.44.6.post1.dev37` | `1.44.6.post1.dev40` |
| Commit | `50ce7784cb636c540aa7af1a2e515d865eb56a0c` | `f40e324ee0aeb316b6e63409455d78e4b3e4726d` |
| DuckDB vector store | `1.0.1` | `1.0.2` |

New DuckDB / old DuckDB ratios:

| Model | Full index | Warm index | `ctx` | `emb` | Phase total | Phase embeddings | Embedding rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `current-minilm-sentence-transformers` | 0.024x | 1.025x | 1.020x | 1.016x | 0.071x | 1.000x | 1.002x |
| `bge-small-en-v1.5-sentence-transformers` | 0.025x | 1.023x | 1.033x | 1.041x | 0.138x | 1.028x | 1.002x |
| `bge-small-en-v1.5-onnx` | 0.026x | 1.041x | 1.020x | 1.025x | 0.182x | 1.024x | 1.002x |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.015x | 0.990x | 1.011x | 0.998x | 0.226x | 1.020x | 1.002x |
| `nomic-embed-text-v1.5-onnx` | 0.014x | 0.996x | 0.992x | 0.989x | 0.221x | 1.008x | 1.002x |
| `jina-embeddings-v2-base-code-onnx` | 0.015x | 1.002x | 0.999x | 0.994x | 0.204x | 1.006x | 1.002x |

This is the key validation result for the DuckDB slowdown fix:

- Full-index hyperfine times dropped by roughly 38x to 71x, depending on model.
- Instrumented phase totals dropped by roughly 4.4x to 14.1x.
- Instrumented embedding time stayed essentially flat.
- Embedding rows are effectively unchanged.

That pattern confirms the previous diagnosis: the severe 20260626 slowdown was
not caused by model embedding computation. It was in the DuckDB vector-store
persistence/materialization path, and the `codira-vector-store-duckdb 1.0.2`
batching fix brought the dominant cost back under control.

## Comparison with 20260618 Comparable DuckDB Baseline

The directly comparable non-final predecessor campaign remains:

```text
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb
```

It used the same four repositories and a pre-separated embedding/vector-store
architecture. Comparing it to the new MiniLM DuckDB slice:

| Metric | 20260618 DuckDB | 20260627 MiniLM DuckDB | Ratio |
| --- | ---: | ---: | ---: |
| Full index | 3.826s | 6.219s | 1.63x |
| Warm index | 0.442s | 0.715s | 1.62x |
| `ctx` | 5.835s | 8.984s | 1.54x |
| `emb` | 4.314s | 5.197s | 1.20x |
| Phase total | 37.975s | 41.263s | 1.09x |
| Phase embeddings | 34.616s | 35.715s | 1.03x |
| Embedding rows | 2608.5 | 2761.0 | 1.06x |

Interpretation:

- The catastrophic DuckDB full-index regression is gone.
- The new architecture still carries moderate overhead versus the 20260618
  predecessor: about 1.6x for hyperfine full/warm index and 1.5x for `ctx`.
- The measured phase total and embedding phase are close to the predecessor,
  suggesting the remaining overhead is mainly process/config/plugin/runtime
  command overhead rather than embedding computation.

## Profile Evidence

There are 48 `profile-summary.json` files, one per completed checkpoint.

Representative `ctx` profile evidence:

- SentenceTransformers/Torch paths spend a lot of cumulative time in config
  loading, backend/plugin resolution, and Torch import/dispatch surfaces.
- ONNX BGE SQLite has much lower query memory and much lower `emb` latency, but
  still shows repeated config parsing and registry work in `ctx`.
- Both engines show recurring `load_effective_config`, `_read_config_file`,
  `tomlkit.parse`, and registry snapshot calls during query execution.

This profile shape explains why ONNX helps strongly with embedding-query
latency but does not eliminate all `ctx` cost. Some remaining query latency is
not model inference; it is repeated config and plugin/backend resolution.

## Recommendation

For this machine, set the default production configuration to:

```toml
[backend]
name = "sqlite"

[embeddings]
enabled = true
engine = "onnx"
vector_store = "sqlite"
model = "BAAI/bge-small-en-v1.5"
version = "1"
dimension = 384
device = "cpu"
batch_size = 8

[embeddings.indexing]
mode = "immediate"
object_types = ["symbol", "documentation"]
max_text_chars = 0

[plugins.embedding-onnx]
enabled = true
precision = "float32"
model_path = ".codira/models/bge-small-en-v1.5/model.onnx"
tokenizer_path = ".codira/models/bge-small-en-v1.5/tokenizer.json"
provider = "CPUExecutionProvider"
normalize = true
max_tokens = 512
```

Use `current-minilm-sentence-transformers + sqlite` only when minimizing
full-index embedding phase time is more important than interactive `ctx` and
`emb` latency.

Do not use a 768-dimensional model as the default until a relevance benchmark
shows enough quality gain to justify the much higher phase embedding cost and
memory footprint.

## Follow-Up Work

1. Investigate repeated config parsing and plugin/backend resolution in query
   paths. The profile summaries show this as a persistent `ctx` cost.
2. Keep the DuckDB vector-store batching Semgrep rule active. This campaign
   validates that the fix addressed the dominant regression.
3. Add a relevance-quality benchmark before choosing between MiniLM and BGE
   only on speed. This campaign measures performance, not retrieval quality.
4. Re-run a small smoke campaign after any future vector-store write-path
   change, because this campaign shows that vector persistence can dominate
   wall-clock behavior without changing embedding computation time.

## Source Artifacts

Primary files inspected:

```text
.artifacts/final-embedding-model-campaign/20260627T201446/README.md
.artifacts/final-embedding-model-campaign/20260627T201446/metadata/environment.txt
.artifacts/final-embedding-model-campaign/20260627T201446/metadata/model-manifest.json
.artifacts/final-embedding-model-campaign/20260627T201446/metadata/manifest-repositories.tsv
.artifacts/final-embedding-model-campaign/20260627T201446/checkpoints/index.tsv
.artifacts/final-embedding-model-campaign/20260627T201446/checkpoints/labels.txt
.artifacts/final-embedding-model-campaign/20260627T201446/configs/*.toml
.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/*-hyperfine.json
.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/*-index-phases.json
.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/failure-summary.json
.artifacts/final-embedding-model-campaign/20260627T201446/campaigns/*/profile-summary.json
.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-hyperfine.json
.artifacts/final-embedding-model-campaign/20260626T023243/campaigns/*/*-index-phases.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/campaign-plan.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-hyperfine.json
.artifacts/benchmarks/backend/20260618T095148Z-bk-cpp-duckdb/*-index-phases.json
```
