"""Compatibility shim for the first-party Markdown analyzer package.

Responsibilities
----------------
- Preserve imports from `codira.analyzers.markdown`.
- Redirect callers to the extracted `codira_analyzer_markdown` package.
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
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from codira_analyzer_markdown import MarkdownAnalyzer as _MarkdownAnalyzerType

__all__ = ["MarkdownAnalyzer"]


try:
    markdown_module = import_module("codira_analyzer_markdown")
except ModuleNotFoundError as exc:
    if exc.name != "codira_analyzer_markdown":
        raise
    msg = (
        "The first-party Markdown analyzer lives in the separate "
        "`codira-analyzer-markdown` package. Install that package to keep "
        "using `codira.analyzers.markdown` compatibility imports."
    )
    raise ModuleNotFoundError(msg, name=exc.name) from exc

MarkdownAnalyzer = cast(
    "type[_MarkdownAnalyzerType]",
    markdown_module.MarkdownAnalyzer,
)
