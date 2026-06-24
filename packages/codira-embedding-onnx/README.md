# codira-embedding-onnx

First-party native ONNX Runtime embedding engine plugin for Codira.

The package publishes the `onnx` engine through the
`codira.embedding_engines` entry-point group. Model artifacts are not bundled;
operators provision an ONNX model file and tokenizer file explicitly.

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
