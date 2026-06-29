# DuckDB Slowdown Fix — 2026-06-25

## Status

Implemented on `feat/embedding-plugins` after the current benchmark campaign
was stopped.

Follow-up full-index work added an optional DuckDB `FullIndexBulkBackend` path.
The core indexer now dispatches `index --full` to that path only for backends
that explicitly implement it; SQLite remains on the existing session path and
continues to serve as the benchmark baseline.

The DuckDB bulk path is intentionally not another incremental tuning layer. It
owns the full-rebuild lifecycle, emits `bulk_full_index.*` profile spans, seeds
full-rebuild ID allocation from empty tables, and avoids the legacy
`persist.store_analysis` profile span. The acceptance gate for keeping DuckDB
as a production indexing backend is a full-index median no worse than `1.15x`
SQLite on the same complete backend-comparison campaign.

This is a deferred implementation plan for the DuckDB slowdown observed after
the embedding architecture changes. It records the comparison evidence, the
proposed code change, and the configuration-knob audit needed before applying
the fix.

## Campaigns Compared

Current campaign:

- Path: `.artifacts/final-embedding-model-campaign/20260623T223843+0200`
- Commit: `ae3c2a21130419744581429d7b31aac6a96f9041`
- Relevant entries: sentence-transformers / DuckDB rows for the overlapping
  repositories.

Preceding comparable campaign:

- Path: `.artifacts/20260618T095148Z-bk-cpp-duckdb`
- Commit: `7df2d1925f46754fe6c64cd9421f220c0c1d96fb`
- Backend: DuckDB
- Embedding engine: sentence-transformers
- Comparable repositories: `codira`, `Fontshow`, `chatops`, `sanikey`

The intermediate final-embedding campaign at
`.artifacts/final-embedding-model-campaign/20260622T115042Z` is not a valid
pre-change comparison because it was run from the same commit as the current
campaign.

## Evidence

For the four overlapping repositories:

- Hyperfine total for comparable commands: old `66.617s`, current `1115.082s`,
  about `16.74x` slower.
- Hyperfine `index --full` only: old `15.304s`, current `1043.876s`, about
  `68.21x` slower.
- Hyperfine excluding `index --full`: old `51.313s`, current `71.206s`, about
  `1.39x` slower.
- Phase `timings.total`: old `151.901s`, current `2194.553s`, about `14.45x`
  slower.
- Phase `timings.embeddings`: old `138.464s`, current `149.132s`, about
  `1.08x` slower.

Interpretation:

- The regression is concentrated in repeated DuckDB `index --full` work.
- Sentence-transformers inference time did not materially increase.
- The current Codira index profile shows most time under importlib
  `_find_and_load`, called from DuckDB connection execution through
  `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`.
- A local DuckDB settings check showed `python_enable_replacements = true` and
  `python_scan_all_frames = false`.

Working hypothesis:

DuckDB Python replacement scans are enabled on Codira-owned DuckDB connections.
That makes ordinary backend SQL execution pay Python/import-frame lookup cost.
Codira backend SQL does not need Python variable replacement, so this should be
disabled for backend-owned connections.

## Proposed Production Fix

Add a small DuckDB connection-configuration helper in
`packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`.

Expected behavior:

- Immediately after opening a raw DuckDB connection, execute:

  ```sql
  SET python_enable_replacements = false
  ```

- Apply the helper to every Codira-owned raw DuckDB connection opened by the
  production backend:

  - `DuckDBBackend.initialize()`, currently opening `module.connect(str(db_path))`
  - `DuckDBBackend.open_connection()`, currently opening
    `_duckdb_module().connect(str(_duckdb_db_path(root)))`

- Keep the setting local to the connection. Do not introduce a user-facing
  config knob unless a later benchmark proves this needs to be optional.

Suggested helper shape:

```python
def _configure_duckdb_connection(raw: _DuckDBRawConnection) -> _DuckDBRawConnection:
    raw.execute("SET python_enable_replacements = false")
    return raw
```

Then wrap raw opens:

```python
raw = _configure_duckdb_connection(module.connect(str(db_path)))
raw = _configure_duckdb_connection(_duckdb_module().connect(str(_duckdb_db_path(root))))
```

## Tests To Add

