"""Persistent runtime configuration for Codira.

Responsibilities
----------------
- Resolve system, user, repository, environment, and built-in configuration.
- Validate the public TOML schema strictly before runtime use.
- Generate deterministic profile templates for user-facing config files.

Architectural role
------------------
This module belongs to the **runtime configuration layer**. It intentionally
does not import plugin registries or embedding runtime modules, so registries
can consume configuration without circular imports.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import cast

import platformdirs
import tomlkit

from codira.config_models import (
    _PLUGIN_CONFIG_RESERVED_KEYS as _PLUGIN_CONFIG_RESERVED_KEYS,
    _SCHEMA as _SCHEMA,
    APP_NAME as APP_NAME,
    CONFIG_FILENAME as CONFIG_FILENAME,
    CONFIG_VERSION as CONFIG_VERSION,
    DEFAULT_BACKEND_NAME as DEFAULT_BACKEND_NAME,
    DEFAULT_CONFIG as DEFAULT_CONFIG,
    DEFAULT_DAEMON_DEBOUNCE_MS as DEFAULT_DAEMON_DEBOUNCE_MS,
    DEFAULT_EMBEDDING_BATCH_SIZE as DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_DEVICE as DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_DIMENSION as DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_ENGINE_NAME as DEFAULT_EMBEDDING_ENGINE_NAME,
    DEFAULT_EMBEDDING_GPU_DEVICE_ID as DEFAULT_EMBEDDING_GPU_DEVICE_ID,
    DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB as DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB,
    DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES as DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES,
    DEFAULT_EMBEDDING_INDEX_MODE as DEFAULT_EMBEDDING_INDEX_MODE,
    DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES as DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES,
    DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER as DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER,
    DEFAULT_EMBEDDING_MODEL as DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_MODEL_ROOT as DEFAULT_EMBEDDING_MODEL_ROOT,
    DEFAULT_EMBEDDING_VERSION as DEFAULT_EMBEDDING_VERSION,
    DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS as DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS,
    DEFAULT_INDEX_CONCURRENCY_MIN_FILES as DEFAULT_INDEX_CONCURRENCY_MIN_FILES,
    DEFAULT_INDEX_CONCURRENCY_STRATEGY as DEFAULT_INDEX_CONCURRENCY_STRATEGY,
    DEFAULT_SIMILARITY_INDEX_NAME as DEFAULT_SIMILARITY_INDEX_NAME,
    DEFAULT_SIMILARITY_SEARCH_PROFILES as DEFAULT_SIMILARITY_SEARCH_PROFILES,
    DEFAULT_VECTOR_STORE_NAME as DEFAULT_VECTOR_STORE_NAME,
    FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS as FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS,
    KNOWN_EMBEDDING_INDEX_MODES as KNOWN_EMBEDDING_INDEX_MODES,
    KNOWN_EMBEDDING_OBJECT_TYPES as KNOWN_EMBEDDING_OBJECT_TYPES,
    KNOWN_INDEX_CONCURRENCY_STRATEGIES as KNOWN_INDEX_CONCURRENCY_STRATEGIES,
    PLUGIN_CONFIG_RENDER_ORDER as PLUGIN_CONFIG_RENDER_ORDER,
    PROFILE_OVERRIDES as PROFILE_OVERRIDES,
    BackendConfig as BackendConfig,
    CodiraConfig as CodiraConfig,
    ConfigError as ConfigError,
    ConfigOrigin as ConfigOrigin,
    ConfigWriteResult as ConfigWriteResult,
    DaemonConfig as DaemonConfig,
    DocumentationAuditRouteConfig as DocumentationAuditRouteConfig,
    EmbeddingsConfig as EmbeddingsConfig,
    EmbeddingsGpuConfig as EmbeddingsGpuConfig,
    EmbeddingsIndexingConfig as EmbeddingsIndexingConfig,
    IndexConcurrencyConfig as IndexConcurrencyConfig,
    IndexCoverageConfig as IndexCoverageConfig,
    LevelName as LevelName,
    PluginsConfig as PluginsConfig,
    ProfileName as ProfileName,
    QueryDaemonConfig as QueryDaemonConfig,
)
from codira.config_toml import (
    _comment_default_config_values as _comment_default_config_values,
    _merge_toml_table as _merge_toml_table,
    render_config_toml as render_config_toml,
)
from codira.config_validation import (
    _require_table as _require_table,
    validate_config_mapping as validate_config_mapping,
)
from codira.contracts import (
    SimilaritySearchProfile,
    validate_similarity_search_profiles,
)
from codira.platform_paths import platform_paths

_EFFECTIVE_CONFIG_CACHE: ContextVar[
    dict[tuple[str | None, bool], CodiraConfig] | None
] = ContextVar("codira_effective_config_cache", default=None)
_REPO_CONFIG_PATH_OVERRIDE: ContextVar[Path | None] = ContextVar(
    "codira_repo_config_path_override",
    default=None,
)


def user_config_path() -> Path:
    """
    Return the platform user config path.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        User-level Codira configuration path.
    """

    return platform_paths().config_root / CONFIG_FILENAME


def system_config_path() -> Path:
    """
    Return the platform system config path.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        System-level Codira configuration path.
    """

    return Path(platformdirs.site_config_dir(APP_NAME)) / CONFIG_FILENAME


def repo_config_path(root: Path) -> Path:
    """
    Return the repository-level config path for one root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose config path should be resolved.

    Returns
    -------
    pathlib.Path
        Repository-level Codira configuration path.
    """

    override = _REPO_CONFIG_PATH_OVERRIDE.get()
    if override is not None:
        return override
    return root / ".codira" / CONFIG_FILENAME


@contextmanager
def override_repo_config_path(path: Path | None) -> Iterator[None]:
    """
    Temporarily override the repository-level config path.

    Parameters
    ----------
    path : pathlib.Path | None
        Explicit repo config file path. ``None`` preserves normal resolution.

    Yields
    ------
    None
        The override is active within the context body.
    """

    token = _REPO_CONFIG_PATH_OVERRIDE.set(path)
    try:
        yield
    finally:
        _REPO_CONFIG_PATH_OVERRIDE.reset(token)


def config_path(level: LevelName, *, root: Path | None = None) -> Path:
    """
    Return the config path for one concrete config level.

    Parameters
    ----------
    level : {"system", "user", "repo", "effective"}
        Configuration level to resolve. ``"effective"`` is rejected because it
        is not file-backed.
    root : pathlib.Path | None, optional
        Repository root required for ``"repo"``.

    Returns
    -------
    pathlib.Path
        File path for the requested level.

    Raises
    ------
    ConfigError
        If ``level`` is not file-backed or a repo root is required.
    """

    if level == "system":
        return system_config_path()
    if level == "user":
        return user_config_path()
    if level == "repo":
        if root is None:
            msg = "Repository config requires a repository root."
            raise ConfigError(msg)
        return repo_config_path(root)
    msg = "Effective configuration does not have a single file path."
    raise ConfigError(msg)


def _deep_copy_mapping(value: Mapping[str, object]) -> dict[str, object]:
    """
    Copy one nested config mapping into mutable built-in containers.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Mapping to copy.

    Returns
    -------
    dict[str, object]
        Deep copied mapping.
    """

    copied: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, (list, tuple)):
            copied_items = [
                _deep_copy_mapping(value) if isinstance(value, Mapping) else value
                for value in item
            ]
            copied[key] = [value for value in copied_items if value != {}]
        elif isinstance(item, Mapping):
            copied[key] = _deep_copy_mapping(item)
        else:
            copied[key] = item
    return copied


def _leaf_keys(value: Mapping[str, object], *, prefix: str = "") -> list[str]:
    """
    Return dotted leaf keys for a nested config mapping.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Mapping to inspect.
    prefix : str, optional
        Prefix accumulated during recursion.

    Returns
    -------
    list[str]
        Dotted leaf keys in deterministic order.
    """

    keys: list[str] = []
    for key in sorted(value):
        item = value[key]
        dotted = key if not prefix else f"{prefix}.{key}"
        if isinstance(item, Mapping):
            keys.extend(_leaf_keys(item, prefix=dotted))
        else:
            keys.append(dotted)
    return keys


def _merge_config(
    target: dict[str, object],
    incoming: Mapping[str, object],
    *,
    origins: dict[str, ConfigOrigin],
    origin: ConfigOrigin,
    prefix: str = "",
) -> None:
    """
    Merge one config mapping into an existing config mapping.

    Parameters
    ----------
    target : dict[str, object]
        Mutable target config mapping.
    incoming : collections.abc.Mapping[str, object]
        Incoming config values.
    origins : dict[str, ConfigOrigin]
        Mutable origin mapping keyed by dotted leaf key.
    origin : ConfigOrigin
        Origin assigned to incoming leaf values.
    prefix : str, optional
        Dotted prefix used during recursion.

    Returns
    -------
    None
        ``target`` and ``origins`` are updated in place.
    """

    for key, item in incoming.items():
        dotted = key if not prefix else f"{prefix}.{key}"
        if isinstance(item, (list, tuple)):
            copied_items = [
                _deep_copy_mapping(value) if isinstance(value, Mapping) else value
                for value in item
            ]
            non_empty_items = [value for value in copied_items if value != {}]
            if (
                (item and not non_empty_items)
                or dotted == "embeddings.similarity_profiles"
                and not non_empty_items
            ):
                continue
            target[key] = non_empty_items
            origins[dotted] = origin
        elif isinstance(item, Mapping):
            current = target.get(key)
            if not isinstance(current, dict):
                current = {}
                target[key] = current
            _merge_config(
                current,
                item,
                origins=origins,
                origin=origin,
                prefix=dotted,
            )
        else:
            target[key] = item
            origins[dotted] = origin


def _read_config_file(path: Path) -> dict[str, object]:
    """
    Parse one TOML configuration file.

    Parameters
    ----------
    path : pathlib.Path
        Config file path to read.

    Returns
    -------
    dict[str, object]
        Parsed config mapping.

    Raises
    ------
    ConfigError
        If the file cannot be parsed or does not contain a TOML table.
    """

    try:
        parsed = tomlkit.parse(path.read_text(encoding="utf-8"))
    except tomlkit.exceptions.ParseError as exc:
        msg = f"Failed to parse config file {path}: {exc}"
        raise ConfigError(msg) from exc
    return _deep_copy_mapping(parsed)


def _environment_bool(raw_value: str) -> bool:
    """
    Parse one truthy/falsy environment override.

    Parameters
    ----------
    raw_value : str
        Raw environment variable value.

    Returns
    -------
    bool
        Parsed boolean value.

    Raises
    ------
    ConfigError
        If the value is not accepted as a boolean.
    """

    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    msg = f"Invalid boolean environment override: {raw_value}"
    raise ConfigError(msg)


def _environment_int(name: str, raw_value: str, *, minimum: int) -> int:
    """
    Parse one integer environment override.

    Parameters
    ----------
    name : str
        Environment variable name.
    raw_value : str
        Raw environment variable value.
    minimum : int
        Lowest accepted value.

    Returns
    -------
    int
        Parsed integer.

    Raises
    ------
    ConfigError
        If the value is not a valid integer in range.
    """

    try:
        parsed = int(raw_value.strip())
    except ValueError as exc:
        msg = f"{name} must be an integer greater than or equal to {minimum}."
        raise ConfigError(msg) from exc
    if parsed < minimum:
        msg = f"{name} must be an integer greater than or equal to {minimum}."
        raise ConfigError(msg)
    return parsed


def _environment_overrides(env: Mapping[str, str]) -> dict[str, object]:
    """
    Convert supported ``CODIRA_*`` variables into config overrides.

    Parameters
    ----------
    env : collections.abc.Mapping[str, str]
        Environment mapping to inspect.

    Returns
    -------
    dict[str, object]
        Nested config override mapping.
    """

    overrides: dict[str, object] = {}
    backend_name = env.get("CODIRA_INDEX_BACKEND", "").strip()
    if backend_name:
        overrides["backend"] = {"name": backend_name}

    raw_disable_plugins = env.get("CODIRA_DISABLE_THIRD_PARTY_PLUGINS")
    if raw_disable_plugins is not None and raw_disable_plugins.strip():
        plugins = cast("dict[str, object]", overrides.setdefault("plugins", {}))
        plugins["disable_third_party"] = _environment_bool(raw_disable_plugins)

    embeddings = cast("dict[str, object]", overrides.setdefault("embeddings", {}))
    raw_batch_size = env.get("CODIRA_EMBED_BATCH_SIZE")
    if raw_batch_size is not None and raw_batch_size.strip():
        embeddings["batch_size"] = _environment_int(
            "CODIRA_EMBED_BATCH_SIZE",
            raw_batch_size,
            minimum=1,
        )
    device = env.get("CODIRA_EMBED_DEVICE", "").strip()
    if device:
        embeddings["device"] = device
    raw_threads = env.get("CODIRA_TORCH_NUM_THREADS")
    if raw_threads is not None and raw_threads.strip():
        embeddings["torch_num_threads"] = _environment_int(
            "CODIRA_TORCH_NUM_THREADS",
            raw_threads,
            minimum=1,
        )
    raw_interop_threads = env.get("CODIRA_TORCH_NUM_INTEROP_THREADS")
    if raw_interop_threads is not None and raw_interop_threads.strip():
        embeddings["torch_num_interop_threads"] = _environment_int(
            "CODIRA_TORCH_NUM_INTEROP_THREADS",
            raw_interop_threads,
            minimum=1,
        )
    if not embeddings:
        overrides.pop("embeddings", None)
    return overrides


def profile_config(profile: ProfileName) -> dict[str, object]:
    """
    Build the complete generated config for one profile.

    Parameters
    ----------
    profile : {"default", "low-memory", "gpu"}
        Profile name to render.

    Returns
    -------
    dict[str, object]
        Complete config mapping for the profile.
    """

    config = _deep_copy_mapping(DEFAULT_CONFIG)
    _merge_config(
        config,
        PROFILE_OVERRIDES[profile],
        origins={},
        origin=ConfigOrigin("profile", None, profile),
    )
    return config


def full_profile_config(profile: ProfileName) -> dict[str, object]:
    """
    Build a generated config that includes all known plugin defaults.

    Parameters
    ----------
    profile : {"default", "low-memory", "gpu"}
        Profile name to render.

    Returns
    -------
    dict[str, object]
        Complete config mapping including first-party plugin option defaults.
    """

    config = profile_config(profile)
    plugins = cast(
        "dict[str, object]", _require_table(config["plugins"], key="plugins")
    )
    plugins.update(_deep_copy_mapping(FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS))
    return config


def write_config_file(
    path: Path,
    *,
    profile: ProfileName = "default",
    force: bool = False,
    full: bool = False,
) -> None:
    """
    Write one generated config profile to disk.

    Parameters
    ----------
    path : pathlib.Path
        Target config file.
    profile : {"default", "low-memory", "gpu"}, optional
        Profile to render.
    force : bool, optional
        Whether to overwrite an existing file.
    full : bool, optional
        Whether to include all known first-party plugin defaults.

    Returns
    -------
    None
        The config file is written.

    Raises
    ------
    ConfigError
        If the target exists and ``force`` is ``False``.
    OSError
        If directory or file creation fails.
    """

    if path.exists() and not force:
        msg = f"Config file already exists: {path}"
        raise ConfigError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = full_profile_config(profile) if full else profile_config(profile)
    defaults = full_profile_config("default") if full else profile_config("default")
    rendered = _comment_default_config_values(
        render_config_toml(payload),
        value=payload,
        defaults=defaults,
    )
    path.write_text(rendered, encoding="utf-8")


def update_config_file(path: Path, updates: Mapping[str, object]) -> ConfigWriteResult:
    """
    Merge partial config updates into one TOML config file.

    Parameters
    ----------
    path : pathlib.Path
        Target config file to create or update.
    updates : collections.abc.Mapping[str, object]
        Partial config mapping to merge.

    Returns
    -------
    ConfigWriteResult
        Replacement status and backup metadata.

    Raises
    ------
    ConfigError
        If existing values, update values, or merged values are invalid.
    OSError
        If directory or file access fails.
    """

    original = path.read_text(encoding="utf-8") if path.exists() else None
    rendered = preview_config_update(path, updates)
    if original == rendered:
        return ConfigWriteResult(path=path, backup_path=None, changed=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Path | None = None
    if original is not None:
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_temporary = backup_path.with_suffix(backup_path.suffix + ".tmp")
        backup_temporary.write_text(original, encoding="utf-8")
        backup_temporary.replace(backup_path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
    return ConfigWriteResult(path=path, backup_path=backup_path, changed=True)


def preview_config_update(path: Path, updates: Mapping[str, object]) -> str:
    """Render a validated comment-preserving configuration update without writing.

    Parameters
    ----------
    path : pathlib.Path
        Existing config path, or a path that does not yet exist.
    updates : collections.abc.Mapping[str, object]
        Partial configuration update.

    Returns
    -------
    str
        Validated TOML replacement text.
    """
    validate_config_mapping(updates)
    document = (
        tomlkit.parse(path.read_text(encoding="utf-8"))
        if path.exists()
        else tomlkit.document()
    )
    existing = _deep_copy_mapping(document)
    validate_config_mapping(existing)
    merged = _deep_copy_mapping(existing)
    _merge_config(
        merged,
        updates,
        origins={},
        origin=ConfigOrigin("preview", path, str(path)),
    )
    validate_config_mapping(merged)
    _merge_toml_table(document, updates)
    return tomlkit.dumps(document)


def ensure_user_config() -> Path:
    """
    Create the default user config file when it is missing and writable.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        User config path.

    Notes
    -----
    Automatic first-run creation is best-effort so read-only host config
    directories do not prevent Codira from running with built-in defaults.
    Explicit ``codira config init --level user`` still reports write failures.
    """

    path = user_config_path()
    if not path.exists():
        try:
            write_config_file(path, profile="default", force=False)
        except OSError:
            return path
    return path


@contextmanager
def effective_config_cache() -> Iterator[None]:
    """
    Cache effective configuration loads within one command scope.

    Parameters
    ----------
    None

    Yields
    ------
    None
        The active context caches default-environment effective config loads
        until the context exits.

    Notes
    -----
    Explicit ``env`` mappings are intentionally excluded so tests and callers
    that model alternate environments always receive freshly merged values.
    """

    if _EFFECTIVE_CONFIG_CACHE.get() is not None:
        yield
        return

    token = _EFFECTIVE_CONFIG_CACHE.set({})
    try:
        yield
    finally:
        _EFFECTIVE_CONFIG_CACHE.reset(token)


def with_effective_config_cache[**P, R](
    func: Callable[P, R],
) -> Callable[P, R]:
    """
    Run one callable inside a command-scoped effective-config cache.

    Parameters
    ----------
    func : collections.abc.Callable
        Callable whose nested default-environment config loads should share
        one command-local cache.

    Returns
    -------
    collections.abc.Callable
        Wrapper preserving the original call signature for type checkers.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        """
        Execute the wrapped callable with scoped config caching.

        Parameters
        ----------
        *args : object
            Positional arguments forwarded to the wrapped callable.
        **kwargs : object
            Keyword arguments forwarded to the wrapped callable.

        Returns
        -------
        object
            Return value from the wrapped callable.
        """

        with effective_config_cache():
            return func(*args, **kwargs)

    return wrapper


