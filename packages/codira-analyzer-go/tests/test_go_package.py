"""Contract tests for the first-party Go analyzer package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_go import GoAnalyzer, build_analyzer


def test_go_package_declares_expected_entry_point() -> None:
    """Keep Go package metadata aligned with analyzer discovery.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Version, grammar dependency, and entry point are asserted.
    """
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    assert project["project"]["version"] == "2.0.0"
    assert "tree-sitter-go>=0.23.4" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "go": "codira_analyzer_go:build_analyzer"
    }


def test_go_analyzer_extracts_issue_38_constructs(tmp_path: Path) -> None:
    """Extract issue #38 Go constructs without compiler execution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Package, imports, declarations, calls, and methods are asserted.
    """
    source = tmp_path / "service.go"
    source.write_text(
        "package service\n"
        'import alias "example.com/alias"\n'
        "const Answer = 42\n"
        'var Name = "codira"\n'
        "type Box[T any] struct { Value T }\n"
        "type Runner interface { Run(value int) error }\n"
        "func Build(value int) int { return helper(value) }\n"
        "func (box *Box[int]) Run(value int) error { return alias.Run(value) }\n",
        encoding="utf-8",
    )

    result = GoAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "service"
    assert [(item.name, item.alias) for item in result.imports] == [
        ("example.com/alias", "alias")
    ]
    assert [(item.kind, item.name) for item in result.declarations] == [
        ("constant", "Answer"),
        ("variable", "Name"),
        ("struct", "Box"),
        ("struct", "Runner"),
    ]
    assert result.functions[0].calls[0].target == "helper"
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [("(box *Box[int])", ["Run"])]


def test_go_factory_builds_expected_analyzer() -> None:
    """Keep factory construction and suffix discovery stable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Analyzer type and Go-only glob are asserted.
    """
    analyzer = build_analyzer()
    assert isinstance(analyzer, GoAnalyzer)
    assert analyzer.discovery_globs == ("*.go",)


def test_go_analyzer_attaches_only_adjacent_go_doc_comments(tmp_path: Path) -> None:
    """Preserve explicit Go comment provenance without heuristic attachment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Package and function documentation ownership are asserted.
    """
    source = tmp_path / "doc.go"
    source.write_text(
        "// Package doc demonstrates attachment.\n"
        "package doc\n\n"
        "// Build creates a value.\n"
        "func Build() int { return 1 }\n",
        encoding="utf-8",
    )
    result = GoAnalyzer().analyze_file(source, tmp_path)
    assert result.module.docstring == "Package doc demonstrates attachment."
    assert result.functions[0].docstring == "Build creates a value."
    assert [item.source_format for item in result.documentation] == [
        "go_doc_comment",
        "go_doc_comment",
    ]