Add focused DuckDB backend tests. Prefer existing DuckDB backend test modules if
there is already a nearby connection/configuration test.

Required assertions:

- A backend-opened DuckDB connection reports `python_enable_replacements` as
  `false` through `duckdb_settings()`.
- Basic backend SQL still works through `DuckDBConnection.execute()` after the
  setting is applied.
- `initialize()` and `open_connection()` both apply the setting, so fresh
  schema bootstrap and normal query/index connections are covered.

If the setting is added through a helper, use a fake raw connection unit test
where useful, but keep at least one integration test against real DuckDB.

## Validation After Applying

Run before committing:

```bash
uv run pytest -q packages/codira-backend-duckdb/tests tests
uv run python scripts/validate_repo.py
```

Then rerun the smallest meaningful performance check after the current campaign
finishes:

```bash
time uv run codira index --full --backend duckdb --root .
```

For the campaign comparison, rerun the same overlapping DuckDB /
sentence-transformers slice for `codira`, `Fontshow`, `chatops`, and `sanikey`.

## Versioning

The fix changes first-party backend runtime behavior. If applying it on a branch
intended for release, bump:

- `codira-backend-duckdb`
- `codira-bundle-official` and its pinned backend dependency

The plugin runtime version should also advance if the project treats backend
runtime behavior changes as cache/runtime-boundary changes for release
coordination.

## Embedding Configuration Knob Audit

This audit was performed against the current code before writing this plan.

### Core `[embeddings]` knobs

Read and acted upon:

- `enabled`: checked by `src/codira/semantic/embeddings.py` before embedding.
- `engine`: selects the active embedding plugin.
- `vector_store`: selects the active vector-store plugin.
- `model`, `version`, `dimension`: form the embedding identity and model load
  settings; vector-store context injects them into the active engine config.
- `device`: passed to sentence-transformers model loading.
- `batch_size`: passed to sentence-transformers `model.encode()` and injected
  into plugin configs as `_codira_batch_size`; ONNX consumes that value for
  batching.
- `torch_num_threads`, `torch_num_interop_threads`: applied through
  `torch.set_num_threads()` and `torch.set_num_interop_threads()` before
  sentence-transformers model use.
- `indexing.mode`, `indexing.object_types`, `indexing.max_text_chars`,
  `indexing.include_paths`, `indexing.exclude_paths`: validated by config
  semantics and used by indexing selection.

Environment overrides are wired for:

- `CODIRA_EMBED_BATCH_SIZE`
- `CODIRA_EMBED_DEVICE`
- `CODIRA_TORCH_NUM_THREADS`
- `CODIRA_TORCH_NUM_INTEROP_THREADS`

Knobs that are validated/rendered but not directly enforced by the embedding
runtime:

- `embeddings.gpu.device_id`
- `embeddings.gpu.memory_limit_mb`

The actual runtime device selection is controlled by `embeddings.device`; the
code does not synthesize `cuda:{device_id}` from `gpu.device_id`, and it does
not enforce `gpu.memory_limit_mb`.

### `[plugins.embedding-sentence-transformers]`

Read and acted upon:

- `enabled`: common plugin discovery/config behavior.
- `trust_remote_code`: read by the legacy sentence-transformers runtime and
  passed to `SentenceTransformer(..., trust_remote_code=...)`.

The package boundary delegates to the legacy runtime without passing `root`
directly, but core sets `_ACTIVE_EMBEDDING_ROOT` around plugin calls, and the
legacy runtime resolves configuration through that context-local root.

Gap:

- The sentence-transformers plugin does not expose a plugin JSON Schema, so
  `trust_remote_code` is not schema-validated as a plugin-specific key. The
  runtime currently treats non-boolean values as `False`.

### `[plugins.embedding-onnx]`

Read and acted upon:

- `enabled`: common plugin discovery/config behavior.
- `model_path`: required, checked during provisioning, used to create the ONNX
  Runtime session.
- `tokenizer_path`: required, checked during provisioning, used to load the
  tokenizer.
- `provider`: passed to `onnxruntime.InferenceSession(..., providers=[...])`.
- `precision`: included in the embedding engine identity.
- `normalize`: controls vector normalization in ONNX pooling.
- `max_tokens`: enables tokenizer truncation and defensive per-encoding
  truncation before runtime input creation.
