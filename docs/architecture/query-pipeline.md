# Query Pipeline

The current query surface is exposed through `src/codira/cli.py` and backed
by two query families:

- exact lookups in `src/codira/query/exact.py`
- embedding-assisted retrieval in `src/codira/semantic/search.py` and
  `src/codira/query/context.py`

## Exact Query Flow

Exact commands such as `sym`, `calls`, `refs`, and `audit`:

1. normalize optional repo-root-relative prefix filters
2. delegate exact lookup work to the active index backend
3. execute deterministic backend-backed retrieval against indexed artifacts
4. emit stable human or JSON output

Phase 7 moved these exact lookup surfaces behind backend methods instead of
having `query/exact.py` own raw SQLite connection setup and SQL execution.

## Context Retrieval Flow

`ctx` combines:

- exact-symbol matches
- docstring issue matches
- bounded graph evidence from static references, call edges, and include edges
- embedding-ranked candidates

The current retrieval stack merges these channels into a deterministic context
report for either human-readable, JSON, or prompt-oriented output.

The embedding channel now depends on persisted real vectors built during
explicit indexing rather than a placeholder local hash projection. Explain
output also reports the active embedding backend metadata so retrieval
diagnostics can be tied to a concrete backend contract.

Phase 17 adds an explicit retrieval planner in
`src/codira/query/classifier.py`. The planner classifies each query into a
deterministic primary intent family:

- behavior or implementation
- test or validation
- configuration
- API surface
- architecture or navigation

The resulting retrieval plan now owns:

- channel routing order
- explain-mode planner diagnostics
- whether docstring issue enrichment should run
- whether include-graph expansion should run
- whether cross-reference collection should run

The current `ctx` implementation uses call-graph, callable-reference,
and include-graph data twice but in bounded forms:

- as low-weight retrieval-time evidence that can support ranking
- as bounded post-merge expansion around the current top matches

The current capability-driven retrieval path also owns shared retrieval
producer metadata in `src/codira/query/producers.py`.

That layer now declares:

- stable producer identity
- producer and capability versions
- retrieval capability sets for channel and enrichment producers

The query core consumes those descriptors generically. It does not require
built-in analyzers to implement retrieval capabilities directly, and it must
not depend on analyzer internals to rank evidence.

Phase 7 also moved the embedding channel behind backend methods. The semantic
wrapper in `src/codira/semantic/search.py` now delegates to the active
backend instead of owning direct SQL access to the embedding tables.

## ADR-004 Query Implication

The CLI contracts remain unchanged, but exact-query and embedding-query paths
now depend on backend methods rather than raw SQLite access. Later phases can
build registries and alternate backends against that seam instead of patching
query modules directly.

Phase 8 completes the backend-selection side of that boundary by routing query
entry points through `codira.registry.active_index_backend()`.

## Repository-local warm query daemon (contract)

ADR-026 establishes a second optional daemon for repeated read/query work. It
is scoped to one resolved repository root and effective output directory, and
will retain warm plugins, an embedding model, and a backend read connection.
The automatic indexing daemon remains the only automatic writer; SQLite and
DuckDB remain authoritative. MCP and eligible CLI commands will use the
service opportunistically and fall back to direct-core execution.

The service is not a repository catalogue and never accepts request-provided
repository paths. Cross-repository service selection remains the separate #51
boundary.

### Warm runtime ownership

The warm runtime owns one backend read connection on a dedicated worker thread
and serializes v1 operations through that worker. It reads only the durable
generation record for its fixed repository/output identity. A `ready` record
builds a replacement session before the runtime swaps it in; `updating` never
becomes current. Direct context retrieval remains unchanged when no supplied
connection is present.

Each worker also holds one effective-configuration and active-plugin scope for
the lifetime of that session. The configured structural backend, vector store,
and embedding engine are therefore reused by repeated reads. When embeddings
are enabled, session warmup initializes the vector store and loads the model
before the session is published. A warmup failure leaves no partial session
installed, so a caller can continue through the existing direct-core path.
Session retirement closes the backend connection, invokes an available vector
store close hook, and clears plus closes the embedding runtime before its
worker-local plugin scope is released.

`MCPAdapter` accepts an optional connection-owning query executor. With no
executor it preserves the current direct-core behavior; with one it sends
approved structural and context reads to the executor while retaining the MCP
startup-trusted-root boundary. IPC proxying and automatic discovery remain
later slices, not part of this in-process seam.

Phases 12 through 17 complete the ranking and retrieval side by adding:

- deterministic file-role classification
- evidence-based merge diagnostics
- diversity-aware result selection
- query-usable include-graph expansion for C
- language-specific semantic text units
- planner-driven retrieval routing

The corresponding indexing-side requirement is now explicit as well:

- analyzers emit durable symbol identities
- changed files preserve unchanged symbol embeddings when their semantic
  payload hash still matches
- query-time semantic work reads persisted vectors only
