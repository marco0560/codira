"""Deterministic TOML rendering helpers for Codira configuration.

Responsibilities
----------------
- Render complete configuration mappings as stable TOML.
- Preserve plugin-table order and default-value comments.

Architectural role
------------------
This module is pure serialization policy. Profile construction and filesystem
writes remain in :mod:`codira.config`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import tomlkit

from codira.config_models import (
    _PLUGIN_CONFIG_RESERVED_KEYS,
    PLUGIN_CONFIG_RENDER_ORDER,
)
from codira.config_validation import _require_table


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


def _ordered_plugin_config_keys(plugins: Mapping[str, object]) -> tuple[str, ...]:
    """
    Return plugin table keys in generated config display order.

    Parameters
    ----------
    plugins : collections.abc.Mapping[str, object]
        Plugins mapping from a config payload.

    Returns
    -------
    tuple[str, ...]
        Plugin-specific table keys with first-party families first and unknown
        plugin keys sorted afterward.
    """

    configured = {key for key in plugins if key not in _PLUGIN_CONFIG_RESERVED_KEYS}
    ordered = [key for key in PLUGIN_CONFIG_RENDER_ORDER if key in configured]
    ordered.extend(sorted(configured.difference(ordered)))
    return tuple(ordered)


def _plugin_globals_table(plugins: Mapping[str, object]) -> dict[str, object]:
    """
    Return only global plugin settings from a plugins mapping.

    Parameters
    ----------
    plugins : collections.abc.Mapping[str, object]
        Plugins mapping from a config payload.

    Returns
    -------
    dict[str, object]
        Reserved global plugin keys in their original order.
    """

    return {key: plugins[key] for key in plugins if key in _PLUGIN_CONFIG_RESERVED_KEYS}


def _plugin_config_sections(plugins: Mapping[str, object]) -> str:
    """
    Render plugin-specific config sections.

    Parameters
    ----------
    plugins : collections.abc.Mapping[str, object]
        Plugins mapping from a config payload.

    Returns
    -------
    str
        TOML section text for plugin-specific configuration tables.
    """

    sections: list[str] = []
    for key in _ordered_plugin_config_keys(plugins):
        section = _require_table(plugins[key], key=f"plugins.{key}")
        body = tomlkit.dumps(_toml_table_from_mapping(section)).strip()
        sections.append(f"[plugins.{key}]\n{body}" if body else f"[plugins.{key}]")
    return "\n\n".join(sections)


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
    backend = _require_table(value["backend"], key="backend")
    plugins = _require_table(value["plugins"], key="plugins")
    embeddings = _require_table(value["embeddings"], key="embeddings")
    index = _require_table(value["index"], key="index")
    daemon = _require_table(value["daemon"], key="daemon")
    query_daemon = _require_table(value["query_daemon"], key="query_daemon")
    document.add("backend", _toml_table_from_mapping(backend))
    document.add("plugins", _toml_table_from_mapping(_plugin_globals_table(plugins)))
    document.add("embeddings", _toml_table_from_mapping(embeddings))
    document.add("index", _toml_table_from_mapping(index))
    document.add("daemon", _toml_table_from_mapping(daemon))
    document.add("query_daemon", _toml_table_from_mapping(query_daemon))
    text = tomlkit.dumps(document).rstrip()
    plugin_sections = _plugin_config_sections(plugins)
    if plugin_sections:
        text = f"{text}\n\n{plugin_sections}"
    text += "\n"
    return text


def _value_at_path(value: Mapping[str, object], path: tuple[str, ...]) -> object:
    """
    Return one nested mapping value by path.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Root mapping to inspect.
    path : tuple[str, ...]
        Nested key path.

    Returns
    -------
    object
        Nested value, or ``None`` when the path is not present.
    """

    current: object = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _comment_default_config_values(
    text: str,
    *,
    value: Mapping[str, object],
    defaults: Mapping[str, object],
) -> str:
    """
    Comment TOML assignment lines whose value matches the default profile.

    Parameters
    ----------
    text : str
        Rendered TOML text.
    value : collections.abc.Mapping[str, object]
        Generated profile mapping.
    defaults : collections.abc.Mapping[str, object]
        Default profile mapping used as the comparison baseline.

    Returns
    -------
    str
        TOML text with default-valued assignment lines prefixed by ``#``.
    """

    current_section: tuple[str, ...] = ()
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = tuple(stripped.strip("[]").split("."))
            lines.append(line)
            continue
        if "=" not in line or stripped.startswith("#"):
            lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        path = (*current_section, key)
        if _value_at_path(value, path) == _value_at_path(defaults, path):
            lines.append(f"# {line}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


__all__ = ("render_config_toml",)
