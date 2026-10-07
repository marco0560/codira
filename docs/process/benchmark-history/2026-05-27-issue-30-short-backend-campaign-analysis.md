# Issue 30 Short Backend Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-27-issue-30-short-backend-campaign-analysis.md`
(SHA-256 `20c27d4f00180da450788cb633d4d0ba3e4c8725969ae48492d7df4e8e86cb24`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260511T151057Z` | available |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-8` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-9` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-sqlite-rerun-3` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-sqlite-rerun-4` | unavailable historical path |
| `benchmarks/performance/benchmarks.local.json` | available |
| `benchmarks/performance/short_benchmark.local.json` | available |

Resolved directory moves:

- `benchmarks/short_benchmark.local.json` → `benchmarks/performance/short_benchmark.local.json`.
- `benchmarks/benchmarks.local.json` → `benchmarks/performance/benchmarks.local.json`.
- `.artifacts/20260511T151057Z` → `.artifacts/benchmarks/backend/20260511T151057Z`.


Date: 2026-05-27

## Compared Artifacts

- Latest SQLite run: `.artifacts/benchmarks/issue-30-short-sqlite-rerun-4`
- Latest DuckDB run: `.artifacts/benchmarks/issue-30-short-duckdb-rerun-9`
- Preceding SQLite run: `.artifacts/benchmarks/issue-30-short-sqlite-rerun-3`
- Preceding DuckDB run: `.artifacts/benchmarks/issue-30-short-duckdb-rerun-8`
- Historical baseline: `.artifacts/benchmarks/backend/20260511T151057Z`

Latest campaign manifest:

```text
benchmarks/performance/short_benchmark.local.json
```

Selected workloads:

| Category | Label | Path |
|---|---|---|
| small | codira | `[historical local path omitted]` |
| large | cpython | `local corpus/cpython` |
| medium | redis | `local corpus/redis` |

## Parity Checks

The latest SQLite and DuckDB campaign plans both record:

- Codira version: `1.25.0.post1.dev0`
- Campaign-plan commit: `879689e25a7e3c5077c6d66bfe1a9dbd309f7095`
- Manifest: `benchmarks/performance/short_benchmark.local.json`
- Analyzer/backend plugin versions:
  - `codira-analyzer-bash==1.5.0`
  - `codira-analyzer-c==1.5.5`
  - `codira-analyzer-cpp==1.5.0`
  - `codira-analyzer-json==1.5.1`
  - `codira-analyzer-python==1.5.2`
  - `codira-backend-duckdb==1.5.3`
  - `codira-backend-sqlite==1.5.3`

Per-workload `*-index-phases.json` files are the more specific source for index
phase measurements. They record matching SQLite-vs-DuckDB commits within each
workload, but not one single commit across all workloads:

| Workload | Latest SQLite phase commit | Latest DuckDB phase commit |
|---|---|---|
| small-codira | `879689e25a7e3c5077c6d66bfe1a9dbd309f7095` | `879689e25a7e3c5077c6d66bfe1a9dbd309f7095` |
| medium-redis | `31896140d1e940cad43d725e830cff0e49d060e5` | `31896140d1e940cad43d725e830cff0e49d060e5` |
| large-cpython | `d948eaa366029bc358dbe9cf32d545c3ad30c502` | `d948eaa366029bc358dbe9cf32d545c3ad30c502` |

The historical baseline is not a direct comparator. It records Codira
`1.23.6.post1.dev1`, uses `benchmarks/performance/benchmarks.local.json`, includes 14
repositories, and has different per-workload commits and counts.

## Latest SQLite vs DuckDB Command Comparison

| Workload | Command | SQLite mean | DuckDB mean | DuckDB vs SQLite | Percent delta |
|---|---|---:|---:|---:|---:|
| small-codira | `index --full` | 40.028s | 244.259s | 6.10x | +510.2% |
| small-codira | `index` incremental | 0.239s | 0.339s | 1.42x | +42.0% |
| small-codira | `ctx` | 5.050s | 5.239s | 1.04x | +3.8% |
| small-codira | `help` | 0.123s | 0.125s | 1.02x | +1.7% |
| small-codira | `cov` | 0.157s | 0.160s | 1.02x | +1.9% |
| small-codira | `sym` | 0.208s | 0.398s | 1.92x | +91.8% |
| small-codira | `symlist` | 0.219s | 0.269s | 1.23x | +22.7% |
| small-codira | `emb` | 5.152s | 5.093s | 0.99x | -1.1% |
| small-codira | `calls` | 0.202s | 0.266s | 1.32x | +31.6% |
| small-codira | `audit` | 0.200s | 0.264s | 1.32x | +32.1% |
| small-codira | `plugins` | 0.180s | 0.178s | 0.99x | -1.3% |
| small-codira | `caps` | 0.144s | 0.149s | 1.04x | +3.5% |
| medium-redis | `index --full` | 178.041s | 1289.932s | 7.25x | +624.5% |
| medium-redis | `index` incremental | 0.750s | 0.998s | 1.33x | +33.1% |
| medium-redis | `ctx` | 6.322s | 5.827s | 0.92x | -7.8% |
| large-cpython | `index --full` | 786.770s | 9446.469s | 12.01x | +1100.7% |
| large-cpython | `index` incremental | 1.191s | 1.791s | 1.50x | +50.3% |
| large-cpython | `ctx` | 18.699s | 34.673s | 1.85x | +85.4% |

## SQLite Stability

SQLite `rerun-4` compared with `rerun-3`:

| Workload | Full index | Incremental index | `ctx` |
|---|---:|---:|---:|
| small-codira | 40.028s vs 44.555s, 10.2% faster | 0.239s vs 0.230s, 4.1% slower | 5.050s vs 5.366s, 5.9% faster |
| medium-redis | 178.041s vs 172.630s, 3.1% slower | 0.750s vs 0.727s, 3.1% slower | 6.322s vs 6.055s, 4.4% slower |
| large-cpython | 786.770s vs 803.801s, 2.1% faster | 1.191s vs 15.596s, 92.4% faster | 18.699s vs 34.522s, 45.8% faster |

SQLite is stable enough to use as the control backend for this comparison. The
only current-vs-previous softness is `medium-redis`, where all measured command
means are roughly 3-4% slower.

SQLite `rerun-4` compared with the historical baseline:

| Workload | Full index vs baseline | Incremental vs baseline | `ctx` vs baseline |
|---|---:|---:|---:|
| small-codira | 40.028s vs 178.613s, 4.46x faster | 0.239s vs 38.048s, 159x faster | 5.050s vs 6.233s, 19.0% faster |
| medium-redis | 178.041s vs 887.202s, 4.98x faster | 0.750s vs 148.840s, 198x faster | 6.322s vs 6.753s, 6.4% faster |
| large-cpython | 786.770s vs 7166.569s, 9.11x faster | 1.191s vs 1406.628s, 1181x faster | 18.699s vs 1417.332s, 75.8x faster |

The baseline result is useful only as historical context because version,
manifest, commits, and indexed counts differ.

## DuckDB Regression Pattern

DuckDB `rerun-9` compared with `rerun-8`:

| Workload | Full index new/old | Incremental new/old | `ctx` new/old |
|---|---:|---:|---:|
| small-codira | 3.00x slower | 0.86x | 1.01x |
| medium-redis | 3.86x slower | 0.96x | 0.99x |
| large-cpython | 4.25x slower | ~0.00x | 0.06x |

Measured conclusion: DuckDB is not performance-stable yet. Recent changes
greatly improved the large warm-read paths, especially `large-cpython`
incremental index and `ctx`, while full indexing regressed by 3-4.25x against
the preceding DuckDB run and remains 6.10-12.01x slower than SQLite in the
latest pair.

## Profile Evidence

Latest DuckDB full-index profiles point at embedding persistence/finalization:

- `large-cpython-index.prof` top entries include `_flush_pending_embedding_rows`,
  `_flush_pending_embeddings`, `_load_class_methods`, and 67,075 calls to
  `executemany`.
- `small-codira-index.prof` shows the same path, with 113 calls to `executemany`
  and high importlib/spec lookup overhead.
- SQLite full-index profile remains dominated by `embed_texts` and
  sentence-transformers work, which matches expected CPU embedding cost.

The bottleneck moved. The previously bad DuckDB warm-read behavior appears
greatly reduced, but the latest full-index path is dominated by DuckDB embedding
flush and finalization behavior.

## Interpretation

Facts:

- SQLite is the stable control for the latest short campaign.
- DuckDB warm paths improved substantially between `rerun-8` and `rerun-9`.
- DuckDB full indexing regressed substantially between `rerun-8` and `rerun-9`.
- Latest DuckDB full indexing is still much slower than latest SQLite full
  indexing across all three workloads.
- The current hot path is DuckDB embedding row persistence, not parser or
  analyzer execution.

Decision:

- DuckDB full-index performance is a no-go in the measured state.
- Further DuckDB optimization should target embedding-row bulk persistence and
  finalization first.

## Follow-Up Validation Note

After this report's original analysis, an Arrow-based DuckDB embedding bulk-load
change was implemented and a direct small Codira full-index sanity pass was run:

```text
env CODIRA_INDEX_BACKEND=duckdb UV_CACHE_DIR=/tmp/uv-cache \
  uv run python scripts/benchmark_index.py . --full \
  --output-dir /tmp/codira-duckdb-arrow-small-index \
  --output /tmp/codira-duckdb-arrow-small-index.json
```

Result:

| Backend/path | Workload | Total | Indexing | Embeddings |
|---|---|---:|---:|---:|
| DuckDB Arrow sanity pass | small-codira | 70.218s | 27.939s | 39.655s |
| Latest DuckDB campaign before Arrow | small-codira | 243.221s | 26.227s | 36.988s |
| Latest SQLite campaign | small-codira | 38.435s | 0.685s | 35.915s |

This sanity pass confirms the Arrow path executes and removes most of the
session-level full-index wall-clock regression for `small-codira`, but DuckDB
still remains slower than SQLite and still spends much more time in the
`indexing` phase. A full rerun of `benchmarks/performance/short_benchmark.local.json` is
required before declaring the campaign fixed.

## Validation Status

Commands run during the implementation follow-up:

```text
uv run codira index
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py
UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --all-files
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q
env CODIRA_INDEX_BACKEND=duckdb UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/benchmark_index.py . --full --output-dir /tmp/codira-duckdb-arrow-small-index --output /tmp/codira-duckdb-arrow-small-index.json
```

Observed results:

- `uv run codira index`: `Indexed: 3`, `Reused: 124`, `Failed: 0`, `Coverage issues: 0`
- Focused DuckDB package tests: `19 passed`
- `pre-commit run --all-files`: passed
- Full pytest: `350 passed`
- Small DuckDB full-index sanity pass completed and wrote `/tmp/codira-duckdb-arrow-small-index.json`
