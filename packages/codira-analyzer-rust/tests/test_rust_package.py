"""Package-local tests for the first-party Rust analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_rust import RustAnalyzer, build_analyzer


def test_rust_package_declares_expected_entry_point() -> None:
    """Keep Rust package metadata aligned with plugin discovery.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The package version, grammar dependency, and entry point are asserted.
    """
    project_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "2.0.0"
    assert "tree-sitter-rust>=0.24.0" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "rust": "codira_analyzer_rust:build_analyzer"
    }


def test_rust_package_builds_expected_analyzer() -> None:
    """Keep the factory aligned with the published analyzer name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The factory returns the Rust analyzer implementation.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, RustAnalyzer)
    assert analyzer.name == "rust"
    assert analyzer.discovery_globs == ("*.rs",)


def test_rust_analyzer_extracts_issue_40_constructs(tmp_path: Path) -> None:
    """Extract Rust declarations, trait and impl methods, imports, and calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        All syntax-only constructs in issue #40 have deterministic artifacts.
    """
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "use crate::io::Writer as Output;\n"
        "mod helpers;\n"
        "pub struct Widget;\n"
        "enum Mode { Fast, Slow }\n"
        "const LIMIT: usize = 2;\n"
        "trait Render { fn render(&self, output: Output); }\n"
        "impl Render for Widget {\n"
        "    fn render(&self, output: Output) { output.write(); helper(); }\n"
        "}\n"
        "fn helper() -> usize { LIMIT }\n",
        encoding="utf-8",
    )

    result = RustAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "src.lib"
    assert result.module.stable_id == "rust:module:src/lib.rs"
    assert [(item.name, item.alias) for item in result.imports] == [
        ("crate::io::Writer", "Output")
    ]
    assert [(item.kind, item.name) for item in result.declarations] == [
        ("namespace", "helpers"),
        ("struct", "Widget"),
        ("enum", "Mode"),
        ("constant", "LIMIT"),
    ]
    assert [member.name for member in result.declarations[2].enum_members] == [
        "Fast",
        "Slow",
    ]
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [
        ("Render", ["render"]),
        ("impl Render for Widget", ["render"]),
    ]
    implementation = result.classes[1].methods[0]
    assert implementation.parameters == ("&self", "output")
    assert [(call.kind, call.target, call.base) for call in implementation.calls] == [
        ("attribute", "write", "output"),
        ("name", "helper", ""),
    ]
    assert [
        (function.name, function.returns_value) for function in result.functions
    ] == [("helper", 1)]


def test_rust_analyzer_extracts_macros_without_expansion(tmp_path: Path) -> None:
    """Extract Rust macro definitions and invocations without expansion.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Macro definitions become declarations and macro calls remain explicit
        unresolved call sites rather than synthesized expanded code.
    """
    source = tmp_path / "src" / "macro_heavy.rs"
    source.parent.mkdir()
    source.write_text(
        "macro_rules! make_value { () => { 1usize }; }\n"
        "fn value() -> usize { make_value!(); crate::emit!(1); 1 }\n",
        encoding="utf-8",
    )

    result = RustAnalyzer().analyze_file(source, tmp_path)

    assert [(item.kind, item.name) for item in result.declarations] == [
        ("macro", "make_value")
    ]
    assert [function.name for function in result.functions] == ["value"]
    assert result.functions[0].returns_value == 1
    assert [
        (call.kind, call.target, call.external_target_kind)
        for call in result.functions[0].calls
    ] == [
        ("unresolved", "make_value", "rust_macro"),
        ("unresolved", "crate::emit", "rust_macro"),
    ]


def test_rust_analyzer_can_suppress_macro_declarations(tmp_path: Path) -> None:
    """Honor the Rust macro declaration configuration switch.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Macro declarations are omitted while syntax analysis remains available.
    """
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("macro_rules! internal { () => {} }\n", encoding="utf-8")

    analyzer = RustAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure({"emit_macros": False})

    result = analyzer.analyze_file(source, tmp_path)

    assert "emit_macros" in properties
    assert result.declarations == ()


def test_rust_analyzer_emits_crate_and_item_rustdoc(tmp_path: Path) -> None:
    """Extract crate and item Rustdoc blocks with explicit attachments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Crate docs, item docs, and doctest fences remain in Rustdoc artifacts.
    """
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        "//! Crate overview.\n"
        "//!\n"
        "//! ```no_run\n"
        "//! use demo::run;\n"
        "//! ```\n"
        "/// Runs the demo.\n"
        "pub fn run() {}\n",
        encoding="utf-8",
    )

    result = RustAnalyzer().analyze_file(source, tmp_path)

    assert [
        (item.title, item.owner_kind, item.text) for item in result.documentation
    ] == [
        ("src.lib", "module", "Crate overview.\n\n```no_run\nuse demo::run;\n```"),
        ("run", "function", "Runs the demo."),
    ]
    assert (
        result.module.docstring == "Crate overview.\n\n```no_run\nuse demo::run;\n```"
    )
    assert result.functions[0].docstring == "Runs the demo."
    assert result.functions[0].has_docstring == 1
