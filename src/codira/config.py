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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import platformdirs
import tomlkit

CONFIG_VERSION = 1
APP_NAME = "codira"
CONFIG_FILENAME = "config.toml"
DEFAULT_BACKEND_NAME = "sqlite"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_VERSION = "1"
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_EMBEDDING_DEVICE = "cpu"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
DEFAULT_EMBEDDING_GPU_DEVICE_ID = 0
DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB = 0
LevelName = Literal["system", "user", "repo", "effective"]
ProfileName = Literal["default", "low-memory", "gpu"]


class ConfigError(ValueError):
    """
    Stable operator-facing configuration error.

    Parameters
    ----------
    message : str
        Human-readable validation or loading failure.
    """


@dataclass(frozen=True)
class BackendConfig:
    """
    Active index backend configuration.

    Parameters
    ----------
    name : str
        Stable backend plugin name.
    """

    name: str = DEFAULT_BACKEND_NAME


@dataclass(frozen=True)
class PluginsConfig:
    """
    Plugin activation configuration.

    Parameters
    ----------
    disable_third_party : bool
        Whether third-party entry-point plugins should be skipped.
    disabled_analyzers : tuple[str, ...]
        Analyzer names to remove from the active analyzer set.
    """

    disable_third_party: bool = False
    disabled_analyzers: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddingsGpuConfig:
    """
    GPU-specific embedding runtime configuration.

    Parameters
    ----------
    device_id : int
        GPU device identifier selected for embedding inference.
    memory_limit_mb : int
        Maximum GPU memory budget in MiB, or ``0`` when no limit is configured.
    """

    device_id: int = DEFAULT_EMBEDDING_GPU_DEVICE_ID
    memory_limit_mb: int = DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB


@dataclass(frozen=True)
class EmbeddingsConfig:
    """
    Semantic embedding runtime configuration.

    Parameters
    ----------
    enabled : bool
        Whether embedding computation and retrieval channels are active.
    model : str
        Sentence-transformers model identifier.
    version : str
        Explicit embedding backend version stored with persisted vectors.
    dimension : int
        Expected vector dimension for the configured model.
    device : str
        Device string passed to sentence-transformers.
    batch_size : int
        Batch size passed to sentence-transformers encode calls.
    torch_num_threads : int
        Torch intra-op thread override, or ``0`` to leave Torch defaults.
    torch_num_interop_threads : int
        Torch inter-op thread override, or ``0`` to leave Torch defaults.
    gpu : EmbeddingsGpuConfig
        GPU-specific embedding runtime configuration.
    """

    enabled: bool = True
    model: str = DEFAULT_EMBEDDING_MODEL
    version: str = DEFAULT_EMBEDDING_VERSION
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    device: str = DEFAULT_EMBEDDING_DEVICE
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    torch_num_threads: int = 0
    torch_num_interop_threads: int = 0
    gpu: EmbeddingsGpuConfig = EmbeddingsGpuConfig()


@dataclass(frozen=True)
class ConfigOrigin:
    """
    Origin metadata for one effective configuration value.

    Parameters
    ----------
    level : str
        Source level that supplied the effective value.
    path : pathlib.Path | None
        File path for file-backed values, or ``None`` for defaults/env values.
    detail : str
        Human-readable source detail.
    """

    level: str
    path: Path | None
    detail: str


@dataclass(frozen=True)
class CodiraConfig:
    """
    Effective Codira runtime configuration.

    Parameters
    ----------
    config_version : int
        Public config schema version.
    backend : BackendConfig
        Active backend configuration.
    plugins : PluginsConfig
        Plugin activation configuration.
    embeddings : EmbeddingsConfig
        Embedding runtime configuration.
    origins : dict[str, ConfigOrigin]
        Origin metadata keyed by dotted config key.
    """

    config_version: int
    backend: BackendConfig
    plugins: PluginsConfig
    embeddings: EmbeddingsConfig
    origins: dict[str, ConfigOrigin]


