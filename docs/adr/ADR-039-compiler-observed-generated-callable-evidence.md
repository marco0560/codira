# ADR-039 — Compiler-observed generated callable evidence

**Date:** 26/10/2026

**Status:** Accepted for implementation and qualification

## Context

[ADR-038](ADR-038-clang-metadata-and-exact-call-identities.md) requires persisted
source-invoked generated callables. The existing version-one provenance model
represents proven generated tokens, operations and source-spelled parameter
types. Clang supplies different evidence: declaration identity, spelling and
expansion locations, and separately observed preprocessing invocation events.
Those observations cannot prove the version-one token derivation claims.

## Decision

Keep version-one fields and strict validation unchanged. Add a tagged
`compiler_observed`, format-version-two variant alongside it. Retain role,
origin, exact source digest and opaque analyzer input fingerprint, optional
compiler coordinates, and a separately correlated observed invocation. Do not
invent token operations, source-spelled types, alias derivations or expansion
stacks. Missing or ambiguous source evidence remains partial.

The producer owns a namespaced canonical JSON receipt. Core validates its shape,
size and finite values without interpreting compiler-specific semantics. Receipts
are limited to 64 KiB and depth 16; the existing complete payload limit is 8 MiB.
Context identities remain exact opaque strings, including long JSON identities.
The analyzer fingerprint, rather than only the inner frontend cache key, must
match the index file's input fingerprint.

The Clang adapters correlate a source-invoked macro callable with exactly one
preprocessing expansion event at its physical expansion position. They verify
the invocation against source bytes, produce a half-open byte range, retain the
captured source digest and callable identity, and include directly observed AST
spans in the receipt. A callable-name spelling point and a macro-body spelling
span are separate facts. Excluding compiler-only implicit/template entities does
not itself mean a source-written declaration was omitted.

Persist version two in the existing opaque `artifact_provenance` JSON column
on both structural backends. No physical schema change is required. Advance
core logical schema to 26 and both analyzer versions to invalidate old analysis.
Query evidence validates source and input freshness and labels the result
`compiler_generated`. It may expose the observed invocation as a separate fact;
it does not slice an AST range and present that as reconstructed source code.

## Qualification boundary

Use source-authored expected generated callables and verify the actual native
frontend, both adapters, full indexing and query evidence on SQLite and DuckDB.
Check exact invocation bytes, body spelling spans, source digest, full context
identity and compiler USR, as well as unchanged version-one behavior. Keep failed
attempts and raw compiler/process evidence. Synthetic DTO tests are focused
contract checks; native indexing evidence is recorded separately.

Header projection, original-repository coverage, native distribution and default
selection remain required continuation. This decision does not establish full
analyzer parity or admit benchmark originals based on helper/test success.
