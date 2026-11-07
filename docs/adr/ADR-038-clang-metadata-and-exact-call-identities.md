# ADR-038 — Shared Clang metadata and exact callable identities

**Date:** 26/10/2026

**Status:** Accepted for implementation; integrated qualification in progress

## Context

The operator approved continuing [ADR-037](ADR-037-optional-shared-clang-production-integration.md)
through complete C/C++ analyzer parity, reusable build contexts and native
qualification. The initial frontend retained compiler-resolved targets in raw
evidence but the core call contract and structural databases discarded them.
Name-only edge keys also collapsed overloaded callers and callees. Out-of-line
C++ definitions could be rejected when their class was defined in a header.

## Decision

Add a generic opaque `SemanticIdentity(namespace, value)` to function artifacts
and call targets. Core and backends compare identities without interpreting a
compiler-specific encoding. Clang emits namespace `clang.usr.v1`. External
identities remain comparable across translation units; internal-linkage identities
include the actual canonical translation unit and declaration file. The latter
prevents same-basename files and static header functions from cross-binding.

An exact call resolves only to one matching definition. Missing, ambiguous,
external or indirect targets remain unresolved, including when a matching display
name exists. Existing analyzers retain their default resolution behavior.
Persist both caller and callee stable identities in derived edges, and carry
those identities through filters, deduplication and graph traversal. Normalize
legacy seven-field third-party edge rows at the core boundary.

Native protocol v3 supplies typed declarations, includes, preprocessing events,
documentation, callable qualifiers, returns, source ranges and call provenance.
Adapters preserve existing supported C/C++ metadata and add ordinary variables
and C++ fields explicitly. Fields retain their owner and access. Out-of-line
methods retain physical implementation coordinates and header ownership without
creating a class definition in the implementation file. Do not invent language
semantics the previous analyzers did not provide.

Preserve declaration signatures and analyzer-reported type text in both
structural databases. Embedding input alone is not persistent declaration
metadata. Compiler type text is not a claim of source-spelled token derivation.

Advance core logical schema to 25 and both structural schemas to 29. Advance
analyzer logical versions and affected plugin distributions. Existing indexes
must follow their established schema-mismatch rebuild contract. Keep shared
frontend records independent of core artifacts.

## Compiler-observed declaration origins — 28 October 2026

The existing variable/constant artifacts, including record fields represented as
variables, may carry `CompilerObservedDeclarationProvenance`. Its distinct
`compiler_observed_declaration` variant uses format version 1. Callable provenance
versions 1, 2 and 3 retain their exact contracts; declaration evidence has no
callable role, body or parameter claims.

Bind declaration evidence to the native declaration identity and metadata, the
source digest, analyzer context, raw compiler receipt and one source-invoked
macro event. Keep compiler spelling and expansion coordinates separate. Exact
invocation bytes establish the physical source anchor; compiler type text does
not establish source-spelled tokens or macro token derivations.

Preserve each adapter's existing declaration scope and owner/access rules.
Function-local variables excluded by those rules do not make coverage partial.
Eligible declarations with ambiguous events, missing required owners, duplicate
source anchors or unsupported origins remain held. An ordinary out-of-line
definition must not acquire evidence from a different macro declaration.

Persist declaration evidence through the existing generic provenance table and
make readers discriminate its variant before inspecting callable-only fields.
Core logical schema advances to 28; structural schema remains 29. C logical
version advances to 29 and distribution to 2.0.20; C++ logical version advances
to 48 and distribution to 2.0.49; the official bundle advances to 2.0.84.
Frontend 0.4.0 and native protocol 5 remain unchanged because the required native
facts already exist. These versions supersede the initial implementation
versions recorded above without changing backend ownership of physical DDL.

## Required continuation

Source-invoked macro-generated callables remain part of the approved full port.
The existing generated-callable provenance requires token derivations that the
current Clang records cannot prove. Do not fabricate those derivations, silently
omit the functions or invoke the bounded custom preprocessor as a workaround.
Implement a truthful compiler-origin provenance representation in a later atomic
phase; until then the adapter exposes generated-declaration partial coverage.
Implicit compiler-only instantiations remain distinct from source-written symbols.

Header projection requires a real owning translation unit and its captured
arguments, separately from the requested header path. Missing or ambiguous
contexts must remain visible. Build/generated-header preparation stays outside
indexing. Larger real-repository qualification, native installation/platform
evidence and default-selection policy remain required before the full goal is
complete. Tree-sitter remains the current default and fallback.

## Qualification

Check source-authored expected fields and exact edges through actual indexing
on SQLite and DuckDB. Include overloaded callers and targets, cross-unit external
identities, internal-linkage collisions, indirect calls and external owners.
Keep pending generated-callable assertions required in the whole-scope oracle.
A passing ordinary subset cannot establish complete analyzer parity.

Run focused tests, repository preflight and the full gate before an atomic
commit. Preserve raw attempts and failed evidence. No helper test, clean AST or
selected-field grade counts as a newly verified original benchmark-file fix.