DEFAULT_CONFIG: dict[str, object] = {
    "config_version": CONFIG_VERSION,
    "backend": {"name": DEFAULT_BACKEND_NAME},
    "plugins": {
        "disable_third_party": False,
        "disabled_analyzers": [],
    },
    "embeddings": {
        "enabled": True,
        "model": DEFAULT_EMBEDDING_MODEL,
        "version": DEFAULT_EMBEDDING_VERSION,
        "dimension": DEFAULT_EMBEDDING_DIMENSION,
        "device": DEFAULT_EMBEDDING_DEVICE,
        "batch_size": DEFAULT_EMBEDDING_BATCH_SIZE,
        "torch_num_threads": 0,
        "torch_num_interop_threads": 0,
        "gpu": {
            "device_id": DEFAULT_EMBEDDING_GPU_DEVICE_ID,
            "memory_limit_mb": DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB,
        },
    },
}
PROFILE_OVERRIDES: dict[ProfileName, dict[str, object]] = {
    "default": {},
    "low-memory": {
        "embeddings": {
            "device": "cpu",
            "batch_size": 8,
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
        }
    },
    "gpu": {
        "embeddings": {
            "device": "cuda",
            "batch_size": 64,
            "gpu": {
                "device_id": 0,
                "memory_limit_mb": 0,
            },
        }
    },
}
_SCHEMA: dict[str, object] = {
    "config_version": int,
    "backend": {"name": str},
    "plugins": {
        "disable_third_party": bool,
        "disabled_analyzers": list,
    },
    "embeddings": {
        "enabled": bool,
        "model": str,
        "version": str,
        "dimension": int,
        "device": str,
        "batch_size": int,
        "torch_num_threads": int,
        "torch_num_interop_threads": int,
        "gpu": {
            "device_id": int,
            "memory_limit_mb": int,
        },
    },
}


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

    return Path(platformdirs.user_config_dir(APP_NAME)) / CONFIG_FILENAME


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

    return root / ".codira" / CONFIG_FILENAME


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
        if isinstance(item, Mapping):
            copied[key] = _deep_copy_mapping(item)
        elif isinstance(item, list):
            copied[key] = list(item)
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


def _validate_known_keys(
    value: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    prefix: str = "",
) -> None:
    """
    Reject keys that are not present in the public config schema.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        User-provided config mapping.
    schema : collections.abc.Mapping[str, object]
        Schema mapping for the same level.
    prefix : str, optional
        Dotted prefix used for error messages.

    Returns
    -------
    None
        The mapping is accepted when no unknown keys are present.

    Raises
    ------
    ConfigError
        If an unknown key is present.
    """

    for key, item in value.items():
        dotted = key if not prefix else f"{prefix}.{key}"
        if key not in schema:
            msg = f"Unknown configuration key: {dotted}"
            raise ConfigError(msg)
        expected = schema[key]
        if isinstance(item, Mapping):
            if not isinstance(expected, Mapping):
                msg = f"Configuration key {dotted} must not be a table."
                raise ConfigError(msg)
            _validate_known_keys(item, expected, prefix=dotted)


def _require_table(value: object, *, key: str) -> Mapping[str, object]:
    """
    Return one config table or fail with a deterministic message.

    Parameters
    ----------
    value : object
        Candidate value.
    key : str
        Dotted key used in the error message.

    Returns
    -------
    collections.abc.Mapping[str, object]
        Validated table mapping.

    Raises
    ------
    ConfigError
        If ``value`` is not a mapping.
    """

    if not isinstance(value, Mapping):
        msg = f"Configuration key {key} must be a table."
        raise ConfigError(msg)
    return value


def _validate_type(value: object, expected: type[object], *, key: str) -> None:
    """
    Validate one scalar config value type.

    Parameters
    ----------
    value : object
        Candidate value.
    expected : type[object]
        Required Python type.
    key : str
        Dotted config key.

    Returns
    -------
    None
        The value is accepted when its type matches.

    Raises
    ------
    ConfigError
        If the value type is invalid.
    """

    if expected is bool:
        if isinstance(value, bool):
            return
    elif expected is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return
    elif expected is str:
        if isinstance(value, str):
            return
    elif expected is list and isinstance(value, list):
        return
    msg = f"Configuration key {key} must be {expected.__name__}."
    raise ConfigError(msg)


