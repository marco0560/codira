# Aggregate Embedding Campaign Report - 2026-07-11

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-11-aggregate-embedding-campaign-report.md`
(SHA-256 `f8f5adff493ceb690a1fd0da22e98ef7d09a1bfa62d13b58d666bb21fdad9a67`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/analysis/2026-07-11-aggregate-embedding-command-times.csv` | available |
| `.artifacts/analysis/2026-07-11-aggregate-embedding-cost-utility.csv` | available |
| `.artifacts/final-embedding-model-campaign/*` | unavailable historical pattern |
| `.artifacts/final-embedding-model-campaign/20260701T045905` | unavailable historical path |
| `.artifacts/issue-057-smoke/20260611-duckdb-batch-smoke-dry-run` | unavailable historical path |
| `.artifacts/onnx-parameter-sweep/*` | unavailable historical pattern |
| `.artifacts/split-embedding-engine-experiment/*` | unavailable historical pattern |


## Scope

This report aggregates the current artifact evidence from:

- `.artifacts/final-embedding-model-campaign/*`
- `.artifacts/onnx-parameter-sweep/*`
- `.artifacts/split-embedding-engine-experiment/*`
- `.artifacts/issue-057-smoke/20260611-duckdb-batch-smoke-dry-run`

The exported tables are:

- `.artifacts/analysis/2026-07-11-aggregate-embedding-command-times.csv`
- `.artifacts/analysis/2026-07-11-aggregate-embedding-cost-utility.csv`

I interpret the requested "size of the report" as repository size, because the artifacts classify benchmark targets as small, medium, large, or huge repositories.

## Parity And Caveats

- The final embedding campaigns span multiple Codira commits, versions, run counts, and manifests. They are good for operational direction, not pure A/B attribution.
- The newest complete broad run, `.artifacts/final-embedding-model-campaign/20260701T045905`, used `RUNS=1`, `WARMUP=0`, `BACKEND_MODE=both`, and a 21-repository manifest.
- The ONNX parameter sweeps are narrower but better controlled for ONNX knobs: four local repositories, SQLite/DuckDB backends, BGE and Nomic ONNX variants.
- The split-engine experiment is a compatibility gate plus query experiment. It is not a general speed benchmark for all model pairs.
- `.artifacts/issue-057-smoke/20260611-duckdb-batch-smoke-dry-run` is a dry-run plan artifact. It contributes reproducibility and planned-command evidence, not elapsed timings.
- No artifact in this scope contains `codira refs` timings. `codira sym` appears in final-campaign Hyperfine output but not in the ONNX/split `results.jsonl` files.
- I do not add `timings.total` and `timings.embeddings`; the report uses command wall-clock means and keeps embedding phase counters as diagnostics only.

## Cost Function

The weighted cost function follows the benchmark-analysis planning bias:

```text
weighted_cost = 1 * mean(codira index --full)
              + 3 * mean(codira index)
              + 20 * mean(codira sym)
              + 20 * mean(codira emb)
              + 20 * mean(codira ctx)
              + 20 * mean(codira refs)
utility = 1000 / weighted_cost
```

Rows with missing commands use only available command weights and expose `available_weight` in the CSV. Do not compare rows with very different available weights as if they had identical coverage.

## Best Local Defaults

Recommended repository-local default for this workstation:

```toml
[backend]
name = "sqlite"

[embeddings]
engine = "onnx"
vector_store = "sqlite"
model = "BAAI/bge-small-en-v1.5"
dimension = 384
batch_size = 4

[plugins.embedding-onnx]
provider = "CPUExecutionProvider"
precision = "float32"
normalize = true
max_tokens = 512
intra_op_num_threads = 0
inter_op_num_threads = 0
```

I applied this to `.codira/config.toml`. I also changed the final embedding campaign generator so 384-dimensional ONNX candidates default to `batch_size = 4`. I did not change Codira built-in defaults in `src/codira/config.py`; those remain portable defaults, while this recommendation is machine- and artifact-specific.

