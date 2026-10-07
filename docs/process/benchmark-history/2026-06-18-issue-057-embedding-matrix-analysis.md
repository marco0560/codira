# Issue #57 Embedding Matrix Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-18-issue-057-embedding-matrix-analysis.md`
(SHA-256 `9441b5e38232fdf1acee10bead58ef4fa88632250e78f296215e064e4d334d34`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb` | available |
| `.artifacts/issue-057-embedding-matrix/20260614T125721Z` | unavailable historical path |
| `.artifacts/issue-057-embedding-matrix/20260614T125721Z/campaigns/20260614T125721Z-immediate-capped-docs-bk-cpp-duckdb` | unavailable historical path |
| `benchmarks/performance/bk-cpp.local.json` | available |

Resolved directory moves:

- `.artifacts/20260611T210041Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite`.
- `.artifacts/20260613T233728Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb`.
- `benchmarks/bk-cpp.local.json` → `benchmarks/performance/bk-cpp.local.json`.


Date: 2026-06-18

## Scope

This report analyzes the completed Issue #57 embedding matrix under:

- `.artifacts/issue-057-embedding-matrix/20260614T125721Z`

The run was interrupted by a power outage during the final
`immediate-capped-docs` DuckDB campaign and then resumed as a backend-level
rerun. Completed scenario artifacts from the first part were preserved. The
final resumed DuckDB campaign wrote into the same matrix campaign directory:

- `.artifacts/issue-057-embedding-matrix/20260614T125721Z/campaigns/20260614T125721Z-immediate-capped-docs-bk-cpp-duckdb`

The previous non-matrix bk-cpp baseline used for comparison is:

- SQLite: `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite`
- DuckDB: `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb`

All matrix campaigns use `benchmarks/performance/bk-cpp.local.json`.

## Artifact Caveats

The matrix is usable, but there are two important caveats:

1. `deferred-full` DuckDB is incomplete for `large-llvm-project`.

   Its `failure-summary.json` reports three failures for `large-llvm-project`.
   Therefore its phase total is not comparable as a complete successful
   backend run.

2. The resumed `immediate-capped-docs` DuckDB campaign reused some state from
   the interrupted partial run.

   The resumed backend-level rerun started at the beginning of the DuckDB
   campaign. For small and some medium labels, the phase JSON shows zero new
   embedding batch rows, indicating vector-cache reuse from the interrupted
   partial campaign. Large labels are still useful, and the campaign completed
   with zero failures, but the aggregate phase total for capped-docs DuckDB is
   not a clean first-run cold phase total.

The code/version drift during the long matrix is acknowledged, but the tested
embedding paths are still comparable for the matrix purpose:

- Early `deferred-full`: `codira_version = 1.44.4`, commit `a0ad733f...`
- Later scenarios: `codira_version = 1.44.4.post1.dev0`, commit `e522f5d7...`

## Scenario Status

| Scenario | SQLite failures | DuckDB failures | SQLite labels | DuckDB labels | Notes |
|---|---:|---:|---:|---:|---|
| `deferred-full` | 0 | 3 | 17 | 16 phase files | DuckDB fails on `large-llvm-project` |
| `immediate-symbol-only` | 0 | 0 | 17 | 17 | Clean |
| `immediate-documentation-only` | 0 | 0 | 17 | 17 | Clean |
| `immediate-no-embeddings` | 0 | 0 | 17 | 17 | Clean |
| `immediate-capped-docs` | 0 | 0 | 17 | 17 | Clean after resumed DuckDB campaign |

## Phase Totals

`phase_total` is the sum of per-label `timings.total` from
`*-index-phases.json`. `timings.embeddings` is a diagnostic timing component and
is not added separately to wall-clock time.

| Scenario | Backend | Phase total (h) | Indexing (h) | Embeddings (h) | Embedding rows | Failure count |
|---|---|---:|---:|---:|---:|---:|
| `deferred-full` | SQLite | 0.220 | 0.102 | 0.039 | 0 | 0 |
| `deferred-full` | DuckDB | 0.116 | 0.056 | 0.049 | 0 | 3 |
| `immediate-symbol-only` | SQLite | 2.724 | 0.080 | 2.569 | 917554 | 0 |
| `immediate-symbol-only` | DuckDB | 2.950 | 0.116 | 2.750 | 917554 | 0 |
| `immediate-documentation-only` | SQLite | 0.256 | 0.076 | 0.113 | 35015 | 0 |
| `immediate-documentation-only` | DuckDB | 0.271 | 0.050 | 0.116 | 35015 | 0 |
| `immediate-no-embeddings` | SQLite | 0.171 | 0.075 | 0.026 | 0 | 0 |
| `immediate-no-embeddings` | DuckDB | 0.175 | 0.046 | 0.026 | 0 | 0 |
| `immediate-capped-docs` | SQLite | 2.792 | 0.088 | 2.625 | 930980 | 0 |
| `immediate-capped-docs` | DuckDB | 2.737 | 0.114 | 2.552 | 908098 | 0 |

Clean scenario DuckDB/SQLite phase ratios:

| Scenario | DuckDB / SQLite phase total |
|---|---:|
| `immediate-symbol-only` | 1.083x |
| `immediate-documentation-only` | 1.058x |
| `immediate-no-embeddings` | 1.023x |
| `immediate-capped-docs` | 0.980x |

The capped-docs ratio is affected by resumed-run cache reuse in the DuckDB
phase artifacts. Treat it as a completion/correctness signal, not as a cold
first-run DuckDB advantage.

## Previous Baseline

| Baseline | Backend | Phase total (h) | Embeddings (h) | Embedding rows | Failures |
|---|---|---:|---:|---:|---:|
| `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite` | SQLite | 2.769 | 2.582 | 952561 | 0 |
| `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb` | DuckDB | 2.923 | 2.707 | 952569 | 0 |

The previous baseline is essentially the full immediate embedding mode:
approximately 952k embedding rows. The matrix explains that workload:

- `immediate-symbol-only`: 917554 rows
- `immediate-documentation-only`: 35015 rows
- combined: 952569 rows

So the full embedding cost is overwhelmingly symbol-driven.

## Embedding Policy Findings

### Symbol Embeddings Dominate

`immediate-symbol-only` accounts for almost the entire previous full embedding
row count:

- Symbol-only rows: 917554
- Documentation-only rows: 35015
- Full baseline rows: about 952.6k

This means most embedding runtime is driven by symbols, not documentation.

### Documentation-Only Is Cheap

Documentation-only is close to no-embeddings at scenario scale:

| Scenario | SQLite phase total (h) | DuckDB phase total (h) |
|---|---:|---:|
| `immediate-no-embeddings` | 0.171 | 0.175 |
| `immediate-documentation-only` | 0.256 | 0.271 |

The added cost of documentation-only is small relative to symbol embeddings.

### Capped Docs Does Not Solve The Dominant Cost

For SQLite:

- `immediate-symbol-only`: 917554 rows
- `immediate-documentation-only`: 35015 rows
- `immediate-capped-docs`: 930980 rows

Capped docs keeps the full symbol load and only reduces documentation rows. It
cuts documentation rows, but the total row count remains close to the full
baseline because symbols dominate.

Large-label capped-docs row counts confirm this:

| Category | SQLite capped-docs rows | DuckDB capped-docs rows |
|---|---:|---:|
| small | 10619 | 0 |
| medium | 16100 | 3837 |
| large | 904261 | 904261 |

The DuckDB small/medium zeroes are from resumed-run cache reuse. The large
category, where the expensive work lives, matches SQLite and confirms capped
docs still performs the dominant symbol embedding workload.

## Hyperfine Command Findings

The previous baseline showed DuckDB's familiar shape:

| Command | SQLite baseline (s) | DuckDB baseline (s) | DuckDB / SQLite |
|---|---:|---:|---:|
| `index_full` | 1019.794 | 2063.215 | 2.023x |
| `index_incremental` | 65.035 | 39.143 | 0.602x |
| `ctx` | 244.472 | 165.432 | 0.677x |
| `emb` | 196.763 | 142.525 | 0.724x |
| `calls` | 81.058 | 55.869 | 0.689x |
| `audit` | 88.991 | 354.734 | 3.986x |

The matrix preserves the same broad story on successful scenarios:

- DuckDB remains strong on query/read commands when embeddings are present.
- DuckDB warm `index_full` remains slower than SQLite when symbol embeddings are
  present.
- `audit` remains a persistent DuckDB outlier.

Selected matrix command ratios:

| Scenario | Command | DuckDB / SQLite |
|---|---|---:|
| `immediate-symbol-only` | `index_full` | 2.026x |
| `immediate-symbol-only` | `ctx` | 0.690x |
| `immediate-symbol-only` | `emb` | 0.738x |
| `immediate-symbol-only` | `audit` | 6.127x |
| `immediate-documentation-only` | `index_full` | 0.833x |
| `immediate-documentation-only` | `ctx` | 0.989x |
| `immediate-documentation-only` | `audit` | 7.640x |
| `immediate-no-embeddings` | `index_full` | 0.775x |
| `immediate-no-embeddings` | `ctx` | 0.986x |
| `immediate-no-embeddings` | `audit` | 7.795x |
| `immediate-capped-docs` | `index_full` | 1.881x |
| `immediate-capped-docs` | `ctx` | 0.707x |
| `immediate-capped-docs` | `emb` | 0.740x |
| `immediate-capped-docs` | `audit` | 5.465x |

`deferred-full` command sums are not comparable as successful totals because
DuckDB fails on `large-llvm-project`; its large ratios on `ctx`, `emb`, and
`index_incremental` are failure-contaminated and should not be treated as
normal performance data.

## DuckDB Failure Evidence

Only `deferred-full` DuckDB failed. The failure is restricted to
`large-llvm-project`:

| Command index | Command surface | Failure |
|---:|---|---|
| 1 | benchmark index full phase | failed |
| 3 | cProfile `index --full` | failed |
| 4 | cProfile `ctx` auto-refresh | failed |

The logs show the first cause is DuckDB memory exhaustion at the storage layer:

- `OutOfMemoryException: ... 37.5 GiB/37.5 GiB used`
- operation: `pending_embeddings_insert`
- failed batches are tiny: 3 to 6 rows, about 1.1 to 2.5 KiB payload

The later error is a secondary cascade:

- `TransactionContext Error: Current transaction is aborted (please ROLLBACK)`

This matters: the small failed insert batches mean "use a smaller embedding
batch size" is not the real fix. DuckDB is out of memory because the session has
already accumulated too much transaction state before the pending queue insert.

## Fix Plan Evaluation

The previous fix plan was directionally right about the aborted transaction, but
it must be amended.

Original plan core:

- add per-file transaction/savepoint protection around DuckDB persistence
- preserve the original error rather than replacing it with the aborted
  transaction cascade
- add regression tests for pending embedding insert failure

Amendments required after full matrix analysis:

1. Treat memory pressure as the primary failure.

   The root failure is `OutOfMemoryException` at 37.5 GiB used. The transaction
   abort is secondary. A fix that only rolls back correctly would improve the
   diagnostic and keep the connection reusable, but it would not make
   `deferred-full / duckdb / large-llvm-project` complete.

2. Target the long DuckDB indexing transaction.

   `_DuckDBIndexWriteSession` opens one transaction for the full indexing
   session. In deferred mode, pending embedding rows are written while that
   long transaction is active. For llvm scale, DuckDB reaches the memory limit
   before the pending queue insert, even when the insert is only a few rows.

3. Bring session persistence closer to the backend-level per-file transaction
   boundary.

   The backend-level `persist_analysis(..., conn=...)` path already isolates
   file writes with transaction boundaries. The write-session path bypasses that
   and keeps a larger transaction open. The fix should either:

   - split session persistence into bounded commit windows, or
   - flush and commit pending deferred embedding queue rows in bounded windows,
     then reopen a transaction for the next work unit, or
   - route file persistence through the same per-file transaction isolation
     already used by the backend-level path.

4. Keep rollback handling anyway.

   Even after reducing transaction memory pressure, expected DuckDB write
   failures should roll back before cleanup or later SQL. The current cascade
   hides the original failure behind `Current transaction is aborted`.

5. Update the operator-facing error.

   The current message suggests retrying with a smaller embedding batch size.
   In this failure, the batch is only 3 to 6 rows. The diagnostic should include
   the underlying DuckDB exception and should not imply row batch size is the
   decisive lever when the database is already memory-saturated.

6. Validate with targeted matrix slices.

   After implementing the fix, do not rerun the whole matrix first. Run:

   - `deferred-full / duckdb / large-llvm-project`
   - then full `deferred-full / duckdb` if the llvm slice passes
   - then the normal validation suite

## Recommended Next Steps

1. Do not add new broad matrix runs.

   The matrix is complete enough for policy and backend-failure decisions.

2. Use the matrix result to choose embedding policy.

   The practical policy result is:

   - symbol embeddings are expensive and dominate runtime
   - documentation-only is cheap
   - capped docs does not materially reduce full embedding runtime because it
     leaves symbol embeddings untouched
   - deferred mode is attractive conceptually but currently blocked on DuckDB
     memory/transaction handling for llvm scale

3. Fix DuckDB deferred mode before treating deferred-full as production-ready.

   Deferred-full works on SQLite but is not reliable on DuckDB at llvm scale.

4. Track `audit` separately.

   `audit` remains a backend performance outlier independent of embedding
   policy.

## Validation Status

This report did not rerun benchmarks. It reads existing artifacts from:

- `.artifacts/issue-057-embedding-matrix/20260614T125721Z`
- `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite`
- `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb`

Repository capability inspection was performed with:

- `uv run codira caps --json`
