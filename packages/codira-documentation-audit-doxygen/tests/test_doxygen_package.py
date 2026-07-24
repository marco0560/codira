"""Package-local tests for the Doxygen documentation audit distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_documentation_audit_doxygen import (
    DoxygenDocumentationAuditPlugin,
    build_audit_plugin,
)


def test_doxygen_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the documentation-audit entry point.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected factory.
    """

    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.55.0"
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
    assert project["project"]["entry-points"]["codira.documentation_audits"] == {
        "doxygen": "codira_documentation_audit_doxygen:build_audit_plugin"
    }


def test_doxygen_package_builds_expected_plugin() -> None:
    """
    Keep the package-local factory aligned to the published plugin name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected plugin type and name.
    """

    plugin = build_audit_plugin()

    assert isinstance(plugin, DoxygenDocumentationAuditPlugin)
    assert plugin.name == "doxygen"
