# Architecture

This section documents the current `codira` architecture and the accepted
migration boundary introduced by
[`ADR-004`](../adr/ADR-004-pluggable-backends-migration-plan.md).

The current implementation remains:

- registry-driven
- SQLite-backed
- mixed-language across Python, JSON, Bash, and C-family analyzers
- CLI-driven through a single repository-local index

These documents describe the post-Phase-9 architecture produced by the
`ADR-004` migration branch.

- [System overview](system-overview.md)
- [Indexing pipeline](indexing-pipeline.md)
- [Query pipeline](query-pipeline.md)
- [Plugin model](plugin-model.md)
- [Core contracts](core-contracts.md)
- [Storage backends](storage-backends.md)
- [Language analyzers](language-analyzers.md)
