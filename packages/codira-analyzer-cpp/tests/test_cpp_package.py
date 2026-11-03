"""Package-local tests for the first-party C++ analyzer distribution."""

from __future__ import annotations

import pytest

import hashlib
import json
from codira.generated import CompilerObservedCallableProvenance
from codira_clang_frontend.contracts import SourcePoint, SourcePosition, SourceSpan
from codira.models import (
    AnalysisResult,
    ClassArtifact,
    DeclarationArtifact,
    DocumentationArtifact,
    FunctionArtifact,
    ImportArtifact,
    ModuleArtifact,
)

import inspect
from importlib.metadata import version
from types import SimpleNamespace
import tomllib
from pathlib import Path
from typing import cast

import codira_analyzer_cpp as cpp_analyzer_module
from codira_analyzer_cpp import CppAnalyzer, build_analyzer
from codira_analyzer_cpp import cpp_syntax

from codira_clang_frontend.contracts import FrontendResult
from codira_clang_frontend.frontend import (
    _decode_documentation_comments,
    _decode_entities,
)


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

    assert project["project"]["version"] == "2.0.52"
    assert version("codira-analyzer-cpp") == "2.0.52"
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
    assert analyzer.version == "51"


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


def _clang_output_options_fixture(path: Path) -> AnalysisResult:
    """Build normalized C++ artifacts for frontend-option routing tests.

    Parameters
    ----------
    path : pathlib.Path
        Source path assigned to each test artifact.

    Returns
    -------
    codira.models.AnalysisResult
        C++ analysis containing every Clang output category controlled by config.
    """
    method = FunctionArtifact(
        name="method",
        stable_id="cpp:method:Thing::method",
        lineno=1,
        end_lineno=1,
        signature="void Thing::method()",
        docstring="Method docs",
        has_docstring=1,
        is_method=1,
        is_public=1,
        parameters=(),
        returns_value=0,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=(),
        callable_refs=(),
    )
    function = FunctionArtifact(
        name="run",
        stable_id="cpp:function:run",
        lineno=1,
        end_lineno=1,
        signature="int run()",
        docstring="Run docs",
        has_docstring=1,
        is_method=0,
        is_public=1,
        parameters=(),
        returns_value=1,
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=(),
        callable_refs=(),
    )
    namespace = DeclarationArtifact(
        "api",
        "cpp:namespace:api",
        "namespace",
        1,
        "namespace api",
        docstring="API docs",
    )
    macro = DeclarationArtifact("FLAG", "cpp:macro:FLAG", "macro", 1, "#define FLAG 1")
    value = DeclarationArtifact(
        "VALUE",
        "cpp:constant:VALUE",
        "constant",
        1,
        "int VALUE",
        docstring="Value docs",
    )
    documentation = tuple(
        DocumentationArtifact(
            stable_id=f"doc:{owner.stable_id}",
            kind="declaration",
            source_format="doxygen",
            source_path=path,
            lineno=1,
            end_lineno=1,
            title=owner.name,
            heading_path=(),
            text=owner.docstring or "docs",
            owner_stable_id=owner.stable_id,
            owner_kind="declaration",
            attachment_confidence="explicit",
        )
        for owner in (namespace, macro, value)
    )
    return AnalysisResult(
        source_path=path,
        module=ModuleArtifact("sample", "cpp:module:sample", "File docs", 1),
        classes=(
            ClassArtifact("Thing", "cpp:type:Thing", 1, 1, "Type docs", 1, (method,)),
        ),
        functions=(function,),
        declarations=(namespace, macro, value),
        imports=(
            ImportArtifact("vector", None, 1, "include_system"),
            ImportArtifact("local.hpp", None, 1, "include_local"),
        ),
        documentation=documentation,
    )


