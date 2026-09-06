"""Schema and semantic validation for Codira configuration mappings.

Responsibilities
----------------
- Enforce the versioned public configuration schema.
- Validate cross-field semantic constraints before runtime construction.

Architectural role
------------------
This module is pure validation policy. File loading, environment resolution,
and typed configuration construction remain in :mod:`codira.config`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from codira.config_models import (
    _PLUGIN_CONFIG_RESERVED_KEYS,
    _SCHEMA,
    CONFIG_VERSION,
    KNOWN_EMBEDDING_INDEX_MODES,
    KNOWN_EMBEDDING_OBJECT_TYPES,
    KNOWN_INDEX_CONCURRENCY_STRATEGIES,
    ConfigError,
)


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
        if prefix == "plugins" and key not in _PLUGIN_CONFIG_RESERVED_KEYS:
            if not isinstance(item, Mapping):
                msg = f"Configuration key {dotted} must be a table."
                raise ConfigError(msg)
            continue
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
        if prefix == "plugins" and key not in _PLUGIN_CONFIG_RESERVED_KEYS:
            _require_table(item, key=f"{prefix}.{key}")
            continue
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


def _validate_plugin_semantics(plugins: Mapping[str, object]) -> None:
    """
    Validate semantic constraints for plugin configuration tables.

    Parameters
    ----------
    plugins : collections.abc.Mapping[str, object]
        Plugin configuration section.

    Returns
    -------
    None
        The plugin configuration is accepted when no exception is raised.

    Raises
    ------
    ConfigError
        If a plugin table name or common enabled flag is invalid.
    """

    disabled = plugins.get("disabled_analyzers")
    if isinstance(disabled, list):
        for item in disabled:
            if not isinstance(item, str) or not item.strip():
                msg = (
                    "Configuration key plugins.disabled_analyzers must "
                    "contain non-empty strings."
                )
                raise ConfigError(msg)
    routes = plugins.get("documentation_audit_routes")
    if isinstance(routes, list):
        _validate_documentation_audit_routes(routes)
    for key, item in plugins.items():
        if key in _PLUGIN_CONFIG_RESERVED_KEYS:
            continue
        if not key.startswith(
            (
                "analyzer-",
                "backend-",
                "embedding-",
                "vector-store-",
                "similarity-index-",
                "documentation-audit-",
            )
        ):
            msg = (
                "Plugin configuration tables must be named "
                "plugins.analyzer-*, plugins.backend-*, "
                "plugins.embedding-*, plugins.vector-store-*, plugins.similarity-index-*, "
                "or plugins.documentation-audit-*: "
                f"plugins.{key}"
            )
            raise ConfigError(msg)
        if not isinstance(item, Mapping):
            msg = f"Configuration key plugins.{key} must be a table."
            raise ConfigError(msg)
        if key.startswith("vector-store-") and "candidate_limit" in item:
            msg = (
                f"Configuration key plugins.{key}.candidate_limit is no longer "
                "supported. Define candidate_limit in a named "
                "similarity-index search profile instead."
            )
            raise ConfigError(msg)
        enabled = item.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            msg = f"Configuration key plugins.{key}.enabled must be bool."
            raise ConfigError(msg)


def _validate_documentation_audit_routes(routes: list[object]) -> None:
    """
    Validate documentation audit route tables.

    Parameters
    ----------
    routes : list[object]
        Candidate ordered route tables from ``plugins.documentation_audit_routes``.

    Returns
    -------
    None
        Routes are accepted when required fields and path lists are valid.

    Raises
    ------
    ConfigError
        If any route is malformed.
    """

    for index, item in enumerate(routes):
        key = f"plugins.documentation_audit_routes[{index}]"
        if not isinstance(item, Mapping):
            msg = f"Configuration key {key} must be a table."
            raise ConfigError(msg)
        allowed = {"language", "convention", "plugin", "include_paths", "exclude_paths"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            msg = f"Unknown configuration key: {key}.{unknown[0]}"
            raise ConfigError(msg)
        for required in ("language", "convention", "plugin"):
            value = item.get(required)
            if not isinstance(value, str) or not value.strip():
                msg = f"Configuration key {key}.{required} must be a non-empty string."
                raise ConfigError(msg)
        for path_key in ("include_paths", "exclude_paths"):
            value = item.get(path_key, [])
            if not isinstance(value, list):
                msg = f"Configuration key {key}.{path_key} must be list."
                raise ConfigError(msg)
            _validate_string_list(
                value,
                key=f"{key}.{path_key}",
                allow_empty_items=False,
            )


def _validate_string_list(
    value: object,
    *,
    key: str,
    allow_empty_items: bool,
) -> None:
    """
    Validate one public config list containing strings.

    Parameters
    ----------
    value : object
        Candidate list value.
    key : str
        Dotted config key used in diagnostics.
    allow_empty_items : bool
        Whether empty strings are accepted as list items.

    Returns
    -------
    None
        The value is accepted when it is not a list or all items are strings
        satisfying the configured emptiness rule.

    Raises
    ------
    ConfigError
        If any item is not an accepted string.
    """

    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, str):
            msg = f"Configuration key {key} must contain strings."
            raise ConfigError(msg)
        if not allow_empty_items and not item.strip():
            msg = f"Configuration key {key} must contain non-empty strings."
            raise ConfigError(msg)


def _validate_embedding_indexing_semantics(indexing: Mapping[str, object]) -> None:
    """
    Validate embedding indexing control semantics.

    Parameters
    ----------
    indexing : collections.abc.Mapping[str, object]
        Embedding indexing configuration table.

    Returns
    -------
    None
        The table is accepted when all present controls are supported.

    Raises
    ------
    ConfigError
        If a control value is unsupported or internally inconsistent.
    """

    mode = indexing.get("mode")
    if isinstance(mode, str) and mode not in KNOWN_EMBEDDING_INDEX_MODES:
        allowed = ", ".join(sorted(KNOWN_EMBEDDING_INDEX_MODES))
        msg = f"Configuration key embeddings.indexing.mode must be one of: {allowed}."
        raise ConfigError(msg)

    object_types = indexing.get("object_types")
    if isinstance(object_types, list):
        _validate_string_list(
            object_types,
            key="embeddings.indexing.object_types",
            allow_empty_items=False,
        )
        seen: set[str] = set()
        for object_type in object_types:
            if object_type not in KNOWN_EMBEDDING_OBJECT_TYPES:
                allowed = ", ".join(sorted(KNOWN_EMBEDDING_OBJECT_TYPES))
                msg = (
                    "Configuration key embeddings.indexing.object_types "
                    f"must contain only supported values: {allowed}."
                )
                raise ConfigError(msg)
            if object_type in seen:
                msg = (
                    "Configuration key embeddings.indexing.object_types "
                    f"contains duplicate value: {object_type}."
                )
                raise ConfigError(msg)
            seen.add(object_type)

    _validate_string_list(
        indexing.get("include_paths"),
        key="embeddings.indexing.include_paths",
        allow_empty_items=False,
    )
    _validate_string_list(
        indexing.get("exclude_paths"),
        key="embeddings.indexing.exclude_paths",
        allow_empty_items=False,
    )


def _validate_index_concurrency_semantics(concurrency: Mapping[str, object]) -> None:
    """
    Validate index analysis scheduling controls.

    Parameters
    ----------
    concurrency : collections.abc.Mapping[str, object]
        Index concurrency configuration table.

    Returns
    -------
    None
        The table is accepted when its strategy and numeric bounds are valid.

    Raises
    ------
    ConfigError
        If a strategy or numeric control is unsupported.
    """

    strategy = concurrency.get("strategy")
    if isinstance(strategy, str) and strategy not in KNOWN_INDEX_CONCURRENCY_STRATEGIES:
        allowed = ", ".join(sorted(KNOWN_INDEX_CONCURRENCY_STRATEGIES))
        msg = f"Configuration key index.concurrency.strategy must be one of: {allowed}."
        raise ConfigError(msg)
    _validate_int_minimums(
        concurrency,
        ("max_workers",),
        prefix="index.concurrency",
        minimum=0,
    )
    _validate_int_minimums(
        concurrency,
        ("min_files",),
        prefix="index.concurrency",
        minimum=1,
    )


def _validate_index_coverage_semantics(coverage: Mapping[str, object]) -> None:
    """Validate configured coverage-root and suffix-exclusion patterns.

    Parameters
    ----------
    coverage : collections.abc.Mapping[str, object]
        Coverage configuration table.

    Returns
    -------
    None
        The table is accepted when patterns are safe and unambiguous.
    """

    roots = coverage.get("roots")
    _validate_string_list(roots, key="index.coverage.roots", allow_empty_items=False)
    if isinstance(roots, list):
        patterns = [str(item).strip() for item in roots]
        if "-" in patterns and patterns != ["-"]:
            msg = "Configuration key index.coverage.roots may use '-' only by itself."
            raise ConfigError(msg)
        if any(
            pattern != "-" and (pattern.startswith("/") or ".." in pattern.split("/"))
            for pattern in patterns
        ):
            msg = (
                "Configuration key index.coverage.roots must use repo-relative "
                "patterns."
            )
            raise ConfigError(msg)
    suffixes = coverage.get("exclude_suffixes")
    _validate_string_list(
        suffixes,
        key="index.coverage.exclude_suffixes",
        allow_empty_items=False,
    )
    if not isinstance(suffixes, list):
        return
    normalized_suffixes = [str(item).strip().lower() for item in suffixes]
    if any(
        suffix != "<no-suffix>"
        and (
            not suffix.startswith(".")
            or "/" in suffix
            or "\\" in suffix
            or suffix == "."
        )
        for suffix in normalized_suffixes
    ):
        msg = (
            "Configuration key index.coverage.exclude_suffixes must contain "
            "file suffixes such as '.yml' or '<no-suffix>'."
        )
        raise ConfigError(msg)


def _validate_daemon_semantics(daemon: Mapping[str, object]) -> None:
    """Validate automatic-indexing daemon controls.

    Parameters
    ----------
    daemon : collections.abc.Mapping[str, object]
        Daemon configuration table.

    Returns
    -------
    None
        The table is accepted when its debounce and path controls are safe.

    Raises
    ------
    ConfigError
        If a daemon control is unsupported or unsafe.
    """

    _validate_int_minimums(daemon, ("debounce_ms",), prefix="daemon", minimum=1)
    for key in ("include_paths", "exclude_paths"):
        value = daemon.get(key)
        _validate_string_list(value, key=f"daemon.{key}", allow_empty_items=False)
        if not isinstance(value, list):
            continue
        patterns = [str(item).strip() for item in value]
        if any(
            pattern.startswith("/") or ".." in pattern.split("/")
            for pattern in patterns
        ):
            msg = f"Configuration key daemon.{key} must use repo-relative paths."
            raise ConfigError(msg)


def _validate_semantics(value: Mapping[str, object]) -> None:  # noqa: C901
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
        msg = (
            f"Unsupported config_version {config_version}; expected {CONFIG_VERSION}. "
            "Regenerate the configuration with `codira config init --force`, then "
            'select embeddings.similarity_index = "exact" or another installed index.'
        )
        raise ConfigError(msg)

    backend = value.get("backend")
    if isinstance(backend, Mapping):
        name = backend.get("name")
        if isinstance(name, str) and not name.strip():
            msg = "Configuration key backend.name must be a non-empty string."
            raise ConfigError(msg)

    plugins = value.get("plugins")
    if isinstance(plugins, Mapping):
        _validate_plugin_semantics(plugins)

    embeddings = value.get("embeddings")
    if isinstance(embeddings, Mapping):
        if config_version == CONFIG_VERSION and "similarity_index" not in embeddings:
            msg = (
                "Configuration version 2 requires embeddings.similarity_index. "
                "Regenerate the configuration with `codira config init --force` "
                'or add similarity_index = "exact" explicitly.'
            )
            raise ConfigError(msg)
        for key in (
            "engine",
            "vector_store",
            "similarity_index",
            "model",
            "version",
            "device",
        ):
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
        indexing = embeddings.get("indexing")
        if isinstance(indexing, Mapping):
            _validate_int_minimums(
                indexing,
                ("max_text_chars",),
                prefix="embeddings.indexing",
                minimum=0,
            )
            _validate_int_minimums(
                indexing,
                ("max_source_file_bytes",),
                prefix="embeddings.indexing",
                minimum=1,
            )
            _validate_int_minimums(
                indexing,
                ("work_batch_multiplier",),
                prefix="embeddings.indexing",
                minimum=1,
            )
            work_batch_multiplier = indexing.get("work_batch_multiplier")
            if isinstance(work_batch_multiplier, int) and work_batch_multiplier > 4096:
                msg = (
                    "Configuration key embeddings.indexing.work_batch_multiplier "
                    "must be less than or equal to 4096."
                )
                raise ConfigError(msg)
            _validate_embedding_indexing_semantics(indexing)

    index = value.get("index")
    if isinstance(index, Mapping):
        concurrency = index.get("concurrency")
        if isinstance(concurrency, Mapping):
            _validate_index_concurrency_semantics(concurrency)
        coverage = index.get("coverage")
        if isinstance(coverage, Mapping):
            _validate_index_coverage_semantics(coverage)

    daemon = value.get("daemon")
    if isinstance(daemon, Mapping):
        _validate_daemon_semantics(daemon)


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


__all__ = ("validate_config_mapping",)
