# System Overview

`codira` currently consists of four practical layers:

| Layer | Current responsibility |
| --- | --- |
| scanner | discover repository files for indexing |
| indexer | orchestrate analyzer routing, normalized artifacts, and backend persistence |
| query | resolve exact and semantic retrieval against the repository index |
| CLI | expose repository-local commands and output contracts |

The implementation is intentionally repository-local:

- the CLI operates relative to the current repository root
- index data lives under `.codira/`
- exact and semantic query paths read the same SQLite database

## Current Module Shape

The current branch centers on these modules:

- `src/codira/cli.py` for command parsing and output formatting
- `src/codira/scanner.py` for Git-backed file discovery with filesystem
  fallback
- `src/codira/registry.py` for backend selection and analyzer activation
- `src/codira/indexer.py` for incremental orchestration and SQLite backend
  persistence/query implementation
- `src/codira/analyzers/python.py` and `src/codira/analyzers/c.py` for
  language-specific analysis
- `src/codira/storage.py` for SQLite initialization and schema refresh
- `src/codira/query/exact.py` for exact lookup helpers
- `src/codira/query/producers.py` for shared retrieval producer metadata
- `src/codira/query/context.py` and `src/codira/semantic/search.py` for
  context retrieval and embedding-backed ranking

## ADR-004 Boundary

`ADR-004` now defines the architecture that this branch implements:

- one active index backend per repository instance
- multiple language analyzers in one indexing run
- documentation and tests landing alongside architectural refactors

The remaining future work is no longer about introducing these boundaries. It
is about extending them without breaking the current contracts.

For retrieval specifically, the current accepted split is:

- analyzers provide indexing-time language knowledge
- shared query producer descriptors provide retrieval-facing capability
  metadata
- the query layer consumes those descriptors without depending on analyzer
  internals
