# Clang metadata and exact-call port qualification — 26 October 2026

This phase implements [ADR-038](../adr/ADR-038-clang-metadata-and-exact-call-identities.md).
The shared frontend supplies typed metadata to both analyzer plugins. Exact
compiler identities now persist through both structural databases and graph
queries, including both endpoints of overloaded calls. This is an optional
Clang integration; Tree-sitter remains the default and fallback.

## Implemented and measured scope

Includes, preprocessing declarations, documentation, enum members, return flags,
variables and record fields are projected into core artifacts. Both databases
retain declaration signatures and analyzer-reported type text, ownership and
access. C struct/union fields use the actual native decoder labels
`entity_kind=variable, decl_kind=Field`, including the distinction from local
variables. Out-of-line C++ methods retain their physical implementation source
and header owner without introducing an implementation-file class definition.
Macro arguments use their physical spelling coordinates; replacement-only
calls anchor to their expansion. Type text and signatures do not promise a
canonical fully qualified type vector or reconstructed preprocessing tokens.

Exact calls resolve only to one matching compiler identity. Missing, external,
indirect and ambiguous targets remain unresolved without display-name guessing.
Internal-linkage identities include the actual translation unit and declaration
file; external identities remain comparable across translation units. Both
endpoint stable IDs survive persistence, filtering and graph traversal.

A source-authored oracle covers nine translation units: C metadata, C++ records
and overloads, cross-unit external calls, out-of-line ownership, same-basename
static functions and static header functions in distinct translation units.
Fresh indexing used the actual indexer and both structural backends. Each run
indexed nine files with zero failures. Backend identity was verified from
persisted metadata; a caller-supplied backend label is insufficient.

The final ordinary-phase grade passed on SQLite and DuckDB with zero required
failures. Overall qualification remains incomplete: the grader retains eight
pending assertions for two source-invoked macro-generated callables, one
header-defined macro and five requested header projections. Its process exits
nonzero while this full-scope work remains pending. Owning-TU discovery from
captured dependencies is not successful requested-header projection.

## Evidence and validation

The qualification worktree retains immutable evidence under
`.artifacts/worktrees/clang-parity-oracles-r1/.artifacts/analysis/clang-parity-qualification-20261026-r1/`.
`snapshots-final-r2/grade-process/stdout.bin` records the two phase grades.
`source-freeze-final-r2.json` binds 54 source, helper, profile, database, snapshot
and terminal-evidence files. Parent verification matched all 54 hashes.

The remediation worktree retains its parent audit and validation records under
`.artifacts/analysis/parser-diagnostics-20261017-r1/clang-analyzer-port-20261026-r1/integration-r1/`.
Repository preflight and full-gate terminal receipts record the actual command,
source candidate, result and raw output. Earlier failed checks, invalid backend
selection, superseded grades and the interrupted first gate remain retained.
No failure was removed from the evidence history.

Local distribution versions are frontend 0.2.0, C 2.0.16, C++ 2.0.45, SQLite
2.0.7, DuckDB 2.0.11 and official bundle 2.0.80. Core logical schema is 25;
both physical structural schemas are 29. Analyzer logical versions are C 25
and C++ 44; native protocol is 3. The installer catalog is unchanged.
No packages were published.

## Required continuation

Implement truthful compiler-origin provenance for generated callables, actual
header projection through owning translation units, reusable build/generated-
header preparation, larger real-repository semantic qualification and native
installation/platform evidence. Default selection remains a separate decision.
The canonical ledger remains 5,030 verified, 716 separated and 20,016 open.
No helper test, clean AST or selected-field grade was counted as a verified
original benchmark-file fix. The complete analyzer-port goal remains active.
