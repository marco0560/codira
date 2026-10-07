# Retrieval quality campaign analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-18-retrieval-quality-campaign-analysis.md`
(SHA-256 `cd53a740af5ad2136fbbaced7285e62b8e74e0c9930a1ecdb07f65e408beb08c`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/retrieval-quality/20260714T073649` | unavailable historical path |
| `.artifacts/retrieval-quality/20260714T073649/report.md` | unavailable historical path |
| `.artifacts/retrieval-quality/20260714T073649/results.jsonl` | unavailable historical path |
| `.artifacts/retrieval-quality/20260714T073649/summary.json` | unavailable historical path |
| `.artifacts/retrieval-quality/dataset.jsonl` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/retrieval-quality/repos.local.json` | available |

Resolved directory moves:

- `benchmarks/retrieval-quality-repos.local.json` → `benchmarks/retrieval-quality/repos.local.json`.
- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.


Date: 2026-07-18

Campaign artifact: `.artifacts/retrieval-quality/20260714T073649`

Command under analysis:

```bash
uv run python -m scripts.run_retrieval_quality_benchmark \
  --dataset .artifacts/retrieval-quality/dataset.jsonl \
  --repo-manifest benchmarks/retrieval-quality/repos.local.json \
  --model-manifest benchmarks/embedding/model-candidates.json \
  --backend sqlite \
  --top-k 10
```

This campaign evaluates retrieval quality for SQLite vector search with
`top-k=10`, without `--include-ctx`. It compares six embedding model/engine
configurations across 15 repositories and 1251 examples per model.

## Validation

The campaign appears complete and internally consistent.

| Check | Result |
|---|---:|
| Active benchmark process | none found |
| `results.jsonl` parse errors | 0 |
| Result rows | 7596 / 7596 expected |
| Status values | 7596 rows with `status = 0` |
| Missing model/repo/phase groups | 0 |
| Duplicate records by `(model, repo, phase, example_id)` | 0 |
| Summary groups | 90 / 90 expected |
| Log files | 7596 |
| Config files | 90 |

Generated files were last updated at `2026-07-18 02:20:43 CEST`:

- `.artifacts/retrieval-quality/20260714T073649/results.jsonl`
- `.artifacts/retrieval-quality/20260714T073649/summary.json`
- `.artifacts/retrieval-quality/20260714T073649/report.md`

Text searches over logs match many words such as `error`, `failed`, and
`exception`, but the matches are commit messages, symbol names, or normal JSON
content. The structured campaign fields do not show command failures.

## Campaign Shape

| Dimension | Value |
|---|---:|
| Models | 6 |
| Repositories | 15 |
| Examples per full model pass | 1251 |
| Index rows | 90 |
| Retrieval rows | 7506 |
| Total measured index time | 68.42 h |
| Total measured retrieval time | 22.31 h |
| Total measured serial time | 90.73 h |

The run is dominated by indexing, especially for large repositories. Retrieval
latency also scales with repository size, but the largest time spikes come from
`codira index --full`.

## Model Results

| Model | Engine | Dim | Examples | Recall | MRR | nDCG | Hit any | Index h | Query h | Total h | Mean query s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `current-minilm-sentence-transformers` | sentence-transformers | 384 | 1251 | 0.1871 | 0.2905 | 0.1905 | 0.3709 | 2.00 | 3.96 | 5.95 | 11.390 |
| `bge-small-en-v1.5-sentence-transformers` | sentence-transformers | 384 | 1251 | 0.2078 | 0.3287 | 0.2161 | 0.4093 | 4.57 | 3.96 | 8.53 | 11.399 |
| `bge-small-en-v1.5-onnx` | onnx | 384 | 1251 | 0.2104 | 0.3251 | 0.2138 | 0.4085 | 5.64 | 2.46 | 8.09 | 7.070 |
| `nomic-embed-text-v1.5-sentence-transformers` | sentence-transformers | 768 | 1251 | 0.1923 | 0.3017 | 0.1961 | 0.3789 | 20.38 | 4.91 | 25.30 | 14.137 |
| `nomic-embed-text-v1.5-onnx` | onnx | 768 | 1251 | 0.1920 | 0.3008 | 0.1956 | 0.3781 | 19.09 | 3.31 | 22.39 | 9.518 |
| `jina-embeddings-v2-base-code-onnx` | onnx | 768 | 1251 | 0.2002 | 0.3116 | 0.2043 | 0.4045 | 16.74 | 3.72 | 20.46 | 10.699 |

### Ranking

By recall:

1. `bge-small-en-v1.5-onnx`: 0.2104
2. `bge-small-en-v1.5-sentence-transformers`: 0.2078
3. `jina-embeddings-v2-base-code-onnx`: 0.2002

By MRR:

1. `bge-small-en-v1.5-sentence-transformers`: 0.3287
2. `bge-small-en-v1.5-onnx`: 0.3251
3. `jina-embeddings-v2-base-code-onnx`: 0.3116

By nDCG:

1. `bge-small-en-v1.5-sentence-transformers`: 0.2161
2. `bge-small-en-v1.5-onnx`: 0.2138
3. `jina-embeddings-v2-base-code-onnx`: 0.2043

By hit-any rate:

1. `bge-small-en-v1.5-sentence-transformers`: 0.4093
2. `bge-small-en-v1.5-onnx`: 0.4085
3. `jina-embeddings-v2-base-code-onnx`: 0.4045

## Cost / Utility

Using total measured campaign time as the cost denominator:

| Model | nDCG/hour | Recall/hour | Hit/hour | Relative total time vs `bge-small-en-v1.5-onnx` |
|---|---:|---:|---:|---:|
| `current-minilm-sentence-transformers` | 0.03200 | 0.03142 | 0.06230 | 0.74x |
| `bge-small-en-v1.5-sentence-transformers` | 0.02532 | 0.02434 | 0.04795 | 1.05x |
| `bge-small-en-v1.5-onnx` | 0.02642 | 0.02599 | 0.05046 | 1.00x |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.00775 | 0.00760 | 0.01498 | 3.13x |
| `nomic-embed-text-v1.5-onnx` | 0.00873 | 0.00857 | 0.01688 | 2.77x |
| `jina-embeddings-v2-base-code-onnx` | 0.00999 | 0.00979 | 0.01977 | 2.53x |

`current-minilm-sentence-transformers` has the best pure quality-per-hour score
because it is fast, but its absolute quality is clearly lower: about -11.1%
recall and -10.9% nDCG relative to `bge-small-en-v1.5-onnx`. For a default
retrieval model, absolute retrieval quality should matter more than this
campaign-level utility ratio.

The best practical default is therefore `bge-small-en-v1.5-onnx`, not MinILM.

## ONNX vs Sentence Transformers

Two models were tested with both engines.

### BGE small

`bge-small-en-v1.5-onnx` compared with
`bge-small-en-v1.5-sentence-transformers`:

| Metric | ONNX delta |
|---|---:|
| Recall | +0.0026 (+1.26%) |
| MRR | -0.0035 (-1.08%) |
| nDCG | -0.0022 (-1.03%) |
| Hit any | -0.0008 (-0.20%) |
| Mean query speedup | 1.61x |
| Total run speedup | 1.05x |

Quality is effectively tied. ONNX is materially faster for query execution.
Indexing was slower for this BGE ONNX run, but total time still favored ONNX.

### Nomic

`nomic-embed-text-v1.5-onnx` compared with
`nomic-embed-text-v1.5-sentence-transformers`:

| Metric | ONNX delta |
|---|---:|
| Recall | -0.0003 (-0.13%) |
| MRR | -0.0009 (-0.31%) |
| nDCG | -0.0004 (-0.23%) |
| Hit any | -0.0008 (-0.21%) |
| Mean query speedup | 1.49x |
| Total run speedup | 1.13x |

Again, quality is effectively tied. ONNX is faster.

Conclusion: for the same model, ONNX does not introduce a meaningful quality
penalty in this campaign and improves query latency. It should be preferred
unless local deployment constraints require Sentence Transformers.

## Repository Effects

| Repo | Examples/model | Recall | MRR | nDCG | Hit any | Avg index h/model | Avg query s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Catch2 | 100 | 0.1913 | 0.2893 | 0.1843 | 0.3933 | 0.03 | 3.473 |
| Fontshow | 100 | 0.2174 | 0.3607 | 0.2347 | 0.4267 | 0.07 | 3.418 |
| chatops | 32 | 0.1555 | 0.4664 | 0.2218 | 0.5885 | 0.01 | 3.400 |
| codira | 100 | 0.1621 | 0.4519 | 0.2230 | 0.5350 | 0.10 | 3.528 |
| cpython | 100 | 0.2877 | 0.4176 | 0.2872 | 0.5133 | 1.15 | 9.470 |
| fmt | 100 | 0.1516 | 0.1693 | 0.1296 | 0.2450 | 0.01 | 3.369 |
| llvm-project | 100 | 0.1834 | 0.3118 | 0.1851 | 0.4267 | 8.55 | 86.361 |
| nvm | 100 | 0.2134 | 0.1868 | 0.1689 | 0.3117 | 0.01 | 3.333 |
| official-images | 100 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 | 3.358 |
| ohmyzsh | 100 | 0.0200 | 0.0164 | 0.0173 | 0.0200 | 0.02 | 3.367 |
| postgres | 100 | 0.3041 | 0.3923 | 0.2864 | 0.5050 | 1.14 | 5.072 |
| redis | 93 | 0.2841 | 0.4711 | 0.3029 | 0.5448 | 0.27 | 4.124 |
| requests | 48 | 0.4065 | 0.4103 | 0.3537 | 0.5556 | 0.01 | 3.346 |
| sanikey | 73 | 0.3249 | 0.6547 | 0.3988 | 0.7420 | 0.02 | 3.343 |
| tree-sitter-c | 5 | 0.0644 | 0.3278 | 0.1205 | 0.4000 | 0.01 | 3.334 |

The repository dimension matters strongly:

- `llvm-project` dominates both indexing and query time. Average query latency
  across all models is 86.36 seconds.
- `cpython` and `postgres` are the next meaningful runtime drivers.
- Small repositories have similar query latency floors around 3.3-3.5 seconds
  in this benchmark harness.
- Absolute quality is very uneven by repository. `official-images` is zero for
  every model and `ohmyzsh` is near zero. These are likely dataset/analyzer/query
  fit issues rather than model-selection signals.

The all-repo average is therefore useful for default selection, but follow-up
quality work should inspect per-repo failures before treating the absolute
score as a product-level metric.

## Interpretation

### Best default

Use `bge-small-en-v1.5-onnx` as the default embedding model/engine for this
machine.

Rationale:

- It has the best recall in the campaign.
- It is within about 1% of the best MRR/nDCG/hit-any result.
- It has much better query latency than the Sentence Transformers variant.
- It avoids the heavy cost of the 768-dimensional Nomic and Jina models.
- It is a better quality default than MinILM, whose speed comes with a clear
  quality loss.

`bge-small-en-v1.5-sentence-transformers` remains acceptable when ONNX is
unavailable, but it should not be the preferred default on this machine.

### 768-dimensional models

The 768-dimensional candidates are not justified as general defaults here.

`jina-embeddings-v2-base-code-onnx` is the strongest of the 768-dimensional
models in this campaign, but it is still below BGE on global quality and about
2.53x the total measured time of `bge-small-en-v1.5-onnx`. Nomic is slower and
lower quality than BGE in both engine variants.

There may be local pockets where a 768-dimensional model wins:

- Jina is best on `llvm-project` and `nvm` by nDCG.
- Nomic is best on `Fontshow` and `fmt` by nDCG.

Those wins are not broad enough to justify a global default change.

### Backend comparison

This campaign only used SQLite, so it does not support conclusions about DuckDB
quality or performance. Backend comparison can make sense for performance
evaluation and for detecting implementation bugs, but it should not be expected
to change embedding-model semantic quality unless backend-specific retrieval
behavior, numeric precision, ranking, filtering, or persistence bugs differ.

If backend comparison is added to quality evaluation, it should be framed as a
parity/regression check first, not as a model-quality search.

## Follow-up Work

1. Investigate `official-images`.

   It scores zero for every model. That usually points to dataset mismatch,
   expected-path mismatch, analyzer coverage, or query construction that does
   not map to indexed content.

2. Investigate `ohmyzsh`.

   It scores near zero for every model. This is less absolute than
   `official-images`, but still likely a benchmark/data-shape issue.

3. Keep `bge-small-en-v1.5-onnx` as the candidate default and run the pending
   performance-regression checks for `refactor/vector-store-authority` against
   this model.

4. If another quality campaign is needed, include a resumable ledger/checkpoint
   by default. This run completed cleanly, but the campaign length justifies
   restart support.

5. Consider adding a backend parity campaign after model selection. The goal
   should be to confirm that SQLite and DuckDB return equivalent rankings and
   comparable latencies for the same vector store semantics.

## Decision

For current Codira defaults on this machine:

- Preferred model/engine: `bge-small-en-v1.5-onnx`
- Fallback model/engine: `bge-small-en-v1.5-sentence-transformers`
- Do not promote MinILM as the quality default.
- Do not promote Nomic or Jina as the general default from this evidence.
