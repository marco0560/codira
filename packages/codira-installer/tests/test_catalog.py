"""Tests for the data-only packaged installer catalog."""

from __future__ import annotations

import sys
from typing import cast

from codira_installer.catalog import load_catalog


def test_catalog_load_requires_no_textual_or_plugin_imports() -> None:
    """Keep catalog loading independent from runtime UI and plugin imports.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts generated package metadata loads as data only.
    """
    modules_before = set(sys.modules)
    catalog = load_catalog()

    assert catalog["coordinated_version"] == "2.0.0"
    packages = cast("list[dict[str, object]]", catalog["packages"])
    package = next(
        row for row in packages if row["name"] == "codira-similarity-index-faiss"
    )
    assert package["family"] == "similarity-index"
    assert package["selectable"] is True
    schema = cast("dict[str, object]", package["configuration_schema"])
    properties = cast("dict[str, dict[str, object]]", schema["properties"])
    assert properties["index_type"]["default"] == "flat"
    assert properties["M"]["minimum"] == 1
    assert properties["efConstruction"]["minimum"] == 1
    imported_modules = set(sys.modules) - modules_before
    assert "textual" not in imported_modules
    assert not any(name.startswith("codira_analyzer_") for name in imported_modules)