def _validate_schema_types(
    value: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    prefix: str = "",
) -> None:
    """
    Validate config value types for keys present in one mapping.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Config values to validate.
    schema : collections.abc.Mapping[str, object]
        Schema values for the same level.
    prefix : str, optional
        Dotted prefix used during recursion.

    Returns
    -------
    None
        The mapping is accepted when all present keys have valid types.

    Raises
    ------
    ConfigError
        If a value has an invalid type.
    """

    for key, item in value.items():
        expected = schema[key]
        dotted = key if not prefix else f"{prefix}.{key}"
        if isinstance(expected, Mapping):
            child = _require_table(item, key=dotted)
            _validate_schema_types(child, expected, prefix=dotted)
        else:
            _validate_type(item, cast("type[object]", expected), key=dotted)


def _validate_int_minimums(
    value: Mapping[str, object],
    keys: tuple[str, ...],
    *,
    prefix: str,
    minimum: int,
) -> None:
    """
    Validate integer minimum constraints for present keys.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Config table to inspect.
    keys : tuple[str, ...]
        Keys whose integer values must be checked.
    prefix : str
        Dotted table prefix used in error messages.
    minimum : int
        Minimum accepted value.

    Returns
    -------
    None
        Values are accepted when absent or greater than or equal to
        ``minimum``.

    Raises
    ------
    ConfigError
        If a present integer value is below ``minimum``.
    """

    for key in keys:
        item = value.get(key)
        if isinstance(item, int) and item < minimum:
            msg = f"Configuration key {prefix}.{key} must be >= {minimum}."
            raise ConfigError(msg)


def _validate_semantics(value: Mapping[str, object]) -> None:
    """
    Validate semantic constraints after type validation.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Fully merged or partial configuration mapping.

    Returns
    -------
    None
        The mapping is accepted when semantic constraints hold.

    Raises
    ------
    ConfigError
        If a value is outside the accepted range.
    """

    config_version = value.get("config_version")
    if config_version is not None and config_version != CONFIG_VERSION:
        msg = f"Unsupported config_version {config_version}; expected {CONFIG_VERSION}."
        raise ConfigError(msg)

    backend = value.get("backend")
    if isinstance(backend, Mapping):
        name = backend.get("name")
        if isinstance(name, str) and not name.strip():
            msg = "Configuration key backend.name must be a non-empty string."
            raise ConfigError(msg)

    plugins = value.get("plugins")
    if isinstance(plugins, Mapping):
        disabled = plugins.get("disabled_analyzers")
        if isinstance(disabled, list):
            for item in disabled:
                if not isinstance(item, str) or not item.strip():
                    msg = (
                        "Configuration key plugins.disabled_analyzers must "
                        "contain non-empty strings."
                    )
                    raise ConfigError(msg)

    embeddings = value.get("embeddings")
    if isinstance(embeddings, Mapping):
        for key in ("model", "version", "device"):
            item = embeddings.get(key)
            if isinstance(item, str) and not item.strip():
                msg = f"Configuration key embeddings.{key} must be non-empty."
                raise ConfigError(msg)
        _validate_int_minimums(
            embeddings,
            ("dimension", "batch_size"),
            prefix="embeddings",
            minimum=1,
        )
        _validate_int_minimums(
            embeddings,
            ("torch_num_threads", "torch_num_interop_threads"),
            prefix="embeddings",
            minimum=0,
        )
        gpu = embeddings.get("gpu")
        if isinstance(gpu, Mapping):
            _validate_int_minimums(
                gpu,
                ("device_id", "memory_limit_mb"),
                prefix="embeddings.gpu",
                minimum=0,
            )


def validate_config_mapping(value: Mapping[str, object]) -> None:
    """
    Validate one partial or complete config mapping.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Parsed config values.

    Returns
    -------
    None
        The mapping is accepted when it matches the public schema.

    Raises
    ------
    ConfigError
        If the mapping contains invalid config.
    """

    _validate_known_keys(value, _SCHEMA)
    _validate_schema_types(value, _SCHEMA)
    _validate_semantics(value)


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
        if isinstance(item, Mapping):
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
        elif isinstance(item, list):
            target[key] = list(item)
            origins[dotted] = origin
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


