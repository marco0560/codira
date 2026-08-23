"""Contract tests for the first-party JavaScript analyzer package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_javascript import JavaScriptAnalyzer, build_analyzer


def test_javascript_package_declares_expected_entry_point() -> None:
    """Keep package metadata aligned with plugin discovery.

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

    assert project["project"]["version"] == "1.65.0"
    assert "tree-sitter-javascript>=0.23.1" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "javascript": "codira_analyzer_javascript:build_analyzer"
    }


def test_javascript_analyzer_extracts_issue_36_surface(tmp_path: Path) -> None:
    """Extract JavaScript symbols, calls, imports, and JSDoc deterministically.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Issue #36 constructs map to stable, ordered artifacts.
    """
    source = tmp_path / "src" / "widget.jsx"
    source.parent.mkdir()
    source.write_text(
        "/** Build a widget. */\n"
        "export function build(value) { return format(value); }\n"
        "import helper from './helper.js';\n"
        "/** Widget API. */\n"
        "export class Widget { render(view) { return view.draw(); } }\n"
        "/** Calculate. */\n"
        "export const calculate = (left, right) => helper(left + right);\n"
        "export const limit = 3;\n"
        "export * as helpers from './helpers.js';\n",
        encoding="utf-8",
    )

    result = JavaScriptAnalyzer().analyze_file(source, tmp_path)

    assert result.module.stable_id == "javascript:module:src/widget.jsx"
    assert [item.name for item in result.imports] == ["./helper.js"]
    assert [item.name for item in result.functions] == ["build", "calculate"]
    assert [(item.kind, item.name) for item in result.declarations] == [
        ("variable", "limit"),
        ("namespace", "helpers"),
    ]
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [("Widget", ["render"])]
    assert [
        (call.kind, call.target, call.base) for call in result.functions[0].calls
    ] == [("name", "format", "")]
    assert [
        (call.kind, call.target, call.base)
        for call in result.classes[0].methods[0].calls
    ] == [("attribute", "draw", "view")]
    assert result.functions[0].docstring == "Build a widget."
    assert result.classes[0].docstring == "Widget API."
    assert [item.source_format for item in result.documentation] == [
        "jsdoc",
        "jsdoc",
        "jsdoc",
    ]


def test_javascript_analyzer_honors_emission_configuration(tmp_path: Path) -> None:
    """Allow variable and JSDoc artifacts to be disabled independently.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Disabled optional artifacts do not alter function extraction.
    """
    source = tmp_path / "entry.mjs"
    source.write_text("/** Value. */\nconst value = 1;\n", encoding="utf-8")
    analyzer = JavaScriptAnalyzer()
    analyzer.configure({"emit_variables": False, "emit_jsdoc_documentation": False})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.declarations == ()
    assert result.documentation == ()
    assert analyzer.supports_path(tmp_path / "component.jsx") is True
    assert analyzer.supports_path(tmp_path / "component.ts") is False


def test_javascript_analyzer_extracts_callable_object_references(
    tmp_path: Path,
) -> None:
    """Extract callable references separately from direct calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Assignment, return, mapping, and sequence reference provenance is stable.
    """
    source = tmp_path / "src" / "handlers.js"
    source.parent.mkdir()
    source.write_text(
        "function build() {\n"
        "  const callback = handler;\n"
        "  registry.current = service.run;\n"
        "  const items = [first, api.second];\n"
        "  const table = { callback: formatter };\n"
        "  return complete;\n"
        "}\n",
        encoding="utf-8",
    )

    result = JavaScriptAnalyzer().analyze_file(source, tmp_path)

    assert [
        (item.ref_kind, item.kind, item.target, item.base)
        for item in result.functions[0].callable_refs
    ] == [
        ("assignment_value", "name", "handler", ""),
        ("assignment_value", "attribute", "run", "service"),
        ("sequence_item", "name", "first", ""),
        ("sequence_item", "attribute", "second", "api"),
        ("mapping_value", "name", "formatter", ""),
        ("return_value", "name", "complete", ""),
    ]


def test_javascript_factory_returns_expected_analyzer() -> None:
    """Keep the public factory aligned to the analyzer implementation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The factory returns the advertised JavaScript analyzer.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, JavaScriptAnalyzer)
    assert analyzer.discovery_globs == ("*.js", "*.jsx", "*.mjs", "*.cjs")


def test_javascript_analyzer_is_deterministic_across_supported_extensions(
    tmp_path: Path,
) -> None:
    """Preserve equal syntax artifacts across repeated supported-file analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Repeated analysis yields equal immutable artifacts for all extensions.
    """
    analyzer = JavaScriptAnalyzer()
    source_text = (
        "import { format } from './format.js';\n"
        "export const render = value => <div>{format(value)}</div>;\n"
    )
    for suffix in (".js", ".jsx", ".mjs", ".cjs"):
        source = tmp_path / f"entry{suffix}"
        source.write_text(source_text, encoding="utf-8")

        first = analyzer.analyze_file(source, tmp_path)
        second = analyzer.analyze_file(source, tmp_path)

        assert first == second
