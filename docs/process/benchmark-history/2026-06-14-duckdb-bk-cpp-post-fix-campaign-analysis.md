# DuckDB bk-cpp Post-Fix Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-14-duckdb-bk-cpp-post-fix-campaign-analysis.md`
(SHA-256 `d5ddb9ec9e1a4a90e69b3447b43236019863a3d67bfb8dc7ed3ea34895b06f62`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260612T204316Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb` | available |
| `benchmarks/performance/bk-cpp.local.json` | available |

Resolved directory moves:

- `.artifacts/20260611T210041Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite`.
- `.artifacts/20260612T204316Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260612T204316Z-bk-cpp-duckdb`.
- `.artifacts/20260613T233728Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb`.
- `benchmarks/bk-cpp.local.json` → `benchmarks/performance/bk-cpp.local.json`.


Date: 2026-06-14

## Scope

This report compares the latest DuckDB `bk-cpp` measurement campaign against
the previous DuckDB campaign and the latest SQLite baseline campaign.

| Role | Artifact | Codira | Git commit | Backend package | Failures |
|---|---|---:|---|---:|---:|
| SQLite baseline | `.artifacts/benchmarks/backend/20260611T210041Z-bk-cpp-sqlite` | 1.44.2 | `7b235dc5fa9248217120565c37187d7c80ae51e8` | `codira-backend-sqlite` 1.45.0 | 0 |
| Previous DuckDB | `.artifacts/benchmarks/backend/20260612T204316Z-bk-cpp-duckdb` | 1.44.3 | `38ea294027d5cb09c07e416c642e873128c3dd7a` | `codira-backend-duckdb` 1.47.0 | 17 |
| Latest DuckDB | `.artifacts/benchmarks/backend/20260613T233728Z-bk-cpp-duckdb` | 1.44.4 | `a0ad733fd4924863687b2a92c9faca587720911c` | `codira-backend-duckdb` 1.47.0 | 0 |

All three campaigns use the same manifest:
`benchmarks/performance/bk-cpp.local.json`.

The campaign selection is comparable:

- Selection labels: 17
- Resolved command matrices match between SQLite and both DuckDB campaigns
- Latest DuckDB failure summary: `failure_count = 0`
- Previous DuckDB failure summary: 17 failures, all on command index 3,
  corresponding to the warm full-reindex path that hit the duplicate
  `symbol_index.stable_id` constraint error

## Executive Summary

The latest DuckDB campaign resolves the previous correctness blocker. The warm
full-reindex path no longer fails, and the campaign completes with zero
failures across all 17 benchmark labels.

Performance is now close enough to proceed with the embedding matrix, but it is
not full parity across every command surface.

The strongest result is that DuckDB preserves its read/query advantage while
recovering complete lifecycle correctness. Incremental index, context, symbol
listing, semantic lookup, and call graph commands are all materially faster than
SQLite in aggregate. The remaining work is concentrated in two surfaces:

- warm `index --full`, now correct but about 2.02x SQLite in aggregate
- `audit`, still the largest read-side outlier at about 3.99x SQLite in
  aggregate

Recommendation: run the embedding matrix now. The remaining gaps are bounded
performance follow-ups, not blockers for the next validation stage.

## Campaign-Level Timing

The table below uses the campaign phase timing totals. `total` is the wall-clock
phase time. `indexing` and `embeddings` are diagnostic subcomponents and must
not be added together as if they were independent elapsed time.

| Size | Count | SQLite total (s) | Previous DuckDB total (s) | Latest DuckDB total (s) | Latest / SQLite | Latest / Previous |
|---|---:|---:|---:|---:|---:|---:|
| small | 8 | 184.748 | 205.227 | 205.757 | 1.114x | 1.003x |
| medium | 4 | 253.383 | 279.315 | 279.441 | 1.103x | 1.000x |
| large | 5 | 9530.541 | 10103.624 | 10037.479 | 1.053x | 0.993x |
| all | 17 | 9968.672 | 10588.167 | 10522.676 | 1.056x | 0.994x |

At campaign level, latest DuckDB is 5.6% slower than SQLite overall and 0.6%
faster than the previous DuckDB campaign. The large workload class dominates the
wall-clock total and is only 5.3% slower than SQLite.

This is substantial parity for the broad campaign runtime, with the caveat that
some individual command surfaces still diverge.

## Phase Breakdown

| Size | SQLite indexing (s) | Latest DuckDB indexing (s) | DuckDB / SQLite | SQLite embeddings (s) | Latest DuckDB embeddings (s) | DuckDB / SQLite |
|---|---:|---:|---:|---:|---:|---:|
| small | 4.131 | 6.122 | 1.482x | 169.020 | 181.680 | 1.075x |
| medium | 6.349 | 10.810 | 1.703x | 239.637 | 261.535 | 1.091x |
| large | 363.060 | 546.667 | 1.506x | 8887.104 | 9301.801 | 1.047x |
| all | 373.541 | 563.599 | 1.509x | 9295.762 | 9745.016 | 1.048x |

The phase diagnostics show a consistent pattern:

- embedding-heavy wall-clock time is close to SQLite, especially on large
  workloads
- indexing diagnostics remain slower for DuckDB, around 1.51x overall
- small and medium workloads show proportionally larger fixed-cost overheads

## Per-Label Campaign Deltas

| Label | SQLite total (s) | Previous DuckDB total (s) | Latest DuckDB total (s) | Latest / SQLite | Latest / Previous |
|---|---:|---:|---:|---:|---:|
| large-cldr-json | 13.752 | 14.397 | 19.045 | 1.385x | 1.323x |
| large-cpython | 882.444 | 975.123 | 927.889 | 1.051x | 0.952x |
| large-llvm-project | 6517.925 | 6843.329 | 6849.333 | 1.051x | 1.001x |
| large-postgres | 638.900 | 687.508 | 696.116 | 1.090x | 1.013x |
| large-texlive | 1477.520 | 1583.267 | 1545.096 | 1.046x | 0.976x |
| medium-catch2 | 26.490 | 29.726 | 29.974 | 1.132x | 1.008x |
| medium-official-images | 8.480 | 9.359 | 9.194 | 1.084x | 0.982x |
| medium-ohmyzsh | 20.163 | 22.328 | 22.278 | 1.105x | 0.998x |
| medium-redis | 198.250 | 217.902 | 217.994 | 1.100x | 1.000x |
| small-codira | 67.327 | 74.540 | 74.874 | 1.112x | 1.004x |
| small-dataset-json-examples | 5.179 | 5.329 | 5.173 | 0.999x | 0.971x |
| small-fmt | 14.472 | 16.369 | 16.374 | 1.131x | 1.000x |
| small-fontshow | 54.680 | 60.906 | 60.876 | 1.113x | 1.000x |
| small-nvm | 7.987 | 9.286 | 9.564 | 1.197x | 1.030x |
| small-requests | 12.237 | 12.626 | 12.609 | 1.030x | 0.999x |
| small-tree-sitter-c | 12.742 | 14.555 | 14.560 | 1.143x | 1.000x |
| small-tree-sitter-python | 10.123 | 11.616 | 11.727 | 1.159x | 1.010x |

All labels preserve indexed/failed counts relative to SQLite and the previous
DuckDB campaign. The latest DuckDB run is broadly stable against the previous
DuckDB run, with most label-level movement within a few percent. The notable
exception is `large-cldr-json`, where latest DuckDB is 32.3% slower than the
previous DuckDB run and 38.5% slower than SQLite; because this label is small in
absolute time, it does not materially affect campaign-level conclusions.

## Hyperfine Command Summary

| Command | Comparable labels | SQLite sum (s) | Previous DuckDB sum (s) | Latest DuckDB sum (s) | Latest / SQLite | Latest / Previous | Previous failures |
|---|---:|---:|---:|---:|---:|---:|---:|
| index_full | 17 | 1019.794 | n/a | 2063.215 | 2.023x | n/a | 17 |
| index_incremental | 17 | 65.035 | 39.253 | 39.143 | 0.602x | 0.997x | 0 |
| ctx | 17 | 244.472 | 166.630 | 165.432 | 0.677x | 0.993x | 0 |
| cov | 17 | 6.409 | 6.556 | 6.412 | 1.000x | 0.978x | 0 |
| sym | 16 | 89.641 | 67.192 | 66.834 | 0.746x | 0.995x | 0 |
| symlist | 16 | 84.908 | 56.772 | 56.625 | 0.667x | 0.997x | 0 |
| emb | 17 | 196.763 | 143.004 | 142.525 | 0.724x | 0.997x | 0 |
| calls | 16 | 81.058 | 56.206 | 55.869 | 0.689x | 0.994x | 0 |
| audit | 17 | 88.991 | 356.162 | 354.734 | 3.986x | 0.996x | 0 |
| help | 17 | 3.482 | 3.574 | 3.499 | 1.005x | 0.979x | 0 |
| plugins | 17 | 4.765 | 4.860 | 4.787 | 1.005x | 0.985x | 0 |
| caps | 17 | 4.578 | 4.704 | 4.608 | 1.007x | 0.980x | 0 |

The previous DuckDB campaign failed every `index_full` hyperfine case. The
latest DuckDB campaign succeeds on all 17. This is the central correctness
improvement in the new campaign.

For query/read commands, DuckDB remains faster than SQLite in aggregate:

- `index_incremental`: 0.602x SQLite
- `ctx`: 0.677x SQLite
- `sym`: 0.746x SQLite
- `symlist`: 0.667x SQLite
- `emb`: 0.724x SQLite
- `calls`: 0.689x SQLite

The neutral command surfaces are also stable:

- `cov`: 1.000x SQLite
- `help`: 1.005x SQLite
- `plugins`: 1.005x SQLite
- `caps`: 1.007x SQLite

The remaining regressions are concentrated:

- `index_full`: 2.023x SQLite
- `audit`: 3.986x SQLite

## Warm Full-Reindex Result

| Label | SQLite `index_full` (s) | Latest DuckDB `index_full` (s) | Latest / SQLite |
|---|---:|---:|---:|
| large-cldr-json | 6.178 | 7.157 | 1.158x |
| large-cpython | 113.516 | 150.658 | 1.327x |
| large-llvm-project | 697.225 | 1588.283 | 2.278x |
| large-postgres | 43.143 | 51.012 | 1.182x |
| large-texlive | 125.822 | 209.204 | 1.663x |
| medium-catch2 | 3.221 | 6.248 | 1.940x |
| medium-official-images | 0.961 | 2.093 | 2.178x |
| medium-ohmyzsh | 1.593 | 3.204 | 2.011x |
| medium-redis | 12.239 | 16.400 | 1.340x |
| small-codira | 4.464 | 6.858 | 1.536x |
| small-dataset-json-examples | 0.448 | 1.133 | 2.528x |
| small-fmt | 2.224 | 3.689 | 1.659x |
| small-fontshow | 3.547 | 8.153 | 2.299x |
| small-nvm | 0.543 | 1.579 | 2.908x |
| small-requests | 1.370 | 2.410 | 1.760x |
| small-tree-sitter-c | 1.699 | 2.639 | 1.553x |
| small-tree-sitter-python | 1.601 | 2.496 | 1.559x |

The warm full-reindex path has moved from failing to consistently completing.
That is sufficient to remove the lifecycle blocker. It is not yet performance
parity: every label remains slower than SQLite on this command, with the worst
absolute delta on `large-llvm-project`.

## Biggest Remaining Slow Paths

The largest latest-DuckDB slowdowns against SQLite are:

| Label | Command | SQLite (s) | Latest DuckDB (s) | DuckDB / SQLite |
|---|---|---:|---:|---:|
| large-cpython | audit | 3.576 | 26.443 | 7.39x |
| large-texlive | audit | 2.491 | 14.987 | 6.02x |
| large-llvm-project | audit | 71.127 | 298.983 | 4.20x |
| small-nvm | index_full | 0.543 | 1.579 | 2.91x |
| large-postgres | audit | 0.814 | 2.102 | 2.58x |
| small-dataset-json-examples | index_full | 0.448 | 1.133 | 2.53x |
| small-fontshow | index_full | 3.547 | 8.153 | 2.30x |
| large-llvm-project | index_full | 697.225 | 1588.283 | 2.28x |
| medium-official-images | index_full | 0.961 | 2.093 | 2.18x |
| medium-ohmyzsh | index_full | 1.593 | 3.204 | 2.01x |

`audit` is the main remaining query-side concern. `index_full` is now correct
but still slower across the matrix.

## Biggest DuckDB Advantages

The strongest latest-DuckDB advantages against SQLite are:

| Label | Command | SQLite (s) | Latest DuckDB (s) | DuckDB / SQLite |
|---|---|---:|---:|---:|
| large-llvm-project | ctx | 117.310 | 47.109 | 0.40x |
| large-llvm-project | index_incremental | 44.073 | 17.977 | 0.41x |
| large-llvm-project | emb | 95.541 | 45.847 | 0.48x |
| large-llvm-project | symlist | 68.060 | 39.624 | 0.58x |
| large-llvm-project | calls | 64.993 | 39.264 | 0.60x |
| large-texlive | ctx | 17.669 | 10.769 | 0.61x |
| large-cpython | ctx | 14.652 | 9.611 | 0.66x |
| large-llvm-project | sym | 70.744 | 46.707 | 0.66x |
| large-cpython | emb | 11.287 | 8.087 | 0.72x |
| large-texlive | emb | 10.436 | 7.742 | 0.74x |

These results are important because they align with the expected DuckDB value:
large indexed datasets and query-heavy workflows benefit most from the backend.

## Highlights

1. Correctness blocker fixed.

   The duplicate `symbol_index.stable_id` constraint failure is no longer
   present in the latest campaign. The previous DuckDB campaign had 17 failures,
   all on the warm full-reindex command. The latest DuckDB campaign has zero
   failures.

2. Campaign-level runtime is close to SQLite.

   Latest DuckDB is 1.056x SQLite across all phase totals. On the large workload
   group, it is 1.053x SQLite.

3. Latest DuckDB is stable against previous DuckDB.

   Excluding the corrected failure behavior, the latest campaign is broadly in
   line with the previous DuckDB measurements. Aggregate phase total improved
   slightly, from 10588.167 seconds to 10522.676 seconds.

4. DuckDB keeps the important read/query wins.

   Incremental indexing, context retrieval, symbol lookup, symbol listing,
   semantic lookup, and call graph queries are all faster than SQLite in
   aggregate.

5. Full parity is not complete.

   Warm `index --full` and `audit` remain clear performance follow-ups.

## Remaining Performance Work

The DuckDB backend no longer needs lifecycle correctness work for the measured
warm full-reindex path before broader validation. Performance work remains, but
it is narrower and can be prioritized separately.

Recommended follow-up items:

1. Investigate `audit` on DuckDB.

   This is the largest remaining regression. Aggregate `audit` time is 3.986x
   SQLite, and the worst labels are `large-cpython`, `large-texlive`, and
   `large-llvm-project`. This likely deserves its own targeted profile because
   the regression is command-specific rather than a general backend slowdown.

2. Profile warm `index --full`.

   The path is correct now, but it is 2.023x SQLite in aggregate. The largest
   absolute gap is `large-llvm-project`, where latest DuckDB takes 1588.283
   seconds versus SQLite at 697.225 seconds.

3. Treat small-workload ratios carefully.

   Several small labels have high ratios on `index_full`, but low absolute
   deltas. These are probably less important than the large absolute deltas on
   `large-llvm-project`, `large-texlive`, and `large-cpython`.

4. Preserve the read/query fast paths.

   Any future optimization should avoid regressing the current DuckDB advantages
   on `ctx`, `index_incremental`, `emb`, `symlist`, `calls`, and `sym`.

## Embedding Matrix Decision

Run the embedding matrix now.

Rationale:

- latest DuckDB completes the full campaign with zero failures
- the previous warm full-reindex correctness blocker is gone
- campaign-level runtime is close to SQLite, especially for large workloads
- DuckDB remains faster than SQLite on the read/query commands that matter for
  indexed workflows
- remaining gaps are bounded to `audit` and warm `index --full`, not global
  instability

The correct framing is substantial parity, not complete parity. DuckDB is ready
for the embedding matrix, while `audit` and warm full-reindex performance should
remain tracked as follow-up optimization work.

## Validation Status

No new benchmark campaign was run for this report. The analysis is based on the
existing campaign artifacts listed in the scope section.

Repository checks performed during the analysis session:

- `uv run codira caps --json`
- `uv run codira index`

The local Codira index completed successfully during analysis:

- Indexed: 1
- Reused: 238
- Deleted: 0
- Failed: 0
- Embeddings recomputed: 2
- Embeddings reused: 4021
- Complete: true