## ONNX Parameters

- Best weighted BGE ONNX setting: `batch4-default-threads` on SQLite. It has the lowest ONNX sweep weighted cost: `143.094s` with available weight `41`.
- Best pure query BGE ONNX setting: `batch8-threads4x1` is slightly faster for `emb`/`ctx`, but the indexing penalty makes it worse as a general default.
- Best Nomic ONNX setting: `batch1-threads4x1`; larger batches are slower in the available sweeps.
- Keep `max_tokens = 512` for these fixed-shape local exports. Changing it changes over-limit vectors and should bump `[embeddings].version`.
- Keep `normalize = true`; split-engine parity and existing model configs assume normalized vectors.

## ONNX Sweep Ranking

| model_id | backend | variant | index_full_seconds | emb_seconds | ctx_seconds | weighted_cost_seconds | utility_per_1000_weighted_seconds | available_weight |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bge-small-en-v1.5-onnx | sqlite | batch4-default-threads | 100.365367 | 0.935695 | 1.200713 | 143.093522 | 6.988437 | 41 |
| bge-small-en-v1.5-onnx | sqlite | batch4-threads4x1 | 107.77074 | 0.880921 | 1.172749 | 148.844142 | 6.718437 | 41 |
| bge-small-en-v1.5-onnx | duckdb | batch4-threads4x1 | 110.016926 | 1.324201 | 1.431381 | 165.128576 | 6.055887 | 41 |
| bge-small-en-v1.5-onnx | sqlite | batch8-default-threads | 124.935518 | 0.93696 | 1.21489 | 167.972513 | 5.953355 | 41 |
| bge-small-en-v1.5-onnx | sqlite | batch8-threads4x1 | 130.549845 | 0.861279 | 1.137791 | 170.531244 | 5.864028 | 41 |
| bge-small-en-v1.5-onnx | duckdb | batch4-default-threads | 120.14932 | 1.25626 | 1.526181 | 175.798155 | 5.688342 | 41 |
| bge-small-en-v1.5-onnx | duckdb | batch8-threads4x1 | 135.942999 | 1.318113 | 1.493161 | 192.168475 | 5.203767 | 41 |
| bge-small-en-v1.5-onnx | duckdb | batch8-default-threads | 146.737699 | 1.421048 | 1.63052 | 207.769059 | 4.813036 | 41 |

## Final Campaign Ranking

| model_id | backend | index_full_seconds | index_seconds | sym_seconds | emb_seconds | ctx_seconds | weighted_cost_seconds | size_influence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bge-small-en-v1.5-onnx | sqlite | 3.538293 | 1.556266 | 1.915414 | 3.093423 | 3.90133 | 227.416428 | size-sensitive |
| bge-small-en-v1.5-onnx | duckdb | 81.238704 | 0.911937 | 1.028377 | 1.797047 | 2.590632 | 229.795162 | size-sensitive |
| nomic-embed-text-v1.5-onnx | duckdb | 57.663889 | 0.974283 | 1.17162 | 2.736681 | 3.603979 | 247.659717 | size-sensitive |
| jina-embeddings-v2-base-code-onnx | duckdb | 58.036371 | 0.978586 | 1.143748 | 2.875535 | 3.641192 | 255.688541 | size-sensitive |
| jina-embeddings-v2-base-code-onnx | sqlite | 3.955695 | 1.627225 | 1.883163 | 4.53586 | 5.403355 | 286.807058 | size-sensitive |
| nomic-embed-text-v1.5-onnx | sqlite | 3.868852 | 1.62163 | 1.864112 | 4.562 | 5.538218 | 289.969768 | size-sensitive |
| current-minilm-sentence-transformers | sqlite | 50.396842 | 1.553917 | 1.848542 | 4.870689 | 7.777559 | 386.013344 | size-sensitive |
| bge-small-en-v1.5-sentence-transformers | sqlite | 13.832008 | 1.545741 | 1.83661 | 6.821397 | 7.717823 | 386.318739 | size-sensitive |
| current-minilm-sentence-transformers | duckdb | 68.189357 | 0.857147 | 0.985886 | 6.424382 | 6.433056 | 387.666252 | size-sensitive |
| nomic-embed-text-v1.5-sentence-transformers | duckdb | 55.20678 | 0.959619 | 1.115376 | 7.18796 | 8.03123 | 420.603406 | size-sensitive |

