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
hard to audit across machines. Issue #17 introduces a persistent configuration
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

The first implementation will add `codira config init`, `codira config dump`,
`codira config explain`, and `codira config validate`. Runtime commands create
the missing user config with the `default` profile before performing work; help,
version, and config inspection commands do not auto-create it.

Repository-level config remains under `.codira/config.toml`, but the repository
ignore rules allow that file to be tracked while keeping index artifacts
ignored.

Plugin activation stays centralized in the main config system:

* `[backend].name` selects exactly one active backend.
* `[plugins].disable_third_party` controls third-party entry-point loading.
* `[plugins].disabled_analyzers` removes named analyzers from the active set.

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

Changing model, version, or dimension changes the embedding backend identity
used for reuse decisions, so stale vectors are recomputed instead of reused.

## Consequences

### Positive

* Codira behavior becomes reproducible from inspectable config files.
* Existing environment workflows continue to work as process overrides.
* Users can keep local hardware tuning out of command invocations.
* Repository config can document shared project policy when desired.

### Negative

* Runtime startup now includes config loading and validation.
* Plugin and embedding code paths need config-aware cache invalidation.
* Full embedding model configurability broadens the compatibility surface.

### Neutral

* No new per-command override flags are added in the first implementation.
* Dynamic runtime reconfiguration remains out of scope.
* System config generation may fail on permissions and should report the exact
  target path and operating-system error.
