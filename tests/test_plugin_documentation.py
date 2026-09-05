"""Tests for the plugin-development documentation inventory.

Responsibilities
----------------
- Keep the primary plugin landing page synchronized with public entry points.
- Make every registry-supported extension family discoverable to plugin authors.

Design principles
-----------------
The landing page is a developer entry point, so its advertised groups must not
fall behind the packaging guide or the registry's runtime contract.

Architectural role
------------------
This module belongs to the documentation verification layer guarding the
third-party plugin discovery contract.
"""

from __future__ import annotations

import re
from pathlib import Path

from codira.registry import (
    ANALYZER_ENTRY_POINT_GROUP,
    BACKEND_ENTRY_POINT_GROUP,
    DOCUMENTATION_AUDIT_ENTRY_POINT_GROUP,
    EMBEDDING_ENGINE_ENTRY_POINT_GROUP,
    SIMILARITY_INDEX_ENTRY_POINT_GROUP,
    VECTOR_STORE_ENTRY_POINT_GROUP,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_INDEX = REPO_ROOT / "docs" / "plugins" / "index.md"
PACKAGING_GUIDE = REPO_ROOT / "docs" / "plugins" / "packaging.md"


def _entry_point_groups(path: Path) -> frozenset[str]:
    """Extract listed Codira entry-point groups from one Markdown document.

    Parameters
    ----------
    path : pathlib.Path
        Markdown document containing backtick-delimited list items.

    Returns
    -------
    frozenset[str]
        The declared ``codira.*`` entry-point group names.
    """
    return frozenset(
        re.findall(
            r"`(codira\.[a-z_]+)`",
            path.read_text(encoding="utf-8"),
        )
    )


def test_plugin_landing_page_lists_every_supported_entry_point_group() -> None:
    """Keep the plugin landing page aligned with packaging and registry groups.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts every public plugin family is listed identically.
    """
    registry_groups = frozenset(
        {
            ANALYZER_ENTRY_POINT_GROUP,
            BACKEND_ENTRY_POINT_GROUP,
            EMBEDDING_ENGINE_ENTRY_POINT_GROUP,
            VECTOR_STORE_ENTRY_POINT_GROUP,
            SIMILARITY_INDEX_ENTRY_POINT_GROUP,
            DOCUMENTATION_AUDIT_ENTRY_POINT_GROUP,
        }
    )

    assert "six extension families" in PLUGIN_INDEX.read_text(encoding="utf-8")
    assert _entry_point_groups(PLUGIN_INDEX) == registry_groups
    assert _entry_point_groups(PACKAGING_GUIDE) == registry_groups
