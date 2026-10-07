# Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-16-measurement-campaign-analysis.md`
(SHA-256 `889d1c6b48615376620be390e87b3ae50c3878d3283b4014eadfdc73aba4f60b`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/20260502T172501Z` | unavailable historical path |
| `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md` | available |
| `.artifacts/benchmarks/backend/20260511T151057Z` | available |

Resolved directory moves:

- `.artifacts/20260511T151057Z` → `.artifacts/benchmarks/backend/20260511T151057Z`.


Date: 2026-05-16

## Hardware Snapshot

- Host kernel: `Linux verona 6.18.26-gentoo-dist #1 SMP PREEMPT_DYNAMIC Thu Apr 30 21:44:48 -00 2026 x86_64`
- OS: `Gentoo Linux 2.18`
- CPU: `Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz`
- CPU topology: `1 socket`, `6 physical cores`, `12 logical CPUs`, max reported frequency `4.70 GHz`
- Memory at analysis time: `46 GiB` RAM total, `83 GiB` swap total
- GPU: NVIDIA device is present historically on this host, but `nvidia-smi` failed with: `NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.`
- Embedding device environment: `CODIRA_EMBED_DEVICE` was unset
- Embedding device selection in code: `src/codira/semantic/embeddings.py::_configured_embedding_device()` returns `cpu` when `CODIRA_EMBED_DEVICE` is unset
- Embeddings in this analysis should therefore be treated as CPU-backed

## Compared Campaigns

- Current campaign: `.artifacts/benchmarks/backend/20260511T151057Z`
- Preceding campaign: `.artifacts/20260502T172501Z`
- Previous saved report examined: `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md`

Metadata:

| Campaign | `profile-summary.json` version | `profile-summary.json` commit | Backend evidence |
|---|---:|---|---|
| `.artifacts/20260502T172501Z` | `1.21.7` | `2a5cbaec12ab3d9874257e8f8c34622120828c8f` | SQLite backend plugin only; indexes contain `.codira/index.db` |
| `.artifacts/benchmarks/backend/20260511T151057Z` | `1.23.6.post1.dev1` | `d7c0182b83d0783b8a0a9f01f284c82ef0cacc5c` | DuckDB backend plugin present; indexes contain `.codira/index.duckdb` |

Artifact consistency note:

- The current campaign's `profile-summary.json` records commit `d7c0182b83d0783b8a0a9f01f284c82ef0cacc5c`.
- The current campaign's `*-index-phases.json` files record commit `8066db57535161dda316a70c1b00a89581bf3399`.
- `git show --no-patch 8066db57535161dda316a70c1b00a89581bf3399` fails in the current repository with `fatal: bad object`.
- The git-history comparison in this report therefore uses the commit recorded by `profile-summary.json`, and the bad-object per-file metadata is treated as an artifact inconsistency.

Git history between the compared campaign commits:

- `36` non-merge commits are present from `2a5cbae` to `d7c0182`.
- The relevant changes include the DuckDB backend package and activation path:
  - `d18b0bc feat(backend): scaffold duckdb backend package`
  - `835d2d6 feat(backend): implement duckdb backend lifecycle`
  - `0efb1f8 feat(backend): integrate duckdb activation path`
  - `6a43f8d test(backend): add duckdb integration coverage`
  - `9a7837b test(backend): stabilize duckdb validation surface`
  - `d237fca docs(backend): document duckdb integration`
  - `2193b60 fix(backend): replace DuckDB savepoints with shared transactions`
  - `a46a9db fix(backend): restore DuckDB parity with SQLite index behavior`
- `git diff --stat 2a5cbae..d7c0182` shows `74 files changed`, including `packages/codira-backend-duckdb`, `src/codira/cli.py`, `src/codira/query/exact.py`, `src/codira/sqlite_backend_support.py`, `scripts/benchmark_index.py`, and `uv.lock`.

Measurement note:

- `scripts/benchmark_index.py` records `timings.total` as wall-clock for one index pass.
- `timings.embeddings` is cumulative diagnostic time across embedding hooks and is not additive to `total`.
- Hyperfine means are the primary top-level comparison surface.

## Objective 1: Performance Evolution

Overall result:

- Comparable hyperfine measurements: `51`
- Improved measurements: `7`
- Regressed measurements: `44`
- The current DuckDB campaign is substantially slower than the preceding SQLite campaign for indexing and for operations that trigger or inspect index state.

Aggregate by command family:

| Family | Previous mean sum | Current mean sum | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 3228.280s | 18369.857s | +15141.577s | +469.03% |
| warm `index` | 20.635s | 2681.025s | +2660.391s | +12892.71% |
| `ctx` | 114.001s | 1507.556s | +1393.555s | +1222.40% |
| `sym` | 0.204s | 1.020s | +0.816s | +400.52% |
| `symlist` | 0.198s | 0.383s | +0.185s | +93.44% |
| `audit` | 0.184s | 0.295s | +0.111s | +60.21% |
| `calls` | 0.190s | 0.285s | +0.095s | +50.12% |
| `emb` | 5.733s | 5.863s | +0.130s | +2.27% |
| `caps` | 0.176s | 0.182s | +0.005s | +3.08% |
| `plugins` | 0.178s | 0.181s | +0.003s | +1.64% |
| `cov` | 0.180s | 0.177s | -0.003s | -1.47% |
| `codira help` | 0.148s | 0.149s | +0.000s | +0.22% |

Aggregate by repository:

| Repository | Previous mean sum | Current mean sum | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython` | 1023.966s | 9990.529s | +8966.563s | +875.67% |
| `large-texlive` | 1230.292s | 6566.661s | +5336.369s | +433.75% |
| `large-postgres` | 691.771s | 4055.877s | +3364.107s | +486.30% |
| `medium-redis` | 209.259s | 1042.796s | +833.537s | +398.33% |
| `small-codira` | 51.166s | 230.289s | +179.123s | +350.08% |
| `small-fontshow` | 42.489s | 203.491s | +161.002s | +378.92% |
| `small-tree-sitter-c` | 20.056s | 151.777s | +131.721s | +656.78% |
| `small-tree-sitter-python` | 16.127s | 142.162s | +126.036s | +781.53% |
| `small-requests` | 19.255s | 64.669s | +45.415s | +235.86% |
| `medium-ohmyzsh` | 12.327s | 41.048s | +28.720s | +232.98% |
| `medium-official-images` | 12.759s | 28.254s | +15.495s | +121.44% |
| `small-nvm` | 11.566s | 18.471s | +6.905s | +59.71% |
| `large-cldr-json` | 22.308s | 23.824s | +1.517s | +6.80% |
| `small-dataset-json-examples` | 6.016s | 5.985s | -0.031s | -0.52% |

Largest regressions:

| Benchmark | Previous | Current | Absolute delta | Delta % | Signal |
|---|---:|---:|---:|---:|---:|
| `large-cpython index --full` | 992.861s | 7166.569s | +6173.709s | +621.81% | 40.39 sigma |
| `large-texlive index --full` | 1213.447s | 5993.477s | +4780.030s | +393.92% | 50.91 sigma |
| `large-postgres index --full` | 679.101s | 3578.159s | +2899.058s | +426.90% | 59.17 sigma |
| `large-cpython warm index` | 7.158s | 1406.628s | +1399.470s | +19551.53% | 30.27 sigma |
| `large-cpython ctx` | 23.947s | 1417.332s | +1393.384s | +5818.52% | 28.14 sigma |
| `medium-redis index --full` | 201.274s | 887.202s | +685.928s | +340.79% | 71.93 sigma |
| `large-texlive warm index` | 3.877s | 559.561s | +555.685s | +14334.69% | 34.13 sigma |
| `large-postgres warm index` | 3.410s | 469.131s | +465.721s | +13656.25% | 14.77 sigma |
| `medium-redis warm index` | 1.173s | 148.840s | +147.668s | +12589.17% | 13.53 sigma |
| `small-codira index --full` | 38.587s | 178.613s | +140.026s | +362.89% | 16.92 sigma |

Measured improvements:

| Benchmark | Previous | Current | Absolute delta | Delta % | Signal |
|---|---:|---:|---:|---:|---:|
| `large-cldr-json ctx` | 10.567s | 8.453s | -2.114s | -20.01% | 6.61 sigma |
| `large-postgres ctx` | 9.260s | 8.587s | -0.673s | -7.26% | 2.09 sigma |
| `small-dataset-json-examples ctx` | 5.599s | 5.235s | -0.364s | -6.49% | 1.70 sigma |
| `small-tree-sitter-c ctx` | 5.732s | 5.382s | -0.350s | -6.11% | 1.47 sigma |
| `small-nvm ctx` | 5.435s | 5.282s | -0.153s | -2.81% | 0.72 sigma |
| `medium-redis ctx` | 6.812s | 6.753s | -0.059s | -0.87% | 0.20 sigma |
| `small-codira cov` | 0.180s | 0.177s | -0.003s | -1.47% | 0.18 sigma |

Index phase deltas:

| Phase | Previous | Current | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython total` | 938.897s | 6909.322s | +5970.425s | +635.90% |
| `large-cpython indexing` | 882.683s | 6851.452s | +5968.769s | +676.21% |
| `large-texlive indexing` | 1160.404s | 6036.035s | +4875.631s | +420.17% |
| `large-texlive total` | 1194.427s | 6069.347s | +4874.920s | +408.14% |
| `large-postgres total` | 670.451s | 3564.978s | +2894.527s | +431.73% |
| `large-postgres indexing` | 657.139s | 3550.851s | +2893.712s | +440.35% |
| `medium-redis total` | 196.937s | 909.916s | +712.978s | +362.03% |
| `medium-redis indexing` | 192.638s | 905.261s | +712.623s | +369.93% |
| `large-cpython embeddings` | 1730.891s | 2096.966s | +366.075s | +21.15% |
| `large-texlive embeddings` | 2299.139s | 2633.243s | +334.104s | +14.53% |

Conclusion for Objective 1:

- The current campaign is dominated by a severe DuckDB indexing regression compared with the preceding SQLite campaign.
- The strongest regression is in the measured `indexing` phase, not in parsing, discovery, or scanner filtering.
- CPU embeddings remain expensive in absolute terms, but they do not explain the largest regression: for `large-cpython`, `indexing` regressed by `+5968.769s`, while `embeddings` regressed by `+366.075s`.
- The few improvements are concentrated in selected `ctx` runs and are not large enough to offset the indexing regression.

## Objective 2: Hotspots And Sensitive Areas

Hotspots in importance order:

1. DuckDB persistence/indexing path

Evidence:

- `index --full` regressed by `+15141.577s` aggregate.
- The `indexing` phase alone regressed by:
  - `large-cpython`: `+5968.769s`
  - `large-texlive`: `+4875.631s`
  - `large-postgres`: `+2893.712s`
  - `medium-redis`: `+712.623s`
- Current `large-cpython-index.prof` is dominated by import-system work:
  - `<frozen importlib._bootstrap>:_find_spec`: `6829.405s`, `28869132` calls
  - `<frozen importlib._bootstrap_external>:find_spec`: `6116.494s`, `28869122` calls
  - `<frozen importlib._bootstrap_external>:_get_spec`: `6093.143s`, `28869122` calls
  - `<frozen importlib._bootstrap_external>:find_spec`: `5601.740s`, `346392454` calls
- The preceding SQLite `large-cpython-index.prof` did not have this importlib pattern; its top entries were `_flush_embedding_rows` and `embed_texts`.
- Current `large-cpython` index storage size is `2.8G` for `.codira/index.duckdb` versus `462M` for the preceding SQLite `.codira/index.db`.

Relevant code areas:

- `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBIndexBackend.persist_analysis`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBConnection.execute`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBConnection.executemany`
- `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::_duckdb_lastrowid`
- `src/codira/sqlite_backend_support.py::_flush_embedding_rows`
- `src/codira/sqlite_backend_support.py::_insert_symbol_index_row`

2. DuckDB warm-index and automatic index-refresh path

Evidence:

- Warm `index` regressed by `+2660.391s` aggregate.
- Largest warm-index regressions:
  - `large-cpython`: `+1399.470s`
  - `large-texlive`: `+555.685s`
  - `large-postgres`: `+465.721s`
  - `medium-redis`: `+147.668s`
- `large-cpython ctx` regressed by `+1393.384s`, nearly the same order as `large-cpython warm index`.

Relevant code areas:

- `src/codira/cli.py::_ensure_index`
- `src/codira/cli.py::_run_locked_index_refresh`
- `src/codira/indexer.py::index_repo`
- backend `load_existing_file_hashes()` and runtime inventory paths inherited or adapted by the DuckDB backend

3. CPU embedding inference

Evidence:

- Current full-index embedding diagnostic time remains high:
  - `large-cpython`: `2096.966s`
  - `large-texlive`: `2633.243s`
  - `large-postgres`: `1410.031s`
  - `medium-redis`: `424.420s`
- `CODIRA_EMBED_DEVICE` is unset and `_configured_embedding_device()` defaults to `cpu`.
- `nvidia-smi` cannot communicate with the NVIDIA driver, so GPU acceleration is not available in this environment.

Relevant code areas:

- `src/codira/semantic/embeddings.py::embed_texts`
- `src/codira/semantic/embeddings.py::_configured_embedding_device`
- `src/codira/sqlite_backend_support.py::_flush_embedding_rows`

4. Semantic retrieval and vector scoring

Evidence:

- The preceding report identified SQLite semantic retrieval and Python-side `_dot_similarity` as a large `ctx` hotspot.
- Current DuckDB `large-cpython-ctx.prof` includes:
  - `codira_backend_duckdb.execute`: `9.382s`
  - `src/codira/query/context.py::_retrieve_embedding_candidates`: `9.362s`
  - `src/codira/query/producers.py::retrieve_candidates`: `9.362s`
- This is no longer the largest current regression because the warm-index/refresh path dominates `large-cpython ctx`, but it remains performance-sensitive.

Relevant code areas:

- `src/codira/query/context.py::_retrieve_embedding_candidates`
- `src/codira/query/producers.py::retrieve_candidates`
- backend `embedding_candidates()` implementations

5. Small query surfaces under DuckDB

Evidence:

- `small-codira sym`: `0.204s` to `1.020s`, `+0.816s`, `+400.52%`
- `small-codira symlist`: `0.198s` to `0.383s`, `+0.185s`, `+93.44%`
- `small-codira audit`: `0.184s` to `0.295s`, `+0.111s`, `+60.21%`
- `small-codira calls`: `0.190s` to `0.285s`, `+0.095s`, `+50.12%`

Relevant code areas:

- DuckDB query adapter and inherited SQLite query helpers
- `src/codira/query/exact.py`
- `src/codira/query/graph_enrichment.py`
- backend `docstring_issues`, `symbol_rows`, and graph query methods

6. JSON analyzer acceptance path

Evidence:

- Current `large-cldr-json ctx` improved by `-2.114s` and `-20.01%`.
- Current `large-cldr-json` total aggregate regressed only `+1.517s`, much smaller than Python/C/TeX workloads.
- The preceding report explicitly benchmarked and rejected the accepted-file double-load follow-up because only `50` files were accepted and `analyze_file()` across accepted files took about `0.005s` total.

Conclusion:

- JSON remains content-sensitive, but the previous no-go decision still stands. No new fact in the current campaign invalidates it.

## Objective 3: Performance Enhancement Plan

Assessment on current hardware:

- There is significant performance headroom.
- The dominant current problem is not hardware saturation; it is a DuckDB backend implementation/regression problem.
- Heavy refactoring can produce large gains if DuckDB gets a backend-native persistence path instead of relying on SQLite-shaped compatibility behavior.

Plan in importance order:

1. Make DuckDB full-index persistence backend-native.

Scope:

- Instrument `DuckDBConnection.execute`, `DuckDBConnection.executemany`, `_duckdb_lastrowid`, `DuckDBIndexBackend.persist_analysis`, and shared `_store_analysis` call sites.
- Add a focused DuckDB-vs-SQLite persistence benchmark on a fixed fixture and one medium real corpus.
- Replace row-by-row SQLite-shaped persistence where it dominates with DuckDB-oriented batch inserts.
- Avoid per-row sequence round trips where possible by allocating IDs deterministically or using DuckDB features that return inserted IDs without a separate `currval()` query per row.
- Keep SQLite behavior unchanged.

Expected gain:

- Measured full-index regression upper bound: `+15141.577s` aggregate across the campaign.
- A reasonable first target is reclaiming `50%` to `80%` of the DuckDB-specific indexing overhead after profiling confirms the exact frame-level cause.
- On the largest measured workloads, that corresponds to approximate savings of:
  - `large-cpython`: `3000s` to `4800s`
  - `large-texlive`: `2400s` to `3900s`
  - `large-postgres`: `1400s` to `2300s`

Risk:

- This is a medium-to-heavy backend refactor because it touches persistence semantics and must preserve deterministic row identity and query parity.

2. Fix DuckDB warm-index and `ctx` refresh regressions.

Scope:

- Profile warm `codira index` separately from full index on the current DuckDB artifacts.
- Verify whether the warm path is spending time in file-hash loading, runtime inventory, analyzer inventory, derived-index rebuild, or unintended re-persistence.
- Add targeted timing around `load_existing_file_hashes()`, `_inspect_index_rebuild_request()`, `_ensure_index()`, and backend connection setup.
- Ensure unchanged files remain cheap under DuckDB and that `ctx` does not pay a near-full refresh cost.

Expected gain:

- Measured warm-index regression upper bound: `+2660.391s` aggregate.
- Measured `large-cpython ctx` regression: `+1393.384s`.
- If the root cause is shared with the persistence path, this may fall out of action 1.
- If it is a separate freshness/read-path problem, a reasonable target is restoring warm `index` to within `2x` of the SQLite campaign for unchanged repositories.

Risk:

- Medium. It may expose backend API gaps rather than a localized bug.

3. Keep vector-native semantic retrieval on the existing roadmap.

Scope:

- Replace brute-force vector retrieval and Python-side similarity scoring with an optional vector-native retrieval backend.
- Preserve deterministic exact retrieval as authoritative.

Expected gain:

- The preceding report estimated `15%` to `35%` on large-repo `ctx`.
- That estimate remains plausible for semantic-heavy `ctx`, but it is not the immediate worst offender in the current DuckDB campaign because warm-index/refresh dominates.

Risk:

- Heavy architecture work. This should stay tied to the existing vector-backend issue rather than becoming an ad hoc local optimization.

4. Keep embedding runtime and calibration work on the existing roadmap.

Scope:

- Use hardware-aware calibration for CPU/GPU/thread/batch choices.
- Consider a long-lived embedding runtime only as part of daemon or runtime-lifetime work.

Expected gain:

- Current CPU embedding diagnostic time is still high: `2096.966s` on `large-cpython`, `2633.243s` on `large-texlive`.
- Previous estimate remains `15%` to `30%` for large full indexes if runtime/backend changes are effective.
- On this host, GPU-based expectations should not be used until `nvidia-smi` works and `CODIRA_EMBED_DEVICE` is explicitly configured.

Risk:

- Medium to heavy. It crosses configuration, hardware detection, and runtime lifecycle.

5. Defer small DuckDB query micro-regressions until actions 1 and 2 are complete.

Scope:

- Re-measure `sym`, `symlist`, `audit`, and `calls` after DuckDB persistence/read-path fixes.
- Optimize adapter/query paths only if micro-regressions remain.

Expected gain:

- Absolute wins are below `1s` per command in the current benchmark matrix.
- This is not first-order work while full-index and warm-index regressions are measured in hundreds or thousands of seconds.

6. Do not reopen the JSON accepted-file double-load optimization.

Reason:

- The previous report benchmarked that idea and explicitly rejected it.
- The current campaign does not provide a substantially new fact that invalidates that decision.
- `large-cldr-json ctx` improved by `20.01%` in the current comparison.

## Objective 4: Roadmap Snapshot Cross-Reference

Snapshot validation:

- `issues.json` exists and parses.
- `milestones.json` exists and parses.
- `issues.json`: `data.repository.issues.totalCount = 17`, `hasNextPage = false`.
- `milestones.json`: `data.repository.milestones.totalCount = 5`, `hasNextPage = false`.
- Nested milestone issue lists all have `hasNextPage = false`.
- Conclusions in this section are based only on the local snapshot files.

Existing open issues related to Objective 3:

| Objective 3 area | Open issue relation | Match quality | Reason |
|---|---|---|---|
| Vector-native semantic retrieval | `#20 Feature: Introduce Optional Vector Database Backend for Semantic Retrieval` | Strong | Issue body directly targets optional vector-database-backed semantic retrieval. |
| Embedding runtime lifetime | `#22 Feature: Daemon Mode for Incremental File Watching and Automatic Reindexing` | Partial | Daemon mode can keep process/runtime state warm, but the issue is broader than embedding inference. |
| Embedding hardware tuning | `#28 feat(embeddings): Add embeddings calibration script (hardware-aware auto-tuning)` | Strong for calibration | Issue body explicitly covers device selection, thread count, batch size, and GPU memory limits. |
| Configuration needed for tuning | `#17 Introduce install-time configuration system for Codira (hardware + plugins)` and `#27 Introduce configuration injection in core <-> plugin interface` | Supporting | These issues provide configuration surfaces, not direct performance fixes. |

Closed or not-open issue check:

- The local open issue snapshot does not list issue `#10`.
- `git log --grep=duckdb` shows the DuckDB backend implementation and follow-up fixes already landed.
- `docs/process/issue-010-duckdb-backend.md` records issue `#10` scope as backend implementation, activation, and SQLite observable parity.
- The current DuckDB performance regression is therefore not covered by an open issue in the local snapshots, and issue `#10` should not be treated as an open performance task.

Completely new points relative to the open roadmap:

- DuckDB full-index persistence performance parity.
- DuckDB warm-index and automatic refresh performance parity.
- DuckDB exact/query adapter micro-regression cleanup, after the large backend regressions are fixed.

Actions that should immediately increase performance, excluding actions already covered by open issues:

1. Create and implement a DuckDB persistence performance task.

Detailed plan:

- Add a targeted benchmark fixture that runs the same index workload with `CODIRA_INDEX_BACKEND=sqlite` and `CODIRA_INDEX_BACKEND=duckdb`.
- Instrument DuckDB persistence frames:
  - `DuckDBIndexBackend.persist_analysis`
  - `DuckDBConnection.execute`
  - `DuckDBConnection.executemany`
  - `_duckdb_lastrowid`
  - shared `_store_analysis` insert helpers
- Confirm whether importlib churn comes from DuckDB driver calls, adapter error-class lookup, parameter binding, or another backend-local path.
- Replace the confirmed slow path with DuckDB-native batch persistence.
- Validate with:
  - identical indexed/reused/deleted/failed counts
  - equivalent query results for `sym`, `ctx`, `calls`, and `cov`
  - benchmark comparison against `.artifacts/benchmarks/backend/20260511T151057Z`

Expected immediate gain:

- Highest expected gain among new actions.
- Target: reclaim at least half of the measured DuckDB full-index overhead before broader backend work continues.

2. Create and implement a DuckDB warm-index/readiness performance task.

Detailed plan:

- Benchmark warm `codira index` on one small, one medium, and one large corpus.
- Add phase-level timing for:
  - existing file hash loading
  - runtime inventory loading
  - analyzer inventory loading
  - derived-index rebuild
  - connection open/close
- Confirm that unchanged files do not flow through expensive persistence or embedding paths.
- Fix the first confirmed warm-path bottleneck.
- Add a regression benchmark or focused test that proves an unchanged DuckDB index has bounded warm-index behavior.

Expected immediate gain:

- Very high if it restores warm indexing close to the previous SQLite campaign.
- Upper bound from measured campaign: `+2660.391s` aggregate warm-index regression.

3. Re-measure and then clean up DuckDB small-query overhead.

Detailed plan:

- Run `sym`, `symlist`, `audit`, `calls`, and `cov` against the same DuckDB and SQLite small-codira indexes.
- Attribute the remaining overhead after actions 1 and 2.
- Optimize adapter or query SQL only for measured remaining regressions.

Expected immediate gain:

- Low in absolute campaign time, but useful for CLI responsiveness.
- Current measured upper bound is under `1s` per command for the small-codira query set.

Actions explicitly not proposed here:

- Do not propose JSON accepted-file double-load reuse. It was evaluated and discarded in the previous report, and the current campaign does not invalidate that decision.
- Do not propose vector-native retrieval as a new action. It is already covered by open issue `#20`.
- Do not propose embedding calibration as a new action. It is already covered by open issue `#28`.
- Do not propose daemon/runtime lifetime as a new action. It is already partially covered by open issue `#22`.

## Final Assessment

The current campaign should be treated as a failed DuckDB performance gate, not as a general Codira slowdown. The strongest evidence is the jump in full-index and warm-index times after the DuckDB backend landed, the presence of `.codira/index.duckdb` in the current campaign indexes, and the phase-level concentration in `indexing`.

There is no basis for saying the current hardware prevents significant gains. The first performance work should target DuckDB persistence and warm-index behavior before returning to broader semantic retrieval or embedding-runtime projects.
