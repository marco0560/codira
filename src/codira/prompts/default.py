"""Prompt rendering helpers for deterministic agent-facing output.

Responsibilities
----------------
- Build structured prompts containing context sections, docstring diagnostics, and retrieval summaries.
- Provide normalized helper functions for snippet formatting, channel weightings, and doc issue rendering.
- Emit consistent prompt text shared by CLI `ctx` and automation workflows.

Design principles
-----------------
Prompt helpers remain deterministic, dataless, and human-readable so agents can rely on stable formatting.

Architectural role
------------------
This module belongs to the **prompt generation layer** consumed by CLI and automation drivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from codira.types import CacheType, ReferenceRow, SymbolRow


@dataclass(frozen=True)
class PromptBuildRequest:
    """
    Request parameters for deterministic prompt rendering.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize file paths.
    query : str
        Original user query being answered.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols selected for the query.
    doc_issues : list[tuple[str, str]]
        Related docstring issues to surface in the prompt.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected from module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations associated with selected symbols.
    prompt_symbol_line : collections.abc.Callable[
        [pathlib.Path, codira.types.SymbolRow],
        str,
    ]
        Formatter used for one-line symbol summaries.
    format_enriched_symbol : collections.abc.Callable[
        [pathlib.Path, codira.types.SymbolRow, codira.types.CacheType],
        list[str],
    ]
        Formatter used for multi-line enriched context blocks.
    """

    root: Path
    query: str
    top_matches: list[SymbolRow]
    doc_issues: list[tuple[str, str]]
    expanded: list[SymbolRow]
    unique_refs: list[ReferenceRow]
    prompt_symbol_line: Callable[[Path, SymbolRow], str]
    format_enriched_symbol: Callable[[Path, SymbolRow, CacheType], list[str]]


def _append_symbol_section(
    lines: list[str],
    *,
    title: str,
    symbols: list[SymbolRow],
    root: Path,
    prompt_symbol_line: Callable[[Path, SymbolRow], str],
) -> None:
    """
    Append one prompt section containing symbol summaries.

    Parameters
    ----------
    lines : list[str]
        Prompt lines being assembled.
    title : str
        Section heading to append.
    symbols : list[codira.types.SymbolRow]
        Symbols rendered in deterministic order.
    root : pathlib.Path
        Repository root passed to the symbol formatter.
    prompt_symbol_line : collections.abc.Callable[
        [pathlib.Path, codira.types.SymbolRow],
        str,
    ]
        Formatter used for one-line symbol summaries.

    Returns
    -------
    None
        The section is appended in place.
    """
    lines.append("")
    lines.append(title)
    lines.append("-" * len(title))
    if not symbols:
        lines.append("None.")
        return
    for symbol in symbols:
        lines.append(prompt_symbol_line(root, symbol))


def _append_enriched_context(
    lines: list[str],
    request: PromptBuildRequest,
    cache: CacheType,
) -> None:
    """
    Append enriched context blocks for primary prompt matches.

    Parameters
    ----------
    lines : list[str]
        Prompt lines being assembled.
    request : PromptBuildRequest
        Prompt rendering request.
    cache : codira.types.CacheType
        Source parsing cache shared across enriched symbol formatting.

    Returns
    -------
    None
        The section is appended in place.
    """
    lines.append("")
    lines.append("ENRICHED CONTEXT")
    lines.append("----------------")
    if not request.top_matches:
        lines.append("None.")
        return

    for symbol in request.top_matches[:5]:
        lines.extend(request.format_enriched_symbol(request.root, symbol, cache))
        lines.append("")
    if lines[-1] == "":
        lines.pop()


def _append_cross_references(
    lines: list[str],
    *,
    root: Path,
    unique_refs: list[ReferenceRow],
) -> None:
    """
    Append cross-reference locations to the prompt.

    Parameters
    ----------
    lines : list[str]
        Prompt lines being assembled.
    root : pathlib.Path
        Repository root used to relativize reference paths.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations associated with selected symbols.

    Returns
    -------
    None
        The section is appended in place.
    """
    lines.append("")
    lines.append("CROSS-REFERENCES")
    lines.append("----------------")
    if not unique_refs:
        lines.append("None.")
        return

    for file_path, lineno in unique_refs:
        try:
            rel_path = str(Path(file_path).relative_to(root))
        except ValueError:
            rel_path = str(file_path)
        lines.append(f"- {rel_path}:{lineno}")


def _append_docstring_issues(
    lines: list[str],
    doc_issues: list[tuple[str, str]],
) -> None:
    """
    Append docstring audit issues to the prompt.

    Parameters
    ----------
    lines : list[str]
        Prompt lines being assembled.
    doc_issues : list[tuple[str, str]]
        Related docstring issues to surface in the prompt.

    Returns
    -------
    None
        The section is appended in place.
    """
    lines.append("")
    lines.append("DOCSTRING ISSUES")
    lines.append("----------------")
    if not doc_issues:
        lines.append("None.")
        return
    for issue_type, message in doc_issues:
        lines.append(f"- {issue_type}: {message}")


def _append_output_format(lines: list[str]) -> None:
    """
    Append deterministic patch-output rules to the prompt.

    Parameters
    ----------
    lines : list[str]
        Prompt lines being assembled.

    Returns
    -------
    None
        The section is appended in place.
    """
    lines.append("")
    lines.append("OUTPUT FORMAT")
    lines.append("-------------")
    lines.append("Follow strict patch discipline:")
    lines.append("- FILE path")
    lines.append("- exact OLD block")
    lines.append("- exact NEW block")
    lines.append("- no partial edits")
    lines.append("- no invented code outside visible scope")


def build_prompt(
    request: PromptBuildRequest,
) -> str:
    """
    Build the default deterministic agent prompt.

    Parameters
    ----------
    request : PromptBuildRequest
        Prompt rendering request.

    Returns
    -------
    str
        Deterministic plain-text prompt containing the selected context.

    Notes
    -----
    This is a direct extraction of the original ``_render_agent_prompt`` logic.
    """

    cache: CacheType = {}
    lines: list[str] = []

    lines.append("TASK")
    lines.append("----")
    lines.append(f"Use the codira context below to work on query: {request.query}")
    lines.append("")
    lines.append("MODE")
    lines.append("----")
    lines.append("Deterministic code assistant")
    lines.append("")
    lines.append("RULES")
    lines.append("-----")
    lines.append("- Work only with the symbols and files listed below.")
    lines.append("- Do not invent modules, files, or functions.")
    lines.append("- Prefer PRIMARY TARGETS over supporting symbols.")
    lines.append("- Keep changes minimal and localized.")
    lines.append("- If required information is missing, say so explicitly.")
    _append_symbol_section(
        lines,
        title="PRIMARY TARGETS",
        symbols=request.top_matches,
        root=request.root,
        prompt_symbol_line=request.prompt_symbol_line,
    )
    _append_symbol_section(
        lines,
        title="SUPPORTING SYMBOLS",
        symbols=request.expanded,
        root=request.root,
        prompt_symbol_line=request.prompt_symbol_line,
    )
    _append_enriched_context(lines, request, cache)
    _append_cross_references(
        lines,
        root=request.root,
        unique_refs=request.unique_refs,
    )
    _append_docstring_issues(lines, request.doc_issues)
    _append_output_format(lines)

    return "\n".join(lines)
