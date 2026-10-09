# Issue #15 local family federation delivery

Approved on 2026-10-09: federated independent indexes; versioned TOML manifests
referencing registered workspaces; optional descriptive roles; family context,
exact symbols, and explicitly linked references through CLI/MCP; startup-bound
MCP member selection; reciprocal-rank merging; strict default with explicit
partial results; attempt every member index and preserve individual outcomes;
dedicated local feature branch with tests, documentation, and commits.

Implementation branch: `feat/multi-repo-family`. This delivery does not authorize
a push, PR, merge, release, or GitHub issue closure.

The implementation contract is [ADR-033](../adr/ADR-033-local-family-federation.md).
The runnable workflow and recovery steps are in [the family guide](../families.md).

## Delivery surfaces

- `family.py`: strict v1 manifest and startup-pinned workspace routing.
- `family_runtime.py`: independent member scopes, readiness/source checks,
  repository-qualified identities, global rank merge, explicit link validation,
  complete member paging, and all-member continuation binding.
- `cli_family.py`: family indexing, status/validation, discovery and evidence.
- `mcp/family_server.py` and MCP startup: read-only family tools and schemas.
- DuckDB plugin: optional owner-scope `close()` releases cached native handles
  and unregisters process-exit cleanup, while allowing subsequent reuse.
- Documentation: guide, architecture decision, navigation, and maintained Ruff
  suppression rationale. Repository and global `AGENTS.md` remain unchanged.

## Validation evidence

The initial family checks passed against mixed SQLite/DuckDB indexes. An existing
MCP daemon test required unrestricted local Unix socket binding. The real family
stdio test exposed DuckDB's process-lifetime connection cache; explicit plugin
scope cleanup resolved the lock conflict. The real MCP client subsequently
initialized the family server and asserted repository origins, whole-definition
evidence, explicit links, and context from both members: one transport test
passed on 2026-10-09. This checks actual indexed facts through the stdio transport.

Examined final results on 2026-10-09:

- Focused family, MCP, workspace, DuckDB and quality-policy checks: 81 passed,
  one skipped. Additional shared-state, discovery and capability checks: 14 passed.
- Quality preflight: index refresh, Ruff, formatting, core/package typing,
  Semgrep and docstring audit all returned zero; 21 Semgrep rules had no findings.
- Final full repository gate: exit zero, 1,478 passed and three skipped in
  517.75 seconds; overall coverage 86%. Index refresh reused 741 files with no
  failures, pending embeddings or source-coverage issues.
- Strict MkDocs build: exit zero, completed in 2.41 seconds.

The final gate ran in `codira-family-gate-20261009-r2` with a separately recorded
exit status. A fresh short pytest temporary path was selected after a slow native
Semgrep filesystem traversal in the first successful gate; the final run retained
the same repository validation command, rules and test selection. Completed gate
sessions and temporary gate records are cleaned only after examination and
reporting, under the repository's validation retention policy.

All implementation changes remain on `feat/multi-repo-family`. This delivery
includes a local commit only; no external publication or issue closure occurred.