def test_cpp_clang_route_applies_output_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply configured output filters to normalized Clang results.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source path used by the mocked Clang route.
    monkeypatch : pytest.MonkeyPatch
        Replaces profile execution and native mapping with fixed normalized facts.

    Returns
    -------
    None
        The test verifies comment, namespace, macro, import, and docs filters.
    """
    source = tmp_path / "sample.cpp"
    source.write_text("int run() { return 1; }\n", encoding="utf-8")
    expected = _clang_output_options_fixture(source)
    fake_frontend_result = SimpleNamespace(callables=(), declarations=())
    analyzer = CppAnalyzer()
    analyzer.configure(
        {
            "frontend": "clang",
            "use_leading_comments": False,
            "include_system_includes": False,
            "emit_namespaces": False,
            "emit_macros": False,
        }
    )
    monkeypatch.setattr(
        analyzer,
        "_try_clang_frontend",
        lambda _path, _root: (fake_frontend_result, ""),
    )
    monkeypatch.setattr(
        cpp_analyzer_module,
        "_analysis_from_clang_result",
        lambda _path, _root, _result, *, context_identity=None: expected,
    )

    analysis = analyzer.analyze_file(source, tmp_path)

    assert analysis.module.docstring is None
    assert analysis.module.has_docstring == 0
    assert analysis.classes[0].docstring is None
    assert analysis.classes[0].has_docstring == 0
    assert analysis.classes[0].methods[0].docstring is None
    assert analysis.classes[0].methods[0].has_docstring == 0
    assert analysis.functions[0].docstring is None
    assert analysis.functions[0].has_docstring == 0
    assert [item.kind for item in analysis.declarations] == ["constant"]
    assert analysis.declarations[0].docstring is None
    assert [item.kind for item in analysis.imports] == ["include_local"]
    assert [item.title for item in analysis.documentation] == ["VALUE"]


def test_cpp_clang_doxygen_option_keeps_semantic_docstrings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disable Doxygen records without clearing semantic docstring fields.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source path used by the mocked Clang route.
    monkeypatch : pytest.MonkeyPatch
        Replaces profile execution and native mapping with fixed normalized facts.

    Returns
    -------
    None
        The test checks Doxygen output can be disabled independently.
    """
    source = tmp_path / "sample.cpp"
    source.write_text("int run() { return 1; }\n", encoding="utf-8")
    expected = _clang_output_options_fixture(source)
    fake_frontend_result = SimpleNamespace(callables=(), declarations=())
    analyzer = CppAnalyzer()
    analyzer.configure({"frontend": "clang", "emit_doxygen_documentation": False})
    monkeypatch.setattr(
        analyzer,
        "_try_clang_frontend",
        lambda _path, _root: (fake_frontend_result, ""),
    )
    monkeypatch.setattr(
        cpp_analyzer_module,
        "_analysis_from_clang_result",
        lambda _path, _root, _result, *, context_identity=None: expected,
    )

    analysis = analyzer.analyze_file(source, tmp_path)

    assert analysis.documentation == ()
    assert analysis.module.docstring == "File docs"
    assert analysis.classes[0].docstring == "Type docs"
    assert analysis.functions[0].docstring == "Run docs"


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
            has_body=True,
            signature_kind="derived_display_only",
            linkage_kind="external",
            linker_symbol=None,
            explicit_linkage_label=None,
            linkage_label_inherited=None,
            alias_target_symbol=None,
            alias_target_usr=None,
            alias_binding_status="not_alias",
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


