# Configuration

## Coverage roots

Configure coverage auditing under `[index.coverage]`. `roots = []` uses the
deterministic union declared by active analyzers; `roots = ["-"]` explicitly
disables coverage auditing. Other values are repository-relative glob patterns.
`exclude_suffixes` removes known, intentionally unsupported file types from
coverage diagnostics after root selection; suffixes use lowercase dotted form
such as `.yml`, or `<no-suffix>` for extensionless files.
The first-party defaults cover Python (`src`, `tests`, `scripts`), Bash
(`scripts`), C/C++ (`src`, `include`, `tests`), JSON (`config`, `.github`,
`scripts`), and Markdown/text (`docs`, `examples`).

Codira can run without a config file. Runtime commands can create a default
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

`codira config init` creates the repository config by default. Use
`codira config init --level user` when the file should be written to the
platform user config directory instead.

Most repository-scoped commands accept `--config-file PATH`. This option tells
Codira which repo-level config file to merge instead of
`<output-dir>/.codira/config.toml`; it does not move databases, indexes, model
artifacts, or other runtime state. `--output-dir DIR` selects the Codira state
root for a command, while `--config-file PATH` selects only the repo-level
configuration source. When both are provided, state is written under
`--output-dir` and configuration is read from `--config-file`.

## Generated Config

The default generated file is:

```toml
config_version = 1

[backend]
name = "sqlite"

[plugins]
disable_third_party = false
disabled_analyzers = []
documentation_audit_routes = []

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
work_batch_multiplier = 256
include_paths = []
exclude_paths = []

[index.concurrency]
strategy = "auto"
max_workers = 0
min_files = 16

[index.coverage]
roots = []
exclude_suffixes = []

[daemon]
enabled = false
debounce_ms = 250
include_paths = []
exclude_paths = []

[query_daemon]
enabled = false
```

`index.concurrency.strategy` is one of `"off"`, `"auto"`, `"process"`, or
`"thread"`. Auto mode prefers isolated process workers, falls back to serial
analysis when an active analyzer has not declared process support, and starts
only when at least `min_files` files are selected. `max_workers = 0` resolves
to at most four workers. Use `codira index --concurrency STRATEGY` or
`codira index --jobs N` for one-run overrides; `--jobs` selects auto mode with
an explicit cap. Backend writes and embedding persistence remain serial.

For example, to keep default coverage roots but suppress intentionally
unsupported CI and documentation asset formats:

