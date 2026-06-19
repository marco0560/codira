"""Backend and analyzer registries for ADR-004 Phase 8.

Responsibilities
----------------
- Discover and register built-in or entry-point analyzers and backends, including dependency metadata.
- Provide deterministic plugin registration reporting for CLI diagnostics and runtime introspection.
- Offer helpers to instantiate plugins, check requirements, and enumerate active analyzers/backends.

Design principles
-----------------
Registry logic keeps discovery predictable, reports duplicates or skips, and isolates optional extras per analyzer.

Architectural role
------------------
This module belongs to the **plugin registration layer** powering ADR-004 analyzer and backend extensibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import TYPE_CHECKING, Any, Literal, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

from codira.config import DEFAULT_BACKEND_NAME, ConfigError, load_effective_config
from codira.contracts import (
    ConfigurablePlugin,
    EmbeddingEngine,
    IndexBackend,
    LanguageAnalyzer,
    PluginConfigurationSchemaProvider,
    VectorStore,
)
from codira.plugin_config import plugin_configuration_fingerprint, plugin_enabled

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

DEFAULT_INDEX_BACKEND = DEFAULT_BACKEND_NAME
INDEX_BACKEND_ENV_VAR = "CODIRA_INDEX_BACKEND"
DISABLE_THIRD_PARTY_PLUGINS_ENV_VAR = "CODIRA_DISABLE_THIRD_PARTY_PLUGINS"
ANALYZER_ENTRY_POINT_GROUP = "codira.analyzers"
BACKEND_ENTRY_POINT_GROUP = "codira.backends"
EMBEDDING_ENGINE_ENTRY_POINT_GROUP = "codira.embedding_engines"
VECTOR_STORE_ENTRY_POINT_GROUP = "codira.vector_stores"
# These package hints are registry metadata only. SQLite remains the
# compatibility default by backend name, while schema and connection ownership
# live in the first-party backend package.
OPTIONAL_BACKEND_PACKAGE_BY_NAME: dict[str, str] = {
    "sqlite": "codira-backend-sqlite",
    "duckdb": "codira-backend-duckdb",
}
OPTIONAL_ANALYZER_PACKAGE_BY_NAME: dict[str, str] = {
    "python": "codira-analyzer-python",
    "json": "codira-analyzer-json",
    "c": "codira-analyzer-c",
    "cpp": "codira-analyzer-cpp",
    "bash": "codira-analyzer-bash",
    "markdown": "codira-analyzer-markdown",
    "text": "codira-analyzer-text",
}
PREFERRED_ANALYZER_ORDER: dict[str, int] = {
    "python": 0,
    "json": 5,
    "c": 10,
    "cpp": 15,
    "bash": 20,
    "markdown": 25,
    "text": 30,
}
REQUIRED_BACKEND_METHODS: tuple[str, ...] = (
    "begin_index_session",
    "open_connection",
    "initialize",
    "load_existing_file_hashes",
    "delete_paths",
    "clear_index",
    "purge_skipped_docstring_issues",
    "load_previous_embeddings_by_path",
    "persist_analysis",
    "count_reusable_embeddings",
    "rebuild_derived_indexes",
    "persist_runtime_inventory",
    "commit",
    "close_connection",
    "list_symbols_in_module",
    "find_symbol",
    "symbol_inventory",
    "docstring_issues",
    "find_call_edges",
    "find_callable_refs",
    "find_include_edges",
    "find_logical_symbols",
    "logical_symbol_name",
    "embedding_inventory",
    "embedding_candidates",
    "prune_orphaned_embeddings",
    "current_embedding_state_matches",
)
PluginFamily = Literal["analyzer", "backend", "embedding", "vector-store"]
PluginSource = Literal["builtin", "entry_point"]
PluginStatus = Literal["loaded", "skipped", "duplicate"]
PluginOrigin = Literal["core", "first_party", "third_party"]


@dataclass(frozen=True)
class PluginRegistration:
    """
    Deterministic plugin registration record.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    name : str
        Stable analyzer or backend name.
    provider : str
        Distribution or built-in provider label.
    source : {"builtin", "entry_point"}
        Registration source.
    status : {"loaded", "skipped", "duplicate"}
        Registration outcome used by diagnostics and CLI reporting.
    version : str
        Plugin implementation version string.
    entry_point : str | None, optional
        Entry-point name for third-party plugins.
    detail : str | None, optional
        Deterministic explanation for skipped or duplicate records.
    origin : {"core", "first_party", "third_party"}
        Ownership classification for operator-facing reporting.
    """

    family: PluginFamily
    name: str
    provider: str
    source: PluginSource
    status: PluginStatus
    version: str
    entry_point: str | None = None
    detail: str | None = None
    origin: PluginOrigin = "third_party"


@dataclass(frozen=True)
class PluginConfigWarning:
    """
    Non-fatal plugin configuration validation diagnostic.

    Parameters
    ----------
    key : str
        Namespaced plugin table key.
    reason : str
        Deterministic warning reason.
    """

    key: str
    reason: str


@dataclass(frozen=True)
class _LoadedPlugin:
    """
    Internal loaded-plugin representation used by registry resolution.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    name : str
        Stable analyzer or backend name.
    provider : str
        Distribution or built-in provider label.
    source : {"builtin", "entry_point"}
        Registration source.
    version : str
        Plugin implementation version string.
    factory : collections.abc.Callable[[], object]
        Zero-argument factory producing the plugin implementation.
    entry_point : str | None, optional
        Entry-point name for third-party plugins.
    """

    family: PluginFamily
    name: str
    provider: str
    source: PluginSource
    version: str
    factory: Callable[[], object]
    entry_point: str | None = None


def _registered_index_backends() -> dict[str, type[IndexBackend]]:
    """
    Return the backend factory registry keyed by backend name.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, type[codira.contracts.IndexBackend]]
        Deterministic backend factories keyed by stable backend name.
    """
    return {}


def _plugin_origin(*, provider: str, source: PluginSource) -> PluginOrigin:
    """
    Classify plugin ownership for diagnostics and operator reporting.

    Parameters
    ----------
    provider : str
        Distribution or built-in provider label.
    source : {"builtin", "entry_point"}
        Registration source.

    Returns
    -------
    {"core", "first_party", "third_party"}
        Ownership classification for the plugin.
    """
    if source == "builtin" and provider == "codira":
        return "core"
    if provider == "codira" or provider.startswith("codira-"):
        return "first_party"
    return "third_party"


def _third_party_plugins_disabled(*, root: Path | None = None) -> bool:
    """
    Return whether third-party entry-point plugins are disabled.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        selection.

    Returns
    -------
    bool
        ``True`` when effective configuration disables third-party plugins.
    """

    return load_effective_config(root=root).plugins.disable_third_party


def _configured_disabled_analyzers(*, root: Path | None = None) -> tuple[str, ...]:
    """
    Return analyzer names disabled by effective configuration.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in analyzer
        selection.

    Returns
    -------
    tuple[str, ...]
        Analyzer names removed from the active analyzer set.
    """

    return load_effective_config(root=root).plugins.disabled_analyzers


def _configured_plugin_tables(
    *, root: Path | None = None
) -> dict[str, dict[str, object]]:
    """
    Return namespaced plugin configuration tables.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should contribute plugin
        tables.

    Returns
    -------
    dict[str, dict[str, object]]
        Plugin-specific config tables keyed by ``analyzer-*`` or
        ``backend-*`` table name.
    """

    return dict(load_effective_config(root=root).plugins.configs or {})


def plugin_config_key(*, family: PluginFamily, name: str) -> str:
    """
    Return the namespaced config key for one plugin.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin family.
    name : str
        Stable plugin name.

    Returns
    -------
    str
        Config table key such as ``"analyzer-python"``.
    """

    return f"{family}-{name}"


def _plugin_config_for(
    *,
    family: PluginFamily,
    name: str,
    root: Path | None = None,
) -> dict[str, object]:
    """
    Return the configured table for one plugin.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin family.
    name : str
        Stable plugin name.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should contribute plugin
        tables.

    Returns
    -------
    dict[str, object]
        Plugin configuration table, or an empty table when absent.
    """

    return _configured_plugin_tables(root=root).get(
        plugin_config_key(family=family, name=name),
        {},
    )


def _configuration_schema(instance: object) -> dict[str, object] | None:
    """
    Return a plugin JSON Schema when the plugin exposes one.

    Parameters
    ----------
    instance : object
        Plugin instance to inspect.

    Returns
    -------
    dict[str, object] | None
        Plugin JSON Schema, or ``None`` when absent.
    """

    if not isinstance(instance, PluginConfigurationSchemaProvider):
        return None
    schema = instance.configuration_json_schema()
    return dict(schema)


def _validate_plugin_config_schema(
    *,
    key: str,
    instance: object,
    config: dict[str, object],
) -> None:
    """
    Validate one plugin configuration table against a plugin schema.

    Parameters
    ----------
    key : str
        Namespaced plugin table key.
    instance : object
        Plugin instance exposing the optional schema.
    config : dict[str, object]
        Plugin configuration table.

    Returns
    -------
    None
        The table is valid when no exception is raised.

    Raises
    ------
    ConfigError
        If the schema is invalid or the table fails validation.
    """

    schema = _configuration_schema(instance)
    if schema is None:
        return
    try:
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(config),
            key=lambda error: tuple(str(part) for part in error.path),
        )
    except SchemaError as exc:
        msg = f"Plugin configuration schema for plugins.{key} is invalid: {exc.message}"
        raise ConfigError(msg) from exc
    if errors:
        error = errors[0]
        suffix = ".".join(str(part) for part in error.path)
        path_label = f"plugins.{key}" if not suffix else f"plugins.{key}.{suffix}"
        msg = f"Invalid plugin configuration {path_label}: {error.message}"
        raise ConfigError(msg) from error


def _configure_plugin_instance(
    *,
    plugin: _LoadedPlugin,
    instance: object,
    root: Path | None = None,
) -> object:
    """
    Inject namespaced configuration into one plugin instance.

    Parameters
    ----------
    plugin : codira.registry._LoadedPlugin
        Loaded plugin metadata.
    instance : object
        Fresh plugin instance.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should configure the plugin.

    Returns
    -------
    object
        The configured plugin instance.
    """

    config = _plugin_config_for(family=plugin.family, name=plugin.name, root=root)
    key = plugin_config_key(family=plugin.family, name=plugin.name)
    _validate_plugin_config_schema(key=key, instance=instance, config=config)
    if isinstance(instance, ConfigurablePlugin):
        instance.configure(config)
    if not hasattr(instance, "configuration_fingerprint"):
        cast(
            "Any", instance
        ).configuration_fingerprint = plugin_configuration_fingerprint(config)
    return instance


def _entry_point_provider(entry_point: metadata.EntryPoint) -> str:
    """
    Return the provider distribution name for an entry point.

    Parameters
    ----------
    entry_point : importlib.metadata.EntryPoint
        Entry point whose owning distribution should be reported.

    Returns
    -------
    str
        Distribution name, or ``"<unknown>"`` when metadata is unavailable.
    """

    return getattr(getattr(entry_point, "dist", None), "name", "") or "<unknown>"


def _disabled_third_party_registration(
    entry_point: metadata.EntryPoint,
    *,
    family: PluginFamily,
    provider: str,
) -> PluginRegistration:
    """
    Build a skipped registration for a disabled third-party plugin.

    Parameters
    ----------
    entry_point : importlib.metadata.EntryPoint
        Entry point intentionally left unloaded.
    family : {"analyzer", "backend"}
        Plugin extension family.
    provider : str
        Distribution name owning the entry point.

    Returns
    -------
    PluginRegistration
        Deterministic skipped registration record.
    """

    return PluginRegistration(
        family=family,
        name=entry_point.name,
        provider=provider,
        source="entry_point",
        status="skipped",
        version="unknown",
        entry_point=entry_point.name,
        detail=("third-party plugins are disabled by configuration"),
        origin="third_party",
    )


def _builtin_backend_plugins() -> list[_LoadedPlugin]:
    """
    Return built-in backend registrations.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.registry._LoadedPlugin]
        Built-in backend plugins in deterministic order.
    """
    return []


def _builtin_embedding_engine_plugins() -> list[_LoadedPlugin]:
    """
    Return built-in embedding engine registrations.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.registry._LoadedPlugin]
        Built-in embedding engine plugins in deterministic order.
    """
    return []


def _builtin_vector_store_plugins() -> list[_LoadedPlugin]:
    """
    Return built-in vector-store registrations.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.registry._LoadedPlugin]
        Built-in vector-store plugins in deterministic order.
    """
    return []


def _registered_language_analyzer_factories() -> tuple[
    Callable[[], LanguageAnalyzer], ...
]:
    """
    Return the registered language analyzer factories in routing order.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[collections.abc.Callable[[], codira.contracts.LanguageAnalyzer], ...]
        Analyzer factories in deterministic first-match order.
    """
    return ()


def _builtin_analyzer_plugins() -> list[_LoadedPlugin]:
    """
    Return built-in analyzer registrations.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.registry._LoadedPlugin]
        Built-in analyzer plugins in deterministic routing order.
    """
    factories = _registered_language_analyzer_factories()
    loaded: list[_LoadedPlugin] = []

    for factory in factories:
        instance = factory()
        loaded.append(
            _LoadedPlugin(
                family="analyzer",
                name=str(instance.name),
                provider="codira",
                source="builtin",
                version=str(instance.version),
                factory=factory,
            )
        )

    return loaded


def _entry_points_for_group(group: str) -> list[metadata.EntryPoint]:
    """
    Return entry points for one plugin group in deterministic order.

    Parameters
    ----------
    group : str
        Entry-point group name.

    Returns
    -------
    list[importlib.metadata.EntryPoint]
        Entry points sorted by provider and entry-point name.
    """
    discovered = list(_cached_entry_points_for_group(group, metadata.entry_points))
    discovered.sort(
        key=lambda entry: (
            entry.name,
            getattr(getattr(entry, "dist", None), "name", "") or "",
            entry.value,
        )
    )
    return discovered


@lru_cache(maxsize=8)
def _cached_entry_points_for_group(
    group: str,
    entry_points_loader: object,
) -> tuple[metadata.EntryPoint, ...]:
    """
    Cache deterministic entry-point discovery for one plugin group.

    Parameters
    ----------
    group : str
        Entry-point group name.
    entry_points_loader : object
        Cache token for ``importlib.metadata.entry_points`` so monkeypatched
        loaders do not reuse stale cached discovery state.

    Returns
    -------
    tuple[importlib.metadata.EntryPoint, ...]
        Entry points as returned by ``importlib.metadata.entry_points`` before
        deterministic sorting in the public wrapper.
    """
    del entry_points_loader
    return tuple(metadata.entry_points(group=group))


def _load_entry_point_plugin(
    entry_point: metadata.EntryPoint,
    *,
    family: PluginFamily,
) -> tuple[_LoadedPlugin | None, PluginRegistration]:
    """
    Load one entry-point plugin and validate its contract.

    Parameters
    ----------
    entry_point : importlib.metadata.EntryPoint
        Entry point to resolve.
    family : {"analyzer", "backend"}
        Expected plugin family for contract validation.

    Returns
    -------
    tuple[
        codira.registry._LoadedPlugin | None,
        codira.registry.PluginRegistration,
    ]
        Loaded plugin and its registration record. Failed loads return
        ``None`` plus a skipped registration record.
    """
    provider = _entry_point_provider(entry_point)

    try:
        loaded_object = entry_point.load()
    except Exception as exc:
        return None, PluginRegistration(
            family=family,
            name=entry_point.name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail=f"load failed: {exc.__class__.__name__}: {exc}",
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )

    if not callable(loaded_object):
        return None, PluginRegistration(
            family=family,
            name=entry_point.name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail="entry point is not callable",
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )

    factory = cast("Callable[[], object]", loaded_object)

    try:
        instance = factory()
    except Exception as exc:
        return None, PluginRegistration(
            family=family,
            name=entry_point.name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail=f"factory failed: {exc.__class__.__name__}: {exc}",
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )

    contract_error = _plugin_contract_error(family=family, instance=instance)
    if contract_error is not None:
        return None, PluginRegistration(
            family=family,
            name=entry_point.name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail=contract_error,
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )

    name = getattr(instance, "name", None)
    raw_version = getattr(instance, "version", None)
    if not isinstance(name, str) or not name.strip():
        return None, PluginRegistration(
            family=family,
            name=entry_point.name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail="plugin name must be a non-empty string",
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )
    version = None if raw_version is None else str(raw_version).strip()
    if not version:
        return None, PluginRegistration(
            family=family,
            name=name,
            provider=provider,
            source="entry_point",
            status="skipped",
            version="unknown",
            entry_point=entry_point.name,
            detail="plugin version must be a non-empty string",
            origin=_plugin_origin(provider=provider, source="entry_point"),
        )

    return (
        _LoadedPlugin(
            family=family,
            name=name,
            provider=provider,
            source="entry_point",
            version=version,
            factory=factory,
            entry_point=entry_point.name,
        ),
        PluginRegistration(
            family=family,
            name=name,
            provider=provider,
            source="entry_point",
            status="loaded",
            version=version,
            entry_point=entry_point.name,
            origin=_plugin_origin(provider=provider, source="entry_point"),
        ),
    )


def _discover_entry_point_plugins(
    *,
    family: PluginFamily,
    group: str,
    third_party_disabled: bool,
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Discover entry-point plugins for one extension family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    group : str
        Entry-point group to inspect.
    third_party_disabled : bool
        Whether third-party entry points are disabled for this snapshot.

    Returns
    -------
    tuple[
        list[codira.registry._LoadedPlugin],
        list[codira.registry.PluginRegistration],
    ]
        Loaded plugins plus diagnostic registration records.
    """
    loaded: list[_LoadedPlugin] = []
    registrations: list[PluginRegistration] = []

    for entry_point in _entry_points_for_group(group):
        provider = _entry_point_provider(entry_point)
        if (
            third_party_disabled
            and _plugin_origin(provider=provider, source="entry_point") == "third_party"
        ):
            registrations.append(
                _disabled_third_party_registration(
                    entry_point,
                    family=family,
                    provider=provider,
                )
            )
            continue
        plugin, registration = _load_entry_point_plugin(entry_point, family=family)
        registrations.append(registration)
        if plugin is not None:
            loaded.append(plugin)

    return loaded, registrations


