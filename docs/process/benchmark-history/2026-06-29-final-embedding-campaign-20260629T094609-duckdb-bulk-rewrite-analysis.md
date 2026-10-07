# DuckDB Bulk Full-Index Campaign Analysis: 20260629T094609

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-29-final-embedding-campaign-20260629T094609-duckdb-bulk-rewrite-analysis.md`
(SHA-256 `0e8a52a7e694aca8b837b0765c514723dcdc6d5835c6d950b298911575f9b6db`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/final-embedding-model-campaign/20260629T002747` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T094609` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.


## Scope

Campaign analyzed:

- Path: `.artifacts/final-embedding-model-campaign/20260629T094609`
- Backend mode: `duckdb`
- Concrete backend: `duckdb`
- Repositories: `codira`, `fontshow`, `chatops`, `sanikey`
- Models: 6 embedding candidates from `benchmarks/embedding/model-candidates.json`
- Runs: 5
- Warmup: 1
- Completed checkpoints: 24 / 24
- Nonzero failure summaries: none found

Primary comparison run:

- Path: `.artifacts/final-embedding-model-campaign/20260629T002747`
- Backend mode: `both`
- Concrete backends: `sqlite`, `duckdb`
- Same repository/model matrix

This report compares the new DuckDB-only run against:

- the previous DuckDB run from `20260629T002747`, to measure the effect of the
  DuckDB bulk full-index rewrite;
- the SQLite rows from `20260629T002747`, to estimate whether DuckDB is close
  to the strict `1.15x` acceptance target.

## Parity Checks

- New campaign git commit in plans: `ed59156b6fa34298bbe833368c9eb93fb980b508`
- Previous campaign git commit in plans: `ed59156b6fa34298bbe833368c9eb93fb980b508`
- New DuckDB backend package: `codira-backend-duckdb 1.49.4`
- Previous DuckDB backend package: `codira-backend-duckdb 1.49.3`
- New DuckDB vector store package: `codira-vector-store-duckdb 1.0.4`
- Previous DuckDB vector store package: `codira-vector-store-duckdb 1.0.3`
- SQLite baseline package in previous run: `codira-backend-sqlite 1.45.0`
- DuckDB profiles emitted in new run: 24 `duckdb-profile.json` files

Important caveat:

The artifact commit field did not change, but package versions did. The
attribution here is therefore based on the artifact package inventory and
profile spans, not only the commit hash recorded in the campaign plan.

## Headline Hyperfine Timings

Median command timings across the 24 model/repository pairs:

| Command | New DuckDB | Previous DuckDB | New / Previous DuckDB | Previous SQLite | New DuckDB / Previous SQLite |
| --- | ---: | ---: | ---: | ---: | ---: |
| `index --full` | 4.784 s | 4.956 s | 0.97x | 2.410 s | 1.99x |
| incremental `index` | 0.446 s | 0.434 s | 1.03x | 0.368 s | 1.21x |
| `ctx` | 3.753 s | 3.660 s | 1.03x | 3.331 s | 1.13x |
| `emb` | 3.529 s | 3.473 s | 1.02x | 2.936 s | 1.20x |
| `sym` | 0.323 s | 0.316 s | 1.02x | 0.265 s | 1.22x |
| `calls` | 0.313 s | 0.308 s | 1.02x | 0.266 s | 1.18x |
| `cov` | 0.235 s | 0.230 s | 1.02x | 0.230 s | 1.02x |
| `symlist` | 0.331 s | 0.321 s | 1.03x | 0.270 s | 1.23x |
| `audit` | 0.324 s | 0.319 s | 1.02x | 0.266 s | 1.22x |
| `help` | 0.169 s | 0.166 s | 1.02x | 0.166 s | 1.02x |
| `plugins` | 0.264 s | 0.261 s | 1.01x | 0.261 s | 1.02x |
| `caps` | 0.275 s | 0.272 s | 1.01x | 0.272 s | 1.01x |

The full-index wall-clock median improved only slightly, from `4.956 s` to
`4.784 s`. Against the previous SQLite baseline, new DuckDB remains about
`1.99x` slower for `index --full`, so it does not meet the `1.15x` acceptance
gate.

## Internal Phase Timings

Mean phase timings across the 24 model/repository pairs:

| Phase | New DuckDB | Previous DuckDB | New / Previous DuckDB | Previous SQLite | New DuckDB / Previous SQLite |
| --- | ---: | ---: | ---: | ---: | ---: |
| total | 176.950 s | 174.085 s | 1.02x | 170.536 s | 1.04x |
| parsing | 0.821 s | 0.813 s | 1.01x | 0.805 s | 1.02x |
| indexing | 0.084 s | 1.071 s | 0.08x | 0.431 s | 0.20x |
| embeddings | 171.221 s | 168.580 s | 1.02x | 167.239 s | 1.02x |
| discovery | 0.018 s | 0.017 s | 1.03x | 0.017 s | 1.03x |
| filtering | 0.011 s | 0.010 s | 1.01x | 0.010 s | 1.04x |
| metadata | 0.008 s | 0.007 s | 1.03x | 0.007 s | 1.05x |
| scan_state | 0.030 s | 0.029 s | 1.03x | 0.029 s | 1.04x |

The structural write-path rewrite worked:

- DuckDB internal `indexing` dropped from `1.071 s` mean to `0.084 s` mean.
- That is a `12.7x` improvement over previous DuckDB.
- It is also about `5.1x` faster than the previous SQLite internal indexing
  phase.

By repository, mean `indexing` phase:

| Repo | New DuckDB | Previous DuckDB | New / Previous DuckDB | Previous SQLite | New DuckDB / Previous SQLite |
| --- | ---: | ---: | ---: | ---: | ---: |
| `chatops` | 0.040 s | 0.525 s | 0.08x | 0.197 s | 0.20x |
| `codira` | 0.174 s | 1.740 s | 0.10x | 0.887 s | 0.20x |
| `fontshow` | 0.095 s | 1.600 s | 0.06x | 0.515 s | 0.19x |
| `sanikey` | 0.029 s | 0.418 s | 0.07x | 0.125 s | 0.23x |

This means the original DuckDB backend write bottleneck has been removed from
the measured `benchmark_index.py` phase timing.

## Why Wall-Clock Did Not Collapse

The full command is now dominated by embedding and vector persistence, not the
structural indexing phase.

Mean phase totals:

- New DuckDB `indexing`: `0.084 s`
- New DuckDB `embeddings`: `171.221 s`
- New DuckDB `total`: `176.950 s`

So the rewritten structural backend phase is now a tiny part of the measured
full-index lifecycle. This explains the apparently contradictory result:

- the backend write path improved dramatically;
- the end-to-end `index --full` command improved only slightly.

The remaining `index --full` delta versus SQLite is therefore no longer
primarily a structural DuckDB table-write problem.

## Model And Repo Shape

New DuckDB `index --full` medians by model:

| Model | Median |
| --- | ---: |
| `current-minilm-sentence-transformers` | 4.450 s |
| `bge-small-en-v1.5-sentence-transformers` | 4.805 s |
| `bge-small-en-v1.5-onnx` | 5.363 s |
| `nomic-embed-text-v1.5-sentence-transformers` | 5.607 s |
| `jina-embeddings-v2-base-code-onnx` | 5.622 s |
| `nomic-embed-text-v1.5-onnx` | 6.157 s |

New DuckDB `index --full` medians by repo:

| Repo | Median |
| --- | ---: |
| `sanikey` | 2.853 s |
| `chatops` | 3.277 s |
| `fontshow` | 7.767 s |
| `codira` | 9.187 s |

New DuckDB embedding phase means by model:

| Model | Mean indexing phase | Mean embedding phase | Mean total |
| --- | ---: | ---: | ---: |
| `current-minilm-sentence-transformers` | 0.083 s | 35.377 s | 40.151 s |
| `bge-small-en-v1.5-sentence-transformers` | 0.081 s | 79.056 s | 84.032 s |
| `bge-small-en-v1.5-onnx` | 0.083 s | 113.361 s | 118.558 s |
| `jina-embeddings-v2-base-code-onnx` | 0.093 s | 249.030 s | 255.318 s |
| `nomic-embed-text-v1.5-onnx` | 0.083 s | 270.326 s | 277.059 s |
| `nomic-embed-text-v1.5-sentence-transformers` | 0.082 s | 280.174 s | 286.584 s |

The 768-dimensional models remain the expensive part of the campaign.

## Profile Evidence

Top DuckDB profile spans in the new run:

| Span | Total seconds | Calls | Rows |
| --- | ---: | ---: | ---: |
| `bulk_full_index.plan_rows` | 56.058 | 24 | 4,866 |
| `sql.select` | 47.444 | 4,938 | 0 |
| `bulk_full_index.load_embeddings` | 36.945 | 24 | 66,594 |
| `vector_store.store_vectors` | 23.868 | 24 | 66,594 |
| `sql.create_index` | 14.228 | 1,128 | 0 |
| `bulk_full_index.create_indexes` | 14.174 | 24 | 0 |
| `embeddings.insert_rows` | 8.931 | 24 | 66,594 |
| `bulk_full_index.commit_structural` | 7.720 | 24 | 0 |
| `duckdb.raw_commit` | 7.719 | 48 | 0 |
| `bulk_full_index.load_structural_tables` | 4.753 | 24 | 0 |
| `bulk_full_index.rebuild_derived_indexes` | 3.439 | 24 | 0 |
| `bulk_full_index.load_reference_scan_rows` | 2.703 | 24 | 1,232,730 |
| `bulk_full_index.load_relationship_tables` | 2.155 | 24 | 223,620 |

Top DuckDB profile spans in the previous run:

| Span | Total seconds | Calls | Rows |
| --- | ---: | ---: | ---: |
| `persist.store_analysis` | 56.998 | 4,866 | 4,866 |
| `sql.select` | 48.627 | 5,082 | 0 |
| `embeddings.flush_pending_rows` | 27.235 | 24 | 66,510 |
| `vector_store.store_vectors` | 20.849 | 24 | 66,510 |
| `session.commit_transaction` | 13.414 | 48 | 0 |
| `prepare.create_schema_indexes` | 13.705 | 24 | 0 |
| `flush.structural_rows` | 4.623 | 48 | 104,172 |
| `rebuild.derived_indexes` | 3.367 | 24 | 0 |

The expected profile signature changed:

- `persist.store_analysis` is gone from the new full-index profile.
- `bulk_full_index.*` spans are present in all 24 DuckDB profile files.
- The old per-file persistence profile shape was replaced.

However, `bulk_full_index.plan_rows` still costs about the same total time as
old `persist.store_analysis`. This is not currently visible in the internal
`indexing` phase, but it matters for full command wall time. The likely reason
is that the row-planning helper still performs much of the same Python-side
artifact planning and still issues thousands of `sql.select` calls while
building rows.

So the rewrite removed expensive backend transaction/session behavior from the
measured indexing phase, but it did not yet make row planning truly
DuckDB-native.

## Memory

New DuckDB `index --full` peak memory medians by model:

| Model | Median peak RSS | Max peak RSS |
| --- | ---: | ---: |
| `current-minilm-sentence-transformers` | 426.0 MiB | 580.3 MiB |
| `bge-small-en-v1.5-sentence-transformers` | 431.0 MiB | 606.7 MiB |
| `bge-small-en-v1.5-onnx` | 439.2 MiB | 610.5 MiB |
| `jina-embeddings-v2-base-code-onnx` | 599.4 MiB | 880.0 MiB |
| `nomic-embed-text-v1.5-sentence-transformers` | 605.6 MiB | 865.3 MiB |
| `nomic-embed-text-v1.5-onnx` | 608.8 MiB | 857.1 MiB |

No failure summaries were found. The campaign did not show the earlier unsafe
memory spiral.

## Interpretation

The DuckDB bulk full-index rewrite achieved one important goal:

- the backend `indexing` phase is no longer the bottleneck;
- it is now substantially faster than the old DuckDB write path;
- it is also faster than the previous SQLite internal indexing phase.

But it did not achieve the acceptance goal:

- `index --full` wall-clock remains about `1.99x` the previous SQLite baseline;
- the strict `1.15x` gate is not met;
- most end-to-end time is now outside the structural backend write phase.

The remaining cost is split between:

1. embedding generation and materialization, which dominates total phase time;
2. vector-store persistence, especially `vector_store.store_vectors`;
3. Python-side row planning inside `bulk_full_index.plan_rows`, which still
   resembles the old per-file artifact planning cost;
4. DuckDB index creation and commits, which remain visible fixed costs.

This means DuckDB is not losing because its structural table loads are slow.
The structural table loads are now cheap. It is losing because the full-index
command still pays embedding/vector costs and because the "bulk" planner still
does too much per-file Python/SQL work before the actual bulk loads.

## Recommendation

Do not declare DuckDB fixed based on this campaign. Also do not revert the
rewrite: it removed the measured backend write bottleneck and provides useful
profile visibility.

Next decision depends on product intent:

- If the goal is `index --full` parity with SQLite on this small-repo benchmark
  matrix, DuckDB still fails the gate and needs one more radical change focused
  on row planning and vector persistence.
- If the goal is keeping DuckDB viable for larger analytical/vector-heavy
  indexes, the rewrite is a credible foundation, but the current full-index
  small-repo acceptance target is not satisfied.

The next resolutive work should not tune table inserts. It should target:

1. eliminate `sql.select` from row planning by building all ID/name maps in
   Python from the complete full-index snapshot;
2. make `bulk_full_index.plan_rows` a pure in-memory transformation with no
   DuckDB queries;
3. reduce separated vector-store duplication by either bulk-loading vector
   rows through a truly shared DuckDB relation path or deferring vector-store
   mirroring outside the critical full-index timing path;
4. consider skipping or deferring secondary index creation for small repos
   where query warmup does not need every index immediately.

Until that is done, a full `--backend both` acceptance campaign would be useful
only for formal confirmation. Based on the current DuckDB-only run compared to
the previous SQLite baseline, DuckDB is still around `2.0x` SQLite for
`index --full`, so it is unlikely to pass the `1.15x` gate without more code
changes.
