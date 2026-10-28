# ADR-041 — Clang generated alias and prototype provenance

**Date:** 27/10/2026

**Status:** Accepted for implementation; qualification pending

## Context

[ADR-038](ADR-038-clang-metadata-and-exact-call-identities.md) and
[ADR-039](ADR-039-compiler-observed-generated-callable-evidence.md) establish
compiler-observed callable identity and generated-callable provenance. The
remaining C++ parity gap is generated aliases, their linker labels and targets,
and generated prototype redeclarations sharing a Clang USR with a definition.

Clang reports several distinct facts here. A GNU alias operand names a linker
target; an `AsmLabelAttr` supplies a label on a declaration; Clang's linker
symbol is the compiler-derived linker spelling; and a canonical declaration USR
identifies a callable. These values are not interchangeable. Likewise,
`is_definition` does not establish that a declaration has a function body, and
the Clang display signature is not the source-spelled declaration.

## Decision

Keep version-one token-derived and version-two compiler-observed payloads
strict and outer-payload-shape compatible. Version-two implementation receipts
may retain additional producer-owned native observations without changing the
version-two field set. Introduce a separate
`compiler_observed` format-version-three payload for callable alias and
prototype roles. V3 carries nullable generic fields `alias_target_identity`
(`SemanticIdentity`) and `linkage_name`; the producer receipt remains bounded,
canonical, and namespaced. Core validates these fields but does not interpret
compiler attributes or linker names.

The frontend receipt retains the distinct native observations:

- `alias_target_symbol`: the raw GNU alias operand;
- `alias_target_usr`: the canonical declaration USR only after unique exact
  binding;
- `explicit_linkage_label` and `linkage_label_inherited`: an `AsmLabelAttr`
  value and whether Clang reports it as inherited;
- `linker_symbol`: Clang's compiler-derived linker spelling;
- `alias_binding_status`: `resolved`, `unresolved`, `ambiguous`, or `not_alias`;
- `has_body`, separately from `is_definition`;
- `signature_kind`, currently `derived_display_only`.

The frontend decoder rejects inconsistent status/target pairs: `resolved`
requires an `alias_target_usr`, and every other status requires it to be null.
Only a uniquely resolved `alias_target_usr` becomes V3
`alias_target_identity`. Missing or ambiguous bindings keep that field null and
remain unresolved. An explicit/inherited assembler label on an alias maps to V3
`linkage_name`; prototype labels stay in the producer receipt. The GNU alias
operand does not populate `linkage_name`. Producer receipts retain both
raw operands so qualification can verify the distinction.

Alias artifacts have role `alias`, no body calls and no body line range.
Clang may still classify an alias declaration as a definition; that fact does
not prove the presence of a body. Body calls and return facts are emitted only for a
declaration with an observed body that is not an alias. A generated prototype
sharing a USR with a definition is retained as an `OverloadArtifact` under the
definition's stable ID, with its own V3 `prototype` provenance and declaration
coordinates. USR deduplication must not discard it.

Internal and `UniqueExternal` identities include both the canonical main
translation-unit path and the canonical declaration-file path. This prevents same-basename files in different directories from colliding
and keeps translation-unit-unique declarations scoped to their source. Ordinary
external-linkage identities retain the same USR across translation units when
Clang reports the same external declaration.

Clang linkage is separate from the existing `is_public` visibility flag. Free
function visibility retains its static-storage heuristic and method visibility
retains access control; qualification must not infer exact linkage from either.
Compiler linkage checks join the native record to persisted exact identities.

Reopened namespace declarations coalesce only when compiler USR, full qualified
name and the existing file-scoped namespace stable ID agree. Keep the last
source declaration's coordinates, signature and documentation, matching the
legacy parser, and emit its Doxygen artifact once. Distinct fully qualified or
translation-unit-local namespaces must not collapse. Inconsistent identities
fail closed.

Both V2 definition and V3 alias/prototype receipts preserve
`signature_kind=derived_display_only`.
`FunctionArtifact.signature` remains presentation text and is not treated as a
source excerpt. A source-signature channel populated only from proven physical
source bytes remains unfinished; no signature tokens or source spellings are
reconstructed from Clang's display string.

Query evidence labels V3 artifacts `compiler_generated`. For an alias, it may
return source text and line bounds only when the same-file observed
preprocessor invocation matches the indexed bytes exactly. Without that proof,
the response omits `source`, `start_line`, and `end_line`; it retains the
structured invocation observation when available. Version-one and version-two
query behavior remains unchanged.

The integration versions are core logical schema 27, C analyzer 2.0.19
(logical 28), C++ analyzer 2.0.48 (logical 47), shared frontend 0.4.0 with
native protocol 5, official bundle 2.0.83, and physical backend schema 29.
Backend and installer versions remain unchanged in this phase.

## Qualification boundary

Qualification must use source-authored fixtures and persisted SQLite and DuckDB
rows. It must separately verify alias operand, alias label, direct target USR,
unresolved/ambiguous target, body suppression, same-USR prototype retention,
same-basename internal-linkage separation, the derived signature marker, and
strict V1/V2 payload compatibility. A successful DTO test or native-helper
build is not native indexing qualification.

This ADR does not establish actual native qualification, full repository
coverage, supported-platform installation, default-frontend selection, or
source-signature preservation. Record those results in the qualification report
template and leave unverified items pending.
