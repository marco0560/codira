# ONNX Parameter Sweep Report - 2026-07-01

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-01-onnx-parameter-sweep-report.md`
(SHA-256 `dba6c2cb5d58386392d08713ff4fcc6b91c38fbfba66bececc666c0053de6a63`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/onnx-parameter-sweep/20260701T002113/results.jsonl` | unavailable historical path |
| `.artifacts/onnx-parameter-sweep/20260701T015702/results.jsonl` | unavailable historical path |


## Artifacts

- SQLite sweep: `.artifacts/onnx-parameter-sweep/20260701T002113/results.jsonl`
- DuckDB sweep: `.artifacts/onnx-parameter-sweep/20260701T015702/results.jsonl`

Both result files are complete for analysis:

- SQLite: 196 rows, all `status = 0`
- DuckDB: 196 rows, all `status = 0`
- Per backend: 28 `index` rows, 84 `emb` rows, 84 `ctx` rows

The split-engine experiment artifacts are not part of this report because both
stopped at the compatibility gate before producing repository timing rows.

## Main Findings

### BGE ONNX prefers smaller batches for indexing

Best full-index mean over the four repositories:

| Backend | Variant | Mean index time |
| --- | --- | ---: |
| SQLite | `batch4-default-threads` | 96.5 s |
| DuckDB | `batch4-default-threads` | 104.4 s |

`batch8` is slower:

| Backend | Variant | Mean index time |
| --- | --- | ---: |
| SQLite | `batch8-default-threads` | 119.3 s |
| DuckDB | `batch8-default-threads` | 122.0 s |

Conclusion: for BGE ONNX on this machine, `batch_size = 4` is better than
`batch_size = 8` for full indexing.

### Nomic ONNX strongly prefers batch 1 for indexing

Best full-index mean:

| Backend | Variant | Mean index time |
| --- | --- | ---: |
| SQLite | `batch1-threads4x1` | 273.4 s |
| DuckDB | `batch1-threads4x1` | 278.1 s |

Larger batches regress:

| Backend | Variant | Mean index time |
| --- | --- | ---: |
| SQLite | `batch2-threads4x1` | 303.8 s |
| SQLite | `batch4-threads4x1` | 359.4 s |
| DuckDB | `batch2-threads4x1` | 308.1 s |
| DuckDB | `batch4-threads4x1` | 364.6 s |

Conclusion: the conservative `batch_size = 1` setting for Nomic ONNX is
justified.

### Thread pinning helps BGE interactive latency more than indexing

BGE SQLite query means:

| Variant | Phase | Mean time |
| --- | --- | ---: |
| `batch4-default-threads` | `emb` | 0.898 s |
| `batch4-threads4x1` | `emb` | 0.849 s |
| `batch8-default-threads` | `ctx` | 1.165 s |
| `batch8-threads4x1` | `ctx` | 1.117 s |

Index time does not improve with `threads4x1`; it is slightly worse in the
measured variants. This points to thread pinning as mainly useful for
interactive ONNX calls, not full indexing.

### DuckDB is near SQLite for ONNX full indexing

DuckDB / SQLite full-index ratios:

| Sweep | Variant | Ratio |
| --- | --- | ---: |
| BGE | `batch4-default-threads` | 1.08x |
| BGE | `batch4-threads4x1` | 1.03x |
| BGE | `batch8-default-threads` | 1.02x |
| BGE | `batch8-threads4x1` | 1.03x |
| Nomic | `batch1-threads4x1` | 1.02x |
| Nomic | `batch2-threads4x1` | 1.01x |
| Nomic | `batch4-threads4x1` | 1.01x |

This is materially different from older full-campaign regressions. In this
ONNX-specific sweep, embedding computation dominates enough that DuckDB storage
overhead is mostly hidden during full indexing.

### DuckDB remains slower for interactive `emb` and `ctx`

DuckDB / SQLite query ratios:

| Sweep | Phase | Ratio range |
| --- | --- | ---: |
| BGE | `emb` | 1.58x-1.67x |
| BGE | `ctx` | 1.24x-1.35x |
| Nomic | `emb` | 1.35x-1.40x |
| Nomic | `ctx` | 1.20x-1.25x |

DuckDB is still meaningfully slower for interactive vector reads even when full
indexing is acceptable.

## Recommended ONNX Configurations

### BGE ONNX, indexing-oriented

```toml
[embeddings]
batch_size = 4

[plugins.embedding-onnx]
max_tokens = 512
intra_op_num_threads = 0
inter_op_num_threads = 0
```

### BGE ONNX, interactive-latency-oriented

```toml
[embeddings]
batch_size = 4

[plugins.embedding-onnx]
max_tokens = 512
intra_op_num_threads = 4
inter_op_num_threads = 1
```

### Nomic ONNX

```toml
[embeddings]
batch_size = 1

[embeddings.indexing]
max_text_chars = 2000

[plugins.embedding-onnx]
max_tokens = 512
intra_op_num_threads = 4
inter_op_num_threads = 1
```

## Bottom Line

- BGE ONNX: use `batch_size = 4`.
- Nomic ONNX: use `batch_size = 1`.
- ONNX full indexing is CPU/model dominated in this sweep; DuckDB is only
  about 1.01x-1.08x slower than SQLite there.
- DuckDB still has a meaningful interactive-query penalty, about 1.2x-1.7x
  depending on model and command.
