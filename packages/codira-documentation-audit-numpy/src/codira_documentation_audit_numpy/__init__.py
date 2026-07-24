"""NumPy documentation audit plugin distribution for codira.

Responsibilities
----------------
- Re-export the core NumPy documentation audit implementation.
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

from codira.docstring import NumpyDocumentationAuditPlugin

__all__ = ["NumpyDocumentationAuditPlugin", "build_audit_plugin"]


def build_audit_plugin() -> NumpyDocumentationAuditPlugin:
    """
    Build the NumPy documentation audit plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.docstring.NumpyDocumentationAuditPlugin
        Stateless NumPy documentation audit plugin instance.
    """

    return NumpyDocumentationAuditPlugin()