def load_effective_config(
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
    auto_create_user: bool = False,
) -> CodiraConfig:
    """
    Load and merge the effective Codira configuration.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root used for repository-level config.
    env : collections.abc.Mapping[str, str] | None, optional
        Environment mapping. ``None`` uses ``os.environ``.
    auto_create_user : bool, optional
        Whether to create the default user config before loading.

    Returns
    -------
    CodiraConfig
        Validated effective configuration with origin metadata.

    Raises
    ------
    ConfigError
        If any present config source is invalid.
    """

    cache = _EFFECTIVE_CONFIG_CACHE.get()
    cache_key: tuple[str | None, bool] | None = None
    if env is None and cache is not None:
        config_override = _REPO_CONFIG_PATH_OVERRIDE.get()
        root_key = None if root is None else str(root.resolve())
        config_key = None if config_override is None else str(config_override)
        cache_key = (f"{root_key}|{config_key}", auto_create_user)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    if auto_create_user:
        ensure_user_config()

    merged = _deep_copy_mapping(DEFAULT_CONFIG)
    origins = {
        key: ConfigOrigin("defaults", None, "built-in defaults")
        for key in _leaf_keys(DEFAULT_CONFIG)
    }

    for level, path in (
        ("system", system_config_path()),
        ("user", user_config_path()),
        ("repo", None if root is None else repo_config_path(root)),
    ):
        if path is None or not path.exists():
            continue
        values = _read_config_file(path)
        validate_config_mapping(values)
        _merge_config(
            merged,
            values,
            origins=origins,
            origin=ConfigOrigin(level, path, str(path)),
        )

    environment_values = _environment_overrides(os.environ if env is None else env)
    if environment_values:
        validate_config_mapping(environment_values)
        _merge_config(
            merged,
            environment_values,
            origins=origins,
            origin=ConfigOrigin("environment", None, "CODIRA_* environment"),
        )

    validate_config_mapping(merged)
    config = _config_from_mapping(merged, origins=origins)
    if cache_key is not None and cache is not None:
        cache[cache_key] = config
    return config