def _analyzer_contract_error(instance: object) -> str | None:
    """
    Return a deterministic analyzer contract error for one plugin instance.

    Parameters
    ----------
    instance : object
        Plugin instance to validate.

    Returns
    -------
    str | None
        Error detail, or ``None`` when the instance satisfies the contract.
    """

    if not isinstance(instance, LanguageAnalyzer):
        return "factory returned a non-LanguageAnalyzer object"
    discovery_globs = getattr(instance, "discovery_globs", None)
    invalid_discovery_globs = (
        not isinstance(discovery_globs, tuple)
        or not discovery_globs
        or any(
            not isinstance(pattern, str) or not pattern.strip()
            for pattern in discovery_globs
        )
    )
    if invalid_discovery_globs:
        return "analyzer discovery_globs must be a non-empty tuple[str, ...]"
    return None


def _backend_contract_error(instance: object) -> str | None:
    """
    Return a deterministic backend contract error for one plugin instance.

    Parameters
    ----------
    instance : object
        Plugin instance to validate.

    Returns
    -------
    str | None
        Error detail, or ``None`` when the instance satisfies the contract.
    """

    if not isinstance(instance, IndexBackend):
        return "factory returned a non-IndexBackend object"
    missing_methods = [
        method
        for method in REQUIRED_BACKEND_METHODS
        if not callable(getattr(instance, method, None))
    ]
    if missing_methods:
        joined = ", ".join(sorted(missing_methods))
        return f"backend is missing required methods: {joined}"
    return None


