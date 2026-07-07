# Retrieval Quality Benchmark Reminder

Run this after the current final embedding campaign completes, because the
quality benchmark performs full indexing and competes for CPU, RAM, disk, and
embedding model caches.

Build the labeled retrieval-quality dataset:

```bash
uv run python -m scripts.build_retrieval_quality_dataset --repo-manifest benchmarks/retrieval-quality-repos.local.json --output .artifacts/retrieval-quality/dataset.jsonl
```

Run the default SQLite quality benchmark:

```bash
uv run python -m scripts.run_retrieval_quality_benchmark --dataset .artifacts/retrieval-quality/dataset.jsonl --repo-manifest benchmarks/retrieval-quality-repos.local.json --model-manifest benchmarks/embedding-model-candidates.json --backend sqlite --top-k 10
```

Optional variants:

```bash
uv run python -m scripts.run_retrieval_quality_benchmark --dataset .artifacts/retrieval-quality/dataset.jsonl --repo-manifest benchmarks/retrieval-quality-repos.local.json --model-manifest benchmarks/embedding-model-candidates.json --backend sqlite --top-k 10 --include-ctx
```

```bash
uv run python -m scripts.run_retrieval_quality_benchmark --dataset .artifacts/retrieval-quality/dataset.jsonl --repo-manifest benchmarks/retrieval-quality-repos.local.json --model-manifest benchmarks/embedding-model-candidates.json --backend both --top-k 10
```

Use the default `emb`-only run first. Add `--include-ctx` only when the mixed
context retrieval behavior is part of the quality question.