def load_config_level(
    level: LevelName, *, root: Path | None = None
) -> dict[str, object]:
    """
    Load one file-backed config level.

    Parameters
    ----------
    level : {"system", "user", "repo", "effective"}
        Config level to load. ``"effective"`` is rejected.
    root : pathlib.Path | None, optional
        Repository root required for ``"repo"``.

    Returns
    -------
    dict[str, object]
        Parsed and validated config mapping.

    Raises
    ------
    ConfigError
        If the config level is missing, invalid, or not file-backed.
    """

    path = config_path(level, root=root)
    if not path.exists():
        msg = f"Config file does not exist: {path}"
        raise ConfigError(msg)
    values = _read_config_file(path)
    validate_config_mapping(values)
    return values


def config_to_mapping(config: CodiraConfig) -> dict[str, object]:
    """
    Convert an effective config object into a serializable mapping.

    Parameters
    ----------
    config : CodiraConfig
        Effective configuration object.

    Returns
    -------
    dict[str, object]
        Config mapping without origin metadata.
    """

    plugin_mapping: dict[str, object] = {
        "disable_third_party": config.plugins.disable_third_party,
        "disabled_analyzers": list(config.plugins.disabled_analyzers),
        "documentation_audit_routes": [
            {
                "language": route.language,
                "convention": route.convention,
                "plugin": route.plugin,
                "include_paths": list(route.include_paths),
                "exclude_paths": list(route.exclude_paths),
            }
            for route in config.plugins.documentation_audit_routes
        ],
    }
    for key, item in sorted((config.plugins.configs or {}).items()):
        plugin_mapping[key] = _deep_copy_mapping(item)

    return {
        "config_version": config.config_version,
        "backend": {"name": config.backend.name},
        "plugins": plugin_mapping,
        "embeddings": {
            "enabled": config.embeddings.enabled,
            "engine": config.embeddings.engine,
            "vector_store": config.embeddings.vector_store,
            "similarity_index": config.embeddings.similarity_index,
            "similarity_profiles": [
                {
                    "name": profile.name,
                    "ef_search": profile.ef_search,
                    "candidate_limit": profile.candidate_limit,
                    "default_result_limit": profile.default_result_limit,
                    "max_result_limit": profile.max_result_limit,
                }
                for profile in config.embeddings.similarity_profiles
            ],
            "model": config.embeddings.model,
            "version": config.embeddings.version,
            "model_root": config.embeddings.model_root,
            "dimension": config.embeddings.dimension,
            "device": config.embeddings.device,
            "batch_size": config.embeddings.batch_size,
            "torch_num_threads": config.embeddings.torch_num_threads,
            "torch_num_interop_threads": config.embeddings.torch_num_interop_threads,
            "gpu": {
                "device_id": config.embeddings.gpu.device_id,
                "memory_limit_mb": config.embeddings.gpu.memory_limit_mb,
            },
            "indexing": {
                "mode": config.embeddings.indexing.mode,
                "object_types": list(config.embeddings.indexing.object_types),
                "max_text_chars": config.embeddings.indexing.max_text_chars,
                "work_batch_multiplier": (
                    config.embeddings.indexing.work_batch_multiplier
                ),
                "max_source_file_bytes": (
                    config.embeddings.indexing.max_source_file_bytes
                ),
                "include_paths": list(config.embeddings.indexing.include_paths),
                "exclude_paths": list(config.embeddings.indexing.exclude_paths),
            },
        },
        "index": {
            "concurrency": {
                "strategy": config.index.strategy,
                "max_workers": config.index.max_workers,
                "min_files": config.index.min_files,
            },
            "coverage": {
                "roots": list(config.coverage.roots),
                "exclude_suffixes": list(config.coverage.exclude_suffixes),
            },
        },
        "daemon": {
            "enabled": config.daemon.enabled,
            "debounce_ms": config.daemon.debounce_ms,
            "include_paths": list(config.daemon.include_paths),
            "exclude_paths": list(config.daemon.exclude_paths),
        },
        "query_daemon": {"enabled": config.query_daemon.enabled},
    }


