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

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer


def test_tree_sitter_analyzers_mark_recovered_syntax_errors_partial(
    tmp_path: Path,
) -> None:
    """Mark every recovered parser error partial and withhold symbol persistence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing malformed source fixtures.

    Returns
    -------
    None
        The test asserts every affected analyzer reports a partial status and
        disables symbol indexing for a recoverable grammar error.
    """
    cases: tuple[tuple[LanguageAnalyzer, str, bytes], ...] = (
        (BashAnalyzer(), "broken.sh", b"function good() {}\nif then\n"),
        (CAnalyzer(), "broken.c", b"int good(void){return 0;}\nint broken(\n"),
        (CppAnalyzer(), "broken.cpp", b"void good() {}\nvoid broken(\n"),
        (GoAnalyzer(), "broken.go", b"package x\nfunc Good() {}\nfunc Broken(\n"),
        (
            JavaScriptAnalyzer(),
            "broken.js",
            b"function good() {}\nfunction broken(\n",
        ),
        (RustAnalyzer(), "broken.rs", b"fn good() {}\nfn broken(\n"),
        (
            TypeScriptAnalyzer(),
            "broken.ts",
            b"function good(): void {}\nfunction broken(\n",
        ),
    )

    for analyzer, name, source in cases:
        path = tmp_path / name
        path.write_bytes(source)

        result = analyzer.analyze_file(path, tmp_path)

        assert result.index_symbols is False
        assert result.status is not None
        assert result.status.coverage_state.value == "partial"
        assert result.status.diagnostics[0].category == "grammar_error"
        assert result.status.reliable_categories == ()
