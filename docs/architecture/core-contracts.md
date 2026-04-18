# Core Contracts

`ADR-004` Phase 3 introduces explicit backend-neutral contracts in code:

- `src/codira/contracts.py`
- `src/codira/models.py`
- `src/codira/normalization.py`

These modules are the first durable abstraction layer between language
analysis, normalized artifacts, and persistence.

## `LanguageAnalyzer`

Responsibilities:

- decide whether an analyzer accepts a file path
- analyze one source file relative to a repository root
- emit one normalized `AnalysisResult`

Invariants:

- analyzers own language-specific parsing only
- analyzers do not own backend initialization or persistence
- emitted artifact ordering must be deterministic
- emitted embedding-bearing artifacts now carry durable analyzer-owned symbol
  identities used for cross-run reuse
- first-party analyzers declare their canonical ontology coverage through
  `analyzer_capability_declaration()`

## Layer 0 Capability Contract

Issue #7 adds a machine-readable capability contract exported by:

```bash
codira caps --json
```

The export includes:

- the canonical ontology version and object types
- command intents, channels, guarantees, and limitations
- retrieval producer declarations and known capability names
- analyzer declarations mapping native artifacts to ontology types
- validation status for the active analyzer declarations

The canonical ontology is intentionally small:

- `module`
- `type`
- `callable`
- `import`
- `constant`
- `variable`
- `namespace`

Analyzer declarations must explicitly list both supported and unsupported
ontology types. Missing declarations produce degraded capability metadata in
the default export and remain hard failures under `codira caps --strict`;
codira must not infer analyzer semantics from emitted rows or from missing
fields.

## `RetrievalProducer`

`ADR-006` adds a retrieval-facing contract beside `LanguageAnalyzer`.

Responsibilities:

- expose versioned producer identity for retrieval diagnostics
- declare retrieval capabilities through explicit metadata
- let the query core reason about score-bearing evidence generically

Invariants:

- retrieval producers do not own final score policy
- the core must consume declared producer metadata rather than analyzer
  internals
- the accepted first migration path keeps producer metadata in shared
  query-side descriptors instead of requiring all analyzers to implement
  `RetrievalProducer`

## `AnalysisResult` and Normalized Artifacts

The normalized artifact model currently includes:

- `ModuleArtifact`
- `ClassArtifact`
- `FunctionArtifact`
- `ImportArtifact`
- `CallSite`
- `CallableReference`
- `FileMetadataSnapshot`

Invariants:

- one `AnalysisResult` represents one source file
- module, class, function, import, call, and reference ordering is stable
- module, class, function, and declaration artifacts now expose durable stable
  identities independent of database row ids
- integer flags stay compatible with the existing SQLite schema while the
  migration is in progress
- logical callable identity remains `function` or `Class.method`

## `IndexBackend`

Responsibilities:

- initialize repository-local backend state
- load indexed file hashes for incremental decisions
- delete persisted artifacts for removed or reindexed paths
- persist one normalized file analysis
- count reusable semantic artifacts for unchanged files
- rebuild derived backend indexes after raw persistence

Invariants:

- exactly one backend is active for one repository index
- backends own storage policy, not language parsing
- backend operations are repository-root-scoped and deterministic

## Current Boundary

The Phase 3 contract layer is now active in the live indexing path:

- analyzers emit `AnalysisResult` objects into the orchestrator
- the registry activates analyzers and the concrete backend
- the SQLite backend persists and serves current query needs

The remaining extension work is additive rather than foundational.

The current split is therefore explicit:

- analyzers own extraction and normalized indexing artifacts
- retrieval producers own retrieval-facing capability metadata
- the query layer bridges those through shared producer descriptors rather than
  analyzer-specific branching
