# Split Engine Gate Investigation Note - 2026-07-01

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-01-split-engine-gate-investigation-note.md`
(SHA-256 `1ddecbf06d8ca6f18410cd25b688ddcc0b3722fe871f30302a8292986845c59a`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.


## Context

The split-engine experiment tested indexing with SentenceTransformers and
querying with ONNX for the same model identity. The first pair failed the
compatibility gate:

```text
pair_id: bge-small-en-v1.5-st-index-onnx-query
left:  bge-small-en-v1.5-sentence-transformers
right: bge-small-en-v1.5-onnx
min_cosine: 0.9524865242
mean_cosine: 0.9580080774
threshold: 0.99
passed: false
```

This is close in a broad semantic sense, but not close enough to treat vectors
from the two engines as interchangeable in the same vector store.

## Documentation Is Useful But Insufficient

HuggingFace model cards and local model metadata can narrow the likely causes.
They may document:

- pooling strategy
- whether final embeddings should be normalized
- query/document prompt or prefix conventions
- intended maximum sequence length
- tokenizer family and special tokens
- model revision or export provenance

However, documentation alone cannot prove that the local SentenceTransformers
pipeline and the local ONNX pipeline are equivalent. Direct testing is needed
to verify:

- identical token ids for the same input text
- identical attention masks
- identical truncation and padding behavior
- same output tensor selection
- same pooling implementation
- same normalization point
- same model revision/checksum

## Likely Causes To Test

The observed cosine around `0.95` is larger drift than expected from a faithful
float32 ONNX export of the same SentenceTransformers pipeline. The most likely
causes are:

1. Pooling mismatch.
2. Normalization mismatch.
3. Prompt or query-prefix mismatch.
4. Tokenizer mismatch.
5. Different model artifact revision.
6. Quantization or export differences.

If token ids and attention masks match, pooling and normalization should be the
first code paths inspected.

## Parameters That May Be Alignable

SentenceTransformers can usually control:

- `normalize_embeddings`
- prompt or prefix selection, when the model defines prompts
- `max_seq_length`
- precision and device choices

ONNX can usually control, depending on plugin/export support:

- tokenizer path and tokenizer config
- `max_tokens`
- normalization on/off
- pooling mode, if exposed
- selected output tensor, if exposed
- provider and precision choices

Pooling is the risky area. SentenceTransformers models are often pipelines:
transformer, pooling, and optional normalization. An ONNX artifact may include
only the transformer, or may include additional post-processing, depending on
how it was exported. If Codira applies a generic pooling rule on top of an ONNX
transformer output, it may not match SentenceTransformers.

## Recommended Diagnostic Order

Run direct parity checks in this order:

```text
1. Compare token ids for the same fixed corpus.
2. Compare attention masks.
3. Compare max-length and truncation behavior.
4. Compare raw ONNX output shape and selected tensor.
5. Compare SentenceTransformers pooling config with Codira ONNX pooling.
6. Compare final normalization behavior.
7. Verify model artifact revision/checksum.
```

Only after those checks pass should the gate threshold be revisited. Lowering
the threshold from `0.99` to `0.95` would accept a known vector-space mismatch
and allow performance timings for a retrieval mode that may return degraded or
mis-ranked results.
