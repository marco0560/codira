"""TSDoc documentation audit plugin distribution for Codira."""

from codira.docstring import TSDocDocumentationAuditPlugin

__all__ = ["TSDocDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> TSDocDocumentationAuditPlugin:
    """Build a fresh stateless TSDoc audit plugin.

    Returns
    -------
    codira.docstring.TSDocDocumentationAuditPlugin
        TSDoc audit plugin instance.
    """
    return TSDocDocumentationAuditPlugin()
