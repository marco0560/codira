# Vector-store authority redress campaign — 2026-07-20

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-20-vector-store-authority-redress-campaign.md`
(SHA-256 `ad7bfd778ff48fe93d9619558cb4d5db9a1c46e7e61d6448877e65e37961e4a7`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/vector-store-authority-redress-20260719T134147Z/` | unavailable historical path |


## Decision

**No-go: do not integrate `refactor/vector-store-authority`.**

The campaign did not satisfy the complete 2x2 merge gate.  The two candidate
SQLite-vector-store runs both contain two failed profiling commands, and the
candidate has severe semantic-query regressions even where commands returned
successfully.  The candidate DuckDB-vector-store half of the matrix was never
started because the outer shell stopped after the non-zero candidate SQLite
campaign status.

## Sources and parity

Campaign root:
`.artifacts/benchmarks/vector-store-authority-redress-20260719T134147Z/`

Six run directories completed:

| Revision | Vector store | Structural backend | Failures |
| --- | --- | --- | ---: |
| main | SQLite | SQLite | 0 |
| main | SQLite | DuckDB | 0 |
| main | DuckDB | SQLite | 0 |
| main | DuckDB | DuckDB | 0 |
| candidate | SQLite | SQLite | 2 |
| candidate | SQLite | DuckDB | 2 |

The candidate worktree contained uncommitted redress changes.  Therefore its
`campaign-plan.json` still records commit `5e30bb3`, while the installed Codira
version is `1.49.0.post1.dev2` and the SQLite vector-store plugin is `1.0.3`.
The main runs use the repository checkout and have the same target repositories,
ONNX model paths, CPU embedding configuration, five Hyperfine repetitions, and
one warmup.  This establishes a useful operational comparison but not a
commit-only comparison.

All runs use ONNX BGE-small on CPU with effective batch size 32.  Wall-clock
phase `total` is reported separately from diagnostic `embeddings` timing; the
two are not added.

## Results

The decisive like-for-like commands are the Codira-repository commands, which
use the same query in main and candidate.

| Structural backend | Command | Main SQLite vectors mean | Candidate SQLite vectors mean | Delta |
| --- | --- | ---: | ---: | ---: |
| SQLite | `index` | 0.528 s | 0.583 s | +10% |
| SQLite | `ctx _inspect_index_rebuild_request` | 1.365 s | 42.889 s | +3042% |
| SQLite | `emb _inspect_index_rebuild_request` | 1.040 s | 35.114 s | +3276% |
| DuckDB | `index` | 0.676 s | 0.671 s | -1% |
| DuckDB | `ctx _inspect_index_rebuild_request` | 1.830 s | 39.377 s | +2052% |
| DuckDB | `emb _inspect_index_rebuild_request` | 1.749 s | 33.401 s | +1810% |

The full-index Hyperfine command is near parity, but it is not enough to offset
the semantic retrieval regression, especially given the workflow weighting of
frequent reads over rare full indexes.

The phase files are consistent with that distinction: candidate DuckDB
structural indexing is low (`indexing` 5.213 s for CPython), while candidate
SQLite structural indexing remains expensive (3578.192 s for CPython).  Those
phase values diagnose different paths and must not be combined with each other
or with the Hyperfine means.

## Functional failures

Both failed candidate profiling commands originate in
`SQLiteVectorStore.similarity_scores`:

* CPython with SQLite structural backend: `k=7681` exceeds sqlite-vec's 4096
  KNN limit.
* Redis with DuckDB structural backend: `k=4324` exceeds the same limit.

The implementation passes the complete binding count as `candidates.k` and
then fetches all nearest rows.  This both violates sqlite-vec's hard limit and
explains the large successful-query regressions below the limit: the query path
still materializes far more candidates than a context request needs.

## Required correction before rerunning

1. Evolve vector retrieval to bounded, paged candidate retrieval.  Start with a
   deterministic page (for example `max(64, 8 * requested_limit)`) and cap each
   sqlite-vec KNN request at 4096.
2. Resolve prefix/structural filtering after each page and request the next page
   only while the caller still needs candidates.
3. Add tests for a vector set above 4096 bindings, bounded page size, prefix
   filtering spanning multiple pages, and parity of the returned top results.
4. Rerun the complete eight-run 2x2 matrix.  A candidate run with any non-zero
   `failure_count` is an automatic no-go.

## Validation and retained evidence

The code-level validation before this campaign passed: 67 targeted tests,
Ruff, mypy, and `scripts/validate_repo.py`.  The measurement gate supersedes
that result for integration because it found real runtime failures and
regressions.

Retained under the campaign root are all campaign plans, manifests, configs,
failure summaries, Hyperfine JSON, utility summaries, phase JSON, profile
summaries, and command logs.  Raw profiler binaries and rendered profiler HTML
are redundant with `profile-summary.json` for this diagnosis and can be
deleted safely.
