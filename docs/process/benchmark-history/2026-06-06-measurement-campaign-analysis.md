# 2026-06-04 Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-06-measurement-campaign-analysis.md`
(SHA-256 `038a02f8760628d2013305fd7e034212c6ac57acc833c7071b18081ed5b8c68b`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb` | available |
| `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb/logs/large-cldr-json-command-2.log` | available |
| `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite` | available |
| `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite` | available |

Resolved directory moves:

- `.artifacts/20260528T155144Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb`.
- `.artifacts/20260528T155144Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite`.
- `.artifacts/20260604T204054Z-bk-cpp-duckdb` → `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb`.
- `.artifacts/20260604T204054Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite`.
- `.artifacts/20260606T145144Z-bk-cpp-sqlite` → `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`.


## Scope

This report compares the paired `bk-cpp` benchmark campaign that started on
2026-06-04 with the preceding paired `bk-cpp` campaign:

- Current SQLite run:
  `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-sqlite`
- Current DuckDB run:
  `.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb`
- Previous SQLite run:
  `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-sqlite`
- Previous DuckDB run:
  `.artifacts/benchmarks/backend/20260528T155144Z-bk-cpp-duckdb`

The newer in-progress run under `.artifacts/benchmarks/backend/20260606T145144Z-bk-cpp-sqlite`
was intentionally ignored.

## Classification

This campaign should be treated as a bug-finding campaign, not as a clean
performance measurement.

Reasons:

- The current SQLite and DuckDB halves are not the same commit:
  - SQLite: `d08e59ea3fc141071d7985662207119b084903a6`,
    `codira_version = 1.42.3.post1.dev12`
  - DuckDB: `cf689bc656ca98b62893ec3a7ba6867ed51ac7de`,
    `codira_version = 1.43.0.post1.dev1`
- The preceding paired run is an older implementation:
  - both backends: `f8190fb285ebf35dc6e57d0b19f7198858334283`,
    `codira_version = 1.26.0.post1.dev3`
- The current DuckDB campaign has campaign-level failures:
  `failure_count = 6`.
- Large-repository results are skewed by correctness failures in
  `texlive`, `llvm-project`, and `cldr-json`.

The CPU embedding context is stable enough to compare shape, but not enough to
attribute deltas to backend runtime alone:

- `embedding_device = cpu`
- `embedding_batch_size = 128`
- `torch_available = true`
- environment requested `CODIRA_TORCH_NUM_THREADS=10` and
  `CODIRA_TORCH_NUM_INTEROP_THREADS=1`
- campaign metadata reports effective `torch_num_threads=6` and
  `torch_num_interop_threads=6`, while individual phase files report
  `10` and `1` in places; this mismatch should be fixed before the next clean
  performance campaign.

## Failure Summary

Campaign-level failures:

| Run | Failure count | Labels |
| --- | ---: | --- |
| 20260528 SQLite | 1 | `llvm-project` command 4 |
| 20260528 DuckDB | 3 | `llvm-project` commands 1, 3, 4 |
| 20260604 SQLite | 0 | none |
| 20260604 DuckDB | 6 | `texlive` commands 1, 3, 4; `llvm-project` commands 1, 3, 4 |

Important detail: SQLite had no campaign-level failures in the current run,
but the index logs still report file-level failures. Those are not equivalent
to successful clean indexing.

## Bugs Found

### 1. Markdown documentation stable IDs collide

Observed in both backends, but with different blast radius.

SQLite `texlive` file-level failures:

- `utils/asymptote/LspCpp/third_party/rapidjson/doc/faq.zh-cn.md`
- `utils/asymptote/LspCpp/third_party/rapidjson/doc/features.zh-cn.md`
- `utils/asymptote/LspCpp/third_party/rapidjson/readme.zh-cn.md`
- `utils/asymptote/gc/README.md`
- `utils/asymptote/gc/doc/gcinterface.md`

SQLite reports these as:

```text
BackendError, UNIQUE constraint failed: documentation_artifacts.stable_id
```

DuckDB aborts the whole `texlive` index on the first duplicate:

```text
doc:section:utils/asymptote/LspCpp/third_party/rapidjson/doc/faq.zh-cn.md:section/section:1
```

The same class appears in `llvm-project`:

```text
doc:section:clang/Maintainers.md:active-maintainers/standards-conformance/c-conformance:1
```

Status: already fixed after the campaign by the Unicode-preserving Markdown
stable-id change that adds deterministic line identity.

### 2. DuckDB duplicate documentation embedding rows

Observed in:

```text
.artifacts/benchmarks/backend/20260604T204054Z-bk-cpp-duckdb/logs/large-cldr-json-command-2.log
```

Signature:

```text
Duplicate key "object_type: documentation, object_id: 1, backend: sentence-transformers/all-MiniLM-L6-v2, version: 1" violates unique constraint.
```

This was not an embedding determinism problem. The duplicate key is the
database identity, so the failure happens even if the vector payload is
identical.

Status: fixed after the campaign by making SQLite and DuckDB embedding writes
idempotent on `(object_type, object_id, backend, version)`.

### 3. Python analyzer file-level failures in test/fixture corpora

Current run failures:

- `large-cpython`: 67 `SyntaxError` file failures in both backends.
- `small-tree-sitter-python`: 10 `SyntaxError` and 1 `IndentationError` in
  both backends.
- `llvm-project`: 3 Python 2 `SyntaxError` files and 1 invalid UTF-8 file
  in SQLite; DuckDB did not reach equivalent file-level reporting because the
  Markdown stable-id duplicate aborted the index.

Interpretation:

- These are not backend failures.
- They are mostly corpus files outside the current Python 3 parser domain:
  future CPython syntax, bad-token fixtures, Python 2 grammar fixtures,
  malformed indentation fixtures, or invalid encoding fixtures.
- They are still useful bug-finding signals for UX: Codira currently reports
  them as file-level failures. If benchmark cleanliness matters, the campaign
  manifest should either exclude known parser fixtures or Codira should add a
  clearer unsupported/malformed-input classification.

No additional backend defect was found beyond the Markdown stable-id and
DuckDB embedding-idempotency issues.

## Timing Evidence

`timings.total` is wall-clock. `timings.embeddings` is diagnostic cumulative
hook time and is not added to total.

Top-level phase-file totals:

| Run | Phase files | Sum of `timings.total` | Sum of file failures |
| --- | ---: | ---: | ---: |
| 20260528 SQLite | 17 | 9459.302 s | 83 |
| 20260528 DuckDB | 16 | 3274.064 s | 78 |
| 20260604 SQLite | 17 | 10273.962 s | 88 |
| 20260604 DuckDB | 15 | 2057.516 s | 78 |

These totals are not directly comparable because missing/failed large labels
dominate the sums. In particular, the current DuckDB phase-file sum excludes
successful `texlive` and `llvm-project` phase JSON, while the current SQLite
sum includes them.

Common labels present in all four runs:

- `large-cldr-json`
- `large-cpython`
- `large-postgres`
- `medium-catch2`
- `medium-official-images`
- `medium-ohmyzsh`
- `medium-redis`
- `small-codira`
- `small-dataset-json-examples`
- `small-fmt`
- `small-fontshow`
- `small-nvm`
- `small-requests`
- `small-tree-sitter-c`
- `small-tree-sitter-python`

For that common subset:

| Backend | Previous total | Current total | Delta |
| --- | ---: | ---: | ---: |
| SQLite | 1905.177 s | 2008.288 s | +5.4% |
| DuckDB | 1951.925 s | 2057.516 s | +5.4% |

This is a regression signal, but not a measured backend conclusion because the
implementation versions changed between runs.

Largest common-label phase movements:

| Label | SQLite delta | DuckDB delta |
| --- | ---: | ---: |
| `small-dataset-json-examples` | +552.9% | +337.4% |
| `medium-ohmyzsh` | +183.4% | +187.7% |
| `small-fontshow` | +71.2% | +67.3% |
| `small-codira` | +47.2% | +47.4% |
| `medium-catch2` | +45.9% | +32.5% |
| `large-postgres` | -1.4% | -1.8% |
| `medium-redis` | +0.2% | +4.7% |

The similar deltas across backends suggest the common slowdown is likely in
shared indexing, analyzer, embedding, or campaign mechanics, not in one backend
alone.

Hyperfine medians in the current campaign also show the same pattern:

| Command kind | SQLite median | DuckDB median |
| --- | ---: | ---: |
| `index --full` | 20.803 s | 22.445 s |
| warm `index` | 0.487 s | 0.613 s |
| `ctx` | 6.158 s | 6.467 s |
| `emb` | 5.167 s | 5.305 s |
| `sym` | 0.533 s | 0.522 s |
| `calls` | 0.408 s | 0.442 s |
| `audit` | 0.400 s | 0.460 s |

Again, this is directional only because the two current halves are different
commits.

## Profile Evidence

Profiles exist for the current campaign under each backend's `profiles/`
directory. The preceding May paired run does not have corresponding `profiles`
directories, so profile comparisons are current-run only.

Representative current profiles:

- `small-codira-index.prof`
  - SQLite: cumulative time is dominated by
    `_flush_pending_embeddings` -> `_flush_prepared_embedding_rows`.
  - DuckDB: cumulative time is dominated by
    `_flush_pending_embedding_rows` -> `_flush_prepared_embedding_rows` and
    DuckDB Arrow registration around embedding flush.
- `large-postgres-index.prof`
  - Both backends are dominated by embedding generation/flush work.
  - DuckDB shows Arrow registration and `embed_texts` in the top cumulative
    stack.
- `large-postgres-ctx.prof`
  - Both backends show substantial import/config/backend activation overhead.
  - DuckDB additionally shows connection `execute`/`fetchall` costs, but not at
    the scale of the indexing/embedding phases.

Interpretation: the dominant performance story in this campaign is still
embedding-heavy full-index cost and command startup/query activation overhead.
The backend-specific write path matters, but the current failed campaign is
not clean enough to quantify backend throughput.

## Decisions

No-go:

- Do not use this campaign as a public or planning-grade performance baseline.
- Do not use DuckDB-vs-SQLite totals from this campaign to select a backend.
- Do not file a new issue for the Markdown stable-id or DuckDB embedding
  duplicate defects if the existing fixes remain in place.

Follow-up:

- Rerun the paired campaign after the Markdown stable-id and backend
  idempotent-embedding fixes.
- Ensure both backend halves run from the same commit and same installed plugin
  set.
- Fix the embedding runtime metadata mismatch between campaign metadata and
  phase-file metadata.
- Decide whether benchmark manifests should exclude known parser fixtures
  (`cpython` bad syntax/token data, `tree-sitter-python` grammar fixtures,
  legacy Python 2 examples) or whether Codira should classify them as
  unsupported/malformed inputs instead of generic failures.
- Keep `cldr-json`, `texlive`, and `llvm-project` in the next bug-finding run
  because they have proven useful for backend/analyzer correctness.

## Validation

Analysis inputs inspected:

- `campaign-plan.json` for all four compared runs.
- `failure-summary.json` for all four compared runs.
- `*-index-phases.json` for phase totals and file-level failure counts.
- `*-hyperfine.json` for command-kind timing medians.
- discovery and command logs for backend and analyzer error signatures.
- representative current-run `cProfile` files for index and context commands.

Report status:

- The current 2026-06-04 campaign is valid as bug-finding evidence.
- It is not valid as a clean performance measurement.