```toml
[index.coverage]
exclude_suffixes = [".yml", ".yaml", ".dot", ".js", ".svg"]
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

Vector stores can retain vectors for older embedding or vector-store
identities. Use `codira emb purge` to inspect or delete retained sets:

```bash
codira emb purge --stale --dry-run
codira emb purge --stale --backend duckdb --keep 1 --yes
codira emb purge --all --backend sqlite --yes
```

The command defaults to the configured `[embeddings].vector_store`. Pass
`--backend sqlite` or `--backend duckdb` to target a specific local vector
store without editing the repository config. Destructive runs require `--yes`;
without it, purge runs as a dry run.

`embeddings.indexing.mode = "immediate"` computes embeddings during
`codira index`. Set it to `"deferred"` to persist structural index rows first
and queue embeddings for a later `codira index --embeddings-only` pass.

`embeddings.indexing.object_types` limits which persisted object types receive
embeddings. Supported values are `"symbol"` and `"documentation"`. An empty
list skips all embedding rows while leaving structural indexing enabled.

`embeddings.indexing.max_text_chars = 0` means no text-size limit. Positive
values skip embedding payloads longer than the configured number of
characters.

`embeddings.indexing.work_batch_multiplier` bounds indexing work segments as a
multiple of `embeddings.batch_size`. With the defaults, Codira processes at
most `32 * 256 = 8192` embedding rows per segment before calling the embedding
engine and vector-store flush path. Valid values are integers from `1` to
`4096`.

`embeddings.indexing.include_paths` and `exclude_paths` are repo-root-relative
path prefixes. Include filters are evaluated first; exclude filters remove
matching files from embedding computation.

## Optional daemon contract

`[daemon]` declares configuration for Codira's optional automatic-indexing
daemon. It does not enable a background process by itself, and explicit
`codira index` remains authoritative.

- `enabled` controls whether a later daemon runtime may start for the
  repository; the default is `false`.
- `debounce_ms` is a positive filesystem-notification coalescing interval.
- `include_paths` and `exclude_paths` are repo-root-relative watch prefixes;
  an empty include list watches every non-ignored path outside Codira and Git
  state directories. A matching change schedules the normal index operation;
  active analyzers still determine which files produce indexed records.

Set `daemon.enabled = true` and run `codira daemon run` to start foreground
automatic indexing. The `watchfiles` runtime debounces configured source-path
events, ignores Codira and Git state directories, and discards batches whose
paths match active Git ignore rules (including `.gitignore`). It checks Git
`HEAD` every second so a branch checkout is reconciled even when no source
event is delivered. The scheduler records the `HEAD` observed after each
successful index and queues a follow-up pass if it changes during indexing.
On Windows, the same lifecycle commands manage a repository-scoped automatic
start SCM service through the Windows-only `pywin32` dependency. Installation
requires permission to create a service and persists the canonical repository
root in that service's SCM parameters.

On Linux with a systemd user manager, `codira daemon install` writes and
enables a repository-scoped unit under the XDG user-unit directory. `start`,
`stop`, `status`, and `uninstall` operate on that same unit. Installation does
not enable systemd user lingering; use `loginctl enable-linger` separately if
the daemon must survive logout.

On macOS, the same lifecycle commands manage a repository-scoped LaunchAgent
under `~/Library/LaunchAgents`. The agent runs while the user GUI session is
available; it is not a system-wide LaunchDaemon.

The lifecycle commands are implemented on Linux, macOS, and Windows:

```bash
codira daemon run
codira daemon install
codira daemon start
codira daemon status
codira daemon stop
codira daemon uninstall
```

`run` and `install` require `daemon.enabled = true`; `status`, `stop`, and
`uninstall` remain available to inspect or clean up an existing service.
`install` creates the platform-specific service definition; use `start` when
you want to start an installed service immediately.

Every foreground daemon writes a current snapshot to
`.codira/daemon-status.json` and appends state-transition snapshots to
`.codira/daemon-activity.jsonl` below Codira's effective storage root. By
default that is the repository root; with `--output-dir`, it is the selected
output directory. The records contain no changed file paths. `codira daemon
status` combines the platform service state with the latest durable
reconciliation snapshot.

## Optional warm query daemon contract

`[query_daemon]` reserves configuration for a second, repository-local daemon
that will keep read/query resources warm. It is disabled by default and does
not change direct CLI or MCP behavior in this slice.

- `enabled` permits a future query-daemon runtime to start. It defaults to
  `false`.

The query daemon will be fixed to one resolved repository root and effective
output directory; it will never accept repository paths from requests. It is
read-only: the indexing daemon remains the sole automatic index writer, and
CLI and MCP will retain direct-core fallback when it is unavailable. This is
separate from the indexing daemon, the MCP stdio server, and the future
multi-repository catalogue work tracked by #51.

The reserved lifecycle hierarchy is:

```bash
codira query-daemon run
codira query-daemon install
codira query-daemon uninstall
codira query-daemon start
codira query-daemon stop
codira query-daemon status
```

In this contract slice, no query-daemon process or platform service starts;
even with enablement set, lifecycle commands report that the runtime is not
yet available.

## Repository Performance Profile

This repository commits an explicit `.codira/config.toml` with operational
defaults for the checked-in ONNX profile:

- `backend.name = "sqlite"` selects the backend with the best measured
  weighted operational cost for the current ONNX profile on this workstation.
- `embeddings.indexing.mode = "immediate"` keeps a one-step indexing workflow
  as the default. Deferred mode remains available for operators who explicitly
  want a two-step structural/indexing workflow.
- `embeddings.indexing.object_types = ["symbol", "documentation"]` keeps both
  retrieval channels active.
- `embeddings.indexing.max_text_chars = 0` keeps documentation embeddings
  uncapped.
- `embeddings.indexing.work_batch_multiplier = 256` caps the memory footprint
  of full-index embedding work while staying aligned with the configured model
  inference batch size.
- `embeddings.engine = "onnx"`, `embeddings.model = "BAAI/bge-small-en-v1.5"`,
  `embeddings.batch_size = 4`, and ONNX Runtime default thread counts are the
  current project defaults.

Embedding performance is hardware-sensitive because throughput and memory
pressure depend on CPU, RAM, GPU, and local model state. Reassess these values
with the maintained retrieval-quality benchmark after a meaningful hardware or
backend change; do not treat them as portable tuning advice.

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

ONNX embedding inputs are truncated before inference. The default
`plugins.embedding-onnx.max_tokens = 512` protects fixed-length exports from
runtime shape errors. Set `max_tokens = 0` only for dynamic-shape exports that
are known to accept arbitrary sequence lengths. Changing `max_tokens` changes
vectors for over-limit texts, so bump `[embeddings].version` when changing it
for an existing index.

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

Documentation audit routing is explicit. Empty
`plugins.documentation_audit_routes = []` disables documentation audit
execution; this is the compatibility mode for repositories that have not chosen
a convention.

Each documentation audit route is an ordered inline table:

```toml
[plugins]
documentation_audit_routes = [
  { language = "python", convention = "numpy", plugin = "numpy", include_paths = ["src/**/*.py"], exclude_paths = ["tests/fixtures/**"] },
  { language = "python", convention = "google", plugin = "google", include_paths = ["tests/**/*.py"] },
  { language = "c", convention = "doxygen", plugin = "doxygen", include_paths = ["src/**/*.c", "include/**/*.h"] },
  { language = "cpp", convention = "doxygen", plugin = "doxygen", include_paths = ["src/**/*.cpp", "include/**/*.hpp"] },
]
```

Route keys:

| Key | Type | Required | Description |
| --- | --- | --- | --- |
| `language` | str | yes | Analyzer language matched by the route, such as `python`, `c`, or `cpp`. |
| `convention` | str | yes | Convention label passed to the selected audit plugin. |
| `plugin` | str | yes | Documentation audit plugin name. First-party names are `numpy`, `google`, and `doxygen`. |
| `include_paths` | list[str] | no | Repo-relative glob patterns accepted by this route. Empty means all paths for the language. |
| `exclude_paths` | list[str] | no | Repo-relative glob patterns rejected by this route. Excludes win over includes. |

A public artifact is audited only when exactly one route matches its language
and path. Multiple matching routes emit an `ambiguous_route` diagnostic instead
of guessing the convention.

`codira audit --json` includes persisted plugin and convention provenance for
single-route matches:

```json
{
  "audit_plugin": {
    "name": "numpy",
    "version": "1"
  },
  "audit_convention": {
    "name": "numpy",
    "version": "1"
  },
  "rule_id": "missing_parameter",
  "severity": "warning",
  "audit_route": {
    "language": "python",
    "convention": "numpy",
    "plugin": "numpy"
  }
}
```

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

First-party backend tables are schema-validated:

```toml
[plugins.backend-sqlite]
enabled = true

