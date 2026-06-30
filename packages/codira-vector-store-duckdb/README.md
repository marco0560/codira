# codira-vector-store-duckdb

First-party DuckDB vector-store plugin for Codira.

The package publishes the `duckdb` vector store through the
`codira.vector_stores` entry-point group and initializes
`.codira/embeddings.duckdb`.

## Full-Index Preservation

The full-index bulk writer accepts complete identity rows through
`VectorStoreFullIndexRequest.identity_rows`. When
`preserve_existing = true`, unchanged `(object_type, stable_id, content_hash)`
rows are preserved in place and only changed or new vector payloads are
deserialized and written. This keeps warm full-index refreshes from rewriting
materialized vectors that are already valid for the active vector set.
