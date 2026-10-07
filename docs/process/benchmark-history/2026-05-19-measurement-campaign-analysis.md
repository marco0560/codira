# Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-19-measurement-campaign-analysis.md`
(SHA-256 `cf24246b1b69ca815a2bd9fd8fa2ef2d9d017826a67a9909747a03d05e619e71`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/20260502T172501Z` | unavailable historical path |
| `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md` | available |
| `.artifacts/analysis/2026-05-16-measurement-campaign-analysis.md` | available |
| `.artifacts/benchmarks/backend/20260511T151057Z` | available |
| `.artifacts/benchmarks/short-duckdb` | unavailable historical path |
| `.artifacts/benchmarks/short-sqlite` | unavailable historical path |
| `benchmarks/performance/short_benchmark.local.json` | available |

Resolved directory moves:

- `benchmarks/short_benchmark.local.json` → `benchmarks/performance/short_benchmark.local.json`.
- `.artifacts/20260511T151057Z` → `.artifacts/benchmarks/backend/20260511T151057Z`.


Date: 2026-05-19

## Hardware Snapshot

- Host kernel: `Linux verona 6.18.31-gentoo-dist #1 SMP PREEMPT_DYNAMIC Fri May 15 16:31:41 -00 2026 x86_64`
- OS: `Gentoo Linux 2.18`
- CPU: `Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz`
- CPU topology: `1 socket`, `6 physical cores`, `12 logical CPUs`, max reported frequency `4.70 GHz`
- Memory at analysis time: `46 GiB` RAM total, `83 GiB` swap total
- GPU: NVIDIA GeForce GTX 1050, driver `580.159.03`, CUDA `13.0`, `727 MiB / 2048 MiB` memory in use, `8%` utilization in the operator-provided `nvidia-smi` output at `2026-05-19 19:04:41`
- Embedding device environment: `CODIRA_EMBED_DEVICE` was unset
- Embedding device selection in code: `src/codira/semantic/embeddings.py::_configured_embedding_device()` returns `cpu` when `CODIRA_EMBED_DEVICE` is unset
- Embeddings in this analysis should therefore be treated as CPU-backed

## Compared Campaigns

- Current campaign: `.artifacts/benchmarks/short-duckdb`
- Preceding campaign: `.artifacts/benchmarks/short-sqlite`
- Previous reports examined:
  - `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md`
  - `.artifacts/analysis/2026-05-16-measurement-campaign-analysis.md`

Metadata:

| Campaign                             | Run time               | Version  | Commit                                     | Manifest                                | Active backend evidence                |
|--------------------------------------|------------------------|---------:|--------------------------------------------|-----------------------------------------|----------------------------------------|
| `.artifacts/benchmarks/short-sqlite` | `2026-05-18T06:52:19Z` | `1.24.2` | `d877d4475824faf003abf40c12c29e11bcb83aae` | `benchmarks/performance/short_benchmark.local.json` | indexes contain `.codira/index.db`     |
| `.artifacts/benchmarks/short-duckdb` | `2026-05-18T13:28:17Z` | `1.24.2` | `d877d4475824faf003abf40c12c29e11bcb83aae` | `benchmarks/performance/short_benchmark.local.json` | indexes contain `.codira/index.duckdb` |

Git-history comparison:

- Both campaigns record the same commit: `d877d4475824faf003abf40c12c29e11bcb83aae`.
- `git log d877d4475824faf003abf40c12c29e11bcb83aae..d877d4475824faf003abf40c12c29e11bcb83aae` returned no commits.
- The difference between the two newest campaigns is therefore not a software-version delta. It is a same-version backend comparison between SQLite and DuckDB.
- `git show --no-patch --format=fuller d877d4475824faf003abf40c12c29e11bcb83aae` identifies the commit as `chore(release): 1.24.2 [skip ci]`, committed on `2026-05-18T06:18:54Z`.

Measurement notes:

- The short campaign covers three repositories: `codira`, `cpython`, and `redis`.
- Hyperfine means are the primary top-level comparison surface.
- `scripts/benchmark_index.py` records `timings.total` as wall-clock for one index pass.
- `timings.embeddings` is cumulative diagnostic hook time and is not additive to `total`.
- The GPU is present and visible on the host, but the benchmarked runs should still be treated as CPU-backed because `CODIRA_EMBED_DEVICE` was unset.

## Objective 1: Performance Evolution

Overall result:

- Comparable Hyperfine measurements: `18`
- Improved measurements: `2`
- Regressed measurements: `16`
- The current DuckDB run is substantially slower than the preceding SQLite run for full indexing, warm indexing, and `ctx` on `large-cpython`.

Aggregate by command family:

| Family         | SQLite sum | DuckDB sum | Absolute delta | Delta %    |
|----------------|-----------:|-----------:|---------------:|-----------:|
| `index --full` | 1245.346s  | 7285.324s  | +6039.977s     | +485.00%   |
| warm `index`   | 9.347s     | 1451.576s  | +1442.229s     | +15429.41% |
| `ctx`          | 39.054s    | 1336.439s  | +1297.385s     | +3322.03%  |
| `sym`          | 0.228s     | 0.917s     | +0.689s        | +302.60%   |
| `symlist`      | 0.227s     | 0.383s     | +0.156s        | +68.54%    |
| `emb`          | 5.640s     | 5.736s     | +0.096s        | +1.70%     |
| `audit`        | 0.209s     | 0.302s     | +0.093s        | +44.50%    |
| `calls`        | 0.213s     | 0.297s     | +0.084s        | +39.55%    |
| `plugins`      | 0.190s     | 0.195s     | +0.006s        | +3.00%     |
| `caps`         | 0.160s     | 0.164s     | +0.003s        | +2.16%     |
| `cov`          | 0.173s     | 0.175s     | +0.001s        | +0.72%     |
| `help`         | 0.146s     | 0.142s     | -0.005s        | -3.08%     |

Largest regressions:

| Benchmark                          | SQLite   | DuckDB    | Absolute delta | Delta %    |
|------------------------------------|---------:|----------:|---------------:|-----------:|
| `large-cpython index --full`       | 993.287s | 6264.873s | +5271.586s     | +530.72%   |
| `large-cpython ctx --json getText` | 26.282s  | 1324.590s | +1298.308s     | +4939.97%  |
| `large-cpython warm index`         | 7.472s   | 1264.227s | +1256.755s     | +16819.34% |
| `medium-redis index --full`        | 205.823s | 824.763s  | +618.940s      | +300.71%   |
| `small-codira index --full`        | 46.236s  | 195.687s  | +149.451s      | +323.23%   |
| `medium-redis warm index`          | 1.473s   | 147.909s  | +146.436s      | +9942.75%  |
| `small-codira warm index`          | 0.402s   | 39.440s   | +39.038s       | +9701.31%  |
| `small-codira sym main --json`     | 0.228s   | 0.917s    | +0.689s        | +302.60%   |

Measured improvements:

| Benchmark                                 | SQLite | DuckDB | Absolute delta | Delta % |
|-------------------------------------------|-------:|-------:|---------------:|--------:|
| `medium-redis ctx --json 'hdr histogram'` | 6.917s | 5.985s | -0.932s        | -13.47% |
| `small-codira help`                       | 0.146s | 0.142s | -0.005s        | -3.08%  |

Index phase deltas:

| Phase                      | SQLite    | DuckDB    | Absolute delta | Delta %  |
|----------------------------|----------:|----------:|---------------:|---------:|
| `large-cpython indexing`   | 919.503s  | 6868.534s | +5949.031s     | +646.98% |
| `large-cpython total`      | 977.551s  | 6924.774s | +5947.222s     | +608.38% |
| `medium-redis indexing`    | 195.060s  | 846.532s  | +651.473s      | +333.99% |
| `medium-redis total`       | 199.807s  | 850.894s  | +651.087s      | +325.86% |
| `large-cpython embeddings` | 1793.998s | 2062.321s | +268.323s      | +14.96%  |
| `small-codira indexing`    | 42.084s   | 204.841s  | +162.757s      | +386.74% |
| `small-codira total`       | 44.538s   | 207.076s  | +162.538s      | +364.94% |
| `small-codira embeddings`  | 82.781s   | 92.947s   | +10.167s       | +12.28%  |
| `medium-redis embeddings`  | 384.061s  | 342.058s  | -42.003s       | -10.94%  |

Storage-size comparison:

| Repository      |      SQLite index | DuckDB index        | Absolute delta       | DuckDB / SQLite |
|-----------------|------------------:|--------------------:|---------------------:|----------------:|
| `small-codira`  | 16,003,072 bytes  | 120,598,528 bytes   | +104,595,456 bytes   | 7.54x           |
| `medium-redis`  | 75,685,888 bytes  | 383,791,104 bytes   | +308,105,216 bytes   | 5.07x           |
| `large-cpython` | 646,705,152 bytes | 1,905,274,880 bytes | +1,258,569,728 bytes | 2.95x           |

Conclusion for Objective 1:

- The current campaign confirms the previous report's DuckDB regression with a cleaner same-version backend comparison.
- Because both campaigns use commit `d877d447...`, the regression cannot be attributed to code changes between the two campaigns.
- The dominant regression is in DuckDB indexing and warm-index refresh behavior.
- CPU embeddings remain expensive, but they do not explain the largest delta. For `large-cpython`, `indexing` regressed by `+5949.031s`, while `embeddings` regressed by `+268.323s`.
- The current hardware does not explain the regression; the SQLite campaign on the same hardware and same commit is much faster.

### Backend-Agnostic Core Impact On SQLite

Comparison:

- Earlier SQLite campaign subset: `.artifacts/20260502T172501Z`, version `1.21.7`, commit `2a5cbaec12ab3d9874257e8f8c34622120828c8f`
- Current SQLite campaign subset: `.artifacts/benchmarks/short-sqlite`, version `1.24.2`, commit `d877d4475824faf003abf40c12c29e11bcb83aae`
- Matched Hyperfine measurements: `18`
- Matched repositories: `small-codira`, `medium-redis`, `large-cpython`

Aggregate by command family:

| Family         | Earlier SQLite | Current SQLite | Absolute delta | Delta % |
|----------------|---------------:|---------------:|---------------:|--------:|
| `index --full` | 1232.721s      | 1245.346s      | +12.625s       | +1.02%  |
| `ctx`          | 36.493s        | 39.054s        | +2.561s        | +7.02%  |
| warm `index`   | 8.737s         | 9.347s         | +0.610s        | +6.98%  |
| `emb`          | 5.733s         | 5.640s         | -0.093s        | -1.63%  |
| `symlist`      | 0.198s         | 0.227s         | +0.029s        | +14.74% |
| `audit`        | 0.184s         | 0.209s         | +0.025s        | +13.78% |
| `sym`          | 0.204s         | 0.228s         | +0.024s        | +11.74% |
| `calls`        | 0.190s         | 0.213s         | +0.024s        | +12.44% |
| `caps`         | 0.176s         | 0.160s         | -0.016s        | -8.93%  |
| `plugins`      | 0.178s         | 0.190s         | +0.012s        | +6.54%  |
| `cov`          | 0.180s         | 0.173s         | -0.007s        | -3.72%  |
| `help`         | 0.148s         | 0.146s         | -0.002s        | -1.45%  |

Largest SQLite deltas:

| Benchmark                          | Earlier SQLite | Current SQLite | Absolute delta | Delta % |
|------------------------------------|---------------:|---------------:|---------------:|--------:|
| `small-codira index --full`        | 38.587s        | 46.236s        | +7.650s        | +19.82% |
| `medium-redis index --full`        | 201.274s       | 205.823s       | +4.549s        | +2.26%  |
| `large-cpython ctx --json getText` | 23.947s        | 26.282s        | +2.334s        | +9.75%  |
| `large-cpython index --full`       | 992.861s       | 993.287s       | +0.426s        | +0.04%  |
| `large-cpython warm index`         | 7.158s         | 7.472s         | +0.314s        | +4.39%  |
| `medium-redis warm index`          | 1.173s         | 1.473s         | +0.300s        | +25.56% |

Interpretation:

- The backend-agnostic core evolution did not produce a large SQLite performance win on the short matched subset.
- It also did not produce a catastrophic SQLite regression.
- The largest absolute SQLite regression is `+7.650s` on `small-codira index --full`; on the largest matched repository, `large-cpython index --full` is effectively flat at `+0.426s`, `+0.04%`.
- Therefore the current severe slowdown is not a backend-agnostic core regression visible on SQLite code paths. It is specific to the DuckDB backend path.

Detailed SQLite regression assessment:

- The operator's concern is valid: the expected direction was progress, and several user-facing SQLite commands regressed.
- The most relevant regressions on the short subset are:
  - `large-cpython ctx --json getText`: `+2.334s`, `+9.75%`
  - `medium-redis warm index`: `+0.300s`, `+25.56%`
  - `small-codira symlist`: `+0.029s`, `+14.74%`
  - `small-codira audit`: `+0.025s`, `+13.78%`
  - `small-codira sym`: `+0.024s`, `+11.74%`
  - `small-codira calls`: `+0.024s`, `+12.44%`
- The absolute deltas for `sym`, `symlist`, `audit`, and `calls` are small, but they are still noticeable because these commands are interactive.
- This should not be accepted as an unavoidable cost of backend agnosticism.

Why the regression is probably optimizable:

- The backend-agnostic core uses an explicit plugin/backend dispatch point through `active_index_backend()`.
- Query functions such as `find_logical_symbols()` now delegate through the active backend interface instead of binding directly to SQLite helpers.
- That abstraction is architecturally necessary, but the current cost model does not require repeated registry/plugin resolution, connection setup, or redundant query-side conversions on every small command.
- The protocol boundary in `BackendQueryConnection` is minimal and does not by itself require a large runtime tax.

Likely optimization directions:

1. Cache active backend factories or backend instances per process for command execution.

    Rationale:

    - Small commands are sensitive to fixed overhead.
    - Plugin snapshot and backend selection should be paid once per command process, not repeatedly across helper calls.

    Expected gain:

    - Low-to-medium absolute gain, but directly relevant to `sym`, `symlist`, `audit`, and `calls`.

2. Reuse backend connections within a single command.

    Rationale:

    - `ctx` and graph expansion can perform several related backend lookups.
    - Passing and reusing a connection through the whole command path should avoid repeated open/close or adapter setup costs.

    Expected gain:

    - Most relevant for `ctx`, `calls`, and graph/reference expansion.

3. Fuse small query backend calls where the backend boundary added round trips.

    Rationale:

    - Backend agnosticism should not mean every logical step becomes a separate backend call.
    - Backend APIs can expose coarse-grained operations while preserving a backend-neutral contract.

    Expected gain:

    - Potentially meaningful for `ctx`, where a `+2.334s` SQLite regression on `large-cpython` is large enough to investigate.

4. Add a SQLite regression budget to the benchmark gate.

    Rationale:

    - Backend-agnostic refactors should keep SQLite as the control backend.
    - A practical gate should fail or warn when core refactors regress key SQLite commands beyond a small threshold.

    Suggested first thresholds:

    - `ctx`: investigate at `>5%` or `>1s`
    - warm `index`: investigate at `>10%` or `>0.25s`
    - `sym`, `symlist`, `audit`, `calls`: investigate at `>10%` even if absolute time is small

Conclusion:

- The SQLite regressions are not dramatic, but they are real enough to track.
- They are not a necessary consequence of backend agnosticism. They are more likely an implementation tax from backend dispatch, plugin lookup, connection lifecycle, or extra query-layer work introduced during the backend-agnostic migration.
- The right response is a targeted SQLite control-backend optimization pass, not backing out the backend-agnostic architecture.

### DuckDB Evolution And Current Badness

DuckDB evolution comparison:

- Earlier DuckDB campaign subset: `.artifacts/benchmarks/backend/20260511T151057Z`, version `1.23.6.post1.dev1`, commit `d7c0182b83d0783b8a0a9f01f284c82ef0cacc5c`
- Current DuckDB campaign subset: `.artifacts/benchmarks/short-duckdb`, version `1.24.2`, commit `d877d4475824faf003abf40c12c29e11bcb83aae`
- Matched Hyperfine measurements: `18`

Aggregate DuckDB movement:

| Family         | Earlier DuckDB | Current DuckDB | Absolute delta | Delta % |
|----------------|---------------:|---------------:|---------------:|--------:|
| `index --full` | 8232.385s      | 7285.324s      | -947.061s      | -11.50% |
| warm `index`   | 1593.516s      | 1451.576s      | -141.940s      | -8.91%  |
| `ctx`          | 1430.318s      | 1336.439s      | -93.878s       | -6.56%  |
| `emb`          | 5.863s         | 5.736s         | -0.127s        | -2.17%  |
| `sym`          | 1.020s         | 0.917s         | -0.103s        | -10.12% |

Largest DuckDB changes:

| Benchmark                          | Earlier DuckDB | Current DuckDB | Absolute delta | Delta % |
|------------------------------------|---------------:|---------------:|---------------:|--------:|
| `large-cpython index --full`       | 7166.569s      | 6264.873s      | -901.696s      | -12.58% |
| `large-cpython warm index`         | 1406.628s      | 1264.227s      | -142.401s      | -10.12% |
| `large-cpython ctx --json getText` | 1417.332s      | 1324.590s      | -92.742s       | -6.54%  |
| `medium-redis index --full`        | 887.202s       | 824.763s       | -62.439s       | -7.04%  |
| `small-codira index --full`        | 178.613s       | 195.687s       | +17.074s       | +9.56%  |

Current DuckDB vs current SQLite:

| Family         | Current SQLite | Current DuckDB | Absolute delta | Delta %    |
|----------------|---------------:|---------------:|---------------:|-----------:|
| `index --full` | 1245.346s      | 7285.324s      | +6039.977s     | +485.00%   |
| warm `index`   | 9.347s         | 1451.576s      | +1442.229s     | +15429.41% |
| `ctx`          | 39.054s        | 1336.439s      | +1297.385s     | +3322.03%  |
| `sym`          | 0.228s         | 0.917s         | +0.689s        | +302.60%   |
| `symlist`      | 0.227s         | 0.383s         | +0.156s        | +68.54%    |

Interpretation:

- DuckDB improved since the previous DuckDB campaign, especially on `large-cpython index --full` (`-901.696s`, `-12.58%`), but it remains far outside an acceptable backend parity envelope.
- The current badness is not marginal. It is multi-hundred-percent slower for full indexing and orders of magnitude slower for warm indexing.
- The fact that current SQLite remains close to the earlier SQLite subset, while DuckDB remains dramatically slower, isolates the problem to DuckDB backend architecture and implementation.

## Objective 2: Hotspots And Performance-Sensitive Areas

Hotspots in importance order:

1. DuckDB full-index persistence and compatibility path

    Evidence:

    - `index --full` regressed by `+6039.977s` across the short campaign.
    - `large-cpython indexing` regressed by `+5949.031s`.
    - Current DuckDB `large-cpython-index.prof` is dominated by import-resolution frames:
    - `<frozen importlib._bootstrap>:_find_spec`: `6025.842s`, `28,838,992` calls
    - `<frozen importlib._bootstrap_external>:find_spec`: `5375.489s`, `28,838,982` calls
    - `<frozen importlib._bootstrap_external>:_get_spec`: `5354.058s`, `28,838,982` calls
    - `<frozen importlib._bootstrap_external>:find_spec`: `4922.607s`, `346,030,708` calls
    - Current DuckDB `small-codira-index.prof` has the same shape:
    - `_find_spec`: `182.435s`, `769,627` calls
    - external `find_spec`: `163.075s`, `769,617` calls
    - Preceding SQLite index profiles are instead dominated by `_flush_embedding_rows` and `embed_texts`.
    - DuckDB index files are substantially larger than SQLite index files on the same corpus.

    Relevant code areas:

    - `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBIndexBackend.persist_analysis`
    - `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBConnection.execute`
    - `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::DuckDBConnection.executemany`
    - `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py::_duckdb_lastrowid`
    - `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_support.py::_store_analysis`

2. DuckDB warm-index and `ctx` freshness path

    Evidence:

    - Warm `index` regressed by `+1442.229s` across only three repositories.
    - `large-cpython warm index` regressed by `+1256.755s`.
    - `large-cpython ctx --json getText` regressed by `+1298.308s`.
    - Current DuckDB `large-cpython-ctx.prof` is also dominated by import-resolution frames:
    - `_find_and_load`: `375.928s`
    - `_find_and_load_unlocked`: `333.310s`
    - `_find_spec`: `328.531s`
    - external `find_spec`: `299.612s`

    Relevant code areas:

    - `src/codira/cli.py::_ensure_index`
    - `src/codira/cli.py::_run_locked_index_refresh`
    - `src/codira/indexer.py::index_repo`
    - DuckDB backend load/reuse paths for existing file hashes, runtime inventory, and connection setup

3. CPU embedding inference

    Evidence:

    - Current DuckDB full-index embedding diagnostic time remains high:
    - `large-cpython`: `2062.321s`
    - `medium-redis`: `342.058s`
    - `small-codira`: `92.947s`
    - `CODIRA_EMBED_DEVICE` is unset, and `_configured_embedding_device()` returns `cpu`.
    - The GPU is available on the host, but GPU acceleration was not used by the benchmarked runs because `CODIRA_EMBED_DEVICE` was unset.
    - This remains a real hotspot, but it is not the primary DuckDB-vs-SQLite regression in this campaign.

    Relevant code areas:

    - `src/codira/semantic/embeddings.py::embed_texts`
    - `src/codira/semantic/embeddings.py::_configured_embedding_device`
    - backend embedding flush/persistence helpers

4. Small query surfaces under DuckDB

    Evidence:

    - `small-codira sym main --json`: `+0.689s`, `+302.60%`
    - `small-codira symlist --json --limit 20`: `+0.156s`, `+68.54%`
    - `small-codira audit --json`: `+0.093s`, `+44.50%`
    - `small-codira calls main --json`: `+0.084s`, `+39.55%`

    Relevant code areas:

    - `src/codira/query/exact.py`
    - `src/codira/query/graph_enrichment.py`
    - DuckDB query adapter methods and backend query implementations

5. Semantic retrieval and vector scoring

    Evidence:

    - Previous reports identified vector retrieval and Python-side similarity scoring as performance-sensitive.
    - In the current short campaign, semantic retrieval is not the largest first-order regression because `large-cpython ctx` is dominated by the DuckDB warm-refresh/import-resolution path.
    - Vector-native retrieval remains important, but it is already covered by open issue `#20`.

    Relevant code areas:

    - `src/codira/query/context.py::_retrieve_embedding_candidates`
    - `src/codira/query/producers.py::retrieve_candidates`
    - backend `embedding_candidates()` implementations

6. JSON analyzer accepted-file double-load path

    Evidence:

    - The 2026-05-03 report evaluated and rejected the accepted-file double-load optimization after measuring the `cldr-json` corpus.
    - The 2026-05-16 report explicitly kept that no-go decision.
    - The current short campaign does not include `cldr-json` and provides no new fact that invalidates the earlier decision.

Conclusion:

- Do not reopen this as an immediate performance action.

## Objective 3: Performance Enhancement Plan

Assessment on current hardware:

- There is significant performance headroom.
- The data does not support a hardware-limited conclusion.
- The dominant issue is backend implementation behavior under DuckDB, not CPU/GPU capacity.
- Heavy refactoring can produce large gains if the DuckDB backend moves away from row-by-row SQLite-shaped compatibility behavior toward backend-native bulk persistence and bounded warm-index checks.

Internet and documentation check:

- DuckDB's Python DB-API documentation warns not to use Python `executemany` for large data ingestion and points users to bulk-oriented alternatives: `https://duckdb.org/docs/stable/clients/python/dbapi`.
- DuckDB's appender documentation describes appenders as the efficient path for loading data, with batched/cached appends rather than statement-by-statement insertion: `https://duckdb.org/docs/current/clients/c/appender.html` and `https://duckdb.org/docs/current/data/appender.html`.
- DuckDB's data import overview documents several efficient ingestion methods beyond ordinary `INSERT` statements: `https://duckdb.org/docs/current/data/overview`.
- SQLite documentation explains the classic transaction-cost issue for many small writes; this is relevant background, but the current SQLite backend already behaves much better than DuckDB on the measured workload: `https://www.sqlite.org/faq.html`.
- SQLite does not expose a DuckDB-style appender API. Its efficient ingestion path is explicit transactions, prepared statement reuse, and, where applicable, multi-row `INSERT` or `INSERT INTO ... SELECT ...`.
- The practical SQLite conclusion for Codira is that further write-path gains may exist through staging tables or table-oriented inserts, but the current SQLite backend is already close enough to its earlier performance that this is secondary to DuckDB.
- These sources do not support treating the measured `+485%` full-index and `+15429%` warm-index DuckDB regressions as an inherent DuckDB-vs-SQLite law. They support the opposite conclusion: DuckDB is being driven through an unsuitable SQLite-shaped row-write interface.

Salvageability assessment:

- The DuckDB backend is salvageable, but not by small query tweaks.
- A substantial refactor is required.
- A complete rewrite is not yet justified because:
  - query parity and backend activation already exist;
  - the failure is concentrated in persistence, warm-index, and adapter behavior;
  - the current DuckDB backend already improved from the previous DuckDB campaign by `-11.50%` on aggregate full indexing and `-8.91%` on aggregate warm indexing.
- It is not a lost cause because the current SQLite backend proves that the core workload can be indexed much faster on the same codebase, hardware, and benchmark subset.

Required DuckDB plugin architecture changes:

1. Split the DuckDB backend into query-compatible and write-native layers.

    Current problem:

    - The backend exposes SQLite-like `execute`, `executemany`, cursor, and `lastrowid` compatibility around DuckDB.
    - This lets shared persistence helpers treat DuckDB like a DB-API SQLite replacement.

    Required change:

    - Keep a compatibility adapter only for query/read paths where it is cheap and correct.
    - Add a DuckDB-native write pipeline owned by the plugin.
    - Route full-index persistence through that write pipeline instead of through SQLite-shaped row operations.

2. Replace row-by-row persistence with table-oriented batch persistence.

    Current problem:

    - `DuckDBConnection.executemany()` delegates to the Python DB-API surface.
    - `DuckDBConnection.execute()` calls `_duckdb_lastrowid()` after sequence-backed inserts, which can add one sequence lookup per inserted row.

    Required change:

    - Accumulate per-file analysis artifacts into table-specific buffers:
    - `files`
    - `modules`
    - `classes`
    - `functions`
    - `imports`
    - `overloads`
    - `enum_members`
    - `docstring_issues`
    - `symbol_index`
    - `embeddings`
    - graph edge tables
    - Flush those buffers with DuckDB-native bulk ingestion rather than per-row inserts.
    - Use explicit ID allocation in Python for a file's persistence batch, or use a backend-owned deterministic ID mapping, so code does not need per-row `lastrowid` emulation.

3. Make transaction boundaries batch-scoped, not file-row scoped.

    Current problem:

    - The plugin emulates SQLite savepoint semantics by committing and starting a transaction around file writes on a shared connection.

    Required change:

    - Use one controlled transaction per index batch or per bounded chunk of files.
    - Preserve failure isolation by staging rows in memory until a file analysis is complete, then append that file's rows atomically within the current batch.
    - If per-file rollback is required by contract, implement it at the staging layer before rows reach DuckDB, not by making DuckDB imitate SQLite savepoints for every file.

    Current rollback contract and backend-specific recommendation:

    - The formal backend contract for `persist_analysis()` says only that a backend persists one normalized file snapshot and returns recomputed/reused semantic-artifact counts.
    - The contract does not explicitly require per-file database rollback.
    - The current indexer behavior does require deterministic per-file failure reporting: `_persist_indexed_file_analyses()` catches persistence failures, records an `IndexFailure`, and continues with the remaining parsed files.
    - Therefore the semantic requirement is not "use a database rollback per file"; it is "a failed file must not leave partial rows that corrupt the final committed index."

    SQLite situation:

    - `index_repo()` opens one shared backend connection for the run and commits after persistence, derived-index rebuild, and runtime inventory updates.
    - SQLite `persist_analysis()` wraps each file in `SAVEPOINT persist_analysis` when called with that shared connection.
    - On one file persistence failure, SQLite rolls back to the savepoint, releases it, reports the failure through the indexer, and continues.
    - This is a reasonable implementation for SQLite incremental indexing because SQLite supports savepoints natively and the existing persistence path is row-oriented.
    - It is still overhead, but the current data does not identify SQLite savepoints as the dominant SQLite regression: `large-cpython index --full` is effectively flat between earlier SQLite and current SQLite (`+0.426s`, `+0.04%`).

    DuckDB situation:

    - DuckDB does not support the SQLite savepoint pattern used by the SQLite backend.
    - The current DuckDB plugin substitutes per-file `COMMIT`, `BEGIN TRANSACTION`, and `COMMIT`/`ROLLBACK` around each file when using a shared connection.
    - That preserves a form of per-file isolation, but it is the wrong hot-path shape for DuckDB full indexing and fights the backend-native bulk-ingestion model.

    Recommendation:

    - Keep the backend-neutral semantic invariant: failed files must not leave partial rows, and valid files must be reported deterministically.
    - Do not encode per-file database rollback as a required backend contract.
    - Let SQLite continue to use savepoints for incremental indexing unless a dedicated SQLite benchmark proves the overhead matters.
    - Move DuckDB full indexing to in-memory per-file staging plus batch-oriented writes. If a file fails before staging completes, skip it. If a batch write fails, fail the batch/run or retry with smaller diagnostic chunks.
    - For incremental DuckDB indexing, use staging-and-swap or bounded chunk transactions rather than per-file transaction cycling.
    - If a later persistence redesign touches both backends, express the contract as "file write atomicity or staged discard on failure," not "savepoint-compatible per-file rollback."

4. Separate warm-index metadata checks from expensive persistence setup.

    Current problem:

    - Warm `index` and `ctx` are orders of magnitude slower under DuckDB, which means unchanged repositories are not staying on a cheap readiness path.

    Required change:

    - Add a minimal metadata/readiness path that opens DuckDB only enough to read file hashes, schema metadata, analyzer inventory, and runtime inventory.
    - Avoid schema repair, bulk writer setup, derived index rebuilds, and embedding machinery unless the readiness check proves they are needed.
    - Add a regression benchmark for unchanged DuckDB indexes.

5. Keep query optimization secondary.

    Current problem:

    - `sym`, `symlist`, `audit`, and `calls` are slower under DuckDB, but their absolute deltas are small compared with indexing and warm refresh.

    Required change:

    - Do not spend first-pass effort on query micro-optimization.
    - Re-measure after the write path and warm path are fixed, then optimize only remaining measured overhead.

    Local GPU assessment:

    - The host GPU is visible and usable according to the operator-provided `nvidia-smi` output.
    - Current Codira embeddings use `sentence-transformers/all-MiniLM-L6-v2`, with fixed dimension `384`.
    - Device selection is controlled by `CODIRA_EMBED_DEVICE`; unset means `cpu`.
    - The current default embedding batch size is `32`.
    - For the local NVIDIA GeForce GTX 1050 with `2 GiB` VRAM, GPU use may help long full-index embedding phases, but it is not a safe default without calibration because:
    - model and CUDA/Torch startup overhead can dominate short `ctx` runs;
    - `2 GiB` VRAM leaves limited headroom for batch size and desktop GPU usage;
    - the current DuckDB bottleneck is much larger than embedding-device effects.
    - Recommended decision: benchmark before changing defaults. Run the short SQLite campaign with `CODIRA_EMBED_DEVICE=cpu` and `CODIRA_EMBED_DEVICE=cuda`, compare `timings.embeddings`, full-index Hyperfine means, and `ctx` latency, then decide whether to encode a host-local setting.

    Decision:

    - Salvage path: substantial refactor of the DuckDB plugin persistence and warm-index architecture.
    - Rewrite threshold: if a focused prototype using DuckDB-native bulk writes cannot get `small-codira` and `medium-redis` full-index times within roughly `2x` of SQLite while preserving query parity, then a plugin rewrite becomes justified.
    - Lost-cause threshold: only if the native-write prototype still shows unavoidable multi-x slowdown after removing DB-API row insertion, `lastrowid` emulation, and warm-path overwork. Current evidence has not reached that threshold.

Plan in importance order:

1. Make DuckDB persistence backend-native.

    Scope:

    - Instrument `DuckDBIndexBackend.persist_analysis`, `DuckDBConnection.execute`, `DuckDBConnection.executemany`, `_duckdb_lastrowid`, and `_store_analysis`.
    - Confirm the source of import-resolution churn seen in `large-cpython-index.prof` and `small-codira-index.prof`.
    - Replace the confirmed slow path with DuckDB-native batch persistence.
    - Avoid per-row sequence round trips where possible.
    - Preserve SQLite behavior and DuckDB query parity.

    Expected gain:

    - Current short-campaign `index --full` overhead is `+6039.977s`.
    - A reasonable first target is reclaiming `50%` to `80%` of that DuckDB-specific overhead after the exact frame-level cause is confirmed.
    - Approximate per-repository savings at that target:
    - `large-cpython`: `2600s` to `4200s`
    - `medium-redis`: `300s` to `500s`
    - `small-codira`: `75s` to `120s`

    Risk:

    - Medium-to-heavy backend refactor.
    - Must preserve deterministic IDs, relation tables, graph query parity, and embedding reuse.

2. Fix DuckDB warm-index and `ctx` refresh behavior.

    Scope:

    - Profile warm `codira index` separately on the three short-campaign corpora.
    - Add phase-level timing for existing file hash loading, runtime inventory loading, analyzer inventory loading, derived-index rebuild, connection open/close, and unchanged-file decisions.
    - Confirm that unchanged files do not re-enter expensive persistence or embedding paths.
    - Fix the first confirmed warm-path bottleneck.
    - Add a bounded-regression benchmark for unchanged DuckDB indexes.

    Expected gain:

    - Current short-campaign warm-index overhead is `+1442.229s`.
    - Current `large-cpython ctx` overhead is `+1298.308s`.
    - A realistic immediate target is restoring warm `index` to within `2x` of the SQLite campaign for unchanged repositories. That would save more than `1200s` on `large-cpython warm index` alone.

    Risk:

    - Medium.
    - It may share the same root cause as action 1, but the `ctx` path must be verified independently because it has user-facing latency impact.

3. Re-measure and then clean up DuckDB small-query overhead.

    Scope:

    - Run `sym`, `symlist`, `audit`, `calls`, and `cov` against fixed DuckDB and SQLite indexes after actions 1 and 2.
    - Attribute remaining overhead to SQL shape, adapter cost, connection setup, or result conversion.
    - Optimize only measured remaining regressions.

    Expected gain:

    - Low absolute campaign gain, below `1s` per measured command in this run.
    - Useful for CLI responsiveness after larger backend regressions are fixed.

    Risk:

    - Low-to-medium.
    - Not first-order until full-index and warm-index regressions are fixed.

4. Keep vector-native semantic retrieval on the existing roadmap.

    Scope:

    - Do not open a new immediate action for this in this report.
    - Continue to treat it as part of issue `#20`.

    Expected gain:

    - Prior estimate remains plausible: `15%` to `35%` on semantic-heavy large-repo `ctx`.
    - It is not the immediate worst offender in the current short campaign.

    Risk:

    - Heavy architecture work.

5. Keep embedding hardware/runtime tuning on the existing roadmap.

    Scope:

    - Do not open a new immediate action for calibration.
    - Continue to treat calibration as issue `#28`, configuration as issues `#17` and `#27`, and daemon/runtime lifetime as issue `#22`.
    - Do not assume GPU gains until the embedding stack is verified on GPU and `CODIRA_EMBED_DEVICE` is explicitly configured.

    Expected gain:

    - Previous estimates remain plausible for large full indexes, but the current same-version backend comparison shows a larger DuckDB-specific regression.

    Risk:

    - Medium-to-heavy because this crosses hardware detection, configuration, and runtime lifecycle.

6. Do not reopen the JSON accepted-file double-load optimization.

    Reason:

    - It was evaluated and discarded in the 2026-05-03 report.
    - The 2026-05-16 report preserved that no-go decision.
    - The current short campaign provides no new JSON-heavy evidence.

## Objective 4: Roadmap Snapshot Cross-Reference

Snapshot validation:

- `issues.json` exists and parses.
- `milestones.json` exists and parses.
- `issues.json`: `data.repository.issues.totalCount = 16`, `hasNextPage = false`.
- `milestones.json`: `data.repository.milestones.totalCount = 5`, `hasNextPage = false`.
- Nested milestone issue lists have `hasNextPage = false`.
- Conclusions in this section are based only on local snapshot files.

Existing open issues related to Objective 3:

| Objective 3 area                 | Open issue relation                                                                    | Match quality          | Reason                                                                                              |
|----------------------------------|----------------------------------------------------------------------------------------|------------------------|-----------------------------------------------------------------------------------------------------|
| Vector-native semantic retrieval | `#20 Feature: Introduce Optional Vector Database Backend for Semantic Retrieval`       | Strong                 | Issue body targets optional vector-database-backed semantic retrieval.                              |
| Embedding runtime lifetime       | `#22 Feature: Daemon Mode for Incremental File Watching and Automatic Reindexing`      | Partial                | Daemon mode can keep process/runtime state warm, but the issue is broader than embedding inference. |
| Embedding hardware tuning        | `#28 feat(embeddings): Add embeddings calibration script (hardware-aware auto-tuning)` | Strong for calibration | Issue body covers device selection, thread count, batch size, and GPU memory limits.                |
| Configuration needed for tuning  | `#17 Introduce install-time configuration system for Codira (hardware + plugins)` and  |                        |                                                                                                     |
|                                  | `#27 Introduce configuration injection in core <-> plugin interface`                   | Supporting             | These issues provide configuration surfaces, not direct performance fixes.                          |

Closed or not-open issue check:

- The local open issue snapshot does not list issue `#10`.
- `milestones.json` lists issue `#10 Enable immediate support for multiple production-grade backends` as `CLOSED` under Phase 1.
- `git log --grep='#10\|issue-10\|DuckDB\|duckdb\|backend' --all` shows the DuckDB implementation and follow-up fixes already landed, including:
  - `d18b0bc feat(backend): scaffold duckdb backend package`
  - `835d2d6 feat(backend): implement duckdb backend lifecycle`
  - `0efb1f8 feat(backend): integrate duckdb activation path`
  - `2193b60 fix(backend): replace DuckDB savepoints with shared transactions`
  - `a46a9db fix(backend): restore DuckDB parity with SQLite index behavior`
  - later backend-agnostic migration commits through `8b9e8b9 refactor(backend): complete backend-agnostic core migration`
- Based on the local snapshots and git history, the current DuckDB performance regression is not covered by an open issue.

Completely new points relative to the open roadmap:

- DuckDB full-index persistence performance parity.
- DuckDB warm-index and automatic refresh performance parity.
- DuckDB small-query overhead cleanup after the larger backend regressions are fixed.

Actions that should immediately increase performance, excluding actions already covered by open issues:

1. Create and implement a DuckDB persistence performance task.

    Detailed plan:

    - Add a focused benchmark that runs the same representative workload with `CODIRA_INDEX_BACKEND=sqlite` and `CODIRA_INDEX_BACKEND=duckdb`.
    - Include at least:
    - `small-codira`
    - `medium-redis`
    - one large Python-heavy corpus, because `large-cpython` is the strongest measured regression
    - Instrument:
    - `DuckDBIndexBackend.persist_analysis`
    - `DuckDBConnection.execute`
    - `DuckDBConnection.executemany`
    - `_duckdb_lastrowid`
    - `_store_analysis`
    - Confirm whether the import-resolution hotspot is caused by repeated backend driver loading, driver-level parameter binding, per-row sequence lookup, or another backend-local path.
    - Replace the confirmed slow path with DuckDB-native bulk persistence.
    - Validate:
    - identical indexed/reused/deleted/failed counts
    - equivalent `sym`, `ctx`, `calls`, `refs`, `audit`, and `cov` results on the benchmarked corpus
    - improved Hyperfine and index-phase timings versus `.artifacts/benchmarks/short-duckdb`

    Expected immediate gain:

    - Highest expected gain among new actions.
    - Target: reclaim at least half of the current DuckDB full-index overhead before broader backend work continues.

2. Create and implement a DuckDB warm-index/readiness performance task.

    Detailed plan:

    - Benchmark warm `codira index` and `ctx` on already-indexed DuckDB output directories.
    - Add phase-level timing around:
    - file hash loading
    - analyzer inventory loading
    - runtime inventory loading
    - derived-index rebuild checks
    - connection open and schema repair
    - unchanged-file skip decisions
    - Confirm that unchanged files stay on the reuse path.
    - Fix the first confirmed warm-path bottleneck.
    - Add a focused regression benchmark or test proving bounded unchanged-index behavior.

    Expected immediate gain:

    - Very high if it restores warm indexing close to the SQLite campaign.
    - Current measured upper bound from the short campaign is `+1442.229s` aggregate warm-index overhead.

3. Re-measure and clean up DuckDB small-query overhead only after actions 1 and 2.

    Detailed plan:

    - Re-run the same short benchmark command set after the persistence and warm-index fixes.
    - If `sym`, `symlist`, `audit`, or `calls` still regress materially, attribute the remaining overhead to adapter, SQL, connection, or result-conversion cost.
    - Patch only the confirmed bottleneck.

    Expected immediate gain:

    - Small in total runtime, but useful for CLI responsiveness.
    - Current measured upper bound is `+0.689s` for `small-codira sym`.

Actions explicitly not proposed as new immediate work:

- Do not propose JSON accepted-file double-load reuse. It was evaluated and discarded in the previous reports, and the current campaign does not invalidate that decision.
- Do not propose vector-native retrieval as a new action. It is already covered by open issue `#20`.
- Do not propose embedding calibration as a new action. It is already covered by open issue `#28`.
- Do not propose configuration plumbing for tuning as a new action. It is already covered by open issues `#17` and `#27`.
- Do not propose daemon/runtime lifetime as a new action. It is already partially covered by open issue `#22`.

## Final Assessment

The current campaign is a same-version backend comparison, and it confirms that DuckDB remains the dominant performance problem. The worst offender is DuckDB indexing, followed by DuckDB warm-index and `ctx` refresh behavior. The profile evidence is materially different from SQLite: DuckDB index and large `ctx` profiles are dominated by repeated import-resolution frames, while SQLite profiles are dominated by embedding work.

There is no basis for saying that no significant gain can be obtained on the current hardware. The preceding SQLite campaign on the same hardware and same commit is much faster. The first performance work should therefore target DuckDB persistence and warm-index behavior before reopening broader semantic retrieval, embedding runtime, or JSON analyzer ideas.
