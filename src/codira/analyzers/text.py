"""Compatibility shim for the extracted plain-text analyzer package.

Responsibilities
----------------
- Preserve imports from `codira.analyzers.text`.
- Redirect callers to the extracted `codira_analyzer_text` package.
- Raise a clear error when the optional package is not installed.

Design principles
-----------------
The shim keeps core lightweight while maintaining a deterministic migration
surface for first-party analyzer packages.

Architectural role
------------------
This module belongs to the **analyzer compatibility layer** during the
first-party package extraction.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from codira_analyzer_text import TextAnalyzer as _TextAnalyzerType

    from codira.contracts import LanguageAnalyzer


class _TextAnalyzerModule(Protocol):
    """Typed surface required from the extracted text analyzer package."""

    TextAnalyzer: type[_TextAnalyzerType]

    def build_analyzer(self) -> LanguageAnalyzer:
        """
        Return a text analyzer instance.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.LanguageAnalyzer
            Plain-text analyzer instance built by the extracted package.
        """


def _load_text_module() -> object:
    """
    Import the external text analyzer package.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Imported `codira_analyzer_text` module.

    Raises
    ------
    ModuleNotFoundError
        If the first-party text analyzer package is not installed.
    """
    try:
        return import_module("codira_analyzer_text")
    except ModuleNotFoundError as exc:
        if exc.name != "codira_analyzer_text":
            raise
        message = (
            "The text analyzer has moved to the optional "
            "`codira-analyzer-text` package. Install that package to keep "
            "using `codira.analyzers.text` compatibility imports."
        )
        raise ModuleNotFoundError(message) from exc


_text_module = _load_text_module()
_typed_text_module = cast("_TextAnalyzerModule", _text_module)
TextAnalyzer: type[_TextAnalyzerType] = _typed_text_module.TextAnalyzer


def build_analyzer() -> LanguageAnalyzer:
    """
    Return a text analyzer from the external package.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Text analyzer instance built by the extracted package.
    """
    return _typed_text_module.build_analyzer()


__all__ = ["TextAnalyzer", "build_analyzer"]
