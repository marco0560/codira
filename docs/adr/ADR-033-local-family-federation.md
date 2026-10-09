# ADR-033 — Local family federation

Status: accepted by the operator on 2026-10-09 for issue #15.

## Context

Codira's workspace domain already assigns stable names to independently routed
repository roots, state directories, and configurations. Queries and evidence
identities are repository-local. Related projects need one context query with
explicit origin without losing autonomous repository indexing and retrieval.

## Decision

Add a strict version-1 TOML family manifest referencing registered workspace
names, optional descriptive roles, and explicit directed symbol links. Select
the manifest explicitly through `codira family` or `codira-mcp --family`.
Freeze manifest and workspace routing at invocation/server startup. Resolve
members in canonical name order, retaining unavailable-member diagnostics.

Federate existing independent indexes rather than introduce a combined database
or change backend schemas. Reuse direct-core MCP adapter retrieval, normalized
evidence, identity expansion, and member pagination. The family runtime owns
origin qualification, completeness policy, global merging, and continuation;
CLI owns writes and MCP owns read-only transport. Member configuration, plugin,
and storage scopes prevent one repository's routing from leaking to another.

Combine context lists with reciprocal rank `1 / (60 + member_rank)` and stable
workspace/source tie-breaks. Preserve member rank and score. Distinct scoped
identities never merge solely because names match. Roles carry no weighting.
Exact lookups use deterministic origin/source ordering. Merge complete member
pages before global pagination; existing producer coverage and candidate limits
remain authoritative.

Bind family identities to manifest, member descriptor, and member symbol
identity. Bind continuations to the manifest, resolved routing, effective
configuration, runtime, query/filter/policy, candidate result digest, and the
entire member generation vector. Check readiness, source hashes, repository
revision, and plugin inventory before and after retrieval; reject a changed
snapshot instead of mixing generations. Reject missing, empty, partial, stale,
updating, or failed selected indexes by default. Explicit partial mode reports
exclusions; unselected members still participate in continuation binding.

Cross-repository references are manifest declarations with exact endpoint
workspace, symbol name, relative file, and line. Validate both endpoints and
label provenance as operator-declared manifest evidence. Do not infer edges
from common names or claim analyzer-discovered call semantics. Family reference
queries cover declared links; existing local reference tools remain available.

Index each member through its existing CLI index implementation, attempt every
member, preserve individual outcomes and successful indexes, and return nonzero
on any failure. Do not promise a family-wide transaction or automatic writes
from query operations.

## Alternatives and consequences

A unified index would require new schema ownership, migrations, and backend
contracts. Federation reuses established plugins and preserves autonomous
repository workflows, including mixed SQLite/DuckDB families.

Raw-score merging would require comparable configurations and calibrated scores.
Rank-based merging gives deterministic behavior across heterogeneous members,
but equal local ranks tie and there is no family-wide score calibration.

Request-selected families would widen MCP's trust boundary. A startup-bound
family retains the existing fixed-selection model while allowing declared member
filters. Descriptor edits require a server restart.

Source verification and complete member paging have a latency cost; this first
implementation deliberately establishes correctness without new warm services.
Shared persistent hosting belongs to #51. Distributed indexing, remote control,
automatic discovery, and language-specific import/export resolution remain
outside this decision. Operational instructions are in [the family guide](../families.md).
