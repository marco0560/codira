# Codira benchmark analysis: 2026-06-06 pair vs 2026-06-04 pair

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-07-bk-cpp-latest-pair-analysis.md`
(SHA-256 `396dafa28dddb03a58e1b2b09140a68ddff428d4d658c9fb3a8c51c5927c94fd`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite` | available |

Resolved directory moves:

- `.artifacts/20260604T204054Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb`.
- `.artifacts/20260604T204054Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite`.
- `.artifacts/20260606T145144Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb`.
- `.artifacts/20260606T145144Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`.


Generated: 2026-06-07

## Scope

This report compares the latest paired benchmark runs against the preceding paired runs:

- latest SQLite: `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`
- latest DuckDB: `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb`
- previous SQLite: `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite`
- previous DuckDB: `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb`

The comparison uses `*-index-phases.json` artifacts. Hyperfine JSON is not available for the latest pair because every Hyperfine command failed before measurement.

Per the benchmark-analysis contract, `timings.total` is treated as wall-clock. Other timing fields are diagnostic phase timers and are not added together to reconstruct total time.

## Parity and run status

| Run | Path | Phase files | Codira version | Codira commit | Failure count | Device | Batch | Torch threads | Interop threads |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: |
| latest SQLite | `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite` | 17 | `1.43.2` | `771dc7f629cebbf3afe2305bcf697b63a208dd59` | 17 | `cpu` | 128 | 6 | 6 |
| latest DuckDB | `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-duckdb` | 17 | `1.43.2` | `771dc7f629cebbf3afe2305bcf697b63a208dd59` | 17 | `cpu` | 128 | 6 | 6 |
| previous SQLite | `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite` | 17 | `1.42.3.post1.dev12` | `d08e59ea3fc141071d7985662207119b084903a6` | 0 | `cpu` | 128 | 6 | 6 |
| previous DuckDB | `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb` | 15 | `1.43.0.post1.dev1` | `cf689bc656ca98b62893ec3a7ba6867ed51ac7de` | 6 | `cpu` | 128 | 6 | 6 |

Notes:

- The latest SQLite and DuckDB pair has matching Codira version/commit and matching embedding runtime settings, so backend-to-backend comparison is usable.
- The previous SQLite and previous DuckDB runs were not the same Codira revision. Use previous-to-latest comparisons as trend signals, not clean backend attribution.
- The previous DuckDB run emitted only 15 phase files because `large-texlive` and `large-llvm-project` failed before phase JSON was persisted. Its previous-to-latest comparison is therefore restricted to those same 15 labels.
- Phase JSON `metadata.git_commit` varies by target repository and is not the Codira commit; Codira revision is taken from `campaign-plan.json` and `failure-summary.json` metadata.

## Why the latest runs finished non-zero

Both latest runs have `failure_count = 17`, one per repository label. Representative logs show Hyperfine failed before executing measurements:

```text
error: the argument '--style <TYPE>' cannot be used with '--show-output'
```

The failed command slot is the Hyperfine slot in each repository plan. This is a campaign-runner/tool-version incompatibility, not an indexing/backend failure. The index phase JSON files were already produced for all 17 repositories in both latest runs, so phase-timing analysis remains usable while Hyperfine timing and profile comparisons are not.

## Backend comparison in the latest run

### Latest DuckDB minus latest SQLite

Label set: 17 repositories.

| Metric | DuckDB latest | SQLite latest | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `total` | 10,260.638s | 10,114.514s | +146.124s | +1.44% |
| `embeddings` | 9,508.927s | 9,446.240s | +62.687s | +0.66% |
| `parsing` | 340.093s | 341.141s | -1.048s | -0.31% |
| `indexing` | 228.136s | 366.882s | -138.746s | -37.82% |
| `discovery` | 19.411s | 19.220s | +0.191s | +1.00% |
| `filtering` | 8.732s | 8.479s | +0.253s | +2.99% |
| `scan_state` | 31.429s | 27.830s | +3.599s | +12.93% |
| `metadata` | 7.605s | 4.474s | +3.131s | +69.99% |

- DuckDB latest: embeddings 92.67% of total, parsing 3.31% of total, perfect parsing-removal ceiling 3.43%.
- SQLite latest: embeddings 93.39% of total, parsing 3.37% of total, perfect parsing-removal ceiling 3.49%.

### Latest DuckDB minus latest SQLite: counters

Label set: 17 repositories.

| Metric | DuckDB latest | SQLite latest | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `indexed` | 92,731 | 92,731 | +0 | +0.00% |
| `failed` | 82 | 82 | +0 | +0.00% |
| `embeddings_recomputed` | 956,254 | 956,254 | +0 | +0.00% |
| `embeddings_reused` | 0 | 0 | +0 | n/a |

- DuckDB latest: embeddings 92.67% of total, parsing 3.31% of total, perfect parsing-removal ceiling 3.43%.
- SQLite latest: embeddings 93.39% of total, parsing 3.37% of total, perfect parsing-removal ceiling 3.49%.

