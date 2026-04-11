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

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ast
    from collections.abc import Callable

    from codira.types import CacheType, ReferenceRow, SymbolRow


def build_prompt(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
    *,
    prompt_symbol_line: Callable[[Path, SymbolRow], str],
    format_enriched_symbol: Callable[[Path, SymbolRow, CacheType], list[str]],
) -> str:
    """
    Build the default deterministic agent prompt.

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
        Cross-reference locations associated with the selected symbols.
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

    Returns
    -------
    str
        Deterministic plain-text prompt containing the selected context.

    Notes
    -----
    This is a direct extraction of the original ``_render_agent_prompt`` logic.
    """

    cache: dict[Path, tuple[str, list[str], ast.Module]] = {}
    lines: list[str] = []

    lines.append("TASK")
    lines.append("----")
    lines.append(f"Use the codira context below to work on query: {query}")
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
    lines.append("")
    lines.append("PRIMARY TARGETS")
    lines.append("---------------")

    if not top_matches:
        lines.append("None.")
    else:
        for symbol in top_matches:
            lines.append(prompt_symbol_line(root, symbol))

    lines.append("")
    lines.append("SUPPORTING SYMBOLS")
    lines.append("------------------")

    if not expanded:
        lines.append("None.")
    else:
        for symbol in expanded:
            lines.append(prompt_symbol_line(root, symbol))

    lines.append("")
    lines.append("ENRICHED CONTEXT")
    lines.append("----------------")

    if not top_matches:
        lines.append("None.")
    else:
        for symbol in top_matches[:5]:
            lines.extend(format_enriched_symbol(root, symbol, cache))
            lines.append("")

        if lines[-1] == "":
            lines.pop()

    lines.append("")
    lines.append("CROSS-REFERENCES")
    lines.append("----------------")

    if not unique_refs:
        lines.append("None.")
    else:
        for file_path, lineno in unique_refs:
            try:
                rel_path = str(Path(file_path).relative_to(root))
            except ValueError:
                rel_path = str(file_path)

            lines.append(f"- {rel_path}:{lineno}")

    lines.append("")
    lines.append("DOCSTRING ISSUES")
    lines.append("----------------")

    if not doc_issues:
        lines.append("None.")
    else:
        for issue_type, message in doc_issues:
            lines.append(f"- {issue_type}: {message}")

    lines.append("")
    lines.append("OUTPUT FORMAT")
    lines.append("-------------")
    lines.append("Follow strict patch discipline:")
    lines.append("- FILE path")
    lines.append("- exact OLD block")
    lines.append("- exact NEW block")
    lines.append("- no partial edits")
    lines.append("- no invented code outside visible scope")

    return "\n".join(lines)
