"""Compatibility shim for the extracted first-party C analyzer package.

Responsibilities
----------------
- Preserve historical imports from `codira.analyzers.c`.
- Redirect callers to the extracted `codira_analyzer_c` package.
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

__all__ = ["CAnalyzer", "_disambiguate_function_stable_ids"]


try:
    c_module = import_module("codira_analyzer_c")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_c":
        raise
    msg = (
        "The first-party C analyzer now lives in the separate "
        "`codira-analyzer-c` package. Install that package to keep using "
        "`codira.analyzers.c` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

CAnalyzer = c_module.CAnalyzer
_disambiguate_function_stable_ids = c_module._disambiguate_function_stable_ids
