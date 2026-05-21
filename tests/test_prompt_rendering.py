"""Regression tests for deterministic prompt rendering helpers.

Responsibilities
----------------
- Verify empty prompt sections render explicit placeholders.
- Ensure enriched prompt context stays bounded and deterministic.
- Cover path rendering and docstring issue formatting in the default prompt.

Design principles
-----------------
Tests stay narrow and textual so prompt-format regressions remain easy to
diagnose from direct string assertions.

Architectural role
------------------
This module belongs to the **prompt rendering verification layer** for the
default agent-facing prompt helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codira.prompts.default import PromptBuildRequest, build_prompt

if TYPE_CHECKING:
    import ast


def _prompt_symbol_line(root: Path, symbol: tuple[str, str, str, str, int]) -> str:
    """
    Render one deterministic one-line symbol summary for prompt tests.

    Parameters
    ----------
    root : pathlib.Path
        Repository root passed by the prompt builder.
    symbol : tuple[str, str, str, str, int]
        Symbol row rendered by the prompt builder.

    Returns
    -------
    str
        Stable prompt line used by the regression fixtures.
    """
    del root
    symbol_type, module_name, name, file_path, lineno = symbol
    return f"- {symbol_type} {module_name}.{name} @ {file_path}:{lineno}"


def _format_enriched_symbol(
    root: Path,
    symbol: tuple[str, str, str, str, int],
    cache: dict[Path, tuple[str, list[str], ast.Module | None]],
) -> list[str]:
    """
    Render one deterministic enriched symbol block for prompt tests.

    Parameters
    ----------
    root : pathlib.Path
        Repository root passed by the prompt builder.
    symbol : tuple[str, str, str, str, int]
        Symbol row rendered by the prompt builder.
    cache : dict[pathlib.Path, tuple[str, list[str], ast.Module | None]]
        Source cache shared across enriched prompt formatting.

    Returns
    -------
    list[str]
        Stable enriched context lines used by the regression fixtures.
    """
    del root, cache
    symbol_type, module_name, name, file_path, lineno = symbol
    return [
        f"{symbol_type} {module_name}.{name}",
        f"  file: {file_path}",
        f"  line: {lineno}",
    ]


def test_build_prompt_renders_empty_sections_explicitly(tmp_path: Path) -> None:
    """
    Render `None.` placeholders for every empty default prompt section.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used for the prompt request.

    Returns
    -------
    None
        The test asserts empty prompt sections remain explicit and
        deterministic.
    """
    prompt = build_prompt(
        PromptBuildRequest(
            root=tmp_path,
            query="missing symbol",
            top_matches=[],
            doc_issues=[],
            expanded=[],
            unique_refs=[],
            prompt_symbol_line=_prompt_symbol_line,
            format_enriched_symbol=_format_enriched_symbol,
        )
    )

    assert "PRIMARY TARGETS\n---------------\nNone." in prompt
    assert "SUPPORTING SYMBOLS\n------------------\nNone." in prompt
    assert "ENRICHED CONTEXT\n----------------\nNone." in prompt
    assert "CROSS-REFERENCES\n----------------\nNone." in prompt
    assert "DOCSTRING ISSUES\n----------------\nNone." in prompt
    assert "OUTPUT FORMAT\n-------------" in prompt


def test_build_prompt_limits_enriched_context_and_keeps_external_refs() -> None:
    """
    Limit enriched context to five symbols and preserve non-relative refs.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the default prompt truncates enriched context after
        five primary matches and leaves external reference paths unchanged.
    """
    root = Path("/workspace/repo")
    top_matches = [
        (
            "function",
            "pkg.core",
            f"symbol_{index}",
            f"src/pkg/core_{index}.py",
            index,
        )
        for index in range(1, 7)
    ]

    prompt = build_prompt(
        PromptBuildRequest(
            root=root,
            query="core symbols",
            top_matches=top_matches,
            doc_issues=[("missing_returns", "Document the return value.")],
            expanded=[
                ("module", "pkg.helpers", "helpers", "src/pkg/helpers.py", 1),
            ],
            unique_refs=[
                (str(root / "src/pkg/core.py"), 12),
                ("/external/shared.py", 33),
            ],
            prompt_symbol_line=_prompt_symbol_line,
            format_enriched_symbol=_format_enriched_symbol,
        )
    )

    assert "function pkg.core.symbol_1" in prompt
    assert "function pkg.core.symbol_5" in prompt
    assert "function pkg.core.symbol_6\n  file:" not in prompt
    assert "- src/pkg/core.py:12" in prompt
    assert "- /external/shared.py:33" in prompt
    assert "- missing_returns: Document the return value." in prompt
    assert "- module pkg.helpers.helpers @ src/pkg/helpers.py:1" in prompt
