"""Compatibility shim for the extracted first-party Bash analyzer package.

Responsibilities
----------------
- Preserve historical imports from `codira.analyzers.bash`.
- Redirect callers to the extracted `codira_analyzer_bash` package.
- Raise a deterministic operator-facing error when the package is absent.

Design principles
-----------------
The shim stays intentionally narrow so the extracted package owns the real
implementation logic.

Architectural role
------------------
This module belongs to the **compatibility layer** of the Phase 1 package
boundary migration.
"""

from __future__ import annotations

from importlib import import_module

__all__ = ["BashAnalyzer"]


try:
    bash_module = import_module("codira_analyzer_bash")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_bash":
        raise
    msg = (
        "The first-party Bash analyzer now lives in the separate "
        "`codira-analyzer-bash` package. Install that package to keep using "
        "`codira.analyzers.bash` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

BashAnalyzer = bash_module.BashAnalyzer
