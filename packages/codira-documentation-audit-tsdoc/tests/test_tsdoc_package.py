"""Contract tests for the first-party TSDoc audit package."""

from pathlib import Path

from codira.contracts import DocumentationAuditRequest
from codira_documentation_audit_tsdoc import build_audit_plugin


def test_tsdoc_plugin_reports_missing_required_tags(tmp_path: Path) -> None:
    """Report stable TSDoc diagnostics from analyzer-emitted documentation."""
    result = build_audit_plugin().audit_documentation(
        DocumentationAuditRequest(
            source_path=tmp_path / "widget.ts",
            language="typescript",
            convention="tsdoc",
            artifact_kind="function",
            symbol_name="build",
            stable_id="typescript:function:widget:build",
            doc="Build a widget.\n@param name Widget name.",
            parameters=("name", "options"),
            require_callable_sections=True,
            returns_value=True,
            raises_exception=True,
        )
    )
    assert [item.code for item in result.diagnostics] == [
        "missing_tsdoc_param",
        "missing_tsdoc_returns",
        "missing_tsdoc_throws",
    ]
