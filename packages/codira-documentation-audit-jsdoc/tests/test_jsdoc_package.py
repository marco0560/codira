"""Contract tests for the first-party JSDoc audit package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira.contracts import DocumentationAuditRequest
from codira_documentation_audit_jsdoc import (
    JSDocDocumentationAuditPlugin,
    build_audit_plugin,
)


def test_jsdoc_package_declares_expected_entry_point() -> None:
    """Keep package metadata aligned to routed plugin discovery.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Version, dependency, and entry point are asserted.
    """
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert project["project"]["version"] == "2.0.0"
    assert project["project"]["dependencies"] == ["codira>=2.0.0,<3.0.0"]
    assert project["project"]["entry-points"]["codira.documentation_audits"] == {
        "jsdoc": "codira_documentation_audit_jsdoc:build_audit_plugin"
    }


def test_jsdoc_plugin_reports_missing_required_tags(tmp_path: Path) -> None:
    """Audit missing JSDoc fields without source parsing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source location for the typed audit request.

    Returns
    -------
    None
        Missing parameter, return, and throw tags have stable codes.
    """
    plugin = build_audit_plugin()
    result = plugin.audit_documentation(
        DocumentationAuditRequest(
            source_path=tmp_path / "src" / "widget.js",
            language="javascript",
            convention="jsdoc",
            artifact_kind="function",
            symbol_name="build",
            stable_id="javascript:function:src/widget.js:build",
            doc="Build a widget.\n@param {string} name Name.",
            parameters=("name", "options"),
            require_callable_sections=True,
            returns_value=True,
            raises_exception=True,
        )
    )

    assert isinstance(plugin, JSDocDocumentationAuditPlugin)
    assert [item.code for item in result.diagnostics] == [
        "missing_jsdoc_param",
        "missing_jsdoc_returns",
        "missing_jsdoc_throws",
    ]