def _plugin_contract_error(
    *,
    family: PluginFamily,
    instance: object,
) -> str | None:
    """
    Return a deterministic contract error for one plugin instance.

    Parameters
    ----------
    family : {"analyzer", "backend", "embedding", "vector-store"}
        Plugin family being validated.
    instance : object
        Plugin instance to validate.

    Returns
    -------
    str | None
        Error detail, or ``None`` when the instance satisfies the contract.
    """

    if family == "analyzer":
        return _analyzer_contract_error(instance)
    if family == "backend":
        return _backend_contract_error(instance)
    if family == "embedding" and not isinstance(instance, EmbeddingEngine):
        return "factory returned a non-EmbeddingEngine object"
    if family == "vector-store" and not isinstance(instance, VectorStore):
        return "factory returned a non-VectorStore object"
    return None


def _resolve_plugins(
    builtins: list[_LoadedPlugin],
    externals: list[_LoadedPlugin],
    external_registrations: list[PluginRegistration],
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Merge built-in and entry-point plugins with duplicate rejection.

    Parameters
    ----------
    builtins : list[codira.registry._LoadedPlugin]
        Built-in plugin registrations.
    externals : list[codira.registry._LoadedPlugin]
        Successfully loaded entry-point plugins.
    external_registrations : list[codira.registry.PluginRegistration]
        Entry-point registration diagnostics.

    Returns
    -------
    tuple[
        list[codira.registry._LoadedPlugin],
        list[codira.registry.PluginRegistration],
    ]
        Loaded plugins that survived duplicate checks plus full diagnostics.
    """
    resolved = list(builtins)
    registrations = [
        PluginRegistration(
            family=plugin.family,
            name=plugin.name,
            provider=plugin.provider,
            source=plugin.source,
            status="loaded",
            version=plugin.version,
            entry_point=plugin.entry_point,
            origin=_plugin_origin(provider=plugin.provider, source=plugin.source),
        )
        for plugin in builtins
    ]
    seen_names = {plugin.name for plugin in builtins}

    duplicate_keys: set[tuple[str, str, str]] = set()

    ordered_externals = list(externals)
    if externals and externals[0].family == "analyzer":
        ordered_externals.sort(
            key=lambda plugin: (
                PREFERRED_ANALYZER_ORDER.get(plugin.name, 1000),
                plugin.name,
                plugin.provider,
                plugin.entry_point or "",
            )
        )

    for plugin in ordered_externals:
        if plugin.name in seen_names:
            duplicate_keys.add(
                (
                    plugin.provider,
                    plugin.entry_point or "",
                    plugin.name,
                )
            )
            registrations.append(
                PluginRegistration(
                    family=plugin.family,
                    name=plugin.name,
                    provider=plugin.provider,
                    source=plugin.source,
                    status="duplicate",
                    version=plugin.version,
                    entry_point=plugin.entry_point,
                    detail="duplicate plugin name rejected",
                    origin=_plugin_origin(
                        provider=plugin.provider,
                        source=plugin.source,
                    ),
                )
            )
            continue
        seen_names.add(plugin.name)
        resolved.append(plugin)

    for registration in external_registrations:
        key = (
            registration.provider,
            registration.entry_point or "",
            registration.name,
        )
        if registration.status == "loaded" and key in duplicate_keys:
            continue
        registrations.append(registration)
    return resolved, registrations


def _plugin_snapshot(
    family: PluginFamily,
    *,
    root: Path | None = None,
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Build the registry snapshot for one plugin family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        selection.

    Returns
    -------
    tuple[
        list[codira.registry._LoadedPlugin],
        list[codira.registry.PluginRegistration],
    ]
        Resolved plugins plus diagnostic registrations.
    """
    configured_tables = _configured_plugin_tables(root=root)
    resolved, registrations = _cached_plugin_snapshot(
        family,
        _third_party_plugins_disabled(root=root),
        _configured_disabled_analyzers(root=root),
        tuple(
            sorted(
                (
                    key,
                    bool(value.get("enabled", True)),
                )
                for key, value in configured_tables.items()
            )
        ),
        (
            _entry_points_for_group,
            _builtin_analyzer_plugins,
            _builtin_backend_plugins,
            _builtin_embedding_engine_plugins,
            _builtin_vector_store_plugins,
        ),
    )
    return list(resolved), list(registrations)


@lru_cache(maxsize=4)
def _cached_plugin_snapshot(
    family: PluginFamily,
    third_party_disabled: bool,
    disabled_analyzers: tuple[str, ...],
    configured_enabled_plugins: tuple[tuple[str, bool], ...],
    cache_tokens: tuple[object, object, object, object, object],
) -> tuple[tuple[_LoadedPlugin, ...], tuple[PluginRegistration, ...]]:
    """
    Cache the resolved plugin snapshot for one family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    third_party_disabled : bool
        Whether third-party entry points are disabled for this snapshot.
    disabled_analyzers : tuple[str, ...]
        Analyzer names disabled by effective configuration.
    configured_enabled_plugins : tuple[tuple[str, bool], ...]
        Enabled-state cache key for namespaced plugin config tables.
    cache_tokens : tuple[object, object, object]
        Cache tokens for plugin discovery wrappers so monkeypatched discovery
        functions invalidate cached snapshots deterministically.

    Returns
    -------
    tuple[
        tuple[codira.registry._LoadedPlugin, ...],
        tuple[codira.registry.PluginRegistration, ...],
    ]
        Immutable resolved plugins plus diagnostic registrations.
    """
    del cache_tokens
    if family == "analyzer":
        builtins = _builtin_analyzer_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="analyzer",
            group=ANALYZER_ENTRY_POINT_GROUP,
            third_party_disabled=third_party_disabled,
        )
    elif family == "backend":
        builtins = _builtin_backend_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="backend",
            group=BACKEND_ENTRY_POINT_GROUP,
            third_party_disabled=third_party_disabled,
        )
    elif family == "embedding":
        builtins = _builtin_embedding_engine_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="embedding",
            group=EMBEDDING_ENGINE_ENTRY_POINT_GROUP,
            third_party_disabled=third_party_disabled,
        )
    else:
        builtins = _builtin_vector_store_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="vector-store",
            group=VECTOR_STORE_ENTRY_POINT_GROUP,
            third_party_disabled=third_party_disabled,
        )

    resolved, registrations = _resolve_plugins(
        builtins,
        externals,
        external_registrations,
    )
    if family == "analyzer":
        resolved, registrations = _apply_disabled_analyzer_config(
            resolved,
            registrations,
            disabled_analyzers,
        )
        resolved.sort(
            key=lambda plugin: (
                PREFERRED_ANALYZER_ORDER.get(plugin.name, 1000),
                plugin.name,
                plugin.provider,
                plugin.entry_point or "",
            )
        )
    resolved, registrations = _apply_enabled_plugin_config(
        resolved,
        registrations,
        family=family,
        configured_enabled_plugins=dict(configured_enabled_plugins),
    )
    return tuple(resolved), tuple(registrations)


