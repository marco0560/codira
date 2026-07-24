"""Google Python documentation audit plugin distribution for codira.

Responsibilities
----------------
- Re-export the core Google Python documentation audit implementation.
- Provide the package entry-point factory used by the plugin registry.

Design principles
-----------------
The distribution wrapper keeps packaging separate from the shared audit
implementation so core tests and first-party package installs use the same
behavior.

Architectural role
------------------
This module belongs to the documentation-audit plugin package layer.
"""

from __future__ import annotations

from codira.docstring import GooglePythonDocumentationAuditPlugin

__all__ = ["GooglePythonDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> GooglePythonDocumentationAuditPlugin:
    """
    Build the Google Python documentation audit plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.docstring.GooglePythonDocumentationAuditPlugin
        Stateless Google Python documentation audit plugin instance.
    """

    return GooglePythonDocumentationAuditPlugin()
