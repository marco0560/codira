# Final Embedding Campaign Report: 20260630T060856

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-30-final-embedding-campaign-20260630T060856-report.md`
(SHA-256 `3fcd29b63e758d6e39c8a1d322c25862b579a254ad7a0396594f0b0f7f6db724`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/final-embedding-model-campaign/20260629T094609` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T140909` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T204308` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260630T060856` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/embedding/uv-backed-repos.local.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.
- `benchmarks/uv-backed-repos.local.json` → `benchmarks/embedding/uv-backed-repos.local.json`.


Date: 2026-06-30

## Scope

Analyzed campaign:

- `.artifacts/final-embedding-model-campaign/20260630T060856`
- Command shape: `runs=5`, `warmup=1`, repository manifest `benchmarks/embedding/uv-backed-repos.local.json`, model manifest `benchmarks/embedding/model-candidates.json`, backend mode `both`
- Completed campaign plans: 48
- Failure summaries: 48/48 with `failure_count = 0`
- Utility summaries: 48/48 present

Primary comparison baselines:

- Same-run SQLite side: `.artifacts/final-embedding-model-campaign/20260630T060856`
- Previous comparable DuckDB campaign: `.artifacts/final-embedding-model-campaign/20260629T204308`
- Earlier DuckDB trend references:
  - `.artifacts/final-embedding-model-campaign/20260629T140909`
  - `.artifacts/final-embedding-model-campaign/20260629T094609`

## Parity

Current run parity is good for backend comparison:

- Same campaign, same commit, same repositories, same models, same run/warmup count.
- Current commit: `d4ec086b33dc532007232a0692c48d83b779f412`
- Codira version in artifacts: `1.44.6.post1.dev54`
- DuckDB backend package in artifacts: `1.50.0`
- DuckDB vector store package in artifacts: `1.0.7`
- SQLite backend package in artifacts: `1.45.1`
- SQLite vector store package in artifacts: `1.0.1`

The previous DuckDB campaign is comparable for DuckDB history but not for same-commit attribution:

- Previous DuckDB run: `20260629T204308`
- Previous commit: `cc0f7b2`
- Same 6 models, same 4 repositories, DuckDB only, same runs/warmup.

## Utility Formula

The current utility summaries use:

```text
score = full_index + 3 * partial_index + 20 * mean(ctx, cov, sym, symlist, emb, calls, audit)
```

Lower is better.

## Backend Summary

| Backend | Full index s | Partial index s | Query mean s | Utility score |
|---|---:|---:|---:|---:|
| sqlite | 4.552 | 0.508 | 1.290 | 31.867 |
| duckdb | 5.364 | 0.583 | 1.456 | 36.229 |

Current DuckDB is slower than SQLite on the workflow-weighted score:

- Utility score: `1.161x` SQLite mean, `1.128x` median paired ratio.
- Full index: `1.387x` SQLite mean, but with wide repo/model spread.
- Partial index: `1.149x` SQLite mean.
- Query mean: `1.160x` SQLite mean.

The result is not a catastrophic DuckDB failure anymore, but DuckDB is still not winning. Under the agreed workflow weighting, SQLite remains the better default.

## Backend Ratios

| Metric | DuckDB / SQLite mean | Median | Min | Max |
|---|---:|---:|---:|---:|
| index --full | 1.387 | 1.335 | 0.926 | 1.971 |
| index | 1.149 | 1.144 | 1.042 | 1.259 |
| qmean | 1.160 | 1.143 | 1.072 | 1.298 |
| score | 1.161 | 1.128 | 1.071 | 1.308 |
| ctx | 1.157 | 1.097 | 1.033 | 1.541 |
| emb | 1.294 | 1.181 | 1.074 | 1.939 |
| audit | 1.099 | 1.109 | 0.900 | 1.213 |
| sym | 1.136 | 1.123 | 1.026 | 1.336 |
| symlist | 1.113 | 1.124 | 0.949 | 1.232 |
| calls | 1.091 | 1.089 | 0.929 | 1.199 |
| cov | 0.999 | 1.007 | 0.875 | 1.159 |

Interpretation:

- `emb` is the worst query path for DuckDB, at `1.294x` mean SQLite.
- `ctx` is also materially slower at `1.157x`.
- Symbol/graph/audit commands are consistently slower but only by about 9-14%.
- `cov` is parity.
- `help`, `plugins`, and `caps` are parity inside the same campaign, so current DuckDB-vs-SQLite overhead is not generic process startup.

## Model Ranking

| Model | SQLite score | DuckDB score | DuckDB/SQLite | Engine |
|---|---:|---:|---:|---|
| bge-small-en-v1.5-onnx | 17.624 | 21.618 | 1.227 | ONNX |
| nomic-embed-text-v1.5-onnx | 22.276 | 26.991 | 1.212 | ONNX |
| jina-embeddings-v2-base-code-onnx | 23.330 | 28.108 | 1.205 | ONNX |
| current-minilm-sentence-transformers | 39.391 | 43.312 | 1.100 | Torch/SentenceTransformers |
| bge-small-en-v1.5-sentence-transformers | 39.899 | 43.758 | 1.097 | Torch/SentenceTransformers |
| nomic-embed-text-v1.5-sentence-transformers | 48.685 | 53.587 | 1.101 | Torch/SentenceTransformers |

Performance conclusions:

- The fastest configuration is `bge-small-en-v1.5-onnx` with SQLite.
- ONNX models dominate for performance under this workload.
- DuckDB penalizes ONNX proportionally more than Torch/SentenceTransformers because ONNX query times are low enough that storage/query overhead is a larger share of total time.
- The Torch/SentenceTransformers models are slower overall, but DuckDB/SQLite ratios are closer because embedding/runtime cost dominates more.

## Repository Effects

| Repo | SQLite score | DuckDB score | DuckDB/SQLite | SQLite full | DuckDB full |
|---|---:|---:|---:|---:|---:|
| chatops | 28.717 | 33.152 | 1.154 | 2.284 | 3.565 |
| codira | 36.551 | 40.188 | 1.100 | 8.516 | 8.128 |
| fontshow | 34.160 | 38.950 | 1.140 | 5.738 | 6.626 |
| sanikey | 28.042 | 32.625 | 1.163 | 1.669 | 3.135 |

Repository-specific observations:

- Codira is the only repo where DuckDB full index is slightly faster than SQLite on average (`8.128s` vs `8.516s`), but DuckDB still loses on total utility due to partial index and query penalties.
- Smaller repos are bad for DuckDB full index: Sanikey is `1.88x` on full index by the aggregate means (`3.135s` vs `1.669s`).
- This suggests a fixed DuckDB setup/query cost still dominates small repositories.

## Current DuckDB vs Previous DuckDB

| Metric | Current mean | Previous mean | Ratio | Delta s |
|---|---:|---:|---:|---:|
| index --full | 5.364 | 4.864 | 1.103 | 0.499 |
| index | 0.583 | 0.442 | 1.317 | 0.140 |
| qmean | 1.456 | 1.258 | 1.157 | 0.197 |
| score | 36.229 | 31.361 | 1.155 | 4.867 |

The latest change is a regression versus the previous DuckDB campaign.

The regression is broad:

- `index --full`: +0.499s mean
- `index`: +0.140s mean
- `ctx`: +0.344s mean
- `emb`: +0.333s mean
- small commands such as `help`, `plugins`, and `caps` also got slower in the latest campaign when compared to the previous commit

That last point matters: the current-vs-previous regression is not only DuckDB full-index logic. It includes a general command overhead increase between commits or environments.

## DuckDB Historical Trend

| Run | Commit | Full | Partial | Query mean | Score | Help | Caps |
|---|---:|---:|---:|---:|---:|---:|---:|
| 20260629T094609 | ed59156 | 5.603 | 0.446 | 1.273 | 32.409 | 0.171 | 0.276 |
| 20260629T140909 | 1982c1a | 4.945 | 0.443 | 1.270 | 31.672 | 0.170 | 0.277 |
| 20260629T204308 | cc0f7b2 | 4.864 | 0.442 | 1.258 | 31.361 | 0.169 | 0.275 |
| 20260630T060856 | d4ec086 | 5.364 | 0.583 | 1.456 | 36.229 | 0.322 | 0.399 |

Before the latest run, DuckDB was slowly improving. The current run reverses that.

The broad command slowdown is visible in `help` and `caps`:

- `help`: `0.169s` to `0.322s`
- `caps`: `0.275s` to `0.399s`

So some of the current-vs-previous regression is process/import/general CLI overhead, not backend-specific execution.

## Full-Index Phase Evidence

| Phase metric | SQLite mean | DuckDB mean | DuckDB/SQLite | DuckDB vs previous |
|---|---:|---:|---:|---:|
| total | 173.600 | 177.281 | 1.021 | 1.013 |
| embeddings | 169.634 | 169.413 | 0.999 | 1.002 |
| parsing | 0.866 | 0.887 | 1.024 | 1.085 |
| indexing | 0.566 | 0.095 | 0.168 | 1.061 |
| discovery | 0.098 | 0.098 | 1.002 | 5.549 |
| scan_state | 0.133 | 0.137 | 1.031 | 4.652 |
| metadata | 0.022 | 0.024 | 1.114 | 3.234 |
| filtering | 0.019 | 0.020 | 1.054 | 1.979 |

Important interpretation:

- Inside the instrumented full-index phase, `timings.indexing` is faster on DuckDB than SQLite (`0.095s` vs `0.566s`).
- Full-index total is dominated by embeddings: about `169s` out of `173-177s` in the phase artifact.
- The hyperfine `index --full` command still shows DuckDB slower because it measures the complete CLI command and warm benchmark wrapper behavior, not only the internal phase timer.
- The current preservation path did not produce a visible full-index win in the end-to-end command metric.

## Torch vs ONNX

ONNX is clearly faster in this campaign.

Average utility scores:

- Best ONNX model, SQLite: `bge-small-en-v1.5-onnx` at `17.624`
- Best Torch/SentenceTransformers model, SQLite: `current-minilm-sentence-transformers` at `39.391`
- Best ONNX model, DuckDB: `bge-small-en-v1.5-onnx` at `21.618`
- Best Torch/SentenceTransformers model, DuckDB: `current-minilm-sentence-transformers` at `43.312`

Operationally, if performance is the only criterion from these artifacts, the current best choice is:

```text
backend = sqlite
embedding model = bge-small-en-v1.5-onnx
```

## What Emerges

1. SQLite remains the best backend for current real workflow weighting.

DuckDB is closer than in early campaigns, but it still loses by about 16% on the utility score in the current same-commit comparison.

2. The latest DuckDB preservation change is not a measured win yet.

The current DuckDB run is slower than the previous DuckDB run by about 15.5% on utility score. Full and partial index both regressed.

3. The current-vs-previous regression has a generic CLI/runtime component.

Small commands regressed too, including `help`, `plugins`, and `caps`. That cannot be explained by full-index vector preservation alone.

4. DuckDB full-index internals are not the main full-index bottleneck in the phase artifact.

`timings.indexing` is faster for DuckDB than SQLite. The full-index wall time is dominated by embeddings, and the residual end-to-end DuckDB penalty is outside the narrow backend write timer.

5. DuckDB query-time vector retrieval remains a real weakness.

`emb` is `1.294x` SQLite on average and up to `1.939x` in the worst pair. Since `emb` and `ctx` are high-weight workflow operations, this matters more than rare full-index wins.

## Decision

Do not treat the latest DuckDB change as a successful optimization.

The DuckDB plugin is still salvageable only if the next work targets measured query and fixed-overhead costs, not another full-index write rewrite. The current evidence says:

- Keep SQLite as the default.
- Keep DuckDB experimental.
- Investigate the broad command-startup regression separately from backend-specific DuckDB query penalties.
- For DuckDB itself, prioritize `emb`/`ctx` retrieval paths and small-repo fixed overhead before more full-index bulk-write changes.

## Recommended Next Interventions

1. Explain the broad command overhead regression.

Compare imports/startup between `cc0f7b2` and `d4ec086`, especially for code imported by `help`, `plugins`, and `caps`. This regression is visible without repository indexing and must be separated from DuckDB work.

2. Profile DuckDB `emb` and `ctx` query paths directly.

Use the current profiles to isolate vector lookup, vector deserialization, candidate assembly, and backend read calls. The highest workflow penalty is query-side, not `timings.indexing`.

3. Add per-command backend timing to query operations.

The full-index phase timer is now too narrow for the current problem. Add comparable timing buckets for `ctx` and `emb`, especially:

- config/plugin initialization
- query embedding generation
- vector-store search
- backend row hydration
- result merge/rendering

4. Add a small-repo fixed-overhead benchmark.

Sanikey and Chatops show large full-index ratios because fixed DuckDB overhead dominates. A minimal synthetic repo can isolate connection/schema/setup overhead from data-volume effects.

5. Re-test the preservation path with a true warm full-index scenario.

The new contract is designed to preserve unchanged materialized vectors, but this campaign's headline `index --full` is still a cold-style command. Add or run a benchmark that performs a second full index over an already populated output directory and measures preserved rows explicitly.

## Validation Status

Analysis inputs were read from local artifact JSON files:

- `campaign-plan.json`
- `*-hyperfine.json`
- `*-index-phases.json`
- `*-utility-summary.json`
- `profile-summary.json`
- `failure-summary.json`
- campaign `README.md`
- checkpoint index metadata

No benchmark commands were rerun during this analysis.