def test_cpp_clang_projection_merges_reopened_namespace_usr_rows(
    tmp_path: Path,
) -> None:
    """Coalesce exact namespace redeclarations and retain legacy latest metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing repeated and lexically distinct namespaces.

    Returns
    -------
    None
        The test checks USR-based merging, last-row documentation, and namespace scope.
    """
    source = tmp_path / "reopened.cpp"
    source_text = (
        "namespace alias_case {}\n"
        "/// Latest namespace docs.\n"
        "namespace alias_case { int second; }\n"
        "namespace left { namespace nested {} }\n"
        "namespace right { namespace nested {} }\n"
        "namespace { int first_anonymous; }\n"
        "namespace { int second_anonymous; }\n"
        "namespace left { namespace { } }\n"
        "namespace right { namespace { } }\n"
    )
    source.write_text(source_text, encoding="utf-8")
    source_bytes = source.read_bytes()

    def point(offset: int) -> SourcePoint:
        prefix = source_bytes[:offset]
        line = prefix.count(b"\n") + 1
        column = offset - prefix.rfind(b"\n")
        position = SourcePosition(
            path=str(source), line=line, column=column, offset=offset
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=False)

    def namespace_row(
        *,
        usr: str,
        name: str,
        qualified_name: str,
        line_text: str,
        documentation: str | None = None,
        documentation_offset: int | None = None,
    ) -> SimpleNamespace:
        line_offset = source_bytes.index(line_text.encode("utf-8"))
        name_offset = (
            line_text.index(name) if name in line_text else line_text.index("namespace")
        )
        location = point(line_offset + name_offset)
        doc_location = (
            point(documentation_offset) if documentation_offset is not None else None
        )
        return SimpleNamespace(
            usr=usr,
            kind="namespace",
            name=name,
            qualified_name=qualified_name,
            decl_kind="Namespace",
            signature=line_text,
            type_text=None,
            parameters=(),
            has_prototype=None,
            is_definition=True,
            provenance="source_written",
            location=location,
            span=None,
            owner_usr=None,
            owner_name=None,
            owner_location=None,
            owner_kind=None,
            access=None,
            source_text=line_text,
            documentation=documentation,
            documentation_location=doc_location,
            documentation_span=None,
            enum_ordinal=None,
            is_file_scope=True,
        )

    latest_doc_offset = source_bytes.index(b"/// Latest namespace docs.")
    declarations = (
        namespace_row(
            usr="c:@N@alias_case",
            name="alias_case",
            qualified_name="alias_case",
            line_text="namespace alias_case {}",
        ),
        namespace_row(
            usr="c:@N@alias_case",
            name="alias_case",
            qualified_name="alias_case",
            line_text="namespace alias_case { int second; }",
            documentation="Latest namespace docs.",
            documentation_offset=latest_doc_offset,
        ),
        namespace_row(
            usr="c:@N@left@N@nested",
            name="nested",
            qualified_name="left::nested",
            line_text="namespace left { namespace nested {} }",
        ),
        namespace_row(
            usr="c:@N@right@N@nested",
            name="nested",
            qualified_name="right::nested",
            line_text="namespace right { namespace nested {} }",
        ),
        namespace_row(
            usr="c:@aN@reopened.cpp@",
            name="(anonymous namespace)",
            qualified_name="(anonymous namespace)",
            line_text="namespace { int first_anonymous; }",
        ),
        namespace_row(
            usr="c:@aN@reopened.cpp@",
            name="(anonymous namespace)",
            qualified_name="(anonymous namespace)",
            line_text="namespace { int second_anonymous; }",
        ),
        namespace_row(
            usr="c:@N@left@aN@reopened.cpp@",
            name="(anonymous namespace)",
            qualified_name="left::(anonymous namespace)",
            line_text="namespace left { namespace { } }",
        ),
        namespace_row(
            usr="c:@N@right@aN@reopened.cpp@",
            name="(anonymous namespace)",
            qualified_name="right::(anonymous namespace)",
            line_text="namespace right { namespace { } }",
        ),
    )
    result = SimpleNamespace(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        declarations=declarations,
        callables=(),
        diagnostics=(),
        includes=(),
        preprocessing=(),
        documentation_comments=(),
        profile_identity="namespace-reopen-test-profile",
        cache_fingerprint="namespace-reopen-test-fingerprint",
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
    namespaces = [item for item in analysis.declarations if item.kind == "namespace"]
    assert [item.name for item in namespaces] == [
        "alias_case",
        "left::nested",
        "right::nested",
        "(anonymous namespace)",
        "left::(anonymous namespace)",
        "right::(anonymous namespace)",
    ]
    reopened = next(item for item in namespaces if item.name == "alias_case")
    assert reopened.lineno == 3
    assert reopened.signature == "namespace alias_case { int second; }"
    namespace_docs = [
        item
        for item in analysis.documentation
        if item.owner_stable_id == reopened.stable_id
    ]
    assert len(namespace_docs) == 1
    assert namespace_docs[0].lineno == 2
    assert namespace_docs[0].text == "Latest namespace docs."
    assert len({item.stable_id for item in namespaces}) == len(namespaces)


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
        has_body=True,
        signature_kind="derived_display_only",
        linkage_kind="external",
        linker_symbol=None,
        explicit_linkage_label=None,
        linkage_label_inherited=None,
        alias_target_symbol=None,
        alias_target_usr=None,
        alias_binding_status="not_alias",
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


def test_cpp_clang_projection_persists_observed_macro_callable_evidence(
    tmp_path: Path,
) -> None:
    """Persist matched C++ macro callable facts and retain namespace identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C++ translation unit.

    Returns
    -------
    None
        The test checks the invocation, profile identity, USR, calls, and origin.
    """
    source = tmp_path / "macro.cpp"
    source.write_text(
        "namespace parity {\n"
        "#define CPP_GENERATE(name, label) int name() { return helper(); }\n"
        'CPP_GENERATE(generated, "café")\n'
        "}\n",
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()
    invocation_text = 'CPP_GENERATE(generated, "café")'
    invocation_bytes = invocation_text.encode("utf-8")
    invocation_start = source_bytes.index(invocation_bytes)
    invocation_end = invocation_start + len(invocation_bytes) - 1
    name_offset = source_bytes.index(b"generated")
    helper_offset = source_bytes.index(b"helper")

    def source_point(offset: int) -> SourcePoint:
        """Build a compiler-compatible source point from a fixture byte offset.

        Parameters
        ----------
        offset : int
            Zero-based byte offset in the translation unit.

        Returns
        -------
        codira_clang_frontend.contracts.SourcePoint
            Point with spelling and expansion coordinates at the same byte.
        """
        prefix = source_bytes[:offset]
        position = SourcePosition(
            path=str(source),
            line=prefix.count(b"\n") + 1,
            column=offset - prefix.rfind(b"\n"),
            offset=offset,
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=False)

    invocation_point = source_point(invocation_start)
    callable_location = SourcePoint(
        spelling=source_point(name_offset).spelling,
        expansion=invocation_point.expansion,
        is_macro=True,
    )
    helper_location = SourcePoint(
        spelling=source_point(helper_offset).spelling,
        expansion=invocation_point.expansion,
        is_macro=True,
    )
    body_start_offset = source_bytes.index(b"int name")
    body_end_offset = source_bytes.index(b"}", body_start_offset)
    body_start = source_point(body_start_offset)
    body_end = source_point(body_end_offset)
    callable_span = SourceSpan(
        begin=SourcePoint(
            spelling=body_start.spelling,
            expansion=invocation_point.expansion,
            is_macro=True,
        ),
        end=SourcePoint(
            spelling=body_end.spelling,
            expansion=source_point(invocation_end).expansion,
            is_macro=True,
        ),
    )
    event = SimpleNamespace(
        kind="macro_expansion",
        name="CPP_GENERATE",
        invocation=invocation_text,
        location=invocation_point,
        span=SourceSpan(
            begin=invocation_point,
            end=source_point(invocation_end),
        ),
    )
    call = SimpleNamespace(
        target="helper",
        qualified_target="helper",
        target_usr="c:@N@parity@F@helper#",
        origin="macro_replacement",
        location=helper_location,
    )
    callable_item = SimpleNamespace(
        usr="c:@N@parity@F@generated#",
        kind="function",
        name="generated",
        qualified_name="parity::generated",
        lexical_owner="parity",
        decl_kind="Function",
        signature="int parity::generated()",
        function_type="int ()",
        parameters=(),
        has_prototype=True,
        is_definition=True,
        is_public=True,
        provenance="macro_argument",
        location=callable_location,
        span=callable_span,
        calls=(call,),
        returns_value=True,
        is_variadic=False,
        owner_usr="c:@N@parity",
        owner_location=source_point(source_bytes.index(b"parity")),
        qualifiers=SimpleNamespace(is_method=False),
        has_body=True,
        signature_kind="derived_display_only",
        linkage_kind="external",
        linker_symbol=None,
        explicit_linkage_label=None,
        linkage_label_inherited=None,
        alias_target_symbol=None,
        alias_target_usr=None,
        alias_binding_status="not_alias",
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    result = SimpleNamespace(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        declarations=(),
        callables=(callable_item,),
        diagnostics=(),
        includes=(),
        preprocessing=(event,),
        documentation_comments=(),
        profile_identity="clang-cpp-profile-r1",
        cache_fingerprint="inner-frontend-cache-fingerprint",
        toolchain_identity=None,
        compilation_context=None,
        dependency_closure=SimpleNamespace(
            status="complete",
            files=(SimpleNamespace(path=source, sha256=source_sha256),),
            sha256="f" * 64,
        ),
        stdout_path=None,
        stdout_sha256="a" * 64,
        stderr_path=None,
        stderr_sha256="b" * 64,
        unowned_calls=(),
    )
    context_identity = '{"schema":"files-input-fingerprint-v1","id":"captured"}'

    analysis = cpp_analyzer_module._analysis_from_clang_result(
        source,
        tmp_path,
        cast("FrontendResult", result),
        context_identity=context_identity,
    )

    assert analysis is not None
    assert analysis.status is not None
    assert analysis.status.omitted_categories == ()
    function = analysis.functions[0]
    assert function.name == "parity::generated"
    assert function.lineno == 3
    assert function.semantic_identity is not None
    assert function.semantic_identity.value == "c:@N@parity@F@generated#"
    assert isinstance(function.generated, CompilerObservedCallableProvenance)
    assert function.generated.origin == "macro_argument"
    assert function.generated.source_sha256 == source_sha256
    assert function.generated.context_identity == context_identity
    assert function.generated.invocation is not None
    assert function.generated.invocation.path == "macro.cpp"
    assert function.generated.invocation.byte_range == (
        invocation_start,
        invocation_start + len(invocation_bytes),
    )
    assert function.generated.invocation.text == invocation_text
    receipt = json.loads(function.generated.receipt_json)
    assert receipt["context"]["cache_fingerprint"] == result.cache_fingerprint
    native_observation = receipt["callable"]["native_observation"]
    assert native_observation["signature_kind"] == "derived_display_only"
    assert native_observation["explicit_linkage_label"] is None
    assert native_observation["linkage_label_inherited"] is None
    assert receipt["callable"]["span"]["begin"]["spelling"]["path"] == str(source)
    assert receipt["callable"]["span"]["begin"]["spelling"]["line"] == 2
    assert receipt["callable"]["span"]["begin"]["spelling"]["offset"] == (
        body_start_offset
    )
    assert receipt["callable"]["span"]["begin"]["expansion"]["offset"] == (
        invocation_start
    )
    assert receipt["callable"]["span"]["end"]["spelling"]["offset"] == (body_end_offset)
    assert receipt["callable"]["owner_usr"] == "c:@N@parity"
    assert len(function.calls) == 1
    assert function.calls[0].target_identity is not None
    assert function.calls[0].target_identity.value == "c:@N@parity@F@helper#"


def test_cpp_clang_header_owner_selection_config_is_strict() -> None:
    """Accept only normalized repository-relative explicit profile selections.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test verifies the additive Clang header selection contract.
    """
    analyzer = CppAnalyzer()
    analyzer.configure(
        {
            "frontend": "clang",
            "clang_header_owner_profiles": {"include/api.h": "captured-profile"},
        }
    )

    assert analyzer._clang_header_owner_profiles == {
        "include/api.h": "captured-profile"
    }
    invalid: object
    for invalid in (
        {"../api.h": "profile"},
        {"/include/api.h": "profile"},
        {"include\\api.h": "profile"},
        {"include/api.h": ""},
        [],
    ):
        with pytest.raises(ValueError, match="clang_header_owner_profiles"):
            CppAnalyzer().configure(
                {"frontend": "clang", "clang_header_owner_profiles": invalid}
            )


def test_cpp_clang_unowned_header_is_claimed_only_as_held(tmp_path: Path) -> None:
    """Route an unresolved header to a non-indexable partial C++ result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test verifies ambiguous routing does not emit heuristic symbols.
    """
    header = tmp_path / "include" / "api.h"
    header.parent.mkdir()
    header.write_text("int declared(void);\n", encoding="utf-8")
    analyzer = CppAnalyzer()
    analyzer.configure({"frontend": "clang"})

    result = analyzer.analyze_file(header, tmp_path)

    assert analyzer.allows_path(header, tmp_path) is True
    assert result.index_symbols is False
    assert result.functions == ()
    assert result.declarations == ()
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_cpp_clang_projection_attaches_documentation_to_qualified_prototype(
    tmp_path: Path,
) -> None:
    """Retain documentation attached to a namespaced header prototype.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the projected header.

    Returns
    -------
    None
        The test checks the native response decoder and documentation mapping.
    """
    source = tmp_path / "api.hpp"
    source_text = (
        "namespace api {\n/// Transform the input.\nint transform(int value);\n}\n"
    )
    source.write_text(source_text, encoding="utf-8")
    comment = {
        "text": "Transform the input.",
        "location": {
            "spelling": {"path": str(source), "line": 2, "column": 1, "offset": 18},
            "expansion": {"path": str(source), "line": 2, "column": 1, "offset": 18},
            "is_macro": False,
        },
        "range": {
            "begin": {
                "spelling": {"path": str(source), "line": 2, "column": 1, "offset": 18},
                "expansion": {
                    "path": str(source),
                    "line": 2,
                    "column": 1,
                    "offset": 18,
                },
                "is_macro": False,
            },
            "end": {
                "spelling": {
                    "path": str(source),
                    "line": 2,
                    "column": 24,
                    "offset": 41,
                },
                "expansion": {
                    "path": str(source),
                    "line": 2,
                    "column": 24,
                    "offset": 41,
                },
                "is_macro": False,
            },
        },
    }
    response = {
        "declarations": [
            {
                "decl_kind": "function",
                "documentation": "Transform the input.",
                "documentation_location": comment["location"],
                "documentation_range": comment["range"],
                "function_type": "int (int)",
                "has_prototype": True,
                "identity": {
                    "decl_kind": "function",
                    "kind": "written",
                    "provenance": "source_written",
                    "usr": "c:@N@api@F@transform#I#",
                },
                "is_definition": False,
                "is_public": True,
                "lexical_owner": "api",
                "location": {
                    "spelling": {
                        "path": str(source),
                        "line": 3,
                        "column": 5,
                        "offset": 43,
                    },
                    "expansion": {
                        "path": str(source),
                        "line": 3,
                        "column": 5,
                        "offset": 43,
                    },
                    "is_macro": False,
                },
                "method_qualifiers": {"is_method": False},
                "name": "transform",
                "native_decl_kind": "Function",
                "owner_usr": "c:@N@api",
                "parameters": [{"name": "value", "type": "int", "location": None}],
                "qualified_name": "api::transform",
                "range": {
                    "begin": {
                        "spelling": {
                            "path": str(source),
                            "line": 3,
                            "column": 1,
                            "offset": 39,
                        },
                        "expansion": {
                            "path": str(source),
                            "line": 3,
                            "column": 1,
                            "offset": 39,
                        },
                        "is_macro": False,
                    },
                    "end": {
                        "spelling": {
                            "path": str(source),
                            "line": 3,
                            "column": 29,
                            "offset": 67,
                        },
                        "expansion": {
                            "path": str(source),
                            "line": 3,
                            "column": 29,
                            "offset": 67,
                        },
                        "is_macro": False,
                    },
                },
                "returns_value": False,
                "signature": "int api::transform(int value)",
            }
        ],
        "non_function_declarations": [],
        "calls": [],
        "documentation_comments": [comment],
    }
    declarations, callables, _ = _decode_entities(response)
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=declarations,
        callables=callables,
        dependency_closure=None,
        profile_identity="header-profile",
        toolchain_identity=None,
        cache_fingerprint="header-fingerprint",
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
        documentation_comments=_decode_documentation_comments([comment]),
    )

    analysis = cpp_analyzer_module._analysis_from_clang_result(source, tmp_path, result)

    assert analysis is not None
    assert [(item.name, item.docstring) for item in analysis.functions] == [
        ("api::transform", "Transform the input.")
    ]
    assert [
        (item.title, item.lineno, item.text, item.owner_stable_id)
        for item in analysis.documentation
    ] == [
        ("api::transform", 2, "Transform the input.", analysis.functions[0].stable_id)
    ]
