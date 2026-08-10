"""Tests for the data-only packaged installer catalog."""

from __future__ import annotations

import sys

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

    assert catalog["coordinated_version"] == "1.55.0"
    imported_modules = set(sys.modules) - modules_before
    assert "textual" not in imported_modules
    assert not any(name.startswith("codira_analyzer_") for name in imported_modules)
