# Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-31-bk-cpp-campaign-analysis.md`
(SHA-256 `05c3c1c1c6727bbff3ce73d1190b54866763349b3f8951ba7c04800338dbcf66`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/analysis` | available |
| `.artifacts/analysis/2026-05-19-measurement-campaign-analysis.md` | available |
| `.artifacts/analysis/2026-05-24-measurement-campaign-analysis.md` | available |
| `.artifacts/analysis/2026-05-31-bk-cpp-campaign-analysis.md` | available |
| `.artifacts/benchmarks/backend/20260511T151057Z` | available |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite` | available |
| `benchmarks/performance/benchmarks.local.json` | available |
| `benchmarks/performance/bk-cpp.local.json` | available |

Resolved directory moves:

- `.artifacts/20260528T155144Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb`.
- `.artifacts/20260528T155144Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite`.
- `benchmarks/benchmarks.local.json` → `benchmarks/performance/benchmarks.local.json`.
- `benchmarks/bk-cpp.local.json` → `benchmarks/performance/bk-cpp.local.json`.
- `.artifacts/20260511T151057Z` → `.artifacts/benchmarks/backend/20260511T151057Z`.


Date: 2026-05-31

## Hardware Snapshot

- Host kernel: `Linux verona 6.18.32-p2-gentoo-dist #1 SMP PREEMPT_DYNAMIC Thu May 21 22:02:45 -00 2026 x86_64`
- OS: `Gentoo Linux 2.18`
- CPU: `Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz`
- CPU topology: `1 socket`, `6 physical cores`, `12 logical CPUs`, max reported frequency `4.70 GHz`
- Memory at analysis time: `46 GiB` RAM total, `83 GiB` swap total, `0B` swap in use
- GPU check: `nvidia-smi` failed with `NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.`
- Current embedding device evidence: current campaign metadata records `CODIRA_EMBED_DEVICE = null`, effective `embedding_device = cpu`, `CODIRA_EMBED_BATCH_SIZE = 128`, and `torch_available = true`
- Embeddings in this analysis should therefore be treated as CPU-backed

## Source Artifacts

Primary campaign artifacts:

| Campaign | Role | Codira version | Codira commit | Run time | Manifest |
|---|---|---:|---|---|---|
| `.artifacts/benchmarks/backend/20260511T151057Z` | historical DuckDB baseline | `1.23.6.post1.dev1` | `d7c0182b83d0783b8a0a9f01f284c82ef0cacc5c` | `2026-05-11T21:13:46Z` | `benchmarks/performance/benchmarks.local.json` |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite` | current SQLite control | `1.26.0.post1.dev3` | `f8190fb285ebf35dc6e57d0b19f7198858334283` | `2026-05-28T18:48:21Z` | `benchmarks/performance/bk-cpp.local.json` |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb` | current DuckDB campaign | `1.26.0.post1.dev3` | `f8190fb285ebf35dc6e57d0b19f7198858334283` | `2026-05-29T18:44:10Z` | `benchmarks/performance/bk-cpp.local.json` |

Previous reports examined for format and comparison context:

- `.artifacts/analysis/2026-05-19-measurement-campaign-analysis.md`
- `.artifacts/analysis/2026-05-24-measurement-campaign-analysis.md`

Notes:

- The two current campaigns are same-version, same-commit, same-manifest backend comparisons.
- The baseline is not a same-version comparator. It predates the current commit, uses a different manifest, lacks the first-party C++ analyzer, and used a different command/profile matrix.
- `timings.total` is wall-clock for one index pass. `timings.embeddings` is diagnostic cumulative hook time and is not added to `total`.
- `llvm-project` is excluded from clean aggregates because the DuckDB run failed before producing a complete index. It is analyzed separately in the quarantined section.

## Workload Scope

The historical baseline and the current campaigns have 14 matched labels:

`cldr-json`, `codira`, `cpython`, `dataset.json.examples`, `fontshow`, `nvm`, `official-images`, `ohmyzsh`, `postgres`, `redis`, `requests`, `texlive`, `tree-sitter-c`, `tree-sitter-python`.

The current `bk-cpp.local.json` campaign adds:

- `Catch2`
- `fmt`
- `llvm-project`

Clean current aggregates exclude only `llvm-project`, retaining `Catch2` and `fmt` as valid C++-campaign data. Historical-baseline aggregates use only the 14 matched labels.

## Objective 1: Historical Baseline To Current Campaign

### Phase Totals On 14 Matched Workloads

| Metric | `20260511T151057Z` baseline | Current DuckDB | Current SQLite |
|---|---:|---:|---:|
| Workloads | 14 | 14 | 14 |
| `timings.total` sum | 18,209.385s | 3,237.944s | 3,177.906s |
| `timings.indexing` sum | 18,079.703s | 27.725s | 67.018s |
| `timings.parsing` sum | 105.123s | 115.523s | 114.631s |
| `timings.embeddings` sum | 6,833.705s | 2,982.560s | 2,960.541s |
| Indexed files | 15,425 | 18,421 | 18,421 |
| Symbol / embedding rows | 221,208 | 245,119 | 245,119 |
| File-level failures | 77 | 78 | 78 |

Observed deltas:

| Comparison | Total delta | Total delta % | File-count delta | Symbol-row delta |
|---|---:|---:|---:|---:|
| Baseline -> current DuckDB | -14,971.441s | -82.22% | +2,996 | +23,911 |
| Baseline -> current SQLite | -15,031.479s | -82.55% | +2,996 | +23,911 |

Interpretation:

- The current code is much faster than the historical baseline on the matched workload set, even while indexing more files and symbols.
- The improvement is not attributable to the C++ analyzer alone. The historical baseline was dominated by a DuckDB/indexing-path problem; current `timings.indexing` dropped from `18,079.703s` to `27.725s` on DuckDB and `67.018s` on SQLite.
- Because the baseline and current campaigns differ by version, commit, manifest, analyzer inventory, and hyperfine matrix, this section is a historical evolution comparison rather than a same-version backend conclusion.

### Largest Per-Workload Improvements

Phase totals on the 14 matched workloads:

| Workload | Baseline total | Current DuckDB total | Current SQLite total | DuckDB delta vs baseline | SQLite delta vs baseline |
|---|---:|---:|---:|---:|---:|
| `cpython` | 6,909.322s | 885.252s | 877.528s | -6,024.070s | -6,031.794s |
| `texlive` | 6,069.347s | 1,322.139s | 1,304.485s | -4,747.208s | -4,764.862s |
| `postgres` | 3,564.978s | 669.256s | 644.414s | -2,895.722s | -2,920.564s |
| `redis` | 909.916s | 204.266s | 204.557s | -705.650s | -705.359s |
| `codira` | 193.672s | 49.235s | 46.810s | -144.437s | -146.862s |
| `fontshow` | 174.216s | 35.592s | 33.578s | -138.624s | -140.638s |

Only `dataset.json.examples` worsened against the baseline in DuckDB phase totals (`+0.212s`), and it indexed `0` files in all compared campaigns. It is not a language-analyzer performance signal.

### Hyperfine Family Sums On 14 Matched Workloads

| Family | Baseline DuckDB | Current DuckDB | Current SQLite |
|---|---:|---:|---:|
| `index --full` | 18,369.857s | 3,249.855s | 3,232.313s |
| warm `index` | 2,681.025s | 14.796s | 14.087s |
| `ctx` | 1,507.556s | 85.125s | 99.657s |
| `emb` | 5.863s | 76.755s | 82.661s |
| `audit` | 0.295s | 54.741s | 12.901s |
| `sym` | 1.020s | 12.365s | 11.190s |
| `symlist` | 0.383s | 12.125s | 11.875s |
| `calls` | 0.285s | 11.762s | 11.156s |
| `plugins` | 0.181s | 2.465s | 2.515s |
| `caps` | 0.182s | 2.040s | 2.050s |
| `cov` | 0.177s | 3.061s | 3.104s |
| `help` | 0.149s | 1.734s | 1.757s |

Interpretation:

- `index --full`, warm `index`, and `ctx` improved dramatically from the baseline.
- Small commands are slower in the current matrix. This is partly a measurement-shape difference: the current command matrix includes more resolved backend/query commands and uses the current plugin/backend architecture. It is still worth tracking because interactive commands are user-visible.
- The current nonzero `emb` failure is isolated to `dataset.json.examples`, where no files were indexed and `emb` returns `status: not_indexed` on both backends.

## Objective 2: Current Backend Comparison Excluding `llvm-project`

### Clean Current Aggregate

This section excludes `llvm-project` and includes the remaining 16 current workloads.

| Metric | Current DuckDB | Current SQLite | DuckDB - SQLite |
|---|---:|---:|---:|
| Workloads | 16 | 16 | 0 |
| `timings.total` sum | 3,274.064s | 3,209.662s | +64.402s |
| `timings.indexing` sum | 28.012s | 67.728s | -39.716s |
| `timings.parsing` sum | 117.339s | 116.435s | +0.904s |
| `timings.embeddings` sum | 3,011.543s | 2,987.324s | +24.219s |
| Indexed files | 18,947 | 18,947 | 0 |
| Symbol / embedding rows | 248,018 | 248,018 | 0 |
| File-level failures | 78 | 78 | 0 |

Interpretation:

- Excluding `llvm-project`, the current campaigns produce identical indexed-file counts, symbol counts, and file-level failure counts.
- DuckDB is faster in the storage/indexing phase (`28.012s` vs `67.728s`, `-58.64%`), but total wall time is slightly slower (`+64.402s`, `+2.01%`).
- The current campaign is embedding-bound. Embeddings account for most wall-clock time on the large workloads, so storage/indexing wins do not dominate the total.

### Current Per-Workload Totals

| Workload | Category | DuckDB total | SQLite total | DuckDB - SQLite | Notes |
|---|---|---:|---:|---:|---|
| `texlive` | large | 1,322.139s | 1,304.485s | +17.654s | embedding-bound |
| `postgres` | large | 669.256s | 644.414s | +24.842s | embedding-bound |
| `cpython` | large | 885.252s | 877.528s | +7.724s | Python syntax failures identical |
| `redis` | medium | 204.266s | 204.557s | -0.291s | effectively flat |
| `codira` | small | 49.235s | 46.810s | +2.425s | embedding-bound |
| `fontshow` | small | 35.592s | 33.578s | +2.014s | embedding-bound |
| `Catch2` | medium | 21.762s | 18.500s | +3.262s | new C++ workload |
| `fmt` | small | 14.358s | 13.256s | +1.102s | new C++ workload |
| `cldr-json` | large | 11.712s | 10.542s | +1.170s | JSON workload |
| `dataset.json.examples` | small | 1.286s | 0.793s | +0.493s | indexes `0` files |

### Current Hyperfine Family Sums

This table covers the 16 current workloads excluding `llvm-project`.

| Family | DuckDB | SQLite | DuckDB - SQLite |
|---|---:|---:|---:|
| `index --full` | 3,284.656s | 3,265.557s | +19.099s |
| warm `index` | 15.489s | 14.678s | +0.811s |
| `ctx` | 95.685s | 110.038s | -14.353s |
| `emb` | 87.115s | 93.020s | -5.905s |
| `audit` | 55.332s | 13.342s | +41.990s |
| `sym` | 12.892s | 11.630s | +1.262s |
| `symlist` | 12.658s | 12.331s | +0.327s |
| `calls` | 12.285s | 11.571s | +0.714s |
| `refs` | 1.736s | 1.822s | -0.086s |
| `plugins` | 2.825s | 2.868s | -0.043s |
| `caps` | 2.333s | 2.342s | -0.009s |
| `cov` | 3.402s | 3.466s | -0.064s |
| `help` | 1.984s | 2.018s | -0.034s |

Interpretation:

- `ctx` and `emb` are faster on DuckDB in the clean current hyperfine aggregate.
- `audit` is materially slower on DuckDB in this aggregate.
- Full-index totals remain close because embedding work dominates the benchmark.
- The only non-`llvm-project` nonzero hyperfine exit status is `dataset.json.examples emb`, on both backends, due to `status: not_indexed`.

## Objective 3: C++ Analyzer Assessment

Current SQLite indexed-file counts excluding `llvm-project`:

| Analyzer | Indexed files |
|---|---:|
| `c` | 11,914 |
| `cpp` | 3,436 |
| `python` | 2,874 |
| `bash` | 629 |
| `json` | 94 |

C++-bearing workloads excluding `llvm-project`:

| Workload | C++ files | Indexed files | Symbols | File failures | SQLite total | SQLite parsing | SQLite embeddings |
|---|---:|---:|---:|---:|---:|---:|---:|
| `texlive` | 2,954 | 10,911 | 95,838 | 0 | 1,304.485s | 45.553s | 1,224.243s |
| `Catch2` | 413 | 449 | 1,877 | 0 | 18.500s | 0.674s | 16.055s |
| `fmt` | 46 | 77 | 1,022 | 0 | 13.256s | 1.130s | 10.729s |
| `redis` | 8 | 903 | 12,239 | 0 | 204.557s | 3.231s | 196.667s |
| `cpython` | 7 | 3,337 | 97,782 | 67 | 877.528s | 50.535s | 798.367s |
| `postgres` | 5 | 2,581 | 33,351 | 0 | 644.414s | 11.089s | 615.911s |
| `tree-sitter-c` | 1 | 20 | 277 | 0 | 13.486s | 0.570s | 11.446s |
| `tree-sitter-python` | 1 | 20 | 211 | 11 | 10.779s | 0.524s | 8.803s |
| `official-images` | 1 | 180 | 290 | 0 | 6.325s | 0.056s | 5.286s |

Findings:

- No `cpp` analyzer file-level failures were found in the non-`llvm-project` logs.
- `fmt` and `Catch2`, the two current workloads absent from the baseline and added for C++ coverage, completed with `0` file-level failures on both backends.
- The C++ analyzer does not appear especially slow in these artifacts. On C++-heavy workloads, parsing is small relative to embeddings:
  - `texlive`: parsing `45.553s`, embeddings `1,224.243s`
  - `Catch2`: parsing `0.674s`, embeddings `16.055s`
  - `fmt`: parsing `1.130s`, embeddings `10.729s`
- The largest current campaign costs are embedding and backend/query phases, not C++ parsing.

No-go decision:

- Do not attribute current campaign runtime to the C++ plugin without a targeted no-embeddings or analyzer-only benchmark. The available phase data do not support that conclusion.

## Quarantined Section: `llvm-project`

This section is intentionally excluded from all clean aggregates above.

Current campaign metadata parity:

- Current DuckDB and SQLite campaigns use the same Codira version: `1.26.0.post1.dev3`
- Both current campaigns record the same Codira commit: `f8190fb285ebf35dc6e57d0b19f7198858334283`
- Both current campaigns use the same manifest: `benchmarks/performance/bk-cpp.local.json`
- Both current campaigns use the same `llvm-project` path: `local corpus/llvm-project`

Observed `llvm-project` outcomes:

| Metric | DuckDB | SQLite |
|---|---:|---:|
| `large-llvm-project-index-phases.json` | missing | present |
| Hyperfine `index --full` mean | 252.404s | 6,465.029s |
| Hyperfine `index --full` exit codes | all `1` | all `0` |
| Persisted files | 0 | 72,354 |
| Persisted symbol rows | 0 | 660,243 |
| Persisted embeddings | 0 | 660,243 |
| Index DB size | 98,316,288 bytes | 6,007,926,784 bytes |

DuckDB failure:

```text
_duckdb.ConstraintException: Constraint Error: PRIMARY KEY or UNIQUE constraint violation: duplicate key "python:module:llvm.utils.lit.lit"
```

SQLite follow-on failure:

```text
sqlite3.OperationalError: too many SQL variables
```

Interpretation:

- The apparent large DuckDB speedup on `llvm-project` is invalid. It is an early failing run, not a successful faster index.
- SQLite completed the cold full index, but warm/query paths later hit a separate large-workload bug in reusable-embedding counting.
- `llvm-project` should be treated as correctness triage, not performance signal.

Required follow-up:

1. Fix or diagnose the DuckDB duplicate `symbol_index` key path for `python:module:llvm.utils.lit.lit`.
2. Fix or diagnose the SQLite `too many SQL variables` path in reusable embedding counting.
3. Rerun `llvm-project` only after both backends can complete the same commands successfully.

## Validation Status

Commands run during this analysis:

```text
uv run codira index
find .artifacts/analysis -maxdepth 1 -type f | sort
find .artifacts/benchmarks/backend/20260511T151057Z -maxdepth 2 -type f | sort
jq ... campaign-plan.json / failure-summary.json / hyperfine JSON / index phase JSON
sqlite3 ... current SQLite index databases
.venv/bin/python ... current DuckDB index databases and aggregate artifact summaries
rg ... failure log checks
uname -a
cat /etc/os-release
lscpu
free -h
nvidia-smi --query-gpu=...
```

Validation notes:

- This was an artifact analysis only. No repository code was changed.
- Full repository validation (`pre-commit run --all-files`, `pytest -q`) was not run because the task produced a report artifact and did not modify source code.
- The saved report is this file: `.artifacts/analysis/2026-05-31-bk-cpp-campaign-analysis.md`.
