# Issue 30 Post-Step4 Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-28-issue-30-post-step4-campaign-analysis.md`
(SHA-256 `014353e57bc12f5ed0f1a10e2d1b3b9c638e16b9a4439b6d58b2c2e92fcdfffe`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks` | available |
| `.artifacts/benchmarks/issue-30-short-duckdb-post-step4-1` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-9` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-sqlite-post-step4-1` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-sqlite-rerun-4` | unavailable historical path |
| `benchmarks/performance/short_benchmark.local.json` | available |
| `benchmarks/performance/short_bk-new.local.json` | available |

Resolved directory moves:

- `benchmarks/short_benchmark.local.json` → `benchmarks/performance/short_benchmark.local.json`.
- `benchmarks/short_bk-new.local.json` → `benchmarks/performance/short_bk-new.local.json`.


Date: 2026-05-28

## Compared Artifacts

- Current SQLite: `.artifacts/benchmarks/issue-30-short-sqlite-post-step4-1`
- Current DuckDB: `.artifacts/benchmarks/issue-30-short-duckdb-post-step4-1`
- Previous SQLite control: `.artifacts/benchmarks/issue-30-short-sqlite-rerun-4`
- Previous DuckDB control: `.artifacts/benchmarks/issue-30-short-duckdb-rerun-9`

## Parity Checks

Current SQLite and current DuckDB are direct backend comparators:

| Field | SQLite post-step4 | DuckDB post-step4 |
|---|---|---|
| Codira version | `1.25.0.post1.dev0` | `1.25.0.post1.dev0` |
| Campaign commit | `91825847d419f7bfb667a160ea527133f8a6d94a` | `91825847d419f7bfb667a160ea527133f8a6d94a` |
| Manifest | `benchmarks/performance/short_bk-new.local.json` | `benchmarks/performance/short_bk-new.local.json` |
| Run time | `2026-05-27T16:59:40Z` | `2026-05-27T19:38:10Z` |

Previous SQLite and DuckDB are direct comparators with each other, but not with
the post-step4 pair:

| Field | SQLite rerun-4 | DuckDB rerun-9 |
|---|---|---|
| Codira version | `1.25.0.post1.dev0` | `1.25.0.post1.dev0` |
| Campaign commit | `879689e25a7e3c5077c6d66bfe1a9dbd309f7095` | `879689e25a7e3c5077c6d66bfe1a9dbd309f7095` |
| Manifest | `benchmarks/performance/short_benchmark.local.json` | `benchmarks/performance/short_benchmark.local.json` |
| Run time | `2026-05-25T06:52:32Z` | `2026-05-25T12:06:41Z` |

The current campaign changed commit and manifest. Treat current-vs-previous
backend deltas as branch movement, not pure backend deltas. Current
SQLite-vs-DuckDB deltas are the primary backend comparison.

## Executive Summary

Facts:

- DuckDB full index is now SQLite-class across all three repositories.
- DuckDB `ctx` is now better than SQLite on `large-cpython` and `medium-redis`.
- DuckDB warm index is still consistently slower than SQLite by about 32-47%.
- DuckDB small exact/graph queries improved materially, but still trail SQLite
  by roughly 15-27% on `small-codira`.
- DuckDB `large-cpython audit` is the largest remaining read-side regression:
  `28.840s` vs SQLite `7.434s`, or `+287.9%`.
- SQLite full-index time regressed versus `rerun-4` by 12-20%, driven by higher
  embedding time. DuckDB absorbed that same embedding slowdown but removed its
  old structural-write collapse.

Decision:

- The branch is now much closer to mergeable for the original DuckDB full-index
  issue.
- Issue #30 should remain open if the target includes SQLite warm-index parity
  and read/query parity on large repositories.
- The next focused targets should be DuckDB warm index, `large-cpython audit`,
  and remaining `sym/calls/refs` query overhead.

## Current SQLite vs DuckDB

### small-codira

| Command | SQLite | DuckDB | Delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 47.857s | 47.861s | +0.003s | +0.0% |
| `index` warm | 0.246s | 0.335s | +0.088s | +35.9% |
| `ctx` | 5.134s | 5.278s | +0.144s | +2.8% |
| `help` | 0.126s | 0.122s | -0.004s | -3.5% |
| `cov` | 0.159s | 0.159s | -0.001s | -0.5% |
| `sym` | 0.198s | 0.251s | +0.053s | +26.9% |
| `symlist` | 0.218s | 0.251s | +0.033s | +15.1% |
| `emb` | 4.973s | 5.044s | +0.071s | +1.4% |
| `calls` | 0.198s | 0.246s | +0.047s | +23.9% |
| `audit` | 0.197s | 0.248s | +0.050s | +25.5% |
| `plugins` | 0.174s | 0.175s | +0.001s | +0.8% |
| `caps` | 0.143s | 0.143s | -0.000s | -0.2% |

### medium-redis

| Command | SQLite | DuckDB | Delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 202.256s | 203.241s | +0.985s | +0.5% |
| `index` warm | 0.733s | 0.964s | +0.231s | +31.5% |
| `ctx` | 5.694s | 5.378s | -0.316s | -5.6% |
| `help` | 0.129s | 0.123s | -0.006s | -4.7% |

### large-cpython

| Command | SQLite | DuckDB | Delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 882.679s | 867.621s | -15.058s | -1.7% |
| `index` warm | 1.194s | 1.753s | +0.559s | +46.8% |
| `ctx` | 13.200s | 8.125s | -5.076s | -38.5% |
| `help` | 0.125s | 0.123s | -0.003s | -2.2% |
| `cov` | 0.149s | 0.150s | +0.001s | +0.5% |
| `sym` | 1.827s | 2.892s | +1.065s | +58.3% |
| `symlist` | 2.711s | 2.490s | -0.220s | -8.1% |
| `emb` | 10.317s | 7.865s | -2.452s | -23.8% |
| `calls` | 1.849s | 2.403s | +0.555s | +30.0% |
| `refs` | 1.821s | 2.361s | +0.540s | +29.6% |
| `audit` | 7.434s | 28.840s | +21.406s | +287.9% |
| `plugins` | 0.177s | 0.173s | -0.004s | -2.3% |
| `caps` | 0.144s | 0.143s | -0.001s | -0.6% |

## Backend Movement vs Previous Campaigns

### SQLite Movement

SQLite stayed stable on warm/read operations but full index regressed.

| Workload | Command | rerun-4 | post-step4 | Delta | Delta % |
|---|---|---:|---:|---:|---:|
| small-codira | `index --full` | 40.028s | 47.857s | +7.830s | +19.6% |
| small-codira | `index` warm | 0.239s | 0.246s | +0.007s | +3.1% |
| small-codira | `ctx` | 5.050s | 5.134s | +0.085s | +1.7% |
| small-codira | `sym` | 0.208s | 0.198s | -0.010s | -4.6% |
| small-codira | `emb` | 5.152s | 4.973s | -0.179s | -3.5% |
| medium-redis | `index --full` | 178.041s | 202.256s | +24.216s | +13.6% |
| medium-redis | `index` warm | 0.750s | 0.733s | -0.017s | -2.3% |
| medium-redis | `ctx` | 6.322s | 5.694s | -0.628s | -9.9% |
| large-cpython | `index --full` | 786.770s | 882.679s | +95.909s | +12.2% |
| large-cpython | `index` warm | 1.191s | 1.194s | +0.003s | +0.2% |
| large-cpython | `ctx` | 18.699s | 13.200s | -5.499s | -29.4% |

### DuckDB Movement

DuckDB changed radically. Full index collapse is gone; warm index is slightly
better; `large-cpython ctx` is much better.

| Workload | Command | rerun-9 | post-step4 | Delta | Delta % |
|---|---|---:|---:|---:|---:|
| small-codira | `index --full` | 244.259s | 47.861s | -196.399s | -80.4% |
| small-codira | `index` warm | 0.339s | 0.335s | -0.004s | -1.3% |
| small-codira | `ctx` | 5.239s | 5.278s | +0.039s | +0.7% |
| small-codira | `sym` | 0.398s | 0.251s | -0.147s | -36.9% |
| small-codira | `calls` | 0.266s | 0.246s | -0.021s | -7.7% |
| small-codira | `audit` | 0.264s | 0.248s | -0.017s | -6.3% |
| medium-redis | `index --full` | 1289.932s | 203.241s | -1086.691s | -84.2% |
| medium-redis | `index` warm | 0.998s | 0.964s | -0.034s | -3.5% |
| medium-redis | `ctx` | 5.827s | 5.378s | -0.449s | -7.7% |
| large-cpython | `index --full` | 9446.469s | 867.621s | -8578.848s | -90.8% |
| large-cpython | `index` warm | 1.791s | 1.753s | -0.038s | -2.1% |
| large-cpython | `ctx` | 34.673s | 8.125s | -26.548s | -76.6% |

## Full-Index Phase Evidence

Treat `timings.total` as wall-clock and `timings.embeddings` as diagnostic
cumulative hook time; do not add phase values together.

### small-codira

| Backend/run | Total | Embeddings | Indexing | Parsing | Embedding rows |
|---|---:|---:|---:|---:|---:|
| SQLite post-step4 | 47.282s | 44.021s | 0.713s | 1.417s | 2289 |
| DuckDB post-step4 | 47.387s | 43.187s | 0.388s | 1.444s | 2289 |
| SQLite rerun-4 | 38.435s | 35.915s | 0.685s | 1.409s | 2250 |
| DuckDB rerun-9 | 243.221s | 36.988s | 26.227s | 1.415s | 2250 |

### medium-redis

| Backend/run | Total | Embeddings | Indexing | Parsing | Embedding rows |
|---|---:|---:|---:|---:|---:|
| SQLite post-step4 | 201.248s | 193.527s | 2.740s | 3.180s | 12239 |
| DuckDB post-step4 | 201.855s | 192.257s | 1.227s | 3.187s | 12239 |
| SQLite rerun-4 | 171.514s | 164.139s | 2.720s | 3.164s | 12239 |
| DuckDB rerun-9 | 1281.003s | 165.650s | 118.295s | 3.226s | 12239 |

### large-cpython

| Backend/run | Total | Embeddings | Indexing | Parsing | Embedding rows |
|---|---:|---:|---:|---:|---:|
| SQLite post-step4 | 874.719s | 795.965s | 22.457s | 50.123s | 97782 |
| DuckDB post-step4 | 873.944s | 784.384s | 10.143s | 50.729s | 97782 |
| SQLite rerun-4 | 740.419s | 662.271s | 22.833s | 51.513s | 97782 |
| DuckDB rerun-9 | 9480.109s | 661.233s | 1089.741s | 51.862s | 97782 |

Phase interpretation:

- The DuckDB structural-write rewrite worked. DuckDB indexing phase is now
  lower than SQLite in all current full-index phase files:
  - small: `0.388s` vs SQLite `0.713s`
  - medium: `1.227s` vs SQLite `2.740s`
  - large: `10.143s` vs SQLite `22.457s`
- The old DuckDB failure was structural write/finalization, not embedding
  generation:
  - old large DuckDB indexing phase: `1089.741s`
  - current large DuckDB indexing phase: `10.143s`
- Current full-index wall time is dominated by embedding generation for both
  backends.
- The current full-index regression versus SQLite rerun-4 is shared by both
  backends and tracks embedding phase time, not backend structural writes.

## Remaining Performance Gaps

### Warm Index

Current DuckDB warm index remains behind SQLite:

| Workload | SQLite | DuckDB | Gap |
|---|---:|---:|---:|
| small-codira | 0.246s | 0.335s | +35.9% |
| medium-redis | 0.733s | 0.964s | +31.5% |
| large-cpython | 1.194s | 1.753s | +46.8% |

This is now the clearest index-path target after the full-index fix.

### Context

Current context retrieval is no longer the DuckDB blocker:

| Workload | SQLite | DuckDB | Gap |
|---|---:|---:|---:|
| small-codira | 5.134s | 5.278s | +2.8% |
| medium-redis | 5.694s | 5.378s | -5.6% |
| large-cpython | 13.200s | 8.125s | -38.5% |

The `large-cpython ctx` regression from `rerun-9` is fixed in this campaign.

### Read-Side Query Gaps

Current DuckDB still trails SQLite on several large read commands:

| Command | SQLite large | DuckDB large | Gap |
|---|---:|---:|---:|
| `sym` | 1.827s | 2.892s | +58.3% |
| `calls` | 1.849s | 2.403s | +30.0% |
| `refs` | 1.821s | 2.361s | +29.6% |
| `audit` | 7.434s | 28.840s | +287.9% |

The `audit` gap is the outlier and should be investigated before broad query
micro-optimization.

## Interpretation

Confirmed:

- The branch achieved the main DuckDB full-index goal. Current full index is
  within `+0.5%` on medium, equal on small, and `1.7%` faster on large.
- The previous suspicion that fixing one path caused another large DuckDB hit
  is not confirmed by this pair. DuckDB improved full index, large `ctx`, and
  small `sym/calls/audit` together.
- The shared full-index slowdown versus previous SQLite is embedding-side and
  affects both backends.

Not confirmed:

- The default embedding batch-size increase did not show a full-index win in
  this campaign. Current embedding phase is slower than rerun-4/rerun-9 for
  the same large and medium embedding row counts.

No-go / follow-up:

- Do not close issue #30 if the target remains "close to SQLite warm index and
  large read workloads".
- Next work should be ordered:
  1. DuckDB `large-cpython audit`.
  2. DuckDB warm-index freshness/maintenance path.
  3. DuckDB large `sym/calls/refs`.
  4. Embedding runtime regression analysis across both backends.

## Validation Status

This report is based only on persisted artifacts under:

- `.artifacts/benchmarks/issue-30-short-sqlite-post-step4-1`
- `.artifacts/benchmarks/issue-30-short-duckdb-post-step4-1`
- `.artifacts/benchmarks/issue-30-short-sqlite-rerun-4`
- `.artifacts/benchmarks/issue-30-short-duckdb-rerun-9`

Commands used for report generation:

```text
find .artifacts/benchmarks -maxdepth 2 -type f
python JSON extraction over campaign-plan.json, *-hyperfine.json, and *-index-phases.json
```
