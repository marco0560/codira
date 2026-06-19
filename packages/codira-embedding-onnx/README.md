# codira-embedding-onnx

First-party native ONNX Runtime embedding engine plugin for Codira.

The package publishes the `onnx` engine through the
`codira.embedding_engines` entry-point group. Model artifacts are not bundled;
operators provision an ONNX model file and tokenizer file explicitly.
