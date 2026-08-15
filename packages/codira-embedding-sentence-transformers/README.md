# codira-embedding-sentence-transformers

First-party SentenceTransformers embedding engine plugin for Codira.

The package publishes the `sentence-transformers` engine through the
`codira.embedding_engines` entry-point group. Its delegated runtime receives a
cache folder beneath Codira's shared model store, so model snapshots are reused
across workspaces and managed runtimes. Select a user-owned absolute root with
`CODIRA_MODEL_ROOT` or `[embeddings].model_root` when the platform default is
not suitable.
