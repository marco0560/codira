"""Compatibility shim for the extracted first-party Python analyzer package.

Responsibilities
----------------
- Preserve historical imports from `codira.analyzers.python`.
- Redirect callers to the extracted `codira_analyzer_python` package.
- Raise a deterministic operator-facing error when the package is absent.

Design principles
-----------------
The shim stays intentionally narrow so the extracted package owns the real
implementation logic.

Architectural role
------------------
This module belongs to the **compatibility layer** of the Phase 2 package
boundary migration.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from codira_analyzer_python import PythonAnalyzer as _PythonAnalyzerType

__all__ = ["PythonAnalyzer"]


try:
    python_module = import_module("codira_analyzer_python")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_python":
        raise
    msg = (
        "The first-party Python analyzer now lives in the separate "
        "`codira-analyzer-python` package. Install that package to keep "
        "using `codira.analyzers.python` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

PythonAnalyzer = cast("type[_PythonAnalyzerType]", python_module.PythonAnalyzer)