[plugins.backend-duckdb]
enabled = true
profiling_enabled = false
```

Disabling the configured active backend is invalid. Disable an inactive backend
only, or change `[backend].name` first.

When `plugins.backend-duckdb.profiling_enabled = true`, DuckDB index runs emit
`.codira/duckdb-profile.json` with aggregate write-path timings. Leave it
disabled for normal usage; enable it only when investigating backend
performance.

First-party embedding tables are also schema-validated:

```toml
[plugins.embedding-sentence-transformers]
enabled = true
trust_remote_code = false

[plugins.embedding-onnx]
enabled = true
model_path = ".codira/models/example/model.onnx"
tokenizer_path = ".codira/models/example/tokenizer.json"
provider = "CPUExecutionProvider"
precision = "float32"
normalize = true
max_tokens = 512
intra_op_num_threads = 0
inter_op_num_threads = 0
```

ONNX batching is controlled by the shared `[embeddings].batch_size` key, not by
a plugin-local option.

The SQLite vector store bounds each sqlite-vec nearest-neighbor request before
structural filtering. Tune that window only when retrieval recall requires it;
larger values increase query latency and must remain supported by the installed
sqlite-vec build.

```toml
[plugins.vector-store-sqlite]
enabled = true
candidate_limit = 256

[plugins.vector-store-duckdb]
enabled = true
```
