# DuckDB campaign analysis: 20260629T140909

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-29-final-embedding-campaign-20260629T140909-duckdb-cache-vector-analysis.md`
(SHA-256 `187ac5200b65b87d24c91e8538a566cc77a2b3b12690a6ddb261c292bfbfe3b1`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/final-embedding-model-campaign/20260629T002747` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T094609` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T140909` | unavailable historical path |


## Compared runs

Primary run:

- Path: `.artifacts/final-embedding-model-campaign/20260629T140909`
- Backend mode: `duckdb`
- Concrete backend: `duckdb`
- Repositories: `codira`, `fontshow`, `chatops`, `sanikey`
- Models: 6 embedding candidates x 4 repositories = 24 campaign cells
- Runs/warmup: 5 / 1
- Commit: `1982c1ae4e7292d07cc5e8a9ea3bbc8b9bb85f01`
- Relevant code change: `perf(backend): reduce duckdb full-index planning cost`

Direct comparison run:

- Path: `.artifacts/final-embedding-model-campaign/20260629T094609`
- Backend mode: `duckdb`
- Same 6 models and 4 repositories
- Runs/warmup: 5 / 1
- Commit family: immediately preceding DuckDB bulk implementation before the
  cache-resolution/vector-store full-index rewrite

Context baseline:

- Path: `.artifacts/final-embedding-model-campaign/20260629T002747`
- Backend mode: `both`
- Same model/repository matrix, with both SQLite and DuckDB cells
- Used only as the current SQLite-vs-DuckDB reference, not as an exact
  same-commit comparison.

## Parity notes

The latest campaign is directly comparable to `20260629T094609` for the effect
of the last DuckDB changes: same campaign shape, same repository/model matrix,
same backend, and same run/warmup count.

It is not same-commit comparable with SQLite because the latest campaign was
DuckDB-only. SQLite ratios below therefore use `20260629T002747` as a practical
baseline, not as proof of exact same-commit backend parity.

## Top-line results

Across the 24 DuckDB cells, median full-index wall time improved:

| Metric | Previous DuckDB `20260629T094609` | Latest DuckDB `20260629T140909` | Delta |
|---|---:|---:|---:|
| Full index median of cells | 4.784 s | 4.385 s | 0.92x |
| Full index mean of cells | 5.602 s | 4.916 s | 0.89x |
| Warm/no-op index median of cells | ~0.43 s | ~0.43 s | unchanged |
| `ctx` median of cells | 3.753 s | 3.687 s | unchanged |
| `emb` median of cells | 3.529 s | 3.514 s | unchanged |

The fix improved full rebuilds only, as intended. Interactive query timings did
not materially move, which is the right result for a storage-write-path change.

Latest DuckDB is still slower than the SQLite baseline from `20260629T002747`:

| Command | Latest DuckDB / SQLite baseline, mean ratio | Median ratio |
|---|---:|---:|
| `index --full` | 1.89x | 1.89x |
| warm/no-op `index` | approximately 1.2x | approximately 1.2x |
| `ctx` | 1.16x | 1.15x |
| `emb` | 1.31x | 1.25x |
| `sym` | 1.23x | 1.22x |
| `calls` | 1.17x | 1.17x |
| `cov` | 1.02x | 1.01x |

## Full-index per-cell deltas

The latest full-index run improved 23 of 24 cells against the direct previous
DuckDB run. The one non-improving cell was small:

- `chatops / jina-embeddings-v2-base-code-onnx`: +0.057 s

Largest improvements:

| Repo | Model | Previous | Latest | Ratio | Delta |
|---|---|---:|---:|---:|---:|
| `fontshow` | `nomic-embed-text-v1.5-onnx` | 8.880 s | 5.978 s | 0.67x | -2.903 s |
| `fontshow` | `bge-small-en-v1.5-onnx` | 8.170 s | 5.831 s | 0.71x | -2.340 s |
| `codira` | `current-minilm-sentence-transformers` | 9.101 s | 7.122 s | 0.78x | -1.980 s |
| `codira` | `nomic-embed-text-v1.5-sentence-transformers` | 9.368 s | 7.708 s | 0.82x | -1.661 s |
| `fontshow` | `jina-embeddings-v2-base-code-onnx` | 7.890 s | 6.419 s | 0.81x | -1.471 s |

Latest full-index mean by repository:

| Repo | Mean full-index time | Range |
|---|---:|---:|
| `sanikey` | 2.566 s | 2.085-2.909 s |
| `chatops` | 3.067 s | 2.654-3.411 s |
| `fontshow` | 6.101 s | 5.358-7.057 s |
| `codira` | 7.931 s | 7.122-8.970 s |

Latest full-index mean by model:

