# codira-embedding-sentence-transformers

First-party SentenceTransformers embedding engine plugin for Codira.

The package publishes the `sentence-transformers` engine through the
`codira.embedding_engines` entry-point group. Its delegated runtime receives a
cache folder beneath Codira's shared model store, so model snapshots are reused
across workspaces and managed runtimes. Select a user-owned absolute root with
`CODIRA_MODEL_ROOT` or `[embeddings].model_root` when the platform default is
not suitable.


Use `[plugins.embedding-sentence-transformers].model_path` for an existing
absolute local snapshot directory. Keep `[embeddings].model` as the logical model
ID and set `version` to its immutable revision so vector identity remains pinned.
Without an explicit model root, an existing legacy Hugging Face cache can be
reused read-only when the shared store lacks that model. Explicit roots retain
precedence; resolution never copies or overwrites model files.

`HF_HUB_OFFLINE=1` or `TRANSFORMERS_OFFLINE=1` forbids automatic provisioning after
a local miss. The error identifies the selected source/cache and explains how
to choose a local artifact. Explicit provisioning with network access requires
a separately launched operator process without these offline flags.