- `intra_op_num_threads`: applied to `onnxruntime.SessionOptions`.
- `inter_op_num_threads`: applied to `onnxruntime.SessionOptions`.

Batching note:

- ONNX does not have a plugin-local `batch_size` knob. It consumes the shared
  `[embeddings].batch_size` value injected by core as `_codira_batch_size`.

Gap:

- The ONNX plugin does not expose a plugin JSON Schema, so ONNX-specific keys
  are validated at engine runtime rather than by `config validate`. The runtime
  does fail fast for missing `model_path`/`tokenizer_path`, invalid integer
  thread/token settings, and invalid boolean `normalize`.

## Required Plugin JSON Schema Work

When applying this plan, make the plugin JSON configuration interface complete
across first-party plugins.

Required behavior:

- Every first-party plugin package under `packages/codira-*` that exposes a
  runtime plugin object must expose `configuration_json_schema()`.
- Schema implementations must return repository-owned JSON Schema objects
  built through the shared helpers in `src/codira/plugin_config.py`, such as
  `plugin_json_schema(...)` or `analyzer_json_schema(...)`.
- Plugin-specific keys must be represented in the schema with strict types and
  `additionalProperties = false` through the shared helper.
- Runtime parsing may still perform normalization and fail-fast checks, but
  wrongly typed or typoed plugin config keys should be rejected by
  `config validate` before indexing starts.

Embedding plugin additions:

- Add `configuration_json_schema()` to
  `packages/codira-embedding-sentence-transformers`.
  - Include `enabled`.
  - Include `trust_remote_code` as a boolean with default `false`.
- Add `configuration_json_schema()` to `packages/codira-embedding-onnx`.
  - Include `enabled`.
  - Include `model_path` and `tokenizer_path` as strings.
  - Include `provider` and `precision` as strings.
  - Include `normalize` as a boolean.
  - Include `max_tokens`, `intra_op_num_threads`, and
    `inter_op_num_threads` as integers with minimum `0`.
  - Do not add a plugin-local `batch_size`; ONNX must continue to consume the
    shared `[embeddings].batch_size` value injected by core as
    `_codira_batch_size`.

Tests to add for plugin JSON schema coverage:

- For both embedding packages, assert `configuration_json_schema()` exists and
  rejects unknown keys through `jsonschema.Draft202012Validator`.
- Assert wrong types are rejected for representative knobs:
  `trust_remote_code`, `model_path`, `max_tokens`, and
  `intra_op_num_threads`.
- Add or extend a first-party plugin inventory test that imports every
  first-party plugin factory and asserts the built plugin object exposes
  `configuration_json_schema()`.
- Add a config-validation integration test proving a typo in
  `[plugins.embedding-onnx]` and a non-boolean
  `[plugins.embedding-sentence-transformers].trust_remote_code` fail before
  indexing.

## Semgrep Regression Guards

Yes, add Semgrep rules, but do not rely on Semgrep alone for the exhaustive
inventory check. Semgrep should guard common code-shape regressions; the
inventory test should be the source of truth for "all plugins expose the JSON
schema interface".

Implemented guard split:

- A first-party plugin inventory test imports every first-party plugin factory
  and asserts the built plugin object exposes strict `configuration_json_schema()`.
- Semgrep guards common code-shape regressions that are cheap and reliable to
  detect syntactically.

Implemented Semgrep rule:

- `codira.plugins.require-shared-plugin-json-schema-helper`
  - Scope: `packages/codira-*/src/**/*.py`.
  - Purpose: flag `configuration_json_schema()` implementations that return a
    hand-written dictionary instead of `plugin_json_schema(...)` or
    `analyzer_json_schema(...)`.
  - Expected limitation: allow narrow exceptions only with a documented
    `nosemgrep` and a test proving equivalent strict JSON Schema behavior.

The missing-schema check was deliberately implemented as the inventory test
rather than Semgrep because the Semgrep expression required to prove absence of
a method across plugin-shaped classes was too slow on the real package tree.
The optional key-to-schema comparison remains a future AST validation test if
runtime config parsing grows more complex.

Validation after adding these guards:

```bash
uv run pytest -q tests/test_semgrep_rules.py
uv run python scripts/validate_semgrep_rules.py
uv run python scripts/validate_repo.py
```
