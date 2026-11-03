"""Regression tests for recovered Tree-sitter syntax errors.

Responsibilities
----------------
- Ensure parser-backed analyzers surface recovered grammar errors through the
  shared partial-analysis contract.

Design principles
-----------------
Recovered parse trees may retain useful nodes, but must never be persisted as
complete symbol analysis.

Architectural role
------------------
This module protects the analyzer-to-indexer failure-path boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira_analyzer_bash import BashAnalyzer
from codira_analyzer_c import CAnalyzer
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_go import GoAnalyzer
from codira_analyzer_javascript import JavaScriptAnalyzer
from codira_analyzer_rust import RustAnalyzer
from codira_analyzer_typescript import TypeScriptAnalyzer

from codira.models import AnalysisCoverageState

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer


def test_tree_sitter_analyzers_mark_recovered_syntax_errors_partial(
    tmp_path: Path,
) -> None:
    """Mark parser errors partial and retain only clean C-family subtrees.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing malformed source fixtures.

    Returns
    -------
    None
        The test asserts C and C++ retain the clean function before the syntax
        error, while other analyzers keep withholding symbols for this fixture.
    """
    cases: tuple[
        tuple[LanguageAnalyzer, str, bytes, tuple[str, ...] | None, tuple[str, ...]],
        ...,
    ] = (
        (
            BashAnalyzer(),
            "broken.sh",
            b"function good() {}\nif then\n",
            None,
            (),
        ),
        (
            CAnalyzer(),
            "broken.c",
            b"int good(void){return 0;}\nint broken(\n",
            ("good",),
            ("unparsed_source_subtrees",),
        ),
        (
            CppAnalyzer(),
            "broken.cpp",
            b"void good() {}\nvoid broken(\n",
            ("good",),
            ("class", "declaration", "import", "documentation"),
        ),
        (
            GoAnalyzer(),
            "broken.go",
            b"package x\nfunc Good() {}\nfunc Broken(\n",
            None,
            (),
        ),
        (
            JavaScriptAnalyzer(),
            "broken.js",
            b"function good() {}\nfunction broken(\n",
            None,
            (),
        ),
        (RustAnalyzer(), "broken.rs", b"fn good() {}\nfn broken(\n", None, ()),
        (
            TypeScriptAnalyzer(),
            "broken.ts",
            b"function good(): void {}\nfunction broken(\n",
            None,
            (),
        ),
    )

    for analyzer, name, source, retained_functions, omitted_categories in cases:
        path = tmp_path / name
        path.write_bytes(source)

        result = analyzer.analyze_file(path, tmp_path)

        assert result.status is not None
        assert result.status.coverage_state is AnalysisCoverageState.PARTIAL
        if retained_functions is None:
            assert result.index_symbols is False
            assert result.status.diagnostics[0].category == "grammar_error"
            assert result.status.reliable_categories == ()
        else:
            assert result.index_symbols is True
            assert tuple(item.name for item in result.functions) == retained_functions
            assert set(omitted_categories).issubset(result.status.omitted_categories)