| Model | Mean full index | Mean `ctx` | Mean `emb` | Mean max RSS |
|---|---:|---:|---:|---:|
| `current-minilm-sentence-transformers` | 4.361 s | 5.085 s | 4.981 s | 415 MB |
| `bge-small-en-v1.5-onnx` | 4.638 s | 1.353 s | 1.210 s | 415 MB |
| `bge-small-en-v1.5-sentence-transformers` | 4.637 s | 5.004 s | 4.868 s | 423 MB |
| `nomic-embed-text-v1.5-onnx` | 5.220 s | 2.167 s | 2.016 s | 591 MB |
| `nomic-embed-text-v1.5-sentence-transformers` | 5.237 s | 6.490 s | 6.348 s | 591 MB |
| `jina-embeddings-v2-base-code-onnx` | 5.403 s | 2.420 s | 2.153 s | 593 MB |

## Profile evidence

Aggregate DuckDB profile totals across 24 cells:

| Span | Previous total | Latest total | Calls previous | Calls latest | Interpretation |
|---|---:|---:|---:|---:|---|
| `bulk_full_index.plan_rows` | 56.058 s | 8.065 s | 24 | 24 | fixed |
| `sql.select` | 47.444 s | 32.092 s | 4,938 | 144 | per-file SELECTs removed |
| `embeddings.load_cached_vectors` | absent/separate per-file cost | 32.072 s | n/a | 24 | now one cache load per cell |
| `bulk_full_index.load_embeddings` | 36.945 s | 66.872 s | 24 | 24 | now includes the bulk cache load |
| `vector_store.store_vectors` | 23.868 s | 22.099 s | 24 | 24 | small improvement |
| `sql.create_index` | 14.228 s | 13.915 s | 1,128 | 1,128 | unchanged |
| `bulk_full_index.commit_structural` | 7.720 s | 7.819 s | 24 | 24 | unchanged |

This validates the last fix precisely:

- `plan_rows` is no longer doing one cache lookup per file.
- `sql.select` calls dropped from thousands to six per campaign cell.
- The remaining `sql.select` time is almost entirely the explicit single
  `embeddings.load_cached_vectors` span per cell.

Example latest profile for `codira / bge-small-en-v1.5-onnx`:

- `bulk_full_index.load_embeddings`: 3.656 s
- `sql.select`: 2.167 s / 6 calls
- `embeddings.load_cached_vectors`: 2.165 s / 1 call / 4,520 rows
- `vector_store.store_vectors`: 0.875 s
- `sql.create_index`: 0.959 s

## Interpretation

The cache-planning regression is fixed. The earlier pathological shape was:

- thousands of `sql.select` calls
- most of them happening during `bulk_full_index.plan_rows`
- full-index row planning behaving like an indexed per-file workflow

The latest shape is:

- one vector-cache load per full-index cell
- low `plan_rows` cost
- no material movement in interactive commands

The residual DuckDB full-index gap is now mostly real backend overhead in these
areas:

1. Reading existing cached vectors from DuckDB before embedding flush.
2. Materializing vectors into the separated DuckDB vector store.
3. Creating 47 structural indexes per cell.
4. DuckDB commit overhead.

The largest remaining single cost is the vector-cache load. On the latest run,
`embeddings.load_cached_vectors` accounts for 32.1 s aggregate, almost exactly
all remaining `sql.select` time. This is not the old per-file query bug anymore;
it is a bulk read of thousands of cached vector blobs/list values from DuckDB.

## Backend decision

DuckDB is salvageable as a supported backend, but not yet as the default
performance backend. The radical full-index rewrite and the cache-planning fix
produced real gains:

- full-index median improved from 4.956 s in the older DuckDB context to 4.385 s
  in the latest run
- the prior row-planning bottleneck is gone
- the latest full-index mean improved by about 11% against the direct previous
  DuckDB run

However, DuckDB still remains about 1.9x slower than the latest SQLite baseline
for full rebuild wall time on this matrix. That gap is too large to ignore.

Recommended status:

- Keep DuckDB supported.
- Do not make DuckDB the default.
- Do one more targeted optimization pass only if it attacks the measured
  remaining costs directly.

## Next target

The next high-value target is vector cache/materialized vector storage, not row
planning.

Candidate fix:

- During full rebuilds, avoid loading cached vectors from DuckDB when the full
  index output directory is fresh or when the cache cannot be reused across
  model/store identity changes.
- Add an explicit full-index policy:
  - fresh output: encode and write directly; skip cache read
  - reused output: cache read allowed
  - deferred embeddings: preserve pending path
- Keep the separated vector-store boundary for issue `#20`, but consider a
  full-index-only fast path that writes cache and materialized vectors together
  in one vector-store transaction.

Validation for that next pass should include:

- a unit/contract test proving fresh full-index does not call cache load
- a regression test proving reused-output full-index can still reuse cached
  vectors
- a Semgrep rule only if a simple anti-pattern is identified, such as calling
  per-file cache lookup inside `persist_full_index`
- another DuckDB-only campaign with the same command line

## Bottom line

The last implementation worked. It removed the accidental per-file SQL behavior
from full-index planning and improved full-index wall time without perturbing
interactive query timings.

The remaining DuckDB gap is now concentrated in vector-cache/vector-store work
and fixed DuckDB lifecycle costs. Further improvements should be deliberately
targeted there; another broad rewrite of row planning would be wasted effort.
