# Configuration

Codira can run without a config file. Runtime commands create a default
user-level config on first use when the platform user config directory is
writable, and users can create or inspect config files explicitly with:

```bash
codira config init
codira config init --full
codira config dump
codira config explain embeddings.batch_size
codira config validate
```

## Precedence

Effective configuration is resolved in this order:

```text
CLI flags
-> CODIRA_* environment variables
-> repository config: .codira/config.toml
-> user config: platform user config directory
-> system config: platform system config directory
-> built-in defaults
```

Repository config lives at `.codira/config.toml`. The file can be committed,
while normal `.codira` index artifacts remain ignored.

## Generated Config

The default generated file is:

```toml
config_version = 1

[backend]
name = "sqlite"

[plugins]
disable_third_party = false
disabled_analyzers = []

[embeddings]
enabled = true
engine = "sentence-transformers"
vector_store = "sqlite"
model = "sentence-transformers/all-MiniLM-L6-v2"
version = "1"
dimension = 384
device = "cpu"
batch_size = 32
torch_num_threads = 0
torch_num_interop_threads = 0

[embeddings.gpu]
device_id = 0
memory_limit_mb = 0

[embeddings.indexing]
mode = "immediate"
object_types = ["symbol", "documentation"]
max_text_chars = 0
include_paths = []
exclude_paths = []
```

`torch_num_threads = 0` and `torch_num_interop_threads = 0` mean Codira leaves
Torch defaults unchanged.

`embeddings.gpu.memory_limit_mb = 0` means no explicit GPU memory limit is
configured.

`embeddings.engine` selects the active embedding engine plugin. The first-party
engines are `"sentence-transformers"` and `"onnx"`.

`embeddings.vector_store` selects the active vector-store plugin. The
first-party local stores are `"sqlite"` and `"duckdb"` and use separated files
under `.codira/embeddings.db` or `.codira/embeddings.duckdb`.

`embeddings.indexing.mode = "immediate"` computes embeddings during
`codira index`. Set it to `"deferred"` to persist structural index rows first
and queue embeddings for a later `codira index --embeddings-only` pass.

`embeddings.indexing.object_types` limits which persisted object types receive
embeddings. Supported values are `"symbol"` and `"documentation"`. An empty
list skips all embedding rows while leaving structural indexing enabled.

`embeddings.indexing.max_text_chars = 0` means no text-size limit. Positive
values skip embedding payloads longer than the configured number of
characters.

`embeddings.indexing.include_paths` and `exclude_paths` are repo-root-relative
path prefixes. Include filters are evaluated first; exclude filters remove
matching files from embedding computation.

## Repository Performance Profile

This repository commits an explicit `.codira/config.toml` tuned from the
Issue #57 backend and embedding matrix:

- `backend.name = "duckdb"` selects the backend with the strongest measured
  read/query performance on the bk-cpp benchmark set.
- `embeddings.indexing.mode = "immediate"` keeps the clean matrix path as the
  default indexing mode. Deferred mode remains available for operators who
  explicitly want a two-step structural/indexing workflow.
- `embeddings.indexing.object_types = ["symbol", "documentation"]` keeps both
  retrieval channels active. The matrix showed symbol embeddings dominate
  runtime, while documentation embeddings are comparatively cheap.
- `embeddings.indexing.max_text_chars = 0` keeps documentation embeddings
  uncapped. The capped-docs matrix did not show enough total-runtime benefit
  to justify reducing retrieval coverage by default.
- `embeddings.batch_size = 32` and zero Torch thread overrides preserve the
  current portable defaults. Host-local calibration can still override them
  through config, CLI flags, or environment variables.

The embedding matrix is hardware-sensitive because embedding throughput,
DuckDB memory pressure, and Torch scheduling depend on CPU, RAM, GPU, and
local model state. Re-run the matrix after a meaningful hardware change before
treating these values as tuned for the new host. The matrix is a long
operation; run it only when the expected hardware or backend signal justifies
the elapsed time.

## Profiles

`codira config init --profile default` writes conservative defaults.

`codira config init --full` writes the core defaults plus every known
first-party plugin option with its default value.

`codira config init --profile low-memory` lowers the embedding batch size and
sets conservative Torch thread counts.

`codira config init --profile gpu` selects a GPU-oriented device and larger
batch size. It includes GPU metadata defaults but does not auto-detect hardware.

## Embedding Calibration

`codira calibrate embeddings` runs a bounded offline calibration workflow and
prints a config-compatible TOML snippet by default:

```bash
codira calibrate embeddings
codira calibrate embeddings --print
make calibrate-embeddings-config
codira calibrate embeddings --output /tmp/codira-embeddings.toml
codira calibrate embeddings --write
```

