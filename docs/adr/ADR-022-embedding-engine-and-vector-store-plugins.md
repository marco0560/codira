# ADR-022 — Embedding engine and vector-store plugins

**Date:** 19/06/2026
**Status:** Accepted

## Context

Codira currently treats persisted embeddings as part of the active structural
index backend. SQLite and DuckDB both own structural index tables, pending
embedding rows, vector-cache rows, persisted vectors, and similarity search.

That coupling worked while there was a single local embedding runtime, but it
does not scale cleanly to the next embedding roadmap:

- embedding models change quickly
- hardware architectures increasingly expose shared CPU/GPU memory
- CPU-only deployments may prefer ONNX Runtime over PyTorch
- operators need to compare multiple model and runtime combinations without
  destroying prior vector sets
- issue `#20` requires a future vector-storage boundary that can preserve
  backend parity while allowing optional vector-store implementations

`ADR-005` established real persisted embeddings with durable symbol identity.
`ADR-008` established batching, vector caching, and runtime tuning. `ADR-021`
established persistent configuration and plugin configuration. Those decisions
remain valid, but the embedding subsystem needs two explicit plugin boundaries
instead of one backend-local implementation detail.

## Decision

Introduce separate plugin families for embedding engines and vector stores.

### Embedding engine plugins

An embedding engine plugin generates vectors from semantic text payloads.

The engine contract owns:

- engine identity
- engine implementation version
- model identity
- model revision or explicit model version
- vector dimension
- precision or quantization metadata
- local provisioning requirements
- text-to-vector inference
- engine-specific calibration
- runtime cache reset

The first-party engines are:

- `sentence-transformers`, preserving the current PyTorch/SentenceTransformers
  behavior
- `onnx`, using native ONNX Runtime

### Vector-store plugins

A vector-store plugin persists vectors, caches reusable vectors, queues deferred
embedding rows, and serves similarity candidates.

The vector-store contract owns:

- vector-store identity
- vector-store implementation version
- vector serialization format
- vector-set identity
- pending embedding queue persistence
- reusable vector cache persistence
- symbol/documentation embedding persistence
- similarity search for active vector sets

The first-party vector stores are:

- `sqlite`
- `duckdb`

### Physical storage boundary

The structural index and the vector store are separate logical stores and should
be separate physical files for first-party local stores:

```text
.codira/index.db
.codira/index.duckdb
.codira/embeddings.db
.codira/embeddings.duckdb
```

The selected structural backend and selected vector store are independent
configuration choices:

```toml
[backend]
name = "duckdb"

[embeddings]
engine = "onnx"
vector_store = "duckdb"
```

### Coexistence policy

Vector stores may retain vectors for multiple engine/model/vector-store-format
identities.

The first implementation queries one active vector set at a time. Multi-vector
fusion, automatic fallback across vector sets, and query-time engine selection
are explicitly out of scope.

### Invalidation policy

Persisted vector identity includes:

- embedding engine name
- embedding engine version
- model name
- model revision or model version
- dimension
- precision or quantization metadata
- vector-store serialization format
- semantic payload content hash

Switching any of those values creates a different vector set. Existing vectors
from the pre-plugin schema intentionally recompute once because they do not
carry the complete identity.

Structural reindexing remains separate from semantic invalidation. A full
structural reindex should not drop reusable vector sets unless the operator
explicitly cleans the vector store or changes the active vector identity.

### Configuration

The effective configuration gains:

```toml
[embeddings]
engine = "sentence-transformers"
vector_store = "sqlite"
```

Engine-specific options live under:

```toml
[plugins.embedding-sentence-transformers]
```

Vector-store-specific options live under:

```toml
[plugins.vector-store-sqlite]
```

This keeps selection simple while preserving the existing plugin configuration
pattern.

### Provisioning and model manifests

Model weights and exported ONNX artifacts are not committed to git.

Codira will ship model manifests and provisioning/verification scripts so
operators can explicitly fetch, export, verify, and benchmark local artifacts.
Normal indexing must not perform hidden downloads.

### Benchmarking

The branch introduces fast smoke measurements and a long-campaign manifest.

The long campaign compares:

- current configured model
- `BAAI/bge-small-en-v1.5`
- `nomic-ai/nomic-embed-text-v1.5`
- `jinaai/jina-embeddings-v2-code-en`

The branch does not run the full campaign by default.

## Consequences

### Positive

- PyTorch, ONNX Runtime, and future engines can coexist behind the same
  indexing and query contracts.
- Structural storage and vector storage can evolve independently.
- Issue `#20` has a concrete vector-store plugin boundary.
- Operators can retain multiple engine/model vector sets for comparison.
- `index --full` can rebuild structural rows without destroying reusable vector
  sets.
- First-party SQLite and DuckDB vector stores preserve local, explicit,
  service-free operation.

### Negative

- The storage contract becomes larger.
- SQLite and DuckDB need vector-store package logic in addition to structural
  backend logic.
- The first pluginized release intentionally invalidates pre-plugin persisted
  embeddings once.
- Native ONNX Runtime requires Codira to own tokenizer, pooling, normalization,
  and artifact layout contracts.

### Neutral / Trade-offs

- The first implementation keeps one active vector set per query to avoid
  ranking-policy churn.
- Multi-vector retrieval fusion can be evaluated later from benchmark evidence.
- External vector databases remain optional future vector-store plugins, not a
  prerequisite for the local architecture.

## Relationship to existing ADRs

- `ADR-005` remains the durable-symbol-identity decision, but its storage model
  is superseded by the vector-store plugin boundary.
- `ADR-008` remains the batching and runtime-tuning decision, but engine-specific
  runtime control moves into embedding engine plugins.
- `ADR-021` remains the configuration hierarchy decision and is extended with
  embedding engine and vector-store selection.
