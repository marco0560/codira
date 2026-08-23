"""JSDoc documentation audit plugin distribution for Codira."""

from __future__ import annotations

from codira.docstring import JSDocDocumentationAuditPlugin

__all__ = ["JSDocDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> JSDocDocumentationAuditPlugin:
    """Build the stateless JSDoc documentation audit plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.docstring.JSDocDocumentationAuditPlugin
        Fresh JSDoc audit plugin instance.
    """
    return JSDocDocumentationAuditPlugin()