## Size Influence

The cost values are not constant with repository size. Full indexing dominates size sensitivity because embedding rows, analyzer work, and storage writes scale with the indexed corpus. Warm `codira index`, `codira sym`, and `codira ctx` are much flatter on already-built indexes, but they still vary with backend and result assembly cost. The CSV exposes per-size weighted ranges in `size_weighted_cost_seconds`.

Practical reading:

- For small/local repos, BGE ONNX on SQLite is the best default balance.
- For larger repos, 768-dimensional models become expensive quickly; Nomic and Jina ONNX remain viable when quality needs justify the index cost, but they are not the default speed profile.
- Backend choice matters less for BGE ONNX than model/engine choice. SQLite edges out DuckDB in the ONNX sweep and is safer as the default vector-store pairing for this host.

## Split Engine Feasibility

| pair | passed | min_cosine | mean_cosine | threshold |
| --- | --- | --- | --- | --- |
| bge-small-en-v1.5-st-index-onnx-query | False | 0.952487 | 0.958008 | 0.99 |
| bge-small-en-v1.5-st-index-onnx-query | False | 0.952487 | 0.958008 | 0.99 |
| bge-small-en-v1.5-st-index-onnx-query | False | 0.952487 | 0.958008 | 0.99 |
| nomic-v1.5-st-index-onnx-query | True | 1.0 | 1.0 | 0.99 |
| bge-small-en-v1.5-st-index-onnx-query | False | 0.952487 | 0.958008 | 0.99 |
| nomic-v1.5-st-index-onnx-query | True | 1.0 | 1.0 | 0.99 |

Separating indexing and query engines is possible only when the model pair passes the vector compatibility gate. Current result:

- BGE SentenceTransformers index plus BGE ONNX query is not acceptable: minimum cosine is about `0.95249`, below the `0.99` threshold. Do not use it as a split-engine default.
- Nomic SentenceTransformers index plus Nomic ONNX query is compatible: minimum cosine is effectively `1.0`. It is possible, but not a better general default because its indexing cost is much higher than BGE ONNX.

## Files Updated

- `.codira/config.toml`: switched local default to BGE ONNX / SQLite / batch 4 / ONNX Runtime default threads.
- `scripts/run_final_embedding_model_campaign.py`: changed 384-dimensional ONNX campaign batch default from 8 to 4.
- `scripts/run_onnx_parameter_sweep.py`: made variant rendering reuse the shared campaign batch default so sweep overrides keep working after the default change.
- `docs/scripts.md` and `docs/configuration.md`: documented the new measured profile and why it is local, not a portable built-in default.
- `tests/test_onnx_parameter_sweep.py`: added coverage for the campaign batch default.

## Validation Status

- `uv run codira caps --json`: passed before edits.
- `uv run codira index`: attempted, then interrupted after several minutes because the current ONNX embedding configuration was doing full embedding work and was not needed for artifact analysis.
- `uv run codira config dump --level repo --json`: passed and resolved BGE ONNX / SQLite / batch 4 / default ONNX threads from `.codira/config.toml`.
- `uv run pytest tests/test_onnx_parameter_sweep.py tests/test_config.py -q`: passed, 25 tests.
- `uv run ruff check scripts/run_final_embedding_model_campaign.py scripts/run_onnx_parameter_sweep.py tests/test_onnx_parameter_sweep.py`: passed.
- `uv run ruff format --check scripts/run_final_embedding_model_campaign.py scripts/run_onnx_parameter_sweep.py tests/test_onnx_parameter_sweep.py`: passed.
- `uv run ruff format --check --preview docs/scripts.md docs/configuration.md`: passed.
