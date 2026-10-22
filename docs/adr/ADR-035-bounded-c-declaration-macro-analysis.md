# ADR-035 — Bounded opt-in C declaration-macro analysis

**Date:** 22/10/2026
**Status:** Accepted by the operator (option A)

## Context

The C analyzer has source-backed include context and generated-callable
provenance, but it does not model declarations produced by C function-like
macros. A frozen set of 92 PostgreSQL originals invokes a file-scope
declaration macro that native syntax-only captures expand into a callable
prototype and definition. The static `Pg_magic_data` declaration is inside the
generated function body; it is not a top-level modeled declaration. The
retained native captures and exact source/header hashes are evidence for this
candidate family, not an implementation selector or a promised recovery count.

The operator approved this separate C capability on 22/10/2026. This is an
independent C decision. [ADR-034](ADR-034-bounded-cpp-declaration-macro-analysis.md)
authorizes C++ only and does not grant this capability.

## Decision

Add bounded declaration-macro expansion to the C analyzer behind the explicit
`expand_declaration_macros` option. Its default is false. Expansion inputs are
limited to the original translation unit and exact repository-contained headers
already captured by the C include-context mechanism. Definition selection is
ordered at each source invocation. Ambiguous, conditional-unknown, undefined,
unsupported, malformed, or over-budget macro state remains unexpanded, and the
original parser diagnostic remains visible.

The analyzer may blank a declaration-macro site only after it has fully
expanded and parsed the selected replacement and proved that every generated
top-level artifact is represented by the existing callable model. Unsupported
top-level objects, types, declarations, extra declarators, and unrepresented
functions reject the complete site. The source invocation and its associated
terminating semicolon are removed only from the coordinate-preserving parse
projection; original source bytes and physical coordinates remain unchanged.
Ordinary calls and calls inside function bodies are not declaration sites.

Retain generated callables through the existing
`GeneratedCallableProvenance`. Generated token spellings carry an invocation
anchor unless a token comes from an exact contiguous source-argument span.
Source-argument call targets retain their physical source coordinates;
replacement-only calls anchor to the invocation. Preserve the full parameter
declarator spelling after removing only the declared parameter name. When one
expansion declares both a prototype and definition for the same function, use
the existing C semantic rule and retain the definition; retain a prototype
when it is the only callable declaration. This keeps identity independent of
line and byte offsets while the generated token evidence retains the complete
expansion. Conflicting same-role signatures remain held.

No core schema change, compiler execution, build-system execution, arbitrary
external header read, or indexing-time native subprocess is introduced. The
configuration and exact source/header context already participate in analyzer
input identity; C logical analyzer version advances from 18 to 19. Advance the
C distribution from 2.0.8 to 2.0.9 and the coordinated official bundle to
2.0.67 with consistent exact pins and generated lock data.

## Validation and qualification

Unit tests cover option default and validation, source-order definitions and
undefinitions, conditional uncertainty, include guards, replacement bounds,
unsupported token operations, argument token origins, generated calls,
parameter declarators, unrelated syntax errors, ordinary calls, and rejected
unmodeled top-level artifacts.

Candidate qualification is separate from implementation tests. Compare each
unchanged original against retained independent native metadata, including
generated names, prototype/definition roles, signatures, parameters, calls,
source/header inputs and origin coordinates. Then index through the real Codira
CLI into SQLite and DuckDB and inspect the complete persisted result. Require
negative controls for wrong or missing metadata and retain per-candidate
checkpoint receipts keyed by source, context, compiler and analyzer versions.
Parser cleanliness, successful expansion, or native syntax acceptance alone
qualifies no file. Keep unsupported candidates open and let the parent update
the authoritative classification ledger.

## Consequences

The explicit option can recover source-backed generated C callables without
changing default analysis or introducing a compiler dependency. Strict
site-level rejection limits false clean results, but valid macros outside the
supported bounded replacement grammar remain partial. Native and persisted
qualification remain necessary before any candidate is classified fixed.
