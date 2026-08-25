# ADR-031 — Similarity-index plugin family

**Date:** 25/08/2026
**Status:** Accepted
**Supersedes in part:** [ADR-022](ADR-022-embedding-engine-and-vector-store-plugins.md)

## Context

ADR-022 created independent embedding-engine and vector-store plugin families.
It also assigned candidate similarity search to vector stores. That assignment
mixes durable semantic state with a rebuildable query acceleration mechanism:
a vector store needs durable rows, caches, pending work, stable ID bindings,
and revisions, while an exact or approximate similarity index needs build
identity, materialized artifacts, and search-time controls.

Codira needs a local FAISS implementation, but FAISS must remain an optional
package. A new valid installation must nevertheless be able to select a
similarity implementation and execute exact semantic retrieval. Multiple Codira
repositories and their fixed-root warm query daemons must never share derived
artifacts or runtime caches.

## Decision

### Separate responsibility families

Structural backends remain authoritative for repository facts, structural
filtering, and returned records. Vector stores are authoritative for durable
semantic state: vector sets, materialized vectors, reusable vector caches,
pending work, stable-ID bindings, purge state, and vector-set revisions.

Similarity indexes are a new plugin family. They own only derived candidate
ranking artifacts and runtime search behavior. An index is built from one
identified vector-set revision and is disposable: it never becomes a source of
truth, and structural filtering remains outside it.

Core provides the always-available exact similarity implementation. It is the
explicitly selectable base implementation, rather than a fallback from a
missing plugin. The first optional first-party plugin is
`codira-similarity-index-faiss`, with exact flat search by default and explicit
HNSW selection. Qdrant is a separate future, authenticated server-mode plugin
that must implement this same contract.

### Identity, artifacts, and freshness

`VectorSetIdentity` continues to name the embedding engine and durable vector
store state. A separate `SimilarityIndexIdentity` includes at least the
repository root identity, vector-set identity and revision, similarity-index
implementation/version, and build configuration.

Build-time settings, including FAISS HNSW construction settings, participate in
the persisted index identity. Runtime profiles do not create a new persisted
identity. Every persisted derived artifact carries a manifest sufficient to
verify that identity and its source revision before use. Missing, corrupt,
stale, incompatible, or cross-root artifacts are rejected rather than reused.

### Query profiles and daemon isolation

Operators choose named search profiles. A profile contains `ef_search`,
`candidate_limit`, `default_result_limit`, and `max_result_limit`. An explicit
result limit above the selected profile maximum is invalid; it is never
clamped. `candidate_limit` bounds candidates before structural filtering, while
the result limit applies after filtering. `ef_search` is an HNSW graph
exploration budget, not a score-fuzziness control.

The warm query daemon remains fixed to one trusted repository root. Its cache
keys include root identity, vector-set/index identity and artifact freshness;
per-query profile and result-limit values must not mutate shared runtime state.
Daemon routing may accelerate a compatible request but must preserve the same
identity and provenance checks as an in-process request.

### Failure and compatibility policy

Selection is strict. A configured similarity-index plugin that is unavailable,
disabled, unreachable, invalid, stale, or incompatible fails with an actionable
error. Codira does not silently switch to core exact similarity, FAISS, another
plugin, or a degraded query mode.

This decision is an intentional breaking change. The old vector-store search
contract, configuration, and persisted semantic state are unsupported. Codira
provides neither compatibility adapters nor staged migration. Operators reset
the affected repository-local semantic state and re-index explicitly; Codira
must not silently translate, delete, migrate, or reuse it.

## Consequences

### Positive

- Durable vector-state lifecycle and similarity performance can evolve
  independently.
- FAISS and later server implementations share one auditable candidate-search
  boundary without making a third-party package mandatory.
- Root, revision, and artifact checks prevent accidental cross-repository or
  stale warm-query reuse.
- Exact retrieval remains explicitly available in every valid installation.

### Negative

- Configuration, provenance, invalidation, installer, and test surfaces gain a
  new first-class component.
- The clean break requires operators with old semantic state to reset and
  re-index.
- A selected optional backend can fail instead of automatically degrading to a
  different retrieval mode.

## Alternatives rejected

Keeping similarity search in `VectorStore` was rejected because it couples
authoritative durable state to optional and rebuildable acceleration. Treating
FAISS as a special SQLite or DuckDB adapter was rejected for the same reason.
Staged deprecation, legacy adapters, and automatic migration were rejected:
they obscure the new contract and make root-scoped state recovery unsafe.

## Relationship to existing ADRs

- ADR-022 remains authoritative for embedding engines and durable vector-store
  ownership. This ADR supersedes only its assignment of similarity candidate
  search and external vector-database classification to vector stores.
- ADR-025 and ADR-026 remain authoritative for daemon lifecycle and fixed-root
  service boundaries; this ADR applies the new identity and freshness rules to
  similarity-index caching.
- ADR-021 remains authoritative for configuration hierarchy; it is extended by
  the mandatory, explicitly selected similarity-index configuration.
