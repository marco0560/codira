"""Compatibility shim for the extracted first-party C++ analyzer package.

Responsibilities
----------------
- Preserve historical imports from `codira.analyzers.cpp`.
- Redirect callers to the extracted `codira_analyzer_cpp` package.
- Raise a deterministic operator-facing error when the package is absent.

Design principles
-----------------
The shim stays intentionally narrow so the extracted package owns the real
implementation logic.

Architectural role
------------------
This module belongs to the **compatibility layer** of the first-party analyzer
package boundary.
"""

from __future__ import annotations

from importlib import import_module

__all__ = ["CppAnalyzer"]


try:
    cpp_module = import_module("codira_analyzer_cpp")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_cpp":
        raise
    msg = (
        "The first-party C++ analyzer now lives in the separate "
        "`codira-analyzer-cpp` package. Install that package to keep using "
        "`codira.analyzers.cpp` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

CppAnalyzer = cpp_module.CppAnalyzer
