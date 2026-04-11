"""Compatibility shim for the extracted first-party JSON analyzer package.

Responsibilities
----------------
- Preserve historical imports from `codira.analyzers.json`.
- Redirect callers to the extracted `codira_analyzer_json` package.
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
    from codira_analyzer_json import JsonAnalyzer as _JsonAnalyzerType

__all__ = ["JsonAnalyzer"]


try:
    json_module = import_module("codira_analyzer_json")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_json":
        raise
    msg = (
        "The first-party JSON analyzer now lives in the separate "
        "`codira-analyzer-json` package. Install that package to keep "
        "using `codira.analyzers.json` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

JsonAnalyzer = cast("type[_JsonAnalyzerType]", json_module.JsonAnalyzer)
