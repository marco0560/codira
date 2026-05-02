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

import os
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from typing import TYPE_CHECKING, Literal, cast

from codira.contracts import IndexBackend, LanguageAnalyzer

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

DEFAULT_INDEX_BACKEND = "sqlite"
INDEX_BACKEND_ENV_VAR = "CODIRA_INDEX_BACKEND"
DISABLE_THIRD_PARTY_PLUGINS_ENV_VAR = "CODIRA_DISABLE_THIRD_PARTY_PLUGINS"
ANALYZER_ENTRY_POINT_GROUP = "codira.analyzers"
BACKEND_ENTRY_POINT_GROUP = "codira.backends"
OPTIONAL_BACKEND_PACKAGE_BY_NAME: dict[str, str] = {
    "sqlite": "codira-backend-sqlite",
}
OPTIONAL_ANALYZER_PACKAGE_BY_NAME: dict[str, str] = {
    "python": "codira-analyzer-python",
    "json": "codira-analyzer-json",
    "c": "codira-analyzer-c",
    "bash": "codira-analyzer-bash",
}
PREFERRED_ANALYZER_ORDER: dict[str, int] = {
    "python": 0,
    "json": 5,
    "c": 10,
    "bash": 20,
}
REQUIRED_BACKEND_METHODS: tuple[str, ...] = (
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
PluginFamily = Literal["analyzer", "backend"]
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


def _third_party_plugins_disabled() -> bool:
    """
    Return whether third-party entry-point plugins are disabled.

    Parameters
    ----------
    None

    Returns
    -------
    bool
        ``True`` when ``CODIRA_DISABLE_THIRD_PARTY_PLUGINS`` is set to a
        truthy value.
    """

    value = os.getenv(DISABLE_THIRD_PARTY_PLUGINS_ENV_VAR, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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
        detail=(
            "third-party plugins are disabled by "
            f"{DISABLE_THIRD_PARTY_PLUGINS_ENV_VAR}"
        ),
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


def _registered_language_analyzer_factories() -> (
    tuple[Callable[[], LanguageAnalyzer], ...]
):
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

    if family == "analyzer":
        if not isinstance(instance, LanguageAnalyzer):
            return None, PluginRegistration(
                family=family,
                name=entry_point.name,
                provider=provider,
                source="entry_point",
                status="skipped",
                version="unknown",
                entry_point=entry_point.name,
                detail="factory returned a non-LanguageAnalyzer object",
                origin=_plugin_origin(provider=provider, source="entry_point"),
            )
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
            return None, PluginRegistration(
                family=family,
                name=entry_point.name,
                provider=provider,
                source="entry_point",
                status="skipped",
                version="unknown",
                entry_point=entry_point.name,
                detail="analyzer discovery_globs must be a non-empty tuple[str, ...]",
                origin=_plugin_origin(provider=provider, source="entry_point"),
            )
    else:
        if not isinstance(instance, IndexBackend):
            return None, PluginRegistration(
                family=family,
                name=entry_point.name,
                provider=provider,
                source="entry_point",
                status="skipped",
                version="unknown",
                entry_point=entry_point.name,
                detail="factory returned a non-IndexBackend object",
                origin=_plugin_origin(provider=provider, source="entry_point"),
            )
        missing_methods = [
            method
            for method in REQUIRED_BACKEND_METHODS
            if not callable(getattr(instance, method, None))
        ]
        if missing_methods:
            joined = ", ".join(sorted(missing_methods))
            return None, PluginRegistration(
                family=family,
                name=entry_point.name,
                provider=provider,
                source="entry_point",
                status="skipped",
                version="unknown",
                entry_point=entry_point.name,
                detail=f"backend is missing required methods: {joined}",
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
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Discover entry-point plugins for one extension family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    group : str
        Entry-point group to inspect.

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

    third_party_disabled = _third_party_plugins_disabled()
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
) -> tuple[list[_LoadedPlugin], list[PluginRegistration]]:
    """
    Build the registry snapshot for one plugin family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.

    Returns
    -------
    tuple[
        list[codira.registry._LoadedPlugin],
        list[codira.registry.PluginRegistration],
    ]
        Resolved plugins plus diagnostic registrations.
    """
    resolved, registrations = _cached_plugin_snapshot(
        family,
        _third_party_plugins_disabled(),
        _entry_points_for_group,
        _builtin_analyzer_plugins,
        _builtin_backend_plugins,
    )
    return list(resolved), list(registrations)


@lru_cache(maxsize=4)
def _cached_plugin_snapshot(
    family: PluginFamily,
    third_party_disabled: bool,
    entry_points_loader: object,
    builtin_analyzers_loader: object,
    builtin_backends_loader: object,
) -> tuple[tuple[_LoadedPlugin, ...], tuple[PluginRegistration, ...]]:
    """
    Cache the resolved plugin snapshot for one family.

    Parameters
    ----------
    family : {"analyzer", "backend"}
        Plugin extension family.
    third_party_disabled : bool
        Whether third-party entry points are disabled for this snapshot.
    entry_points_loader : object
        Cache token for the entry-point discovery wrapper so monkeypatched
        discovery functions invalidate cached snapshots deterministically.
    builtin_analyzers_loader : object
        Cache token for built-in analyzer discovery.
    builtin_backends_loader : object
        Cache token for built-in backend discovery.

    Returns
    -------
    tuple[
        tuple[codira.registry._LoadedPlugin, ...],
        tuple[codira.registry.PluginRegistration, ...],
    ]
        Immutable resolved plugins plus diagnostic registrations.
    """
    del (
        third_party_disabled,
        entry_points_loader,
        builtin_analyzers_loader,
        builtin_backends_loader,
    )
    if family == "analyzer":
        builtins = _builtin_analyzer_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="analyzer",
            group=ANALYZER_ENTRY_POINT_GROUP,
        )
    else:
        builtins = _builtin_backend_plugins()
        externals, external_registrations = _discover_entry_point_plugins(
            family="backend",
            group=BACKEND_ENTRY_POINT_GROUP,
        )

    resolved, registrations = _resolve_plugins(
        builtins,
        externals,
        external_registrations,
    )
    if family == "analyzer":
        resolved.sort(
            key=lambda plugin: (
                PREFERRED_ANALYZER_ORDER.get(plugin.name, 1000),
                plugin.name,
                plugin.provider,
                plugin.entry_point or "",
            )
        )
    return tuple(resolved), tuple(registrations)


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


def plugin_registrations() -> list[PluginRegistration]:
    """
    Return deterministic plugin registration diagnostics.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.registry.PluginRegistration]
        Built-in and external plugin registrations for analyzers and backends.
    """
    analyzer_plugins, analyzer_registrations = _plugin_snapshot("analyzer")
    backend_plugins, backend_registrations = _plugin_snapshot("backend")
    del analyzer_plugins, backend_plugins
    return analyzer_registrations + backend_registrations


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

    if suffix in {".sh", ".bash"} and "bash" not in analyzer_names:
        package_name = OPTIONAL_ANALYZER_PACKAGE_BY_NAME["bash"]
        return (
            "Shell indexing support is optional. "
            f"Install `{package_name}` to enable `*.sh` and `*.bash` files, or "
            "use `codira[bundle-official]` when the curated bundle is available."
        )

    return None


def configured_index_backend_name() -> str:
    """
    Return the configured backend name for the current process.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Configured backend name, defaulting to ``"sqlite"``.
    """
    configured_name = os.getenv(INDEX_BACKEND_ENV_VAR, DEFAULT_INDEX_BACKEND).strip()
    if configured_name:
        return configured_name
    return DEFAULT_INDEX_BACKEND


def active_index_backend() -> IndexBackend:
    """
    Instantiate the configured index backend.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.IndexBackend
        Active backend implementation for indexing and querying.

    Raises
    ------
    ValueError
        If the configured backend name is not registered.
    """
    configured_name = configured_index_backend_name()
    plugins, _registrations = _plugin_snapshot("backend")
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

    return factory()


def _instantiate_language_analyzers(
    analyzer_factories: Sequence[Callable[[], LanguageAnalyzer]],
) -> list[LanguageAnalyzer]:
    """
    Instantiate registered analyzers in deterministic routing order.

    Parameters
    ----------
    analyzer_factories : collections.abc.Sequence[Callable[[], LanguageAnalyzer]]
        Analyzer factories in deterministic routing order.

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Instantiated analyzers in the same order as the supplied factories.

    Raises
    ------
    ValueError
        If no analyzers are registered.
    """
    analyzers = [factory() for factory in analyzer_factories]
    if analyzers:
        return analyzers

    msg = "No language analyzers are registered for codira"
    raise ValueError(msg)


def active_language_analyzers() -> list[LanguageAnalyzer]:
    """
    Instantiate the active language analyzers for one indexing run.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.contracts.LanguageAnalyzer]
        Active analyzers in deterministic first-match routing order.
    """
    plugins, _registrations = _plugin_snapshot("analyzer")
    factories = [
        cast("Callable[[], LanguageAnalyzer]", plugin.factory) for plugin in plugins
    ]
    return _instantiate_language_analyzers(factories)
