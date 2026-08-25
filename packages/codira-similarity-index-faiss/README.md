# codira-similarity-index-faiss

First-party FAISS similarity-index plugin for Codira. It provides exact flat
inner-product search by default and an explicitly configured approximate HNSW
mode. FAISS artifacts are derived from one repository-local vector snapshot;
they can be rebuilt with `codira emb rebuild` and are never authoritative
vector storage.

Configure it with `embeddings.similarity_index = "faiss"`. The plugin table is
`[plugins.similarity-index-faiss]`; `index_type` is `flat` by default, while
`hnsw` accepts build-time `M` and `efConstruction` settings. Runtime
`ef_search` belongs to named semantic search profiles, not this build table.

Install with `python -m pip install codira-similarity-index-faiss`, or with
`python -m pip install "codira-bundle-official[faiss]"`. Configure
`similarity_index = "faiss"`, then run `codira emb rebuild` after selecting
FAISS or changing `index_type`, `M`, or `efConstruction`. Changing only a
profile applies at query time. `ef_search` is HNSW graph exploration breadth,
not score fuzziness; `candidate_limit` applies before structural filtering and
the profile's result limits apply after filtering. If a persisted format is
incompatible, use `codira emb reset` and reindex instead of migrating artifacts.
