# ADR-021 — Codira configuration hierarchy and runtime policy

**Date:** 04/06/2026
**Status:** Accepted

## Context

Codira currently exposes runtime selection mostly through environment
variables:

* `CODIRA_INDEX_BACKEND` selects the active backend.
* `CODIRA_DISABLE_THIRD_PARTY_PLUGINS` disables third-party plugin loading.
* `CODIRA_EMBED_*` and `CODIRA_TORCH_*` tune embedding inference behavior.

Those controls are explicit and deterministic, but they are process-local and
hard to audit across machines. Issue #17 introduced a persistent configuration
layer for hardware-sensitive embedding behavior, plugin activation, backend
selection, and reproducible runtime defaults.

The configuration layer must preserve existing behavior for users who do not
create config files, and it must avoid hiding behavior behind host-specific
auto-detection.

## Decision

Codira will use a strict multi-level TOML configuration hierarchy:

```text
CLI flags, where existing flags map to config keys
-> CODIRA_* environment overrides
-> repository config: <repo>/.codira/config.toml
-> user config: platformdirs.user_config_dir("codira")/config.toml
-> system config: platformdirs.site_config_dir("codira")/config.toml
-> built-in defaults
```

The implemented command surface is:

* `codira config init`
* `codira config dump`
* `codira config explain`
* `codira config validate`
* `codira calibrate embeddings`

Runtime commands create the missing user config with the `default` profile
before performing work when the user config location is writable. Help, version,
config inspection, and calibration print/output modes do not auto-create it.
`codira config init` writes compact core defaults by default, while
`codira config init --full` writes those defaults plus every known first-party
plugin option with its default value.

Repository-level config remains under `.codira/config.toml`, but the repository
ignore rules allow that file to be tracked while keeping index artifacts
ignored.

Plugin activation stays centralized in the main config system:

* `[backend].name` selects exactly one active backend.
* `[plugins].disable_third_party` controls third-party entry-point loading.
* `[plugins].disabled_analyzers` removes named analyzers from the active set.
* `[plugins.<plugin-name>]` tables carry plugin-specific options.

The core explicitly injects namespaced plugin configuration by calling optional
`configure(config)` hooks on plugins that provide them. Plugins that do not need
configuration remain compatible because the hook is optional. Loaded plugins may
also expose strict JSON Schemas; effective config validation applies those
schemas before runtime work proceeds.

First-party analyzer plugin configuration currently includes:

* `analyzer-python`: `emit_module_documentation`, `emit_imports`,
  `emit_constants`, `emit_type_aliases`
* `analyzer-json`: `enabled_families`, `emit_dependencies`, `emit_scripts`,
  `emit_schema_properties`
* `analyzer-c`: `use_leading_comments`, `emit_doxygen_documentation`,
  `include_system_includes`, `emit_macros`
* `analyzer-cpp`: `use_leading_comments`, `emit_doxygen_documentation`,
  `include_system_includes`, `emit_namespaces`, `emit_macros`
* `analyzer-bash`: `emit_functions`
* `analyzer-markdown`: `strip_front_matter`,
  `emit_file_artifact_without_headings`, `min_heading_level`,
  `max_heading_level`
* `analyzer-text`: `include_root_files`, `include_docs_directories`,
  `exclude_generated`, `exclude_fixtures_logs`

All configurable analyzers accept the common `enabled`, `include_paths`, and
`exclude_paths` plugin keys. Include and exclude path filters are deterministic,
repo-relative, and validated before indexing.

Embedding configuration owns both runtime tuning and the active embedding
backend contract:

* `enabled`
* `model`
* `version`
* `dimension`
* `device`
* `batch_size`
* `torch_num_threads`
* `torch_num_interop_threads`
* `gpu.device_id`
* `gpu.memory_limit_mb`

Changing model, version, or dimension changes the embedding backend identity
used for reuse decisions, so stale vectors are recomputed instead of reused.

`codira calibrate embeddings` is an explicit hardware-aware tuning surface. It
runs bounded offline calibration against deterministic text payloads and locally
available embedding model artifacts. By default, and with `--print`, it emits a
complete config-compatible `[embeddings]` plus `[embeddings.gpu]` TOML block to
standard output. `--output <path>` writes that block to a chosen file, and
`--write` is the only mode that mutates the user config file. If the semantic
stack or local model artifacts are unavailable, calibration emits safe CPU
fallback values instead of failing the command.

## Consequences

### Positive

* Codira behavior becomes reproducible from inspectable config files.
* Existing environment workflows continue to work as process overrides.
* Users can keep local hardware tuning out of command invocations.
* Repository config can document shared project policy when desired.
* Plugin behavior can be controlled without hidden global config access.
* Effective plugin options are validated before indexing.
* Embedding tuning can be generated from a deterministic local calibration
  command.

### Negative

* Runtime startup now includes config loading and validation.
* Plugin and embedding code paths need config-aware cache invalidation.
* Full embedding model configurability broadens the compatibility surface.
* First-party plugin option changes require package, bundle, and analyzer
  runtime version updates when emitted artifacts or index reuse boundaries
  change.

### Neutral

* No broad per-command override flag surface is added in the first
  implementation.
* Dynamic runtime reconfiguration remains out of scope.
* System config generation may fail on permissions and should report the exact
  target path and operating-system error.
