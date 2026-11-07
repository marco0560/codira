# ADR-040 — Header projection through captured owning translation units

**Date:** 26/10/2026

**Status:** Accepted for implementation; final qualification pending

## Decision

Continue ADR-038 with an additive header projection request. Keep the requested
physical header separate from the owning translation unit and its captured
compiler argv. Native protocol v4 parses the actual translation unit and filters
projected records to the requested file. Bind source hashes, both paths, compiler
context and projection identity into reuse fingerprints. Never guess header flags
or compile a project during indexing.

Resolve owner contexts from complete captured dependency profiles containing
the current header. A unique owner can be selected automatically. Missing, stale
or ambiguous contexts remain held. The additive `clang_header_owner_profiles`
plugin option maps repository-relative headers to exact captured profile
identities reported by preparation. An explicit choice must be a current
candidate, including when one TU has multiple compiler contexts.

Preparation is a separate explicit CLI operation. It consumes captured inputs,
prepares owner profiles before header discovery, writes immutable profiles and
raw attempts, supports identity-bound resume, and retains missing generated
headers as held inputs. It never runs a project build. Profile collection filters
by the requested dependency before reading candidate TU source bytes, avoiding
an all-TU source hash pass for every header. Preserve canonical test fixtures;
actual indexing qualification uses an isolated frozen Git input checkout.

## Verification requirements

Grade actual indexing and persisted source facts on SQLite and DuckDB in default
and explicit-owner modes. Verify held ambiguities, requested header hash/path,
owner TU/profile, projection identity, callable/type/macro/documentation facts,
and exact cross-TU call behavior after a header definition is projected. A parsed
header AST or owner discovery alone is insufficient. Retain failed selection,
helper/source drift and superseded attempts.

The header Doxygen regression must use actual decoded native records: a qualified
function artifact must match the frontend qualified name as well as the bare name
when locating its attached comment. Prototype extraction must not invent a body.

Core logical schema remains 26 and physical backend schemas remain 29. Advance
the shared frontend to 0.3.0, C to logical 27/distribution 2.0.18 and C++ to logical
46/distribution 2.0.47; regenerate installer catalog 2.0.8 and bundle 2.0.82.
No publication or default switch is authorized by this phase. Generated alias,
linkage and prototype-redeclaration parity, original-repository qualification
and native distribution/platform evidence remain required continuation.
