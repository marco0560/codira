# Partial indexes and recovery

Codira commits successful file analyses even when another selected file fails.
A ready generation with at least one successfully indexed file is queryable.
Every CLI index-dependent response warns on stderr when source analysis is
partial. JSON responses include `index_coverage`; MCP responses include the same
object under `provenance.index_coverage`, plus `partial_index_warning`.
Context JSON uses the MCP envelope. Metadata reports usable/partial/complete,
indexed/attempted/failed counts and failed paths. Complete refers only to the
selected analyzer-supported scope. Repository-wide completeness is never implied.
In particular, empty references or impact results cannot prove that omitted files
contain no references or dependents. Static analysis also cannot prove dynamic
completeness, even after all selected files succeed.

Generation schema 2 retains relative failed paths, hashes of the attempted source,
analyzer identity and original diagnostics, and a digest of effective configuration.
Unchanged failures are reused during automatic freshness refreshes. Changed failed
source, analyzer identity or configuration triggers another attempt on CLI freshness
refresh or daemon reconciliation. MCP stays read-only; use the CLI or daemon to refresh it. Ordinary
`codira index` and `codira index --full` explicitly retry failures. A legacy partial
generation without snapshots is refreshed once to establish the ledger. Missing
indexes retain automatic initialization; existing corrupt, failed/updating or
zero-file indexes remain fatal for queries and require explicit recovery.

From the repository with its configured environment:

```bash
uv run codira index --json
uv run codira sym NAME --json
uv run codira cov --json
```

For registered isolated state, use `--workspace WORKSPACE` on each command. Correct
the failed source before indexing, or explicitly configure analyzer exclusions and
coverage exclusions where appropriate; exclusions change the selected scope and
must never be described as analysis of the excluded source. Strict
`--require-full-coverage` rejects source failures as well as coverage gaps.
Structural readiness is independent of embedding readiness. Deferred/pending
embeddings require `codira index --embeddings-only --json` before measurements
that require those vectors. This does not retry structural analysis failures.

The core generation format advances from 1 to 2. Backend DDL and plugin runtime
versions are unchanged because failure snapshots belong to the core publication
contract; existing independent analyzer fixes and official bundle pins are retained.

Family queries require `--allow-partial` (MCP `allow_partial: true`) to include usable partial members. Their generation vector preserves each member's coverage. Strict family indexing still returns a nonzero status for a member analysis failure.
