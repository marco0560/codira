"""Shared helpers for plugin configuration contracts.

Responsibilities
----------------
- Provide reusable JSON Schema fragments for first-party plugin configuration.
- Normalize common analyzer include/exclude path filters.
- Evaluate repo-relative analyzer path filters deterministically.

Architectural role
------------------
This module belongs to the plugin configuration support layer. It is imported
by plugin packages but does not discover or instantiate plugins.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


@dataclass(frozen=True)
class AnalyzerPathFilters:
    """
    Normalized analyzer include/exclude filters.

    Parameters
    ----------
    include_paths : tuple[str, ...]
        Repo-relative paths that should be included. Empty means include all
        otherwise-supported paths.
    exclude_paths : tuple[str, ...]
        Repo-relative paths that should be excluded. Excludes take precedence
        over includes.
    """

    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


def plugin_enabled(config: Mapping[str, object]) -> bool:
    """
    Return the common plugin enabled flag.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.

    Returns
    -------
    bool
        ``False`` only when the table explicitly sets ``enabled = false``.
    """

    enabled = config.get("enabled", True)
    if isinstance(enabled, bool):
        return enabled
    return True


def plugin_configuration_fingerprint(config: Mapping[str, object]) -> str:
    """
    Return a stable fingerprint for one plugin configuration table.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration table.

    Returns
    -------
    str
        Short deterministic SHA-256 fingerprint.
    """

    payload = json.dumps(dict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def plugin_base_schema() -> dict[str, object]:
    """
    Return the shared plugin JSON Schema properties.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Schema fragment containing common plugin keys.
    """

    return {
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether this plugin participates in runtime discovery.",
        }
    }


def analyzer_path_filter_schema() -> dict[str, object]:
    """
    Return the shared analyzer path-filter JSON Schema properties.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Schema fragment containing ``include_paths`` and ``exclude_paths``.
    """

    path_items = {
        "type": "string",
        "minLength": 1,
        "pattern": r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+",
    }
    return {
        "include_paths": {
            "type": "array",
            "items": path_items,
            "default": [],
        },
        "exclude_paths": {
            "type": "array",
            "items": path_items,
            "default": [],
        },
    }


def plugin_json_schema(properties: Mapping[str, object]) -> dict[str, object]:
    """
    Build a strict plugin configuration JSON Schema.

    Parameters
    ----------
    properties : collections.abc.Mapping[str, object]
        Plugin-specific schema properties.

    Returns
    -------
    dict[str, object]
        Strict object schema with common ``enabled`` support.
    """

    merged = plugin_base_schema()
    merged.update(dict(properties))
    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "type": "object",
        "additionalProperties": False,
        "properties": merged,
    }


def analyzer_json_schema(properties: Mapping[str, object]) -> dict[str, object]:
    """
    Build a strict analyzer plugin configuration JSON Schema.

    Parameters
    ----------
    properties : collections.abc.Mapping[str, object]
        Analyzer-specific schema properties.

    Returns
    -------
    dict[str, object]
        Strict object schema with common analyzer path filters.
    """

    merged = analyzer_path_filter_schema()
    merged.update(dict(properties))
    return plugin_json_schema(merged)


def _normalize_filter_path(raw_path: object, *, key: str) -> str:
    """
    Normalize one repo-relative POSIX filter path.

    Parameters
    ----------
    raw_path : object
        Candidate path value from plugin configuration.
    key : str
        Configuration key used in validation messages.

    Returns
    -------
    str
        Normalized repo-relative POSIX path.

    Raises
    ------
    ValueError
        If the path is empty, absolute, or escapes the repository.
    """

    if not isinstance(raw_path, str) or not raw_path.strip():
        msg = f"Configuration key {key} must contain non-empty strings."
        raise ValueError(msg)
    normalized = raw_path.strip().replace("\\", "/").strip("/")
    path = PurePosixPath(normalized)
    if raw_path.startswith("/") or path.is_absolute():
        msg = f"Configuration key {key} must contain repo-relative paths."
        raise ValueError(msg)
    if any(part == ".." for part in path.parts):
        msg = f"Configuration key {key} must not contain '..' path segments."
        raise ValueError(msg)
    if not normalized or normalized == ".":
        msg = f"Configuration key {key} must contain non-empty paths."
        raise ValueError(msg)
    return path.as_posix()


def _normalize_filter_paths(values: object, *, key: str) -> tuple[str, ...]:
    """
    Normalize one path-filter list.

    Parameters
    ----------
    values : object
        Candidate list from plugin configuration.
    key : str
        Configuration key used in validation messages.

    Returns
    -------
    tuple[str, ...]
        Deterministically ordered normalized paths.

    Raises
    ------
    ValueError
        If the value is not a list of valid path strings.
    """

    if values is None:
        return ()
    if not isinstance(values, list):
        msg = f"Configuration key {key} must be a list."
        raise TypeError(msg)
    normalized = [_normalize_filter_path(item, key=key) for item in values]
    return tuple(dict.fromkeys(normalized))


def analyzer_path_filters_from_config(
    config: Mapping[str, object],
) -> AnalyzerPathFilters:
    """
    Build normalized analyzer path filters from plugin configuration.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Analyzer plugin configuration table.

    Returns
    -------
    AnalyzerPathFilters
        Normalized include/exclude path filters.
    """

    return AnalyzerPathFilters(
        include_paths=_normalize_filter_paths(
            config.get("include_paths"),
            key="include_paths",
        ),
        exclude_paths=_normalize_filter_paths(
            config.get("exclude_paths"),
            key="exclude_paths",
        ),
    )


def _path_matches_filter(rel_path: str, filter_path: str) -> bool:
    """
    Return whether one repo-relative path matches one filter path.

    Parameters
    ----------
    rel_path : str
        Candidate repo-relative path.
    filter_path : str
        Normalized filter path.

    Returns
    -------
    bool
        ``True`` for exact file matches or recursive directory matches.
    """

    return rel_path == filter_path or rel_path.startswith(f"{filter_path}/")


def analyzer_path_allowed(
    *,
    path: Path,
    root: Path,
    filters: AnalyzerPathFilters,
) -> bool:
    """
    Evaluate analyzer include/exclude path filters for one path.

    Parameters
    ----------
    path : object
        Candidate path, expected to be ``pathlib.Path`` compatible.
    root : object
        Repository root, expected to be ``pathlib.Path`` compatible.
    filters : AnalyzerPathFilters
        Normalized include/exclude filters.

    Returns
    -------
    bool
        ``True`` when the path is allowed after include/exclude evaluation.
    """

    try:
        rel_path = path.relative_to(root).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    if filters.exclude_paths and any(
        _path_matches_filter(rel_path, item) for item in filters.exclude_paths
    ):
        return False
    if filters.include_paths:
        return any(
            _path_matches_filter(rel_path, item) for item in filters.include_paths
        )
    return True


def boolean_property(default: bool) -> dict[str, object]:
    """
    Return a boolean JSON Schema property with one default value.

    Parameters
    ----------
    default : bool
        Default property value.

    Returns
    -------
    dict[str, object]
        Boolean property schema.
    """

    return {"type": "boolean", "default": default}


def string_enum_array_property(values: Iterable[str]) -> dict[str, object]:
    """
    Return a string-enum array JSON Schema property.

    Parameters
    ----------
    values : collections.abc.Iterable[str]
        Accepted string values.

    Returns
    -------
    dict[str, object]
        Array property schema.
    """

    accepted = tuple(values)
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(accepted)},
        "default": list(accepted),
    }
