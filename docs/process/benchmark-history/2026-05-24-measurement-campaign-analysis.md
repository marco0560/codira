# Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-24-measurement-campaign-analysis.md`
(SHA-256 `f128aeb11bbf5793b11d589f199eeb3d8ae6ce4fe1934c8365e0c1f2016dc9b9`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/20260502T172501Z` | unavailable historical path |
| `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md` | available |
| `.artifacts/analysis/2026-05-11-cpython-failures-classification.md` | available |
| `.artifacts/analysis/2026-05-16-measurement-campaign-analysis.md` | available |
| `.artifacts/analysis/2026-05-19-measurement-campaign-analysis.md` | available |
| `.artifacts/benchmarks/backend/20260511T151057Z` | available |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-7` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-8` | unavailable historical path |
| `.artifacts/benchmarks/issue-30-short-sqlite-rerun-3` | unavailable historical path |

Resolved directory moves:

- `.artifacts/20260511T151057Z` → `.artifacts/benchmarks/backend/20260511T151057Z`.


Date: 2026-05-24

## Hardware Snapshot

- Host kernel: `Linux verona 6.18.32-p2-gentoo-dist #1 SMP PREEMPT_DYNAMIC Thu May 21 22:02:45 -00 2026 x86_64`
- OS: `Gentoo Linux 2.18`
- CPU: `Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz`
- CPU topology: `1 socket`, `6 physical cores`, `12 logical CPUs`, max reported frequency `4.70 GHz`
- Memory at analysis time: `46 GiB` RAM total, `83 GiB` swap total
- GPU check: `nvidia-smi` failed with `NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.`
- Embedding device environment: `CODIRA_EMBED_DEVICE` was unset
- Embedding device conclusion: current evidence supports CPU-backed embeddings for this analysis

## Source Artifacts

Primary campaign artifacts:

| Campaign | Role | Codira version | Codira commit | Run time |
|---|---|---:|---|---|
| `.artifacts/benchmarks/backend/20260511T151057Z` | earlier DuckDB baseline | `1.23.6.post1.dev1` | `d7c0182b83d0783b8a0a9f01f284c82ef0cacc5c` | `2026-05-11T21:13:46Z` |
| `.artifacts/benchmarks/issue-30-short-sqlite-rerun-3` | current SQLite control | `1.25.0.post1.dev0` | `062f080b525b6df7f76a1426cb22e55ad9d4fa82` | `2026-05-23T20:40:11Z` |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-8` | current DuckDB campaign | `1.25.0.post1.dev0` | `36060425a906fa154779bdd22cc7447823de1fe8` | `2026-05-24T10:07:38Z` |
| `.artifacts/benchmarks/issue-30-short-duckdb-rerun-7` | superseded interrupted DuckDB run | `1.25.0.post1.dev0` | `062f080b525b6df7f76a1426cb22e55ad9d4fa82` | `2026-05-23T23:55:44Z` |

Previous reports examined:

- `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md`
- `.artifacts/analysis/2026-05-16-measurement-campaign-analysis.md`
- `.artifacts/analysis/2026-05-19-measurement-campaign-analysis.md`
- `.artifacts/analysis/2026-05-11-cpython-failures-classification.md`

Notes:

- `issue-30-short-duckdb-rerun-8` replaces rerun 7 as the current DuckDB measurement source because it completed the short campaign after the graph-rebuild fix.
- `issue-30-short-duckdb-rerun-7` completed `small-codira` and `large-cpython index --full`, then failed at `large-cpython` warm index. It is retained only as failure context and is not used for the current DuckDB performance comparison.
- Per-repository `*-index-phases.json` metadata can contain the benchmark target repository commit. The Codira commit for campaign comparison is taken from `campaign-plan.json` or `profile-summary.json`.

## Git History

Between the earlier DuckDB baseline commit and the current DuckDB campaign commit:

```text
d7c0182..3606042
331f352 fix(contracts): harden analyzer and backend typing invariants
e1d5d36 chore(release): 1.23.7 [skip ci]
40c332a feat(config): introduce initial semgrep architecture rules
c162061 feat(config): integrate semgrep into repository validation
91b0c3c feat(config): complete phase 3 semgrep policy integration
54b98c5 feat(config): simplify repo tool runner and coverage reporting
f3ff8cd feat(config): add allowlisted semgrep architecture guardrails
877748d feat(config): route semgrep state through repo tool runner
5e27e10 docs(plugins): add semgrep reuse guidance
4bd8a87 test(config): extend semgrep fixture coverage
24a684b fix(tests): keep wheel discovery build offline-safe
0a0118f fix(dev): resolve semgrep from repo interpreter env
bc71818 feat(dev): integrate semgrep guardrails
fa99dff chore(release): 1.24.0 [skip ci]
9e52022 fix(cli): mark the active backend in plugin reports
a9554f8 chore(release): 1.24.1 [skip ci]
cc500ee refactor(contracts): lift embedding row models out of sqlite support
edac62d refactor(query): type backend-agnostic core query connections
832e036 refactor(backend): move sqlite helper ownership behind package boundary
6e0c86a refactor(backend): localize duckdb persistence helpers
75c3b44 refactor(backend): localize duckdb compatible query surface
5ad3c5c refactor(backend): remove core sqlite helper shim
f5eab57 refactor(backend): benchmark the active backend helper path
1564491 refactor(backend): type duckdb compatibility connections agnostically
d175227 refactor(backend): widen duckdb compatibility connection typing
62f5d8c refactor(backend): localize sqlite bootstrap entrypoints
1429236 refactor(backend): guard plugin storage imports locally
b8d5e91 refactor(backend): route sqlite setup through plugin seams
cac3fa0 docs(backend): align storage boundary documentation
155d5b0 refactor(query): remove legacy docstrings compatibility lookup
3e7bd9c refactor(backend): localize duckdb repo storage paths
0d37879 docs(backend): retire resolved core-query transition note
934eb41 refactor(backend): drop dead duckdb sqlite bootstrap fallback
4036584 refactor(backend): remove stale duckdb compat file
ceb56b4 refactor(backend): rename duckdb query mixin surface
2d1528e refactor(backend): remove duckdb sqlite runtime types
0e1e9b5 docs(backend): tighten duckdb sqlite guardrails
8e06b43 docs(backend): remove stale duckdb sqlite wording
8a40fd9 refactor(backend): complete duckdb package migration
55bf94d docs(backend): align duckdb helper docstrings
8b9e8b9 refactor(backend): complete backend-agnostic core migration
2ce1c7f fix(dev): eliminated null-byte artifact that failed github action
d877d44 chore(release): 1.24.2 [skip ci]
195b8ee feat(analyzer): add first-party c++ analyzer
adc67a7 feat(analyzer): merge c++ analyzer branch
13768ec chore(process): close issue 11
27bbcbd chore(release): 1.25.0 [skip ci]
c7c3ff1 feat(backend): refactor index sessions and validation tooling
be2eeea docs(docs): align current docs with backend plugins
062f080 feat(backend): harden backend storage boundaries
3606042 fix(backend): DuckDB now rebuilds derived graph tables
```

Current branch commits after the current DuckDB campaign:

```text
b62d4aa fix(cli): Invalid --path values now fail with a message
```

Interpretation:

- The major software delta from `20260511T151057Z` to the current DuckDB campaign is the backend-agnostic core migration, DuckDB package migration, storage-boundary hardening, index-session refactor, the first-party C++ analyzer, and commit `3606042`.
- The warm-index failure observed in rerun 7 was addressed by commit `3606042`; rerun 8 completed the short DuckDB matrix and has command logs.

## Objective 1: Performance Evolution

### Current SQLite vs current DuckDB rerun 8

Comparable hyperfine measurements: `18`.

| Family | SQLite sum | DuckDB rerun 8 sum | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 1020.985s | 2639.326s | +1618.341s | +158.51% |
| `ctx` | 45.944s | 599.307s | +553.363s | +1204.43% |
| warm `index` | 16.553s | 556.646s | +540.093s | +3262.83% |
| `sym` | 0.197s | 0.385s | +0.189s | +95.97% |
| `audit` | 0.194s | 0.256s | +0.062s | +31.65% |
| `calls` | 0.195s | 0.248s | +0.053s | +27.24% |
| `symlist` | 0.213s | 0.264s | +0.052s | +24.32% |
| `emb` | 4.993s | 4.980s | -0.013s | -0.27% |

Largest current deltas:

| Benchmark | SQLite | DuckDB rerun 8 | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython index --full` | 803.801s | 2223.492s | +1419.692s | +176.62% |
| `large-cpython ctx email-unpack` | 34.522s | 588.214s | +553.691s | +1603.86% |
| `large-cpython warm index` | 15.596s | 555.211s | +539.615s | +3460.00% |
| `medium-redis index --full` | 172.630s | 334.436s | +161.807s | +93.73% |
| `small-codira index --full` | 44.555s | 81.398s | +36.843s | +82.69% |
| `medium-redis warm index` | 0.727s | 1.038s | +0.310s | +42.66% |
| `small-codira sym build_parser` | 0.197s | 0.385s | +0.189s | +95.97% |
| `small-codira ctx build parser` | 5.366s | 5.188s | -0.179s | -3.33% |
| `medium-redis ctx hdr histogram` | 6.055s | 5.905s | -0.150s | -2.47% |

Conclusion:

- Rerun 8 completed the short campaign and confirms that the graph-rebuild fix removed the rerun 7 campaign failure.
- DuckDB is improved enough to complete the benchmark, but it is not performance-competitive with SQLite on the short campaign.
- The largest remaining regression is `large-cpython` warm index and `ctx`, where DuckDB spends about `555s` to refresh before query execution.

Phase-level evidence:

| Repository | Phase | SQLite | DuckDB rerun 8 | Absolute delta | Delta % |
|---|---|---:|---:|---:|---:|
| `large-cpython` | `indexing` | 730.355s | 2148.316s | +1417.961s | +194.14% |
| `large-cpython` | `total` | 782.645s | 2216.589s | +1433.945s | +183.22% |
| `large-cpython` | `embeddings` | 1409.045s | 1623.258s | +214.213s | +15.20% |
| `medium-redis` | `indexing` | 164.431s | 326.836s | +162.405s | +98.77% |
| `medium-redis` | `total` | 168.880s | 333.777s | +164.897s | +97.64% |
| `medium-redis` | `embeddings` | 322.278s | 351.825s | +29.547s | +9.17% |
| `small-codira` | `indexing` | 40.522s | 78.875s | +38.353s | +94.65% |
| `small-codira` | `total` | 42.368s | 82.330s | +39.962s | +94.32% |
| `small-codira` | `embeddings` | 79.352s | 84.695s | +5.343s | +6.73% |

Storage size:

| Repository | SQLite index | DuckDB rerun 8 index | Observation |
|---|---:|---:|---|
| `small-codira` | 20M | 22M | DuckDB is slightly larger |
| `medium-redis` | 84M | 67M | DuckDB is smaller |
| `large-cpython` | 740M | 505M | DuckDB is smaller |

### Earlier DuckDB baseline vs current DuckDB

Comparable hyperfine measurements against rerun 8: `13`.

| Family | `20260511T151057Z` DuckDB | DuckDB rerun 8 | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 8232.385s | 2639.326s | -5593.058s | -67.94% |
| warm `index` | 1593.516s | 556.646s | -1036.871s | -65.07% |
| `ctx` | 6.753s | 5.905s | -0.847s | -12.55% |
| `symlist` | 0.383s | 0.264s | -0.118s | -30.93% |
| `audit` | 0.295s | 0.256s | -0.039s | -13.15% |

Largest improvements:

| Benchmark | `20260511T151057Z` | DuckDB rerun 8 | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython index --full` | 7166.569s | 2223.492s | -4943.077s | -68.97% |
| `large-cpython warm index` | 1406.628s | 555.211s | -851.417s | -60.53% |
| `medium-redis index --full` | 887.202s | 334.436s | -552.766s | -62.30% |
| `medium-redis warm index` | 148.840s | 1.038s | -147.803s | -99.30% |
| `small-codira index --full` | 178.613s | 81.398s | -97.215s | -54.43% |
| `small-codira warm index` | 38.048s | 0.397s | -37.651s | -98.96% |

Phase-level improvement:

| Repository | Phase | `20260511T151057Z` | Rerun 8 | Absolute delta | Delta % |
|---|---|---:|---:|---:|---:|
| `large-cpython` | `indexing` | 6851.452s | 2148.316s | -4703.136s | -68.64% |
| `large-cpython` | `total` | 6909.322s | 2216.589s | -4692.733s | -67.92% |
| `large-cpython` | `embeddings` | 2096.966s | 1623.258s | -473.708s | -22.59% |
| `small-codira` | `indexing` | 190.873s | 78.875s | -111.998s | -58.67% |
| `small-codira` | `total` | 193.672s | 82.330s | -111.342s | -57.49% |

Conclusion:

- DuckDB improved materially since `20260511T151057Z`.
- The improvement is large, but it starts from a severe regression and remains far behind SQLite on the current short benchmark.

### SQLite evolution since the earlier reports

Current SQLite rerun 3 compared with `.artifacts/20260502T172501Z` on matched short-campaign commands:

| Family | 20260502 SQLite | Current SQLite | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 1232.721s | 1020.985s | -211.736s | -17.18% |
| warm `index` | 8.737s | 16.553s | +7.816s | +89.46% |
| `ctx` | 6.812s | 6.055s | -0.757s | -11.11% |
| `symlist` | 0.198s | 0.213s | +0.015s | +7.47% |
| `audit` | 0.184s | 0.194s | +0.010s | +5.69% |

Largest SQLite changes:

| Benchmark | 20260502 SQLite | Current SQLite | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython index --full` | 992.861s | 803.801s | -189.060s | -19.04% |
| `medium-redis index --full` | 201.274s | 172.630s | -28.645s | -14.23% |
| `large-cpython warm index` | 7.158s | 15.596s | +8.438s | +117.88% |
| `small-codira index --full` | 38.587s | 44.555s | +5.969s | +15.47% |
| `medium-redis ctx hdr histogram` | 6.812s | 6.055s | -0.757s | -11.11% |

Conclusion:

- SQLite full indexing improved substantially on `large-cpython` and `medium-redis`.
- SQLite warm indexing regressed on `large-cpython`.
- The current branch therefore contains both real improvements and a warm-index regression that should remain visible in future benchmark gates.

## Objective 2: Merge Readiness And Hotspots

Merge-readiness judgment:

- The current branch is not ready to merge as a performance-complete resolution of issue `#30`.
- Correctness evidence improved in the current DuckDB campaign: commit `3606042` fixed the graph-rebuild failure, and rerun 8 completed the short DuckDB campaign.
- Performance evidence is still not acceptable for a branch whose open issue is "make DuckDB native-fast": rerun 8 remains `+158.51%` slower than SQLite in aggregate full indexing, `+3262.83%` slower in aggregate warm indexing, and `+1204.43%` slower in aggregate `ctx`.
- The branch may be close on functional parity, but the measured performance target is not met.

Hotspots in requested importance order:

1. Warm index on DuckDB

Evidence:

- Rerun 8 `large-cpython warm index`: SQLite `15.596s`, DuckDB `555.211s`, delta `+539.615s`, `+3460.00%`.
- Rerun 8 `medium-redis warm index`: SQLite `0.727s`, DuckDB `1.038s`, delta `+0.310s`, `+42.66%`.
- Rerun 8 `small-codira warm index`: SQLite `0.230s`, DuckDB `0.397s`, delta `+0.167s`, `+72.77%`.
- The `large-cpython` result is the dominant current performance blocker.

Sensitive code areas:

- `src/codira/cli.py::_ensure_index`
- `src/codira/cli.py::_run_locked_index_refresh`
- `src/codira/indexer.py::index_repo`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_query_backend.py`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_support.py`

2. `ctx` on DuckDB

Evidence:

- Rerun 8 `large-cpython ctx`: SQLite `34.522s`, DuckDB `588.214s`, delta `+553.691s`, `+1603.86%`.
- Rerun 8 `small-codira ctx`: SQLite `5.366s`, DuckDB `5.188s`, delta `-0.179s`, `-3.33%`.
- Rerun 8 `medium-redis ctx`: SQLite `6.055s`, DuckDB `5.905s`, delta `-0.150s`, `-2.47%`.
- The `ctx` regression is therefore not generic across all repos. It is currently dominated by `large-cpython`.

Profile evidence:

- `large-cpython-ctx.prof`: `_find_and_load` consumed `982.180s`, `_find_spec` consumed `866.455s`, and external `find_spec` consumed `795.591s`.

Conclusion:

- The `large-cpython ctx` result is approximately the same size as the `large-cpython warm index` result, so the first hypothesis to test is that `ctx` is paying a warm-index refresh or backend-maintenance cost before retrieval.
- The import-system profile evidence is a concrete symptom, but the current artifacts do not prove whether its root cause is DuckDB driver behavior, backend/plugin lifecycle churn, or third-party ML/runtime behavior.

Sensitive code areas:

- `src/codira/cli.py::_ensure_index`
- `src/codira/query/context.py`
- `src/codira/query/producers.py`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_query_backend.py`

3. Warm index on SQLite

Evidence:

- Current SQLite `large-cpython warm index`: `15.596s`.
- `.artifacts/20260502T172501Z` SQLite `large-cpython warm index`: `7.158s`.
- Absolute delta: `+8.438s`.
- Delta percentage: `+117.88%`.
- Current SQLite `medium-redis warm index` improved from `1.173s` to `0.727s`, delta `-0.446s`, `-37.98%`.
- Current SQLite `small-codira warm index` improved from `0.406s` to `0.230s`, delta `-0.177s`, `-43.46%`.

Conclusion:

- The SQLite warm-index regression is specific to `large-cpython` in the matched evidence, not a uniform SQLite regression.
- It is still important because SQLite is the control backend and `large-cpython` is the largest short-campaign workload.

Sensitive code areas:

- `src/codira/indexer.py::index_repo`
- `src/codira/indexer.py::_load_existing_index_state`
- `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`
- `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_support.py`

4. Full index on DuckDB

Evidence from rerun 8 profiles:

- `large-cpython-index.prof`: `<frozen importlib._bootstrap>:_find_spec` consumed `2220.412s` cumulative across `10,295,969` calls.
- `large-cpython-index.prof`: `<frozen importlib._bootstrap_external>:find_spec` consumed `1998.734s`.
- `large-cpython-ctx.prof`: `_find_and_load` consumed `982.180s`, `_find_spec` consumed `866.455s`, and external `find_spec` consumed `795.591s`.
- `medium-redis-index.prof`: `_find_spec` consumed `264.102s`.
- `small-codira-index.prof`: `_find_spec` consumed `60.737s`.

Conclusion:

- This is the top currently measured CPU sink in DuckDB profiles.
- The evidence does not prove from profiles alone whether the repeated import probes are caused by DuckDB driver behavior, Torch/Transformers behavior under the current call pattern, or backend/plugin lifecycle churn. It proves the symptom and where to investigate.

Full-index timing evidence:

- Rerun 8 `large-cpython index --full`: SQLite `803.801s`, DuckDB `2223.492s`, delta `+1419.692s`, `+176.62%`.
- Rerun 8 phase `large-cpython indexing`: SQLite rerun 3 `730.355s`, DuckDB rerun 8 `2148.316s`, delta about `+1417.961s`.
- Rerun 8 `medium-redis index --full`: SQLite `172.630s`, DuckDB `334.436s`, delta `+161.807s`, `+93.73%`.

Sensitive code areas:

- DuckDB write-session lifecycle and `_store_analysis`
- DuckDB graph and reference rebuild functions
- typed bulk ingestion boundaries planned in issue `#30`

5. Cross-file embedding batching for both DuckDB and SQLite

Evidence:

- Rerun 8 `large-cpython` phase `embeddings`: `1623.258s`.
- Rerun 8 `medium-redis` phase `embeddings`: `351.825s`.
- Rerun 8 `small-codira` phase `embeddings`: `84.695s`.
- SQLite rerun 3 `large-cpython-index.prof` is dominated by `embed_texts`, `model.encode`, and Torch/Transformers execution.

Conclusion:

- Cross-file embedding batching is backend-agnostic and should be tracked as a separate performance issue applying to both DuckDB and SQLite.
- It should not be mixed into issue `#30`, because issue `#30` is the deterministic backend contract and native DuckDB performance work.

6. Small query surfaces under DuckDB

Evidence:

- Rerun 8 `small-codira sym`: SQLite `0.197s`, DuckDB `0.385s`, delta `+0.189s`, `+95.97%`.
- Rerun 8 `small-codira audit`: SQLite `0.194s`, DuckDB `0.256s`, delta `+0.062s`, `+31.65%`.
- Rerun 8 `small-codira calls`: SQLite `0.195s`, DuckDB `0.248s`, delta `+0.053s`, `+27.24%`.
- Rerun 8 `small-codira symlist`: SQLite `0.213s`, DuckDB `0.264s`, delta `+0.052s`, `+24.32%`.

Conclusion:

- These are not the largest absolute losses.
- They are still user-facing interactive commands and should remain protected by a regression budget.

7. JSON analyzer double-load path

Decision from previous report:

- The 2026-05-19 report measured the accepted-file double-load idea and rejected it for the measured `cldr-json` corpus: only `50` files were accepted and `analyze_file()` across accepted files took about `0.005s` total.
- There is no new measurement in the current artifacts invalidating that decision.

Conclusion:

- Do not reopen this optimization now.

## Objective 3: Performance Enhancement Plan

The estimates below are bounded by measured deltas in the current artifacts. They are planning estimates, not guaranteed outcomes.

1. Fix DuckDB warm-index refresh first.

   Target:

   - eliminate the `large-cpython` DuckDB warm-index delta of `+539.615s`
   - ensure `ctx` does not pay writer setup, schema repair, graph rebuild, or maintenance unless needed

   Expected gain:

   - up to about `540s` on `large-cpython warm index`
   - likely similar order of gain on `large-cpython ctx` if the `ctx` regression is caused by the same refresh path

   Refactor weight:

   - high, but already inside open issue `#30`

2. Fix DuckDB `ctx` after the warm-index path is understood.

   Target:

   - reduce `large-cpython ctx` from `588.214s` toward the SQLite control time of `34.522s`
   - isolate how much of that delta is pre-query index refresh and how much is retrieval/query execution

   Required first step:

   - run one focused profile that separates `_ensure_index`, backend maintenance, embedding query work, and DuckDB query execution.

   Expected gain:

   - up to about `554s` on `large-cpython ctx` if the warm-refresh cost is the dominant cause
   - smaller but still significant gain if only part of the import-system profile is avoidable

   Refactor weight:

   - unknown until caller isolation; likely medium if lifecycle/cache related

3. Investigate and fix SQLite warm-index regression on `large-cpython`.

   Target:

   - recover the `+8.438s`, `+117.88%` regression against `.artifacts/20260502T172501Z`
   - keep the SQLite backend as the control path for future backend work

   Expected gain:

   - about `8s` on `large-cpython warm index`
   - larger process value because it prevents accepting backend-agnostic regressions in the control backend

   Refactor weight:

   - low to medium after profiling, assuming the regression is in incremental-state loading or maintenance checks

4. Optimize DuckDB `index --full` after warm-index and `ctx`.

   Target:

   - reduce `large-cpython index --full` delta of `+1419.692s`, `+176.62%`
   - reduce `medium-redis index --full` delta of `+161.807s`, `+93.73%`
   - reduce `small-codira index --full` delta of `+36.843s`, `+82.69%`

   Expected gain:

   - up to about `1,400s` on `large-cpython index --full` if the remaining DuckDB persistence overhead is eliminated
   - about `160s` on `medium-redis index --full`

   Refactor weight:

   - high, already inside open issue `#30`

5. Track cross-file embedding batching as a separate DuckDB and SQLite performance issue.

   Target:

   - reduce the thousands of per-file `embed_texts()` and `model.encode()` calls visible in profiles
   - preserve deterministic persistence and failure accounting for both SQLite and DuckDB

   Expected gain:

   - plausible `10%` to `25%` on full indexing where embedding model calls dominate
   - applies to both first-party backends

   Refactor weight:

   - medium to high, because current persistence is file-oriented and failure semantics must remain deterministic

## Objective 4: Roadmap Cross-Reference And New Immediate Actions

Snapshot status:

- `issues.json` exists and parses successfully.
- `milestones.json` exists and parses successfully.
- `issues.totalCount`: `16`
- `issues.pageInfo.hasNextPage`: `false`
- `milestones.totalCount`: `5`
- `milestones.pageInfo.hasNextPage`: `false`
- Nested milestone issue lists all reported `hasNextPage: false`.

Issue mapping:

| Performance point | Existing issue relation | Status |
|---|---|---|
| DuckDB native-fast write and refresh path | `#30 perf(backend): clarify backend contract and make DuckDB native-fast` | open, Phase 1 |
| typed bulk ingestion and backend contract redesign | `#30` | open, Phase 1 |
| keep query commands cheap and avoid writer setup on read commands | `#30` | open, Phase 1 |
| optional vector database for semantic retrieval | `#20 Feature: Introduce Optional Vector Database Backend for Semantic Retrieval` | open, Phase 5 |
| daemon/background indexing | `#22 Feature: Daemon Mode for Incremental File Watching and Automatic Reindexing` | open, Phase 5 |

Closed-issue check:

- `#10 Enable immediate support for multiple production-grade backends` is closed in `milestones.json`.
- `git log --grep` finds issue-10-related commits including `d2a1fc6 docs(process): bootstrap issue 10 duckdb ledger`, `8d91b05 docs(process): record issue 10 phase 1 audit`, `2193b60 fix(backend): replace DuckDB savepoints with shared transactions`, and `a46a9db fix(backend): restore DuckDB parity with SQLite index behavior`.
- Current performance work is tracked by open issue `#30`, so no GitHub fetch was needed to establish the active perimeter.

Actions related to existing issues and therefore excluded from the "new immediate" list:

- DuckDB native-fast contract and writer work: issue `#30`
- vector-native semantic retrieval: issue `#20`
- daemon or long-lived indexing process: issue `#22`

New immediate performance actions not already covered by the visible open issues:

1. Implement cross-file embedding batching as a separate DuckDB and SQLite performance issue.

   Rationale:

   - Existing issues cover vector retrieval, daemon mode, and DuckDB native writing.
   - No open issue in the snapshot directly covers changing the indexer from per-file embedding calls to a deterministic cross-file embedding batch stage for both SQLite and DuckDB.
   - Current profiles show thousands of `embed_texts()` / `model.encode()` calls during full indexing.

   Detailed plan:

   1. Add a new issue for deterministic cross-file embedding batching across both first-party backends.
   2. Define invariants before code changes:
      - same stored embedding rows as the current per-file path
      - same `embeddings_recomputed` and `embeddings_reused` accounting
      - same failed-file exclusion behavior
      - no backend-specific semantic change
   3. Add a benchmark fixture or focused test that indexes multiple files with repeated and unique texts and verifies row parity.
   4. Change the indexer to collect embedding work for the changed-file set before persistence.
   5. Batch calls to the embedding backend with deterministic ordering.
   6. Pass computed embeddings into backend persistence without forcing each backend to call `embed_texts()` per file.
   7. Benchmark at least `small-codira`, `medium-redis`, and `large-cpython` against SQLite and DuckDB.

   Expected gain:

   - likely `10%` to `25%` on full indexing where embedding runtime dominates
   - possible larger gain if the importlib probe pattern is partly caused by repeated model encode boundaries

   Risk:

   - medium/high; failure isolation and deterministic accounting must be proven by tests.

2. Add a SQLite warm-index regression gate.

   Rationale:

   - Current SQLite improved on full indexing but regressed on `large-cpython` warm index by `+8.438s`, `+117.88%` versus `.artifacts/20260502T172501Z`.
   - The open issue list does not contain a dedicated SQLite control-backend regression gate.

   Detailed plan:

   1. Add threshold metadata to the benchmark reporting script or campaign comparison tooling.
   2. Start with warning thresholds:
      - warm index: `>10%` and `>0.25s`
      - `ctx`: `>5%` and `>1s`
      - interactive commands: `>10%`
   3. Keep the gate advisory until two more campaigns confirm stability.
   4. Promote to a hard gate only after thresholds are calibrated against repeated local runs.

   Expected gain:

   - no direct runtime gain
   - immediate process gain: prevents backend-contract work from hiding SQLite regressions.

   Risk:

   - low; this is tooling and reporting, not runtime behavior.

Discarded action not reopened:

- JSON accepted-file parse reuse remains excluded. The previous report measured it and found no meaningful gain on the measured corpus; current artifacts add no new contrary evidence.

## Final Conclusion

- The DuckDB backend is much better than the `.artifacts/benchmarks/backend/20260511T151057Z` baseline.
- The current branch is not performance-ready for merge as the completion of issue `#30`.
- The graph-rebuild failure is fixed by commit `3606042`, and rerun 8 completed, but performance remains dominated by DuckDB warm refresh, DuckDB full-index persistence, and repeated import-system work.
- On the current hardware, there is still significant software-side performance headroom. The evidence does not support a "no significant gain possible on this hardware" conclusion.
- Heavy refactoring remains justified for two areas: DuckDB native persistence/refresh under issue `#30`, and cross-file embedding batching as a new issue.
