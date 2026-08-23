"""Contract tests for the first-party Go documentation audit package."""

from pathlib import Path

from codira.contracts import DocumentationAuditRequest
from codira_documentation_audit_go_doc_comments import (
    GoDocCommentsDocumentationAuditPlugin,
    build_audit_plugin,
)


def test_go_doc_comment_audit_requires_symbol_prefix(tmp_path: Path) -> None:
    """Report the Go declaration-name convention deterministically.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source location.

    Returns
    -------
    None
        The stable convention diagnostic is asserted.
    """
    result = build_audit_plugin().audit_documentation(
        DocumentationAuditRequest(
            source_path=tmp_path / "example.go",
            language="go",
            convention="go_doc_comment",
            artifact_kind="function",
            symbol_name="Build",
            stable_id="go:function:example.go:Build",
            doc="Creates a value.",
            parameters=(),
            require_callable_sections=False,
            returns_value=False,
            raises_exception=False,
        )
    )
    assert isinstance(build_audit_plugin(), GoDocCommentsDocumentationAuditPlugin)
    assert [item.code for item in result.diagnostics] == ["go_doc_comment_name"]
