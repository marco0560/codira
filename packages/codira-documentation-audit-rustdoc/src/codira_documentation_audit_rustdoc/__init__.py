"""Rustdoc documentation audit plugin distribution for Codira."""

from __future__ import annotations

from codira.docstring import RustdocDocumentationAuditPlugin

__all__ = ["RustdocDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> RustdocDocumentationAuditPlugin:
    """Build the Rustdoc documentation audit plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.docstring.RustdocDocumentationAuditPlugin
        Stateless Rustdoc documentation audit plugin instance.
    """
    return RustdocDocumentationAuditPlugin()
