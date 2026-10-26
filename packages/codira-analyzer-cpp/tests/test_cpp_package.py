"""Package-local tests for the first-party C++ analyzer distribution."""

from __future__ import annotations

import inspect
from importlib.metadata import version
from types import SimpleNamespace
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

import codira_analyzer_cpp as cpp_analyzer_module
from codira_analyzer_cpp import CppAnalyzer, build_analyzer
from codira_analyzer_cpp import cpp_syntax

if TYPE_CHECKING:
    from codira_clang_frontend.contracts import FrontendResult


def test_cpp_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the analyzer entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected analyzer factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "2.0.45"
    assert version("codira-analyzer-cpp") == "2.0.45"
    assert (
        Path(inspect.getfile(CppAnalyzer)).resolve()
        == (
            pyproject_path.parent / "src" / "codira_analyzer_cpp" / "__init__.py"
        ).resolve()
    )
    assert "codira>=2.0.0,<3.0.0" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "cpp": "codira_analyzer_cpp:build_analyzer"
    }


def test_cpp_package_builds_expected_analyzer() -> None:
    """
    Keep the package-local factory aligned to the published analyzer name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected analyzer type and name.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, CppAnalyzer)
    assert analyzer.name == "cpp"
    assert analyzer.version == "44"


def test_cpp_clang_frontend_is_opt_in_and_missing_profile_is_visible(
    tmp_path: Path,
) -> None:
    """Keep the Tree-sitter default and surface missing Clang context.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C++ source file.

    Returns
    -------
    None
        The test checks the opt-in schema and explicit fallback status.
    """
    source = tmp_path / "sample.cpp"
    source.write_text("int run() { return 7; }\n", encoding="utf-8")

    analyzer = CppAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["frontend"]["default"] == "tree-sitter"
    analyzer.configure({"frontend": "clang"})
    analysis = analyzer.analyze_file(source, tmp_path)

    assert [item.name for item in analysis.functions] == ["run"]
    assert analysis.status is not None
    assert analysis.status.coverage_state == "partial"
    assert analysis.status.target_contract["selected_frontend"] == "tree-sitter"
    assert analysis.status.diagnostics[-1].category == "clang_frontend_fallback"


def test_cpp_clang_projection_preserves_source_using_alias(tmp_path: Path) -> None:
    """Project a source-written C++ using alias into the core declaration DTO.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one using declaration.

    Returns
    -------
    None
        The test checks kind, spelling, and source coordinate projection.
    """
    source = tmp_path / "aliases.cpp"
    source_text = (
        "namespace first { void run() {} }\n"
        "namespace second { void run() {} }\n"
        "using Count = unsigned long;\n"
    )
    source.write_text(source_text, encoding="utf-8")

    def source_point(line: int, column: int, offset: int) -> SimpleNamespace:
        position = SimpleNamespace(
            path=str(source),
            line=line,
            column=column,
            offset=offset,
        )
        return SimpleNamespace(spelling=position, expansion=position, is_macro=False)

    alias = SimpleNamespace(
        provenance="source_written",
        kind="type_alias",
        name="Count",
        qualified_name="Count",
        signature="using Count = unsigned long",
        type_text="unsigned long",
        location=source_point(3, 7, source_text.index("Count")),
        span=None,
    )
    functions = tuple(
        SimpleNamespace(
            usr=f"c:@N@{namespace}@F@run",
            kind="function",
            name="run",
            qualified_name=f"{namespace}::run",
            lexical_owner=namespace,
            decl_kind="function",
            signature="void run()",
            function_type="void ()",
            parameters=(),
            has_prototype=True,
            is_definition=True,
            is_public=True,
            provenance="source_written",
            location=source_point(
                line,
                source_text.splitlines()[line - 1].index("run") + 1,
                source_text.index(
                    "run", 0 if line == 1 else source_text.index("\n") + 1
                ),
            ),
            span=None,
            calls=(),
        )
        for namespace, line in (("first", 1), ("second", 2))
    )
    compilation_context = SimpleNamespace(
        target_triple="x86_64-unknown-linux-gnu",
        sysroot="/usr/x86_64-unknown-linux-gnu",
        sysroot_path=Path("/usr/x86_64-unknown-linux-gnu"),
    )
    frontend_result = SimpleNamespace(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        declarations=(alias,),
        callables=functions,
        diagnostics=(),
        includes=(),
        preprocessing=(),
        documentation_comments=(),
        profile_identity="test-profile",
        cache_fingerprint="test-fingerprint",
        toolchain_identity=None,
        compilation_context=compilation_context,
        dependency_closure=None,
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
    )

    # Keep the unit test independent of the optional frontend at runtime; this
    # stand-in supplies the result fields consumed by the projection boundary.
    analysis = cpp_analyzer_module._analysis_from_clang_result(
        source, tmp_path, cast("FrontendResult", frontend_result)
    )

    assert analysis is not None
    assert [
        (item.kind, item.name, item.lineno, item.signature)
        for item in analysis.declarations
    ] == [("type_alias", "Count", 3, "using Count = unsigned long")]
    assert [(item.name, item.lineno) for item in analysis.functions] == [
        ("first::run", 1),
        ("second::run", 2),
    ]
    assert len({item.stable_id for item in analysis.functions}) == 2
    assert analysis.status is not None
    assert analysis.status.omitted_categories == ()
    expected_context = {
        "target_triple": "x86_64-unknown-linux-gnu",
        "sysroot": "/usr/x86_64-unknown-linux-gnu",
        "sysroot_path": "/usr/x86_64-unknown-linux-gnu",
    }
    assert analysis.status.target_contract["compilation_context"] == expected_context
    attempt = analysis.status.target_contract["attempt_evidence"]
    assert isinstance(attempt, dict)
    assert attempt["compilation_context"] == expected_context


def test_cpp_clang_projection_selects_call_coordinates_by_macro_origin(
    tmp_path: Path,
) -> None:
    """Use spelling coordinates for macro arguments and expansion for replacements.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C++ translation unit.

    Returns
    -------
    None
        The test checks projected call columns for both macro origins.
    """
    source = tmp_path / "calls.cpp"
    source.write_text("int invoke() { return argument_call() + replacement_call(); }\n")

    def macro_point(spelling_column: int, expansion_column: int) -> SimpleNamespace:
        """Build one macro-derived location with distinct source coordinates.

        Parameters
        ----------
        spelling_column : int
            One-based physical spelling column.
        expansion_column : int
            One-based macro expansion column.

        Returns
        -------
        types.SimpleNamespace
            Frontend-compatible point retaining spelling and expansion.
        """
        spelling = SimpleNamespace(
            path=str(source), line=1, column=spelling_column, offset=spelling_column
        )
        expansion = SimpleNamespace(
            path=str(source), line=1, column=expansion_column, offset=expansion_column
        )
        return SimpleNamespace(spelling=spelling, expansion=expansion, is_macro=True)

    calls = (
        SimpleNamespace(
            target="argument_call",
            qualified_target="argument_call",
            target_usr="c:@F@argument_call",
            origin="macro_argument",
            location=macro_point(30, 11),
        ),
        SimpleNamespace(
            target="replacement_call",
            qualified_target="replacement_call",
            target_usr="c:@F@replacement_call",
            origin="macro_replacement",
            location=macro_point(50, 61),
        ),
    )
    callable_item = SimpleNamespace(
        usr="c:@F@invoke",
        kind="function",
        name="invoke",
        qualified_name="invoke",
        lexical_owner=None,
        decl_kind="Function",
        signature="int invoke()",
        function_type="int ()",
        parameters=(),
        has_prototype=True,
        is_definition=True,
        is_public=True,
        provenance="source_written",
        location=macro_point(5, 5),
        span=None,
        calls=calls,
        returns_value=True,
        is_variadic=False,
        qualifiers=SimpleNamespace(is_method=False),
    )
    result = SimpleNamespace(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        declarations=(),
        callables=(callable_item,),
        diagnostics=(),
        includes=(),
        preprocessing=(),
        documentation_comments=(),
        profile_identity="test-profile",
        cache_fingerprint="test-fingerprint",
        toolchain_identity=None,
        compilation_context=None,
        dependency_closure=None,
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
    )

    analysis = cpp_analyzer_module._analysis_from_clang_result(
        source, tmp_path, cast("FrontendResult", result)
    )

    assert analysis is not None
    assert [(call.target, call.col_offset) for call in analysis.functions[0].calls] == [
        ("argument_call", 29),
        ("replacement_call", 60),
    ]


def test_cpp_syntax_helpers_remain_available_to_package_traversal() -> None:
    """Keep the extracted parser and normalization boundary usable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts traversal dependencies keep their deterministic shape.
    """

    assert cpp_syntax._normalize_signature("int  run(  int value )") == (
        "int run( int value )"
    )
    assert cpp_syntax._split_qualified_name("demo :: Widget") == ("demo", "Widget")
    assert cpp_syntax._new_parser() is not None


def test_cpp_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply C++ analyzer documentation, import, namespace, and macro toggles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured options prune optional C++ artifacts.
    """

    source = tmp_path / "src" / "sample.cpp"
    source.parent.mkdir()
    source.write_text(
        "#include <vector>\n"
        "#define VALUE 1\n"
        "/** Module docs. */\n"
        "namespace demo { int run() { return VALUE; } }\n",
        encoding="utf-8",
    )

    analyzer = CppAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "include_paths": ["src"],
            "use_leading_comments": False,
            "emit_doxygen_documentation": False,
            "include_system_includes": False,
            "emit_namespaces": False,
            "emit_macros": False,
        }
    )
    analysis = analyzer.analyze_file(source, tmp_path)

    assert "emit_namespaces" in properties
    assert "emit_macros" in properties
    assert analyzer.allows_path(source, tmp_path) is True
    assert analysis.module.docstring is None
    assert analysis.imports == ()
    assert analysis.documentation == ()
    assert all(declaration.kind != "namespace" for declaration in analysis.declarations)
    assert all(declaration.kind != "macro" for declaration in analysis.declarations)


def test_cpp_analyzer_emits_doxygen_documentation_only(tmp_path: Path) -> None:
    """
    Keep C++ documentation artifacts scoped to explicit Doxygen comments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts nested C++ owners can emit Doxygen documentation
        artifacts while ordinary comments do not.
    """
    source = tmp_path / "sample.cpp"
    source.write_text(
        "\n".join(
            (
                "/** Widget type. */",
                "class Widget {",
                "public:",
                "  /// Runs the widget.",
                "  void run() {}",
                "};",
                "",
                "// Ordinary implementation note.",
                "int undocumented() { return 0; }",
            )
        ),
        encoding="utf-8",
    )

    analysis = CppAnalyzer().analyze_file(source, tmp_path)

    assert [
        (doc.title, doc.source_format, doc.owner_kind, doc.text)
        for doc in analysis.documentation
    ] == [
        ("Widget", "doxygen", "class", "Widget type."),
        ("run", "doxygen", "method", "Runs the widget."),
    ]
    assert all(
        doc.attachment_confidence == "explicit" for doc in analysis.documentation
    )
