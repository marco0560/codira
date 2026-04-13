# Indexing Pipeline

The current indexing entry point is `index_repo()` in
`src/codira/indexer.py`.

## Current Flow

1. The CLI resolves the repository root and calls `index_repo()`.
2. `scanner.iter_project_files()` derives file-discovery globs from the active
   analyzer set, discovers tracked matching files through Git, and falls back
   to a filtered filesystem scan outside Git repositories.
3. `indexer.py` compares current file metadata against stored index state to
   decide whether each file is indexed, reused, or deleted.
4. Reindexed files are routed to the first registered analyzer that supports
   each path.
5. The selected analyzer emits one normalized `AnalysisResult` per file.
6. Normalized semantic artifacts now include analyzer-owned durable symbol
   identities for every embedding-owning unit.
7. The same indexing pass computes persisted embeddings for indexed symbols.
8. When a file changes, the backend compares old and new stable-id sets so
   unchanged symbols can reuse stored vectors while disappeared symbols are
   removed deterministically.
9. The active backend persists all artifacts into `.codira/index.db` and
   rebuilds derived indexes.
10. Canonical source directories are audited for uncovered tracked files so the
   summary can report files under `src/`, `tests/`, or `scripts/` that no
   active analyzer currently covers.
11. After a successful run, the backend persists the runtime plugin inventory
   and per-file analyzer ownership so later phases can compare current plugin
   availability against the indexed state.

## Phase-5 Orchestrator Boundary

Phases 5 through 9 make `index_repo()` act as an explicit orchestrator:

1. discover current files and metadata
2. compute incremental indexing decisions
3. route indexed files through registered language analyzers
4. collect normalized `AnalysisResult` artifacts
5. delegate persistence to the selected backend
6. rebuild derived backend indexes

The current analyzer registry is package-driven:

- `PythonAnalyzer` for `*.py` from `codira-analyzer-python`
- `JSONAnalyzer` for supported JSON families from `codira-analyzer-json`
- `CAnalyzer` for `*.c` and `*.h` from `codira-analyzer-c`
- `BashAnalyzer` for Bash scripts from `codira-analyzer-bash`

The important Phase 18 boundary is now in place: file discovery follows
analyzer metadata rather than a hard-coded scanner tuple, so future
third-party analyzers can participate in indexing without changing scanner
code.

Phase 19 adds a deterministic coverage-audit layer on top of that discovery:

- tracked canonical-directory files are inspected even when they are not
  covered by any active analyzer
- uncovered files are reported in the index summary
- indexing still proceeds for covered files

Phase 20 adds persisted run ownership metadata:

- each indexed file records the analyzer name and version that produced it
- the database stores the backend inventory and analyzer inventory for the
  successful run
- coverage-complete state is persisted alongside the runtime inventory

Phase 21 makes that persisted metadata active in rebuild policy:

- unchanged files are reindexed when their owning analyzer name or version no
  longer matches the stored ownership metadata
- CLI canary checks rebuild when the stored backend inventory no longer matches
  the active backend
- CLI canary checks rebuild when the stored analyzer inventory no longer
  matches the active analyzer set

Phase 22 adds the operator-facing coverage controls:

- `codira cov` reports canonical-directory gaps without mutating the
  index
- `codira index` continues to warn by default through its summary output
- `codira index --require-full-coverage` fails before indexing when
  canonical tracked files remain uncovered

## Current Coupling

The current implementation still combines two SQLite-specific responsibilities
inside `indexer.py`:

- incremental orchestration decisions
- direct SQLite backend implementation details

Language-specific extraction no longer lives in the indexer itself.

## Stability Requirements

Current behavior that later phases must preserve unless explicitly changed by a
new ADR:

- deterministic file-order processing
- deterministic per-file reuse decisions
- deterministic stable-id ownership for embedding-bearing symbols
- stable CLI-visible indexing summaries
- deterministic symbol-embedding persistence
- deterministic analyzer routing by registry order
