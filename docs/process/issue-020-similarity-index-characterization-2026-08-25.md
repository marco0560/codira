# Issue 20 Similarity-Index Characterization — 2026-08-25

## Purpose

This is deterministic, synthetic characterization evidence for Slice 11 of
issue #20. It is not a #59 retrieval-quality campaign and creates no quality
threshold or release gate. It compares exact reference ordering with the
first-party FAISS `flat` and `hnsw` modes while preserving the machine context
needed to interpret timing values.

## Reproduction

From the Slice 11 branch commit that contains this report, run:

```bash
uv run --no-sync python scripts/characterize_similarity_indexes.py \
  --output /tmp/codira-issue-020-characterization.json
```

The runner fixes seed `20`, creates 128 normalized float32 vectors of dimension
32, uses 16 normalized queries, compares top 10 results, and reports medians
over three rebuild/query repetitions. It records the exact first-query top-k
reference alongside the FAISS modes. Timings are wall-clock `perf_counter_ns`
measurements and must not be compared across hosts as an implementation-quality
claim.

## Host context

| Field | Value |
| --- | --- |
| OS | Linux 6.18.33.2-microsoft-standard-WSL2 x86_64 |
| CPU | Intel Core i5-10310U, 4 cores / 8 logical CPUs |
| Python | 3.13.14 |
| FAISS | 1.15.0 (`faiss-cpu`) |
| Embedding device | Not used; vectors are synthetic |

## Observed record

| Mode | Exact reference / recall@10 | Build median | Cold-query median (16 queries) | Warm-query median (16 queries) | Artifact bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| Core exact reference | Reference ordering | N/A | N/A | N/A | 0 |
| FAISS flat | 1.0000 | 855,000 ns | 1,293,100 ns | 1,182,000 ns | 58,658 |
| FAISS HNSW (`M=16`, `efConstruction=80`, `ef_search=64`) | 1.0000 | 3,105,500 ns | 1,604,400 ns | 1,414,200 ns | 114,374 |

The fixed first-query reference was:

```text
synthetic:0059, synthetic:0100, synthetic:0061, synthetic:0004,
synthetic:0029, synthetic:0025, synthetic:0072, synthetic:0022,
synthetic:0006, synthetic:0034
```

Both measured FAISS modes returned that same first-query ordering in this
corpus. The HNSW result is an observation for this corpus and settings, not an
exactness or recall guarantee.

## Lifecycle coverage

The package contract tests exercise missing, stale, and corrupt artifacts;
rebuild publication; runtime-cache reset; and concurrent profiles. The isolated
wheel rehearsal additionally imports the installed FAISS wheel, exercises both
FAISS modes and two profiles, checks a stale revision fails closed, resets the
warm cache, and confirms a reloaded artifact still serves a query. Core
`emb reset --yes` lifecycle behavior is covered by
`tests/test_similarity_lifecycle.py`; it removes only the temporary
repository-scoped semantic state after explicit confirmation.
