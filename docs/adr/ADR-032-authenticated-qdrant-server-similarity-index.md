# ADR-032 — Authenticated Qdrant server-mode similarity index

**Date:** 26/08/2026
**Status:** Accepted
**Extends:** [ADR-021](ADR-021-codira-configuration-hierarchy-runtime-policy.md), [ADR-025](ADR-025-optional-deterministic-daemon-mode.md), [ADR-026](ADR-026-repository-local-warm-query-daemon.md), and [ADR-031](ADR-031-similarity-index-plugin-family.md)

## Context

Codira needs an optional Qdrant similarity-index plugin for deployments where a
server-managed approximate nearest-neighbour service is appropriate. Qdrant
must not change Codira's authority boundaries: vector stores remain the durable
owner of embedding vectors, vector-set identity, stable-ID bindings, and
revisions; structural backends remain the owner of repository-record
resolution, structural filtering, and final returned records.

Remote collections can be copied, deleted, or accidentally shared across
repositories. A collection name, endpoint, local path, model name, or a
credential source is not sufficient ownership evidence and some of that data
must never be exposed. The plugin therefore needs a server-only security
boundary and a credential-free, repository-scoped derived-artifact identity
before a client or collection lifecycle is introduced.

## Decision

### Authority and failure boundary

`codira-similarity-index-qdrant` is an optional, non-authoritative
similarity-index plugin. It stores only rebuildable candidate-ranking
artifacts. A Qdrant point and its payload are never authoritative repository
records and cannot be used to resolve, filter, or render final results.

When Qdrant is explicitly selected, selection, configuration, connection,
authentication, artifact, freshness, and compatibility failures fail closed.
Codira must not fall back to exact, FAISS, another similarity index, or a
degraded query path. The core exact index remains an explicitly selected
alternative under ADR-031; it is not a Qdrant recovery mechanism.

### Authenticated server mode only

The plugin supports remote Qdrant server mode only. It accepts REST by default
and gRPC only when explicitly configured. Embedded clients, local filesystem
paths, `:memory:`, anonymous connections, empty credentials, and
unauthenticated configurations are invalid before any network operation.

Configuration follows ADR-021's centrally validated, namespaced plugin model.
An API-key environment value is preferred only when it is non-empty; otherwise
the configured credential file is considered. Credential values, credential
source paths, authorization headers, endpoint URLs, and server exception
payloads are secret data. They must not appear in fingerprints, collection
names, local ledgers, provenance, installer plans, journals, logs, errors, or
machine-readable output. Errors use stable, credential-free classifications
and actionable remediation without echoing remote responses.

### Repository-scoped derived identity

Before any remote identity is computed, Codira creates and persists a random
repository UUID under `.codira`. It is repository-local state, is written
atomically, and is preserved by `codira emb reset`. A mandatory non-empty
namespace is an additional operator-controlled partition; it is not a secret,
but its raw text is not exposed in remote artifact names or provenance.

Every Qdrant artifact identity is a canonical, domain-separated hash of these
typed inputs:

- the repository UUID;
- the hash of the resolved canonical repository root;
- the hash of the mandatory namespace;
- the complete vector-set identity, including embedding and vector-store
  identities and vector dimension;
- the Qdrant index identity, including plugin format and bounded HNSW build
  settings;
- object type; and
- source vector-set revision.

The endpoint contributes only its normalized endpoint hash. Credentials and
transport selection do not contribute to collection identity, so equivalent
server access paths cannot create a second ownership domain. A stable alias is
derived from the build identity and object type; an immutable physical
collection is derived from that alias identity plus source revision. Both are
opaque, constrained Qdrant-safe names containing only approved hash-derived
components. No raw root path, namespace, endpoint URL, model name, credential
source, or credential value is present.

Remote points use deterministic UUIDs derived from repository UUID, object
type, and stable ID. Each physical collection contains a reserved manifest
point with the same credential-free identity hashes and source revision. It is
never a search candidate. The manifest and a local credential-free ownership
ledger are necessary evidence for publication, query validation, retention,
and cleanup; neither makes remote state authoritative or independently proves
ownership.

### Publication, query, and daemon boundaries

Publication uses immutable revision collections and an atomic alias update
only after the new collection is completely verified. The implementation keeps
the current and immediately previous verified revisions. It deletes an older
collection only when exact local and remote ownership metadata agree; otherwise
it leaves the remote state intact and reports the credential-free hashes needed
for recovery.

Queries resolve and verify the alias and manifest before candidate ranking.
They bind requests to the repository identity, vector-set identity, selected
index configuration, object type, and source revision. Structural backends
then resolve and filter the returned stable IDs, retaining typed,
credential-free candidate and query provenance through final result assembly.

ADR-025's indexing lock remains the sole mutation coordinator. Any remote
publication, purge, or reset recovery integrates with that lock; a reset does
not silently orphan Qdrant state. Under ADR-026, a warm daemon stays fixed to
one resolved repository root and may cache only a compatible client or derived
artifact. It never accepts arbitrary repository paths, mutates shared state
for a query profile, or bypasses the same identity, authentication, freshness,
and provenance checks used by direct execution.

## Consequences

### Positive

- Server-managed approximate search remains optional without making Qdrant a
  source of truth.
- Repository UUIDs, namespace partitioning, and opaque identity hashes prevent
  accidental cross-root artifact reuse without disclosing sensitive metadata.
- Strict failure and verified ownership prevent a selected remote backend from
  silently changing retrieval semantics or deleting ambiguous remote state.
- Immutable publication and fixed-root daemon checks preserve reproducible
  revision and cache boundaries.

### Negative

- Operators must provide a reachable authenticated Qdrant server and explicit
  namespace; no local or anonymous convenience mode is available.
- Qdrant lifecycle and result provenance introduce typed contract, installer,
  reset, schema, and testing work across the 2.0 compatibility boundary.
- Deterministic fake-client tests can prove Codira's client boundary but do not
  establish live-server interoperability, recall, latency, or scalability.

## Alternatives rejected

Embedded or local-path Qdrant was rejected because it weakens the server-mode
security and lifecycle boundary. Anonymous remote access was rejected because
collection names alone are insufficient protection. Using raw repository paths,
namespace text, URLs, or model names in collection identifiers was rejected
because it leaks operational metadata and permits brittle identity reuse.
Treating Qdrant vectors or payloads as durable vectors or final records was
rejected because it violates ADR-022 and ADR-031. Falling back to an available
local index was rejected because it hides selected-plugin failure and changes
retrieval semantics.

## Relationship to existing ADRs

- ADR-021 remains authoritative for configuration precedence and strict plugin
  schema validation. This ADR adds Qdrant's server-only and redaction rules.
- ADR-025 remains authoritative for mutation coordination. This ADR requires
  remote derived-state lifecycle operations to share that coordinator.
- ADR-026 remains authoritative for fixed-root warm query isolation. This ADR
  requires Qdrant cache identity and query behavior to remain inside it.
- ADR-031 remains authoritative for similarity-index ownership and strict
  selection. This ADR specifies its Qdrant server-mode implementation.