def _apply_enabled_plugin_config(
    plugins: list[_LoadedPlugin],
    registrations: list[PluginRegistration],
    *,
    family: PluginFamily,
    configured_enabled_plugins: dict[str, bool],
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Remove plugins disabled by namespaced plugin configuration.

    Parameters
    ----------
    plugins : list[codira.registry._LoadedPlugin]
        Resolved plugins for one family.
    registrations : list[codira.registry.PluginRegistration]
        Registration diagnostics to update.
    family : {"analyzer", "backend"}
        Plugin family being filtered.
    configured_enabled_plugins : dict[str, bool]
        Enabled flags keyed by namespaced plugin config table.

    Returns
    -------
    tuple[list[codira.registry._LoadedPlugin], list[codira.registry.PluginRegistration]]
        Filtered plugins and diagnostics with disabled plugins reported as
        skipped.
    """

    disabled = {
        plugin.name
        for plugin in plugins
        if not configured_enabled_plugins.get(
            plugin_config_key(family=family, name=plugin.name),
            True,
        )
    }
    if not disabled:
        return plugins, registrations

    filtered_plugins = [plugin for plugin in plugins if plugin.name not in disabled]
    filtered_registrations: list[PluginRegistration] = []
    for registration in registrations:
        if (
            registration.family == family
            and registration.status == "loaded"
            and registration.name in disabled
        ):
            filtered_registrations.append(
                PluginRegistration(
                    family=registration.family,
                    name=registration.name,
                    provider=registration.provider,
                    source=registration.source,
                    status="skipped",
                    version=registration.version,
                    entry_point=registration.entry_point,
                    detail="plugin is disabled by configuration",
                    origin=registration.origin,
                )
            )
            continue
        filtered_registrations.append(registration)
    return filtered_plugins, filtered_registrations


def _apply_disabled_analyzer_config(
    plugins: list[_LoadedPlugin],
    registrations: list[PluginRegistration],
    disabled_analyzers: tuple[str, ...],
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Remove config-disabled analyzers from a resolved analyzer snapshot.

    Parameters
    ----------
    plugins : list[codira.registry._LoadedPlugin]
        Resolved analyzer plugins.
    registrations : list[codira.registry.PluginRegistration]
        Analyzer registration diagnostics.
    disabled_analyzers : tuple[str, ...]
        Analyzer names disabled by effective configuration.

    Returns
    -------
    tuple[list[codira.registry._LoadedPlugin], list[codira.registry.PluginRegistration]]
        Filtered plugins and diagnostics with disabled analyzers reported as
        skipped.

    Raises
    ------
    ValueError
        If config disables an analyzer name that is not loaded.
    """

    disabled = set(disabled_analyzers)
    if not disabled:
        return plugins, registrations

    available = {plugin.name for plugin in plugins}
    unknown = sorted(disabled - available)
    if unknown:
        available_label = ", ".join(sorted(available))
        unknown_label = ", ".join(unknown)
        msg = (
            "Unsupported disabled analyzer configuration "
            f"{unknown_label!r}. Available analyzers: {available_label}"
        )
        raise ValueError(msg)

    filtered_plugins = [plugin for plugin in plugins if plugin.name not in disabled]
    filtered_registrations: list[PluginRegistration] = []
    for registration in registrations:
        if registration.status == "loaded" and registration.name in disabled:
            filtered_registrations.append(
                PluginRegistration(
                    family=registration.family,
                    name=registration.name,
                    provider=registration.provider,
                    source=registration.source,
                    status="skipped",
                    version=registration.version,
                    entry_point=registration.entry_point,
                    detail="analyzer is disabled by configuration",
                    origin=registration.origin,
                )
            )
            continue
        filtered_registrations.append(registration)
    return filtered_plugins, filtered_registrations


def reset_plugin_registry_caches() -> None:
    """
    Clear cached plugin discovery state.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Entry-point discovery and resolved plugin snapshots are reloaded on the
        next registry access.
    """
    _cached_entry_points_for_group.cache_clear()
    _cached_plugin_snapshot.cache_clear()


def plugin_registrations(*, root: Path | None = None) -> list[PluginRegistration]:
    """
    Return deterministic plugin registration diagnostics.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        diagnostics.

    Returns
    -------
    list[codira.registry.PluginRegistration]
        Built-in and external plugin registrations for all plugin families.
    """
    analyzer_plugins, analyzer_registrations = _plugin_snapshot("analyzer", root=root)
    backend_plugins, backend_registrations = _plugin_snapshot("backend", root=root)
    embedding_plugins, embedding_registrations = _plugin_snapshot(
        "embedding",
        root=root,
    )
    vector_plugins, vector_registrations = _plugin_snapshot("vector-store", root=root)
    del analyzer_plugins, backend_plugins, embedding_plugins, vector_plugins
    return (
        analyzer_registrations
        + backend_registrations
        + embedding_registrations
        + vector_registrations
    )


def validate_plugin_configuration(
    *,
    root: Path | None = None,
) -> list[PluginConfigWarning]:
    """
    Validate configured plugin tables against discovered plugin contracts.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should be validated.

    Returns
    -------
    list[codira.registry.PluginConfigWarning]
        Non-fatal warnings for configuration tables that cannot be applied
        because the plugin is unavailable or does not expose configuration
        support.

    Raises
    ------
    ConfigError
        If a loaded plugin schema rejects its table or the active backend is
        disabled by configuration.
    """

    warnings: list[PluginConfigWarning] = []
    config = load_effective_config(root=root)
    configured_tables = _configured_plugin_tables(root=root)
    analyzer_plugins, analyzer_registrations = _plugin_snapshot("analyzer", root=root)
    backend_plugins, backend_registrations = _plugin_snapshot("backend", root=root)
    embedding_plugins, embedding_registrations = _plugin_snapshot(
        "embedding",
        root=root,
    )
    vector_plugins, vector_registrations = _plugin_snapshot("vector-store", root=root)
    all_plugins = {
        plugin_config_key(family=plugin.family, name=plugin.name): plugin
        for plugin in [
            *analyzer_plugins,
            *backend_plugins,
            *embedding_plugins,
            *vector_plugins,
        ]
    }
    loaded_before_enabled = {
        plugin_config_key(family=registration.family, name=registration.name)
        for registration in [
            *analyzer_registrations,
            *backend_registrations,
            *embedding_registrations,
            *vector_registrations,
        ]
        if registration.status in {"loaded", "skipped"}
    }

    for key in sorted(configured_tables):
        plugin = all_plugins.get(key)
        if plugin is None:
            if key in loaded_before_enabled:
                continue
            warnings.append(
                PluginConfigWarning(
                    key=key,
                    reason="configured plugin is not loaded",
                )
            )
            continue
        instance = plugin.factory()
        _validate_plugin_config_schema(
            key=key,
            instance=instance,
            config=configured_tables[key],
        )
        if not isinstance(instance, ConfigurablePlugin) and len(
            configured_tables[key]
        ) > int("enabled" in configured_tables[key]):
            warnings.append(
                PluginConfigWarning(
                    key=key,
                    reason="configured plugin does not expose configure()",
                )
            )

    configured_backend = config.backend.name.strip() or DEFAULT_INDEX_BACKEND
    backend_config_key = plugin_config_key(family="backend", name=configured_backend)
    if backend_config_key in configured_tables and not plugin_enabled(
        configured_tables[backend_config_key]
    ):
        msg = (
            f"Configured backend '{configured_backend}' is disabled by "
            f"plugins.{backend_config_key}."
        )
        raise ConfigError(msg)

    configured_engine = config.embeddings.engine.strip()
    engine_config_key = plugin_config_key(family="embedding", name=configured_engine)
    if engine_config_key in configured_tables and not plugin_enabled(
        configured_tables[engine_config_key]
    ):
        msg = (
            f"Configured embedding engine '{configured_engine}' is disabled by "
            f"plugins.{engine_config_key}."
        )
        raise ConfigError(msg)

    configured_vector_store = config.embeddings.vector_store.strip()
    vector_store_config_key = plugin_config_key(
        family="vector-store",
        name=configured_vector_store,
    )
    if vector_store_config_key in configured_tables and not plugin_enabled(
        configured_tables[vector_store_config_key]
    ):
        msg = (
            f"Configured vector store '{configured_vector_store}' is disabled by "
            f"plugins.{vector_store_config_key}."
        )
        raise ConfigError(msg)

    return warnings


def missing_language_analyzer_hint(path: Path) -> str | None:
    """
    Return an installation hint when a path targets an unavailable analyzer.

    Parameters
    ----------
    path : pathlib.Path
        Repository file whose suffix can imply an optional analyzer.

    Returns
    -------
    str | None
        Deterministic installation hint, or ``None`` when no optional analyzer
        applies.
    """
    suffix = path.suffix.lower()
    analyzer_names = {plugin.name for plugin in _plugin_snapshot("analyzer")[0]}

    if suffix == ".py" and "python" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["python"]
        return (
            "Python indexing support now ships through the first-party "
            f"`{package_name}` package. Install that package to enable `*.py` "
            "files, or use `codira[bundle-official]` when the curated "
            "bundle is available."
        )

    if suffix == ".json" and "json" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["json"]
        if path.name == "package.json":
            return (
                "Structured JSON indexing now ships through the first-party "
                f"`{package_name}` package. Install that package to enable "
                "`package.json` manifests, or use `codira[bundle-official]` "
                "when the curated bundle is available."
            )
        if path.name == ".releaserc.json" or (
            path.parent.name == "schema" or "schema" in path.stem.lower()
        ):
            return (
                "Structured JSON indexing now ships through the first-party "
                f"`{package_name}` package. Install that package to enable "
                "supported JSON Schema and release-config files, or use "
                "`codira[bundle-official]` when the curated bundle is "
                "available."
            )

    if suffix in {".c", ".h"} and "c" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["c"]
        return (
            "C-family indexing support is optional. "
            f"Install `{package_name}` to enable `*.c` and `*.h` files, or use "
            "`codira[bundle-official]` when the curated bundle is available."
        )

    if (
        suffix in {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp"}
        and "cpp" not in analyzer_names
    ):
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["cpp"]
        return (
            "C++ indexing support is optional. "
            f"Install `{package_name}` to enable standard C++ source and header "
            "files, or use `codira[bundle-official]` when the curated bundle is "
            "available."
        )

    if suffix in {".sh", ".bash"} and "bash" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["bash"]
        return (
            "Shell indexing support is optional. "
            f"Install `{package_name}` to enable `*.sh` and `*.bash` files, or "
            "use `codira[bundle-official]` when the curated bundle is available."
        )

    if suffix == ".md" and "markdown" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["markdown"]
        return (
            "Markdown documentation indexing support ships through the "
            f"first-party `{package_name}` package. Install that package to "
            "enable `*.md` files, or use `codira[bundle-official]` when the "
            "curated bundle is available."
        )

    if suffix == ".txt" and "text" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["text"]
        return (
            "Plain-text documentation indexing support ships through the "
            f"first-party `{package_name}` package. Install that package to "
            "enable documentation-scoped `*.txt` files, or use "
            "`codira[bundle-official]` when the curated bundle is available."
        )

    return None


def configured_index_backend_name(*, root: Path | None = None) -> str:
    """
    Return the configured backend name for the current process.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in backend
        selection.

    Returns
    -------
    str
        Configured backend name, defaulting to ``"sqlite"``.

    Notes
    -----
    The default is a backend selection policy for compatibility. It does not
    make core own SQLite schema, connection, or query behavior.
    """
    configured_name = load_effective_config(root=root).backend.name.strip()
    if configured_name:
        return configured_name
    return DEFAULT_INDEX_BACKEND


def active_index_backend(*, root: Path | None = None) -> IndexBackend:
    """
    Instantiate the configured index backend.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in backend
        selection.

    Returns
    -------
    codira.contracts.IndexBackend
        Active backend implementation for indexing and querying.

    Raises
    ------
    ValueError
        If the configured backend name is not registered.
    """
    configured_name = configured_index_backend_name(root=root)
    plugins, _registrations = _plugin_snapshot("backend", root=root)
    registry = {
        plugin.name: cast("Callable[[], IndexBackend]", plugin.factory)
        for plugin in plugins
    }
    factory = registry.get(configured_name)

    if factory is None:
        available = ", ".join(sorted(registry))
        package_hint = ""
        if configured_name in OPTIONAL_BACKEND_PACKAGE_BY_NAME:
            package_name = OPTIONAL_BACKEND_PACKAGE_BY_NAME[configured_name]
            package_hint = (
                " Install the first-party "
                f"`{package_name}` package, or use "
                "`codira-bundle-official` when the curated bundle is available."
            )
        msg = (
            f"Unsupported codira backend '{configured_name}'. "
            f"Available backends: {available}"
            f"{package_hint}"
        )
        raise ValueError(msg)

    instance = factory()
    plugin = next(item for item in plugins if item.name == configured_name)
    return cast(
        "IndexBackend",
        _configure_plugin_instance(plugin=plugin, instance=instance, root=root),
    )


def _instantiate_language_analyzers(
    analyzer_plugins: Sequence[_LoadedPlugin],
    *,
    root: Path | None = None,
) -> list[LanguageAnalyzer]:
    """
    Instantiate registered analyzers in deterministic routing order.

    Parameters
    ----------
    analyzer_plugins : collections.abc.Sequence[codira.registry._LoadedPlugin]
        Analyzer plugins in deterministic routing order.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should configure analyzers.

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Instantiated analyzers in the same order as the supplied factories.

    Raises
    ------
    ValueError
        If no analyzers are registered.
    """
    analyzers = [
        cast(
            "LanguageAnalyzer",
            _configure_plugin_instance(
                plugin=plugin,
                instance=plugin.factory(),
                root=root,
            ),
        )
        for plugin in analyzer_plugins
    ]
    if analyzers:
        return analyzers

    msg = "No language analyzers are registered for codira"
    raise ValueError(msg)


def active_language_analyzers(*, root: Path | None = None) -> list[LanguageAnalyzer]:
    """
    Instantiate the active language analyzers for one indexing run.

    Parameters
    ----------
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in analyzer
        selection and configuration.

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Active analyzers in deterministic first-match routing order.
    """
    plugins, _registrations = _plugin_snapshot("analyzer", root=root)
    return _instantiate_language_analyzers(plugins, root=root)
