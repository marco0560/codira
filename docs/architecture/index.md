# Architecture

This section documents the current `codira` architecture and the accepted
migration boundary introduced by
[`ADR-004`](../adr/ADR-004-pluggable-backends-migration-plan.md).

The current implementation remains:

- registry-driven
- backed by one active storage backend, defaulting to SQLite
- mixed-language across Python, JSON, C, C++, and Bash analyzers
- CLI-driven through a single repository-local index

These documents describe the current architecture produced by the accepted
`ADR-004` migration work and later backend/analyzer extensions.

- [System overview](system-overview.md)
- [Indexing pipeline](indexing-pipeline.md)
- [Query pipeline](query-pipeline.md)
- [Plugin model](plugin-model.md)
- [Core contracts](core-contracts.md)
- [Storage backends](storage-backends.md)
- [Language analyzers](language-analyzers.md)