### Latest DuckDB minus latest SQLite: embedding batches

Label set: 17 repositories.

| Metric | DuckDB latest | SQLite latest | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `calls` | 17 | 17 | +0 | +0.00% |
| `total_rows` | 952,487 | 952,487 | +0 | +0.00% |
| `unique_rows` | 952,487 | 952,487 | +0 | +0.00% |
| `duplicate_rows` | 0 | 0 | +0 | n/a |

- DuckDB latest: embeddings 92.67% of total, parsing 3.31% of total, perfect parsing-removal ceiling 3.43%.
- SQLite latest: embeddings 93.39% of total, parsing 3.37% of total, perfect parsing-removal ceiling 3.49%.

### Largest `total` deltas: latest DuckDB vs latest SQLite

| Label | DuckDB latest | SQLite latest | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `large-llvm-project` | 6,744.505s | 6,624.256s | +120.249s | +1.82% |
| `large-cpython` | 928.407s | 895.653s | +32.754s | +3.66% |
| `large-texlive` | 1,430.011s | 1,454.751s | -24.740s | -1.70% |
| `medium-redis` | 213.582s | 208.684s | +4.898s | +2.35% |
| `small-codira` | 72.233s | 70.182s | +2.051s | +2.92% |
| `small-fontshow` | 59.873s | 58.253s | +1.621s | +2.78% |
| `medium-catch2` | 29.324s | 27.837s | +1.487s | +5.34% |
| `small-tree-sitter-c` | 15.228s | 13.781s | +1.447s | +10.50% |

## Backend versus previous version

### Latest SQLite minus previous SQLite

Label set: 17 repositories.

| Metric | SQLite latest | SQLite previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `total` | 10,114.514s | 10,273.962s | -159.447s | -1.55% |
| `embeddings` | 9,446.240s | 9,583.519s | -137.279s | -1.43% |
| `parsing` | 341.141s | 358.734s | -17.594s | -4.90% |
| `indexing` | 366.882s | 388.930s | -22.048s | -5.67% |
| `discovery` | 19.220s | 19.208s | +0.012s | +0.06% |
| `filtering` | 8.479s | 8.843s | -0.364s | -4.12% |
| `scan_state` | 27.830s | 27.838s | -0.008s | -0.03% |
| `metadata` | 4.474s | 4.518s | -0.044s | -0.97% |

- SQLite latest: embeddings 93.39% of total, parsing 3.37% of total, perfect parsing-removal ceiling 3.49%.
- SQLite previous: embeddings 93.28% of total, parsing 3.49% of total, perfect parsing-removal ceiling 3.62%.

### Latest SQLite minus previous SQLite: counters

Label set: 17 repositories.

| Metric | SQLite latest | SQLite previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `indexed` | 92,731 | 92,725 | +6 | +0.01% |
| `failed` | 82 | 88 | -6 | -6.82% |
| `embeddings_recomputed` | 956,254 | 956,141 | +113 | +0.01% |
| `embeddings_reused` | 0 | 0 | +0 | n/a |

- SQLite latest: embeddings 93.39% of total, parsing 3.37% of total, perfect parsing-removal ceiling 3.49%.
- SQLite previous: embeddings 93.28% of total, parsing 3.49% of total, perfect parsing-removal ceiling 3.62%.

### Largest `total` deltas: SQLite latest vs previous

| Label | SQLite latest | SQLite previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `large-llvm-project` | 6,624.256s | 6,870.697s | -246.441s | -3.59% |
| `large-texlive` | 1,454.751s | 1,394.977s | +59.774s | +4.28% |
| `large-postgres` | 664.817s | 635.489s | +29.328s | +4.62% |
| `large-cpython` | 895.653s | 908.584s | -12.931s | -1.42% |
| `medium-redis` | 208.684s | 204.922s | +3.762s | +1.84% |
| `small-codira` | 70.182s | 68.899s | +1.284s | +1.86% |
| `medium-catch2` | 27.837s | 26.991s | +0.846s | +3.13% |
| `medium-ohmyzsh` | 21.439s | 20.605s | +0.834s | +4.05% |

### Latest DuckDB minus previous DuckDB, common 15 labels only

Label set: 15 repositories.

| Metric | DuckDB latest | DuckDB previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `total` | 2,086.121s | 2,057.516s | +28.605s | +1.39% |
| `embeddings` | 1,898.312s | 1,871.827s | +26.486s | +1.41% |
| `parsing` | 78.442s | 79.909s | -1.467s | -1.84% |
| `indexing` | 31.327s | 31.135s | +0.192s | +0.62% |
| `discovery` | 6.896s | 6.798s | +0.099s | +1.45% |
| `filtering` | 0.760s | 0.695s | +0.066s | +9.46% |
| `scan_state` | 9.225s | 7.732s | +1.493s | +19.31% |
| `metadata` | 1.868s | 0.572s | +1.296s | +226.41% |

