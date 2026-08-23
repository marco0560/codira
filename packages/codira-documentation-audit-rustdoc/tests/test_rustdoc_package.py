"""Package-local tests for the Rustdoc documentation audit distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_documentation_audit_rustdoc import (
    RustdocDocumentationAuditPlugin,
    build_audit_plugin,
)
from codira.contracts import DocumentationAuditRequest


def test_rustdoc_package_declares_expected_entry_point() -> None:
    """Keep Rustdoc package metadata aligned with plugin discovery.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The version, dependency, and Rustdoc entry point are asserted.
    """
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.55.0"
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
    assert project["project"]["entry-points"]["codira.documentation_audits"] == {
        "rustdoc": "codira_documentation_audit_rustdoc:build_audit_plugin"
    }


def test_rustdoc_plugin_reports_missing_documentation(tmp_path: Path) -> None:
    """Validate the bounded Rustdoc audit contract.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source location used by the typed audit request.

    Returns
    -------
    None
        Missing public Rustdocs receive a convention-specific diagnostic.
    """
    plugin = build_audit_plugin()
    result = plugin.audit_documentation(
        DocumentationAuditRequest(
            source_path=tmp_path / "src" / "lib.rs",
            language="rust",
            convention="rustdoc",
            artifact_kind="function",
            symbol_name="run",
            stable_id="rust:function:src/lib.rs:run",
            doc=None,
        )
    )

    assert isinstance(plugin, RustdocDocumentationAuditPlugin)
    assert plugin.name == "rustdoc"
    assert [item.code for item in result.diagnostics] == ["missing_rustdoc"]