def explain_key(config: CodiraConfig, key: str) -> tuple[object, ConfigOrigin]:
    """
    Return one effective config value and its origin.

    Parameters
    ----------
    config : CodiraConfig
        Effective configuration object.
    key : str
        Dotted key to explain.

    Returns
    -------
    tuple[object, ConfigOrigin]
        Effective value and its origin.

    Raises
    ------
    ConfigError
        If the key is unknown.
    """

    mapping = config_to_mapping(config)
    current: object = mapping
    for token in key.split("."):
        if not isinstance(current, Mapping) or token not in current:
            msg = f"Unknown configuration key: {key}"
            raise ConfigError(msg)
        current = current[token]
    origin = config.origins.get(key)
    if origin is None:
        msg = f"Configuration key is not explainable as a leaf value: {key}"
        raise ConfigError(msg)
    return current, origin


def _config_from_mapping(
    value: Mapping[str, object],
    *,
    origins: dict[str, ConfigOrigin],
) -> CodiraConfig:
    """
    Convert a validated mapping into typed config objects.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Validated complete config mapping.
    origins : dict[str, ConfigOrigin]
        Origin metadata keyed by dotted config key.

    Returns
    -------
    CodiraConfig
        Typed configuration object.
    """

    backend = cast("Mapping[str, object]", value["backend"])
    plugins = cast("Mapping[str, object]", value["plugins"])
    plugin_configs: dict[str, dict[str, object]] = {}
    documentation_audit_routes: list[DocumentationAuditRouteConfig] = []
    for key, item in plugins.items():
        if key in _PLUGIN_CONFIG_RESERVED_KEYS:
            continue
        plugin_configs[key] = _deep_copy_mapping(
            _require_table(item, key=f"plugins.{key}")
        )
    for item in cast("list[object]", plugins["documentation_audit_routes"]):
        route = cast("Mapping[str, object]", item)
        documentation_audit_routes.append(
            DocumentationAuditRouteConfig(
                language=cast("str", route["language"]).strip(),
                convention=cast("str", route["convention"]).strip(),
                plugin=cast("str", route["plugin"]).strip(),
                include_paths=tuple(
                    str(path).strip()
                    for path in cast("list[object]", route.get("include_paths", []))
                ),
                exclude_paths=tuple(
                    str(path).strip()
                    for path in cast("list[object]", route.get("exclude_paths", []))
                ),
            )
        )
    embeddings = cast("Mapping[str, object]", value["embeddings"])
    profile_values = cast("list[object]", embeddings["similarity_profiles"])
    try:
        similarity_profiles = validate_similarity_search_profiles(
            tuple(
                SimilaritySearchProfile(
                    name=cast(
                        "str",
                        _require_table(item, key="embeddings.similarity_profiles")[
                            "name"
                        ],
                    ),
                    ef_search=cast(
                        "int",
                        _require_table(item, key="embeddings.similarity_profiles")[
                            "ef_search"
                        ],
                    ),
                    candidate_limit=cast(
                        "int",
                        _require_table(item, key="embeddings.similarity_profiles")[
                            "candidate_limit"
                        ],
                    ),
                    default_result_limit=cast(
                        "int",
                        _require_table(item, key="embeddings.similarity_profiles")[
                            "default_result_limit"
                        ],
                    ),
                    max_result_limit=cast(
                        "int",
                        _require_table(item, key="embeddings.similarity_profiles")[
                            "max_result_limit"
                        ],
                    ),
                )
                for item in profile_values
            )
        )
    except (KeyError, TypeError, ValueError) as error:
        message = f"Invalid embeddings.similarity_profiles: {error}"
        raise ConfigError(message) from error
    if not similarity_profiles:
        msg = "embeddings.similarity_profiles must declare a default profile."
        raise ConfigError(msg)
    if not any(profile.name == "default" for profile in similarity_profiles):
        msg = "embeddings.similarity_profiles must include a profile named 'default'."
        raise ConfigError(msg)
    gpu = cast("Mapping[str, object]", embeddings["gpu"])
    indexing = cast("Mapping[str, object]", embeddings["indexing"])
    index = cast("Mapping[str, object]", value["index"])
    concurrency = cast("Mapping[str, object]", index["concurrency"])
    coverage = cast("Mapping[str, object]", index["coverage"])
    daemon = cast("Mapping[str, object]", value["daemon"])
    query_daemon = cast("Mapping[str, object]", value["query_daemon"])
    return CodiraConfig(
        config_version=cast("int", value["config_version"]),
        backend=BackendConfig(name=cast("str", backend["name"]).strip()),
        plugins=PluginsConfig(
            disable_third_party=cast("bool", plugins["disable_third_party"]),
            disabled_analyzers=tuple(
                str(item).strip()
                for item in cast("list[object]", plugins["disabled_analyzers"])
            ),
            documentation_audit_routes=tuple(documentation_audit_routes),
            configs=plugin_configs,
        ),
        embeddings=EmbeddingsConfig(
            enabled=cast("bool", embeddings["enabled"]),
            engine=cast("str", embeddings["engine"]).strip(),
            vector_store=cast("str", embeddings["vector_store"]).strip(),
            similarity_index=cast("str", embeddings["similarity_index"]).strip(),
            similarity_profiles=similarity_profiles,
            model=cast("str", embeddings["model"]).strip(),
            version=cast("str", embeddings["version"]).strip(),
            model_root=cast("str", embeddings["model_root"]).strip(),
            dimension=cast("int", embeddings["dimension"]),
            device=cast("str", embeddings["device"]).strip(),
            batch_size=cast("int", embeddings["batch_size"]),
            torch_num_threads=cast("int", embeddings["torch_num_threads"]),
            torch_num_interop_threads=cast(
                "int",
                embeddings["torch_num_interop_threads"],
            ),
            gpu=EmbeddingsGpuConfig(
                device_id=cast("int", gpu["device_id"]),
                memory_limit_mb=cast("int", gpu["memory_limit_mb"]),
            ),
            indexing=EmbeddingsIndexingConfig(
                mode=cast("str", indexing["mode"]),
                object_types=tuple(
                    str(item).strip()
                    for item in cast("list[object]", indexing["object_types"])
                ),
                max_text_chars=cast("int", indexing["max_text_chars"]),
                work_batch_multiplier=cast(
                    "int",
                    indexing["work_batch_multiplier"],
                ),
                max_source_file_bytes=cast(
                    "int",
                    indexing["max_source_file_bytes"],
                ),
                include_paths=tuple(
                    str(item).strip()
                    for item in cast("list[object]", indexing["include_paths"])
                ),
                exclude_paths=tuple(
                    str(item).strip()
                    for item in cast("list[object]", indexing["exclude_paths"])
                ),
            ),
        ),
        index=IndexConcurrencyConfig(
            strategy=cast("str", concurrency["strategy"]),
            max_workers=cast("int", concurrency["max_workers"]),
            min_files=cast("int", concurrency["min_files"]),
        ),
        coverage=IndexCoverageConfig(
            roots=tuple(
                str(item).strip() for item in cast("list[object]", coverage["roots"])
            ),
            exclude_suffixes=tuple(
                str(item).strip().lower()
                for item in cast("list[object]", coverage["exclude_suffixes"])
            ),
        ),
        daemon=DaemonConfig(
            enabled=cast("bool", daemon["enabled"]),
            debounce_ms=cast("int", daemon["debounce_ms"]),
            include_paths=tuple(
                str(item).strip()
                for item in cast("list[object]", daemon["include_paths"])
            ),
            exclude_paths=tuple(
                str(item).strip()
                for item in cast("list[object]", daemon["exclude_paths"])
            ),
        ),
        query_daemon=QueryDaemonConfig(
            enabled=cast("bool", query_daemon["enabled"]),
        ),
        origins=origins,
    )