`--write` is the only mode that mutates the user config file. `--print` and
`--output` do not create or update user config.

Calibration benchmarks deterministic text payloads against locally available
embedding model artifacts. It does not download models or contact external
services. If the semantic dependency stack or local model artifact is missing,
Codira emits safe CPU fallback values instead of failing the command.

The printed block includes the complete `[embeddings]` section plus
`[embeddings.gpu]`, including model identity fields and calibrated runtime
parameters.

## Model Candidate Manifest

`benchmarks/embedding-model-candidates.json` records the model/engine
combinations used for embedding-engine campaigns. It includes the current
MiniLM default, `BAAI/bge-small-en-v1.5`,
`nomic-ai/nomic-embed-text-v1.5`, and
`jinaai/jina-embeddings-v2-base-code`.

Inspect the manifest and render a config snippet for one entry:

```bash
uv run python scripts/embedding_model_manifest.py --list
uv run python scripts/embedding_model_manifest.py \
  --id bge-small-en-v1.5-onnx \
  --print-config
```

The manifest does not contain model weights. Use
`scripts/download_embedding_model.py` to source `$HOME/.hf_token`, download the
required Hugging Face artifacts, install ONNX files under the manifest's
`.codira/models/...` paths, and smoke-test each candidate before launching the
long campaign.

The current Jina candidate is ONNX-only because the
`jinaai/jina-embeddings-v2-base-code` SentenceTransformers remote-code path is
not compatible with the pinned Transformers API used by this repository.

## Environment Overrides

Existing process-local environment overrides still work and take precedence
over config files:

| Variable | Config key |
| --- | --- |
| `CODIRA_INDEX_BACKEND` | `backend.name` |
| `CODIRA_DISABLE_THIRD_PARTY_PLUGINS` | `plugins.disable_third_party` |
| `CODIRA_EMBED_BATCH_SIZE` | `embeddings.batch_size` |
| `CODIRA_EMBED_DEVICE` | `embeddings.device` |
| `CODIRA_TORCH_NUM_THREADS` | `embeddings.torch_num_threads` |
| `CODIRA_TORCH_NUM_INTEROP_THREADS` | `embeddings.torch_num_interop_threads` |

## Validation

Config validation is strict. Unknown keys, invalid types, invalid enum values,
and invalid numeric ranges fail before runtime work proceeds.

When validating the effective config, Codira also validates plugin tables
against schemas exposed by loaded plugins. Configured plugin tables for
unloaded plugins produce warnings and keep exit status `0`; JSON output reports
`status = "ok_with_warnings"`.

## Plugin Configuration

Plugin activation and plugin-specific settings live under namespaced tables:

```toml
[plugins.analyzer-python]
enabled = true
include_paths = ["src", "tests"]
exclude_paths = ["tests/fixtures"]
emit_imports = true

[plugins.backend-sqlite]
enabled = true
```

Common plugin keys:

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Disables the plugin when set to `false`. |

Common analyzer keys:

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `include_paths` | list[str] | `[]` | Repo-relative POSIX paths to include after suffix/family eligibility. Empty means include all otherwise eligible paths. |
| `exclude_paths` | list[str] | `[]` | Repo-relative POSIX paths to exclude after suffix/family eligibility. Excludes win over includes. |

Path filter values must be non-empty repo-relative paths. Absolute paths and
`..` traversal segments are invalid.

First-party analyzer options:

| Table | Options |
| --- | --- |
| `[plugins.analyzer-python]` | `emit_module_documentation`, `emit_imports`, `emit_constants`, `emit_type_aliases` |
| `[plugins.analyzer-json]` | `enabled_families = ["schema", "package", "release"]`, `emit_dependencies`, `emit_scripts`, `emit_schema_properties` |
| `[plugins.analyzer-c]` | `use_leading_comments`, `emit_doxygen_documentation`, `include_system_includes`, `emit_macros` |
| `[plugins.analyzer-cpp]` | `use_leading_comments`, `emit_doxygen_documentation`, `include_system_includes`, `emit_namespaces`, `emit_macros` |
| `[plugins.analyzer-bash]` | `emit_functions` |
| `[plugins.analyzer-markdown]` | `strip_front_matter`, `emit_file_artifact_without_headings`, `min_heading_level`, `max_heading_level` |
| `[plugins.analyzer-text]` | `include_root_files`, `include_docs_directories`, `exclude_generated`, `exclude_fixtures_logs` |

First-party backend tables currently accept only common plugin keys:

```toml
[plugins.backend-sqlite]
enabled = true

[plugins.backend-duckdb]
enabled = true
```

Disabling the configured active backend is invalid. Disable an inactive backend
only, or change `[backend].name` first.