- DuckDB latest: embeddings 91.00% of total, parsing 3.76% of total, perfect parsing-removal ceiling 3.91%.
- DuckDB previous: embeddings 90.98% of total, parsing 3.88% of total, perfect parsing-removal ceiling 4.04%.

### Latest DuckDB minus previous DuckDB, common 15 labels only: counters

Label set: 15 repositories.

| Metric | DuckDB latest | DuckDB previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `indexed` | 8,858 | 8,858 | +0 | +0.00% |
| `failed` | 78 | 78 | +0 | +0.00% |
| `embeddings_recomputed` | 160,841 | 160,828 | +13 | +0.01% |
| `embeddings_reused` | 0 | 0 | +0 | n/a |

- DuckDB latest: embeddings 91.00% of total, parsing 3.76% of total, perfect parsing-removal ceiling 3.91%.
- DuckDB previous: embeddings 90.98% of total, parsing 3.88% of total, perfect parsing-removal ceiling 4.04%.

### Largest `total` deltas: DuckDB latest vs previous, common 15 labels

| Label | DuckDB latest | DuckDB previous | Delta | Delta % |
| --- | ---: | ---: | ---: | ---: |
| `large-cpython` | 928.407s | 908.114s | +20.293s | +2.23% |
| `large-postgres` | 664.074s | 656.895s | +7.179s | +1.09% |
| `large-cldr-json` | 14.654s | 15.204s | -0.550s | -3.62% |
| `medium-catch2` | 29.324s | 28.829s | +0.495s | +1.72% |
| `small-fmt` | 16.780s | 16.300s | +0.479s | +2.94% |
| `small-requests` | 13.056s | 12.675s | +0.381s | +3.01% |
| `small-tree-sitter-python` | 12.266s | 11.899s | +0.367s | +3.08% |
| `small-codira` | 72.233s | 72.593s | -0.359s | -0.49% |

### DuckDB recovered labels

The latest DuckDB run also persisted phase JSON for `large-texlive` and `large-llvm-project`, which were missing in the previous DuckDB run. These two labels add:

| Metric | Latest DuckDB all 17 | Latest DuckDB common 15 | Added by recovered labels |
| --- | ---: | ---: | ---: |
| `total` | 10,260.638s | 2,086.121s | +8,174.517s |
| `embeddings` | 9,508.927s | 1,898.312s | +7,610.614s |
| `parsing` | 340.093s | 78.442s | +261.651s |
| `indexing` | 228.136s | 31.327s | +196.809s |
| `indexed` | 92,731 | 8,858 | +83,873 |
| `failed` | 82 | 78 | +4 |
| `embeddings_recomputed` | 956,254 | 160,841 | +795,413 |

## Does the timing data support issue #57?

Yes. The latest data supports issue #57 more directly than the previous 2026-06-04 data because both latest backends produced phase JSON for all 17 repositories.

- Latest SQLite: embeddings are 93.39% of total wall time; parsing is 3.37%. Removing parsing entirely would have a theoretical ceiling of about 3.49%.
- Latest DuckDB: embeddings are 92.67% of total wall time; parsing is 3.31%. Removing parsing entirely would have a theoretical ceiling of about 3.43%.
- The latest pair recomputed 956,254 embeddings on each backend and generated 952,487 embedding-batch rows. Backend counters are identical, so embedding volume is backend-independent in this run.
- DuckDB diagnostic indexing time is much lower than SQLite on the latest pair (`228.136s` vs `366.882s`, -37.82%), but full wall-clock still differs by only +1.44% in DuckDB because embedding work dominates both runs.

This supports the issue #57 prioritization: tune/reduce/reuse embeddings before expecting large full-index gains from analyzer parallelization or backend write work alone.

## Interpretation

- Latest SQLite improved versus previous SQLite on total wall time by -159.447s (-1.55%). The largest single improvement is `large-llvm-project` at -246.441s (-3.59%), partly offset by `large-texlive` at +59.774s (+4.28%) and `large-postgres` at +29.328s (+4.62%).
- Latest DuckDB worsened versus previous DuckDB on the comparable 15-label set by +28.605s (+1.39%); that delta is almost entirely mirrored in diagnostic embedding time (+26.486s, +1.41%).
- Latest DuckDB versus latest SQLite on all 17 labels is +146.124s (+1.44%) in total wall time. This is small relative to total runtime and does not indicate a large backend-write bottleneck in the phase data.
- Both latest runs are not valid Hyperfine campaigns because Hyperfine failed systematically. They are valid phase-timing runs for full-index indexing behavior.

## Follow-up decisions

- Fix `scripts/benchmark_campaign.py` or its local Hyperfine invocation policy so it does not combine `--style full` with `--show-output` on this Hyperfine version.
- Keep using phase JSON for issue #57 planning, but rerun a clean paired campaign after fixing Hyperfine to recover command-level query timings and profile artifacts.
- For embedding work, prioritize instrumentation that splits generation time from write time and reports encode-call distribution, because the latest phase data again shows embeddings dominate.
