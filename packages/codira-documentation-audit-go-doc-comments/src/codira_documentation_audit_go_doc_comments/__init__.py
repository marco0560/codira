"""Go documentation-comment audit plugin distribution for Codira."""

from codira.docstring import GoDocCommentsDocumentationAuditPlugin

__all__ = ["GoDocCommentsDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> GoDocCommentsDocumentationAuditPlugin:
    """Build a stateless Go documentation-comment audit plugin.

    Returns
    -------
    codira.docstring.GoDocCommentsDocumentationAuditPlugin
        Fresh Go documentation-comment audit plugin.
    """
    return GoDocCommentsDocumentationAuditPlugin()
