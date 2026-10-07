# Final Embedding Campaign 20260629T204308 DuckDB Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-06-30-final-embedding-campaign-20260629T204308-duckdb-intervention-plan.md`
(SHA-256 `36dbc51897ac1fe7adda9a402666fd1441a8efde5e551fed1bffa2d8b2f88a4f`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/final-embedding-model-campaign/20260629T002747` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T140909` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T192544` | unavailable historical path |
| `.artifacts/final-embedding-model-campaign/20260629T204308` | unavailable historical path |
| `benchmarks/embedding/model-candidates.json` | available |
| `benchmarks/embedding/uv-backed-repos.local.json` | available |

Resolved directory moves:

- `benchmarks/embedding-model-candidates.json` → `benchmarks/embedding/model-candidates.json`.
- `benchmarks/uv-backed-repos.local.json` → `benchmarks/embedding/uv-backed-repos.local.json`.


## Scope

Artifacts analyzed:

- Current DuckDB campaign: `.artifacts/final-embedding-model-campaign/20260629T204308`
- Last comparable SQLite campaign: `.artifacts/final-embedding-model-campaign/20260629T002747`
- Pre-schema-change DuckDB campaign: `.artifacts/final-embedding-model-campaign/20260629T140909`
- Broken cache-regression DuckDB campaign, used only as a sanity check: `.artifacts/final-embedding-model-campaign/20260629T192544`

The current campaign completed all 6 model configurations across the 4 benchmark repositories on DuckDB.

The comparison uses the agreed backend utility score:

```text
score = full_index + 3 * partial_index + 20 * mean(ctx, cov, sym, symlist, emb, calls, audit)
```

Lower is better. `help`, `plugins`, and `caps` are excluded because they mostly measure process/config/plugin overhead rather than backend behavior.

## Parity Checks

The current run was executed at commit:

```text
cc0f7b2f9e3bd7d3bad5b0c5e942282de27dc452
```

Relevant plugin versions in the current run:

```text
codira-backend-duckdb: 1.50.0
codira-backend-sqlite: 1.45.1
codira-vector-store-duckdb: 1.0.6
codira-vector-store-sqlite: 1.0.1
codira-embedding-onnx: 1.0.1
codira-embedding-sentence-transformers: 1.0.1
```

The current run is comparable by repository and model manifest with the SQLite run `20260629T002747` and the pre-schema DuckDB run `20260629T140909`.

## Utility Scores

Average score over the 4 repositories:

| Model | SQLite 20260629T002747 | DuckDB before schema 20260629T140909 | DuckDB after schema 20260629T204308 | After / SQLite | After / Before |
|---|---:|---:|---:|---:|---:|
| bge-small-en-v1.5-onnx | 12.803 | 17.622 | 17.619 | 1.376x | 1.000x |
| bge-small-en-v1.5-sentence-transformers | 33.176 | 38.578 | 38.134 | 1.149x | 0.989x |
| current-minilm-sentence-transformers | 32.834 | 39.104 | 37.427 | 1.140x | 0.957x |
| jina-embeddings-v2-base-code-onnx | 18.420 | 24.117 | 23.953 | 1.300x | 0.993x |
| nomic-embed-text-v1.5-onnx | 17.304 | 22.924 | 23.039 | 1.331x | 1.005x |
| nomic-embed-text-v1.5-sentence-transformers | 42.056 | 47.689 | 47.995 | 1.141x | 1.006x |
| Overall mean | 26.099 | 31.672 | 31.361 | 1.202x | 0.990x |

Interpretation:

- The schema ownership/native DuckDB rewrite did not create a material score improvement by itself.
- It recovered from the cache-regression failure and is about 1% better than the pre-schema DuckDB run overall.
- DuckDB remains about 20% worse than SQLite on the agreed workflow-weighted utility score.
- ONNX models are still much better for normal workflow utility because query latency dominates the score.

## Current DuckDB Model Ranking

Average current-run score over 4 repositories:

| Rank | Model | Score | Full index | Partial index | Query mean |
|---:|---|---:|---:|---:|---:|
| 1 | bge-small-en-v1.5-onnx | 17.619 | 4.497 | 0.446 | 0.589 |
| 2 | nomic-embed-text-v1.5-onnx | 23.039 | 5.373 | 0.441 | 0.817 |
| 3 | jina-embeddings-v2-base-code-onnx | 23.953 | 5.133 | 0.443 | 0.875 |
| 4 | current-minilm-sentence-transformers | 37.427 | 4.280 | 0.441 | 1.591 |
| 5 | bge-small-en-v1.5-sentence-transformers | 38.134 | 4.484 | 0.441 | 1.616 |
| 6 | nomic-embed-text-v1.5-sentence-transformers | 47.995 | 5.418 | 0.442 | 2.063 |

The backend choice matters, but engine/model choice matters more for day-to-day utility. The ONNX query path gives the strongest workflow score.

## Warm Full-Index DuckDB Profile

The current-minilm run showed the same profile shape as the other models, so the broader all-model profile is more useful.

For current-minilm, aggregate warm full-index hyperfine sum was `17.120s`. Top-level DuckDB spans:

| Span | Seconds | Share |
|---|---:|---:|
| `bulk_full_index.load_embeddings` | 9.281 | 54.2% |
| `bulk_full_index.create_indexes` | 2.232 | 13.0% |
| `bulk_full_index.plan_rows` | 1.343 | 7.8% |
| `bulk_full_index.commit_structural` | 1.025 | 6.0% |
| `bulk_full_index.load_structural_tables` | 0.798 | 4.7% |
| `bulk_full_index.rebuild_derived_indexes` | 0.594 | 3.5% |
| `bulk_full_index.load_reference_scan_rows` | 0.390 | 2.3% |
| `bulk_full_index.load_relationship_tables` | 0.307 | 1.8% |

Nested costs inside and around embedding load:

| Span | Seconds | Share |
|---|---:|---:|
| `embeddings.load_cached_vectors` | 5.330 | 31.1% |
| `vector_store.store_vectors` | 2.685 | 15.7% |
| `embeddings.insert_rows` | 0.873 | 5.1% |
| `sql.create_index` | 2.240 | 13.1% |
| `duckdb.raw_commit` | 1.025 | 6.0% |

The same pattern holds across models:

- 384-dimensional models: `load_embeddings` is about 52-54% of warm full index.
- 768-dimensional models: `load_embeddings` rises to about 56-57%, mostly because vector-store writes and embedding-row inserts carry larger vectors.
- `create_indexes` remains a stable 12-17% of warm full index.

## Cold Index Diagnostic

The `*-index-phases.json` files are cold diagnostic runs, not warm hyperfine means. They correctly show:

- `embeddings_recomputed > 0`
- `embeddings_reused = 0`
- embedding hook time around 86-88% of cold total for the 384-dimensional sentence-transformer models

That is useful for cold-start safety, but it is not the bottleneck in the warm full-index campaign. Warm full index is dominated by cached-vector load plus vector-store rewrite.

## Main Findings

1. DuckDB is no longer broken by the full re-embedding regression.
   The broken run `20260629T192544` had current-minilm warm full-index sum around `168.5s`; the fixed run is back to `17.1s`.

2. The schema ownership/native bulk rewrite did not yet move the practical score enough.
   Overall weighted utility improved only from `31.672` to `31.361` versus pre-schema DuckDB.

3. SQLite is still ahead on the agreed workflow-weighted score.
   Current DuckDB is about `1.202x` SQLite overall. The gap is larger for ONNX models because ONNX makes query latency low enough that backend overhead is more visible.

4. Full-index backend cost is concentrated and actionable.
   The top warm full-index costs are cache-vector loading, vector-store rewriting, index creation, commit cost, and full-index row planning.

5. The specialized DuckDB schema has value mainly as an enabler.
   It did not produce direct speedup, but it gives enough backend ownership to replace row/blob lifecycle behavior with DuckDB-native table lifecycle behavior.

## Recommended Intervention Areas

### 1. Preserve Materialized Vectors On Warm Full Index

Problem:

Warm full index currently loads cached vectors and rewrites materialized vector-store rows. For current-minilm, that costs:

```text
embeddings.load_cached_vectors: 5.330s
vector_store.store_vectors:    2.685s
embeddings.insert_rows:        0.873s
```

This is about 52% of warm full-index time before considering overlapping/nested span semantics.

Contract extension:

The current vector-store full-index contract is too narrow for a real DuckDB-native fast path. `VectorStoreFullIndexRequest` carries `rows: Sequence[PreparedVectorRow]`, where cached rows must already have their serialized vector payload loaded into Python before the vector store can materialize them. That forces the measured warm path:

```text
embedding_vector_cache lookup -> Python vector bytes/list materialization -> vector-store rewrite
```

Add a full-index identity row contract so vector stores can preserve existing rows without Python vector round-trips:

```python
@dataclass(frozen=True)
class PreparedVectorIdentityRow:
    object_type: str
    stable_id: str
    content_hash: str
    vector: bytes | None = None
```

Extend `VectorStoreFullIndexRequest` with a field such as:

```python
identity_rows: Sequence[PreparedVectorIdentityRow] = ()
preserve_existing: bool = False
```

The existing `rows` field remains the payload-bearing path for newly computed or explicitly supplied vectors. The new identity rows describe the complete desired materialized vector set, including rows that should be copied from existing `vectors` or `vector_cache` tables by backend-native joins.

Plan:

- Add a backend-owned full-index vector preservation path.
- Stage the new embedding identities as `(object_type, object_id, content_hash, backend, dimensions, model/version identity)`.
- Join staged identities against existing vector cache/materialized vector rows in DuckDB.
- Reuse already-valid rows by table operation, not by loading vectors into Python.
- Only compute and insert genuinely missing vectors.
- Keep semantic invalidation tied to content hash, embedding backend identity, dimensions, and vector-set identity.

Expected effect:

- Large reduction in warm full-index time.
- Largest benefit on 768-dimensional models where vector rewrites are most expensive.

Tests:

- Full-index second run must report reused vectors and must not call the embedder for unchanged content.
- Full-index second run must not invoke vector-store bulk rewrite for unchanged vector identities.
- Changing model identity, dimensions, backend name, or content hash must force recomputation/materialization.

Semgrep:

- Add a rule forbidding full-index warm paths from calling Python vector deserialization for cache reuse.
- Add a rule requiring DuckDB full-index vector preservation to use backend-owned set operations, not row-wise `load_vectors` loops.

Docs:

- Document full-index vector preservation semantics in the DuckDB backend README and backend architecture notes.

### 2. Replace Vector Cache Lookup With Set-Based DuckDB Resolution

Problem:

`embeddings.load_cached_vectors` costs about 25-31% of warm full index across models. It exists to avoid recomputation, but the current path still pays to fetch vector blobs/lists through the generic cache resolution boundary.

Plan:

- Introduce a DuckDB-native `resolve_full_index_embedding_cache` helper.
- Store staged pending embedding rows in a temporary DuckDB table.
- Use `LEFT JOIN` against `embedding_vector_cache` to classify rows as cached or missing.
- For cached rows, keep vector data inside DuckDB and pass only identity rows to downstream materialization.
- For missing rows, export only text payloads to Python embedding generation.

Expected effect:

- Eliminate most of the current 5.2-5.4s cached-vector lookup cost on warm full index.
- Reduce Python memory pressure because cached vectors are not materialized in Python.

Tests:

- Regression test with cached vectors proving no embedder call and no Python vector fetch on all-cached full index.
- Mixed cached/missing test proving only missing payloads reach `embed_texts`.
- Profile assertion test or fake profiler test proving the warm all-cached path records a set-based cache-resolution span instead of `embeddings.load_cached_vectors`.

Semgrep:

- Rule forbidding `_load_cached_embedding_vectors` inside `persist_full_index` except in explicitly documented fallback code.

Docs:

- Update backend contract docs to distinguish ordinary incremental cache lookup from full-index set-based cache resolution.

### 3. Rework DuckDB Index Lifecycle

Problem:

`bulk_full_index.create_indexes` costs 12-17% of warm full index across models. The current backend drops/recreates many indexes for every full index. The schema is now backend-owned, so this can be redesigned around DuckDB behavior instead of inherited SQLite assumptions.

Plan:

- Audit each DuckDB index for actual query benefit using the benchmark query mix.
- Split indexes into:
  - persistent indexes that survive full index table refreshes,
  - indexes only needed for rare lookup paths,
  - indexes that can be removed because DuckDB scans/vectorized joins are faster at this scale.
- Prefer table-swap or CTAS lifecycle where possible:
  - build staged tables,
  - build only necessary indexes,
  - atomically swap/rename,
  - avoid recreating indexes unrelated to changed data.
- For lookup/materialized tables, test whether sorted CTAS or denormalized tables remove the need for secondary indexes.

Expected effect:

- Recover up to the 2-3s per four-repo full-index cost currently spent in index creation.
- Reduce SQLite/DuckDB utility-score gap, especially for ONNX models where query time is low and full-index overhead is more visible.

Tests:

- Query contract tests for `sym`, `symlist`, `calls`, `refs`, `ctx`, and `audit` after index lifecycle change.
- Backend-specific schema tests proving required indexes/tables are present and stale indexes are absent.
- Performance guard test with fake profiler ensuring no full-index path recreates indexes that are marked persistent.

Semgrep:

- Rule forbidding direct `_drop_duckdb_schema_indexes` / `_create_duckdb_schema_indexes` calls outside the backend-owned full-index lifecycle helper.
- Rule requiring new DuckDB index definitions to be declared in the package schema module, not inline.

Docs:

- Add a DuckDB schema/index lifecycle section explaining which indexes are persistent and which are rebuilt.

### 4. Fuse Structural Load, Derived Tables, And Commit Boundaries

Problem:

Structural table load, derived-index rebuild, and commit account for meaningful residual time:

```text
load_structural_tables:       ~4-5%
rebuild_derived_indexes:      ~3%
commit_structural/raw_commit: ~5-6%
relationship/reference load:  ~3-4%
```

The cost is not individually dominant, but together it is large enough to matter after fixing vector reuse.

Plan:

- Keep the full-index transaction open through structural and embedding table staging where safe.
- Reduce commit count and avoid commit-before-embedding unless required by external vector-store visibility.
- Rebuild derived tables using CTAS from staged structural tables instead of delete/insert into existing derived tables.
- Fuse reference and relationship CSV ingestion where practical, or use Arrow/table registration for medium-sized row groups to avoid CSV write/read overhead.

Expected effect:

- Moderate full-index improvement.
- Cleaner backend-native lifecycle once vector preservation removes the need for split structural/vector commits.

Tests:

- Crash/rollback tests around failed embedding flush after staged structural load.
- Freshness metadata tests proving no partially committed full-index state is visible.
- Profile tests proving only one required commit boundary remains.

Semgrep:

- Rule limiting raw commits in DuckDB full-index lifecycle to named helper methods.

Docs:

- Document full-index transaction phases and failure semantics.

### 5. Make Backend Utility Score A First-Class Benchmark Output

Problem:

The current reports require ad hoc calculation of practical backend value. Full-index time alone is misleading, and raw command tables obscure the normal workflow weighting.

Plan:

- Add the agreed utility score to campaign analysis scripts:

```text
score = full_index + 3 * partial_index + 20 * mean(ctx, cov, sym, symlist, emb, calls, audit)
```

- Emit score per repo/model/backend and aggregated by model/backend.
- Store a machine-readable `utility-summary.json` and a markdown table in campaign artifacts.
- Keep `audit` in the query mean and exclude `help`, `plugins`, and `caps`.

Expected effect:

- Faster go/no-go decisions.
- Reduces risk of optimizing the wrong phase.

Tests:

- Unit tests for score calculation with fixed hyperfine fixtures.
- Regression test proving command classification keeps `audit` and excludes `help/plugins/caps`.

Docs:

- Document the score in benchmark process docs and report templates.

## Proposed Combined Implementation Plan

The next change should be one coordinated DuckDB backend pass, not another narrow micro-optimization. The areas are coupled: set-based vector reuse changes embedding cache lookup, vector-store materialization, transaction boundaries, and what indexes are worth rebuilding.

### Phase 1: Measurement And Guard Rails

1. Add utility score generation to benchmark tooling.
2. Extend the vector-store full-index contract with identity rows and preservation intent:
   - add `PreparedVectorIdentityRow`,
   - add `identity_rows` and `preserve_existing` to `VectorStoreFullIndexRequest`,
   - keep existing `rows` as the payload-bearing compatibility path.
3. Add focused tests for warm full-index vector reuse:
   - all cached,
   - mixed cached/missing,
   - model/dimension invalidation.
4. Add Semgrep rules for:
   - no Python cached-vector loading in DuckDB full-index warm path,
   - no direct index drop/create outside lifecycle helper.
5. Validate with `uv run python scripts/validate_repo.py`.
6. Commit.

### Phase 2: DuckDB-Native Vector Reuse

1. Add staged embedding identity table for full-index persistence.
2. Implement set-based cache classification in DuckDB.
3. Preserve valid materialized vector rows without Python vector round-trip.
4. Compute and insert only missing vectors.
5. Keep `fresh_full_index=True` cleanup optimization.
6. Validate tests, Semgrep, `codira audit`, and targeted campaign on current-minilm.
7. Commit.

### Phase 3: Vector Store Materialization Rewrite

1. Extend the DuckDB vector store full-index writer with a preservation path.
2. Use `INSERT INTO ... SELECT`/CTAS from existing vector tables for unchanged rows.
3. Write only new/missing vector rows via Arrow/table registration.
4. Add tests proving unchanged vector rows are not rewritten.
5. Validate and commit.

### Phase 4: Index And Transaction Lifecycle

1. Introduce a single DuckDB full-index lifecycle helper owning:
   - staging table creation,
   - table swap,
   - derived table rebuild,
   - index creation/preservation,
   - commit/rollback boundaries.
2. Remove unnecessary recreated indexes based on query coverage.
3. Convert derived rebuilds to CTAS/table swap where possible.
4. Validate query contract tests and targeted benchmark.
5. Commit.

### Phase 5: Full Campaign

1. Run DuckDB-only campaign first:

```bash
uv run python -m scripts.run_final_embedding_model_campaign --runs 5 --warmup 1 --manifest benchmarks/embedding/uv-backed-repos.local.json --model-manifest benchmarks/embedding/model-candidates.json --backend duckdb
```

2. If DuckDB score approaches SQLite, run `--backend both` for final confirmation.
3. Write a follow-up report comparing:
   - current post-schema baseline `20260629T204308`,
   - latest SQLite baseline `20260629T002747`,
   - new DuckDB run.

## Go / No-Go Recommendation

DuckDB is still salvageable only if the next intervention attacks vector reuse and vector-store preservation directly. Further tuning of row insertion, CSV loading, or index count alone is unlikely to close the gap because the main measured cost is cached-vector and materialized-vector lifecycle work.

If the next coordinated pass does not reduce the overall weighted DuckDB score by at least 10-15%, the pragmatic decision should be to keep SQLite as the default backend and retain DuckDB as an experimental/large-data backend until issue #20 vector backend work changes the storage equation.