def _toml_table_from_mapping(value: Mapping[str, object]) -> tomlkit.items.Table:
    """
    Convert a nested config mapping into a TOML table.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Config section mapping to render.

    Returns
    -------
    tomlkit.items.Table
        TOML table containing scalar, list, and nested table values.
    """

    table = tomlkit.table()
    for key, item in value.items():
        if isinstance(item, Mapping):
            table.add(key, _toml_table_from_mapping(item))
        else:
            table.add(key, item)
    return table


def _merge_toml_table(table: object, updates: Mapping[str, object]) -> None:
    """
    Merge nested updates into an existing TOML table-like object.

    Parameters
    ----------
    table : object
        TOML document or table to mutate.
    updates : collections.abc.Mapping[str, object]
        Validated config updates.

    Returns
    -------
    None
        The TOML object is updated in place.
    """

    mutable_table = cast("dict[str, object]", table)
    for key, item in updates.items():
        if isinstance(item, Mapping):
            child = mutable_table.get(key)
            if not isinstance(child, Mapping):
                child = tomlkit.table()
                mutable_table[key] = child
            _merge_toml_table(child, item)
        else:
            mutable_table[key] = item


def render_config_toml(value: Mapping[str, object]) -> str:
    """
    Render a config mapping as deterministic TOML.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Config mapping to render.

    Returns
    -------
    str
        TOML text ending in a newline.
    """

    document = tomlkit.document()
    document.add("config_version", value["config_version"])
    for section_name in ("backend", "plugins", "embeddings"):
        section = _require_table(value[section_name], key=section_name)
        document.add(section_name, _toml_table_from_mapping(section))
    text = tomlkit.dumps(document)
    if not text.endswith("\n"):
        text += "\n"
    return text


def write_config_file(
    path: Path,
    *,
    profile: ProfileName = "default",
    force: bool = False,
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
    path.write_text(render_config_toml(profile_config(profile)), encoding="utf-8")


def update_config_file(path: Path, updates: Mapping[str, object]) -> None:
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
    None
        The target file is updated in place.

    Raises
    ------
    ConfigError
        If existing values, update values, or merged values are invalid.
    OSError
        If directory or file access fails.
    """

    validate_config_mapping(updates)
    if path.exists():
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
        existing = _deep_copy_mapping(document)
        validate_config_mapping(existing)
    else:
        document = tomlkit.document()
        existing = {}

    merged = _deep_copy_mapping(existing)
    _merge_config(
        merged,
        updates,
        origins={},
        origin=ConfigOrigin("update", path, str(path)),
    )
    validate_config_mapping(merged)
    _merge_toml_table(document, updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(document), encoding="utf-8")


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
    return _config_from_mapping(merged, origins=origins)


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

    return {
        "config_version": config.config_version,
        "backend": {"name": config.backend.name},
        "plugins": {
            "disable_third_party": config.plugins.disable_third_party,
            "disabled_analyzers": list(config.plugins.disabled_analyzers),
        },
        "embeddings": {
            "enabled": config.embeddings.enabled,
            "model": config.embeddings.model,
            "version": config.embeddings.version,
            "dimension": config.embeddings.dimension,
            "device": config.embeddings.device,
            "batch_size": config.embeddings.batch_size,
            "torch_num_threads": config.embeddings.torch_num_threads,
            "torch_num_interop_threads": config.embeddings.torch_num_interop_threads,
            "gpu": {
                "device_id": config.embeddings.gpu.device_id,
                "memory_limit_mb": config.embeddings.gpu.memory_limit_mb,
            },
        },
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
    embeddings = cast("Mapping[str, object]", value["embeddings"])
    gpu = cast("Mapping[str, object]", embeddings["gpu"])
    return CodiraConfig(
        config_version=cast("int", value["config_version"]),
        backend=BackendConfig(name=cast("str", backend["name"]).strip()),
        plugins=PluginsConfig(
            disable_third_party=cast("bool", plugins["disable_third_party"]),
            disabled_analyzers=tuple(
                str(item).strip()
                for item in cast("list[object]", plugins["disabled_analyzers"])
            ),
        ),
        embeddings=EmbeddingsConfig(
            enabled=cast("bool", embeddings["enabled"]),
            model=cast("str", embeddings["model"]).strip(),
            version=cast("str", embeddings["version"]).strip(),
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
        ),
        origins=origins,
    )
