# codira-similarity-index-qdrant

First-party, authenticated remote-Qdrant similarity-index plugin for Codira.
It owns only derived candidate-ranking artifacts: the selected vector-store
remains authoritative for vectors and revisions, while the structural backend
resolves and filters final records.

The official bundle installs this package; select it explicitly through
`embeddings.similarity_index = "qdrant"`. It supports authenticated remote
HTTP(S) Qdrant only: local paths, embedded mode, `:memory:`, anonymous clients,
and fallback to exact or FAISS are rejected.

```toml
[embeddings]
similarity_index = "qdrant"

[plugins.similarity-index-qdrant]
url = "https://qdrant.example.invalid"
namespace = "production"
api_key_env = "QDRANT_API_KEY"
# api_key_file = "/private/path/qdrant-api-key" # used only if the env value is empty
transport = "rest" # or "grpc" with optional grpc_port
read_consistency = "quorum"
write_ordering = "medium"
hnsw_m = 16
hnsw_ef_construct = 100
upload_batch_size = 256
```

The non-empty configured environment value takes precedence. If it is missing
or blank, Codira reads `api_key_file`; use a private regular non-symlink file
with no group or world permissions. REST is the default and gRPC is opt-in.
`hnsw_m` and `hnsw_ef_construct` are bounded build settings; a profile's
`ef_search` is query-scoped and never mutates shared daemon state.

Run `codira emb rebuild` after selecting Qdrant or changing a build setting,
then query with `codira emb`, `codira docs`, or `codira ctx`. Codira publishes
immutable revision collections through a stable alias, retains current plus the
immediately previous revision, and resolves final records from its structural
backend. Qdrant points and payloads are derived ranking evidence, never
authoritative repository records.

Use `codira emb similarity-purge` to preview exact-owned remote artifacts and
add `--yes` to delete them. `codira emb reset --yes` attempts this remote cleanup
before removing its local ownership ledger; it stops on cleanup failure unless
`--allow-remote-orphans` is an explicit recovery choice. That override reports
only opaque artifact hashes that may remain remotely.

The tests use an injectable fake client. They verify the Codira/client boundary,
not live-server interoperability, recall, latency, capacity, or scalability.
