# codira-vector-store-sqlite

First-party SQLite vector-store plugin for Codira.

The package publishes the `sqlite` vector store through the
`codira.vector_stores` entry-point group and initializes
`.codira/embeddings.db`.

The pending-vector lookup index is created when the store is initialized,
including for an existing database. Its creation takes time and disk space
proportional to the pending queue and adds overhead to queue writes.

The plugin runtime version is part of each vector-set identity. Upgrading from
runtime version `1.0.6` to `1.0.7` selects a new vector set; existing vectors,
cache entries and pending rows remain in the database under their old identity
and are not migrated. Rebuild embeddings for the new identity before relying on
semantic results. Remove old state only after deciding it is no longer needed;
`codira emb reset --yes` removes the selected vector store and its contents.
