# DuckDB bk-cpp Regression Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-11-duckdb-bk-cpp-regression-analysis.md`
(SHA-256 `7efec94d2719b26543516862b29b2b949dd88783ef49d78002ed1b57e7b42f35`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb/indexes/large-llvm-project` | unavailable historical path |
| `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb/logs/large-llvm-project-command-1.log` | available |
| `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-sqlite` | available |

Resolved directory moves:

- `.artifacts/20260606T145144Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb`.
- `.artifacts/20260606T145144Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`.
- `.artifacts/20260607T162106Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb`.
- `.artifacts/20260607T162106Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-sqlite`.


Date: 2026-06-11

## Scope

Compared benchmark artifacts:

- `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb`
- `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb`
- `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`
- `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-sqlite` as a same-branch control

The requested run, `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb`, is not complete. It reached `large-llvm-project`, created `large-llvm-project-hyperfine.json`, and then stalled in the llvm hyperfine command sequence. The llvm hyperfine JSON contains only two results, both failed:

- `codira index --full`: mean `12195.262s`, exit code `1`, peak RSS about `44.0 GiB`
- `codira index`: mean `12505.322s`, exit code `1`, peak RSS about `44.0 GiB`

No llvm hyperfine result exists for `ctx`, `cov`, `emb`, `audit`, `plugins`, or `caps` in the new DuckDB run.

## Parity Checks

The compared runs are not the same Codira revision:

- Previous DuckDB and SQLite baseline index-phase artifacts report `codira_version=1.43.2` and backend package versions `1.44.0`.
- New DuckDB and SQLite artifacts report `codira_version=1.44.1` and backend package versions `1.45.0`.

The repository inputs inside each run are comparable by commit per target. For example, common phase files show the same target commit IDs for old and new artifacts:

- postgres: `d6a72bbe...`
- texlive: `591eb2aa...`
- llvm-project: `2e06e008...`
- redis: `31896140...`

Therefore the regression is attributable to Codira/backend/runtime changes between the artifact generations, not to different target repository revisions.

## Measured Deltas

Index-phase comparison for common successful targets:

| Target | Old DuckDB total | New DuckDB total | New SQLite total | DuckDB old to new | New DuckDB vs SQLite |
|---|---:|---:|---:|---:|---:|
| large-postgres | `664.074s` | `867.808s` | `672.076s` | `1.31x` | `1.29x` |
| large-texlive | `1430.011s` | `2508.913s` | `1496.618s` | `1.75x` | `1.68x` |
| medium-redis | `213.582s` | `268.032s` | `210.413s` | `1.25x` | `1.27x` |
| small-codira | `72.233s` | `90.812s` | `72.224s` | `1.26x` | `1.26x` |

For these targets, embedding generation itself did not explain the full regression:

| Target | Old DuckDB embeddings | New DuckDB embeddings | New SQLite embeddings |
|---|---:|---:|---:|
| large-postgres | `631.228s` | `644.637s` | `643.863s` |
| large-texlive | `1331.332s` | `1450.989s` | `1410.902s` |
| medium-redis | `202.711s` | `200.863s` | `201.983s` |
| small-codira | `66.499s` | `68.465s` | `67.697s` |

The new DuckDB wall time grew disproportionately outside the embedding model computation. The same branch's SQLite run remained close to the old baseline, including llvm:

- new SQLite llvm index phase: `6600.520s`
- old SQLite llvm index phase: `6624.330s`
- old DuckDB llvm index phase: `6744.505s`

The new DuckDB llvm index did not produce an index-phase JSON because it failed during final embedding flush. The hyperfine result shows each attempted full or incremental index consumed roughly `3h23m` to `3h28m` before failing, repeated across the warmup/runs.

## Root-Cause Evidence

The decisive failure is in `.artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb/logs/large-llvm-project-command-1.log` and the matching discovery log. The traceback ends in:

```text
_store_cached_embedding_vectors
conn.executemany(...)
_duckdb.OutOfMemoryException: Out of Memory Error ... (37.5 GiB/37.5 GiB used)
```

The failing source location is:

- `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_support.py:3748`

The Semgrep findings point at the same hot path:

- `_store_pending_embedding_rows`: row-wise `executemany()` into `pending_embeddings`
- `_store_cached_embedding_vectors`: row-wise `executemany()` into `embedding_vector_cache`
- `_delete_pending_embedding_rows`: row-wise `executemany()` delete from `pending_embeddings`

The llvm failure occurred specifically in `_store_cached_embedding_vectors()`, while inserting cached vectors. That aligns with the rule forbidding DuckDB `executemany`: this is row-wise Python-to-DuckDB persistence of many large vector blobs, and the result is both very slow and memory explosive at llvm scale.

Profiles on successful new DuckDB targets show the same path as the dominant cost:

- `large-postgres-index.prof`
  - `_flush_pending_embeddings`: `842.336s`
  - `_flush_prepared_embedding_rows`: `842.135s`
  - DuckDB `register`: `841.613s`
  - `embed_texts`: `636.070s`
  - row-wise `executemany`: `91.271s`
- `large-texlive-index.prof`
  - `_flush_pending_embeddings`: `2383.928s`
  - `_flush_prepared_embedding_rows`: `2383.324s`
  - `embed_texts`: `1378.846s`
  - DuckDB `register`: `1001.876s`
  - row-wise `executemany`: `276.353s`

The old DuckDB profiles did not show this extra cache-write cost. For example, old `large-postgres-index.prof` had `_flush_prepared_embedding_rows` at `635.423s`, essentially tracking the embedding phase, while the new profile adds roughly `200s` around the same target. On texlive the extra cost is roughly `1000s`.

## What Went Wrong

The branch introduced or retained a DuckDB embedding-vector cache path that is not implemented with DuckDB-appropriate batch loading.

The main regression pattern is:

1. Session-level pending embeddings are accumulated.
2. `_flush_prepared_embedding_rows()` deduplicates rows and computes vectors.
3. Newly encoded vectors are persisted through `_store_cached_embedding_vectors()`.
4. `_store_cached_embedding_vectors()` uses `conn.executemany()` with a Python list of `(backend, version, dim, content_hash, vector)` rows.
5. For large corpora, especially llvm, that row-wise insert of vector blobs drives DuckDB to the configured memory limit and raises `_duckdb.OutOfMemoryException`.

This also explains why SQLite did not regress similarly: the problematic implementation is DuckDB-specific, and the same new-branch SQLite artifact remains close to the old baseline on the largest completed targets.

The branch also failed the repository validation gate. `uv run python scripts/validate_repo.py` would have caught the three DuckDB `executemany()` violations through the custom Semgrep rule. Because that gate was not clean before the long benchmark campaign, the benchmark run exposed exactly the kind of performance regression the rule was designed to prevent.

## About `codira ctx` Memory Usage

The observed live process:

```text
codira ctx --json schema migration logic --path .../llvm-project --output-dir .artifacts/benchmarks/backend/20260607T162106Z-bk-cpp-duckdb/indexes/large-llvm-project
```

was not represented as a completed hyperfine result in the new DuckDB llvm artifact. The hyperfine file stopped after the two failed index commands.

However, the behavior is still consistent with the same underlying failure mode. The llvm DuckDB index directory left by the failed run is much smaller than the previous successful DuckDB index:

- new failed llvm DuckDB index: `index.duckdb` about `120 MB`
- old successful llvm DuckDB index: `index.duckdb` about `5.9 GB`

Running `ctx` against a partially failed DuckDB index can force query-time work over incomplete or inconsistent embedding/cache state. The memory symptom should therefore be treated as a follow-on failure until reproduced against a cleanly built DuckDB index.

## Exception Handling Gap

The `_duckdb.OutOfMemoryException` propagates as a raw backend exception through CLI and benchmark tooling. The current behavior is useful for exposing the traceback during debugging, but poor for operator guidance and automated campaign control.

The backend should handle expected DuckDB operational failures at the backend boundary, preserving the original exception as cause while producing a Codira-level diagnostic that includes:

- operation phase, for example `embedding_vector_cache_insert`
- target table or cache
- row count and approximate payload size
- DuckDB memory limit if discoverable
- actionable mitigation, for example reduced batch size or disabled cache write

This should not hide failures or make them non-blocking by default. It should make the failure typed, documented, and easier for scripts to classify.

## Recommended Fix

Do not whitelist the three Semgrep violations as-is. The llvm failure proves the rule is valid for these spots.

Fix direction:

1. Replace `_store_cached_embedding_vectors()` `executemany()` with a columnar batch path:
   - build Arrow arrays or a DataFrame/table for `backend`, `version`, `dim`, `content_hash`, `vector`
   - register it as a temporary DuckDB relation
   - perform set-based `INSERT OR REPLACE INTO embedding_vector_cache SELECT ...`
   - unregister in `finally`
2. Replace `_store_pending_embedding_rows()` with the same pattern for `pending_embeddings`.
3. Replace `_delete_pending_embedding_rows()` with a registered table plus set-based `DELETE ... USING`.
4. Add tests that assert these helpers do not call `executemany()` for DuckDB.
5. Add a large synthetic embedding-cache persistence test with enough rows/vector bytes to exercise the batch path without requiring llvm-scale data.
6. Add documented handling for DuckDB memory exceptions at the backend boundary.
7. Re-run `uv run python scripts/validate_repo.py`; it must pass before any commit and must pass at branch completion.
8. Re-run a bounded benchmark before the full campaign:
   - small representative target
   - medium target such as redis
   - large target such as postgres or texlive
   - llvm only after the above are clean

## Validation Status

Performed for this report:

- inspected Codira capability contract with `.venv/bin/codira caps --json`
- refreshed a Codira repository index into `/tmp/codira-analysis-index`
- compared campaign console logs, hyperfine JSON, phase timing JSON, profiles, and llvm command logs
- inspected the current DuckDB backend source around the failing helpers

Not performed:

- no code fix was implemented
- no repository validation run was executed after this analysis
- no new benchmark was run
