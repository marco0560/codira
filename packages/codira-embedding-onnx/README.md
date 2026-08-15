# codira-embedding-onnx

First-party native ONNX Runtime embedding engine plugin for Codira.

The package publishes the `onnx` engine through the
`codira.embedding_engines` entry-point group. Model artifacts are not bundled.
Codira can resolve `model_artifact` and `tokenizer_artifact` from its shared
verified model store; both names are bound to the configured embedding model
and version. Existing explicit `model_path` and `tokenizer_path` settings stay
available for non-destructive migration. New relative paths are rooted in the
shared model store when Codira injects that root; the historical `.codira/...`
shape remains a compatibility path until migration.

Long inputs are truncated before ONNX Runtime inference. The default limit is
`max_tokens = 512`, matching the common fixed sequence length used by BERT-style
embedding exports. Dynamic-shape or longer-context ONNX exports can override the
limit through repository, user, or system config:

```toml
[plugins.embedding-onnx]
max_tokens = 512
```

Set `max_tokens = 0` only for ONNX exports that are known to accept arbitrary
sequence lengths. Changing `max_tokens` changes vectors for over-limit texts, so
bump `[embeddings].version` when changing it for an existing index.
