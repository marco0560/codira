"""Package-local tests for the first-party C analyzer distribution."""

from __future__ import annotations

import pytest

import hashlib
import json
from types import SimpleNamespace
from codira.generated import (
    CompilerObservedCallableProvenance,
    generated_provenance_payload,
    generated_provenance_rows,
)
from codira.models import (
    AnalysisResult,
    DeclarationArtifact,
    DocumentationArtifact,
    FunctionArtifact,
    ImportArtifact,
    ModuleArtifact,
)
from codira_clang_frontend.contracts import (
    DependencyClosure,
    DependencyInput,
    FrontendPreprocessorEvent,
    SourceSpan,
)

from dataclasses import asdict
import tomllib
from pathlib import Path


import codira_analyzer_c as c_analyzer_module
from codira_analyzer_c import CAnalyzer, _analysis_from_clang_result, build_analyzer
from codira_clang_frontend.frontend import _decode_entities
from codira_clang_frontend.contracts import (
    FrontendCallable,
    FrontendCall,
    FrontendDeclaration,
    FrontendResult,
    SourcePoint,
    SourcePosition,
)


def test_c_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "2.0.22"
    assert "codira>=2.0.0,<3.0.0" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "c": "codira_analyzer_c:build_analyzer"
    }


def test_c_package_builds_expected_analyzer() -> None:
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

    assert isinstance(analyzer, CAnalyzer)
    assert analyzer.name == "c"
    assert analyzer.version == "31"


def test_c_clang_frontend_is_opt_in_and_missing_profile_is_visible(
    tmp_path: Path,
) -> None:
    """Keep the Tree-sitter default and surface missing Clang context.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C source file.

    Returns
    -------
    None
        The test checks the opt-in schema and explicit fallback status.
    """
    source = tmp_path / "sample.c"
    source.write_text("int run(void) { return 7; }\n", encoding="utf-8")

    analyzer = CAnalyzer()
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
    """Build normalized C artifacts for frontend-option routing tests.

    Parameters
    ----------
    path : pathlib.Path
        Source path assigned to each test artifact.

    Returns
    -------
    codira.models.AnalysisResult
        C analysis containing each output category affected by Clang options.
    """
    function = FunctionArtifact(
        name="run",
        stable_id="c:function:run",
        lineno=1,
        end_lineno=1,
        signature="int run(void)",
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
    documentation = DocumentationArtifact(
        stable_id="doc:function:run",
        kind="declaration",
        source_format="doxygen",
        source_path=path,
        lineno=1,
        end_lineno=1,
        title="run",
        heading_path=(),
        text="Run docs",
        owner_stable_id=function.stable_id,
        owner_kind="function",
        attachment_confidence="explicit",
    )
    return AnalysisResult(
        source_path=path,
        module=ModuleArtifact("sample", "c:module:sample", "File docs", 1),
        classes=(),
        functions=(function,),
        declarations=(
            DeclarationArtifact(
                "PROJECT_MACRO", "macro:project", "macro", 1, "#define PROJECT_MACRO 1"
            ),
            DeclarationArtifact(
                "VALUE",
                "c:constant:VALUE",
                "constant",
                1,
                "int VALUE",
                docstring="Value docs",
            ),
        ),
        imports=(
            ImportArtifact("stdio.h", None, 1, "include_system"),
            ImportArtifact("local.h", None, 1, "include_local"),
        ),
        documentation=(documentation,),
    )


def test_c_clang_route_applies_output_options(
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
        The test verifies filters for comments, macros, imports, and docs.
    """
    source = tmp_path / "sample.c"
    source.write_text("int run(void) { return 1; }\n", encoding="utf-8")
    expected = _clang_output_options_fixture(source)
    fake_frontend_result = SimpleNamespace(callables=(), declarations=())
    analyzer = CAnalyzer()
    analyzer.configure(
        {
            "frontend": "clang",
            "use_leading_comments": False,
            "include_system_includes": False,
            "emit_macros": False,
        }
    )
    monkeypatch.setattr(
        analyzer,
        "_try_clang_frontend",
        lambda _path, _root: (fake_frontend_result, ""),
    )
    monkeypatch.setattr(
        c_analyzer_module,
        "_analysis_from_clang_result",
        lambda _path, _root, _result, *, context_identity=None: expected,
    )

    analysis = analyzer.analyze_file(source, tmp_path)

    assert analysis.module.docstring is None
    assert analysis.module.has_docstring == 0
    assert analysis.functions[0].docstring is None
    assert analysis.functions[0].has_docstring == 0
    assert [item.kind for item in analysis.declarations] == ["constant"]
    assert analysis.declarations[0].docstring is None
    assert [item.kind for item in analysis.imports] == ["include_local"]
    assert [item.title for item in analysis.documentation] == ["run"]


def test_c_clang_doxygen_option_keeps_semantic_docstrings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disable Doxygen artifacts without clearing artifact docstring fields.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source path used by the mocked Clang route.
    monkeypatch : pytest.MonkeyPatch
        Replaces profile execution and native mapping with fixed normalized facts.

    Returns
    -------
    None
        The test checks independent behavior of documentation output toggles.
    """
    source = tmp_path / "sample.c"
    source.write_text("int run(void) { return 1; }\n", encoding="utf-8")
    expected = _clang_output_options_fixture(source)
    fake_frontend_result = SimpleNamespace(callables=(), declarations=())
    analyzer = CAnalyzer()
    analyzer.configure({"frontend": "clang", "emit_doxygen_documentation": False})
    monkeypatch.setattr(
        analyzer,
        "_try_clang_frontend",
        lambda _path, _root: (fake_frontend_result, ""),
    )
    monkeypatch.setattr(
        c_analyzer_module,
        "_analysis_from_clang_result",
        lambda _path, _root, _result, *, context_identity=None: expected,
    )

    analysis = analyzer.analyze_file(source, tmp_path)

    assert analysis.documentation == ()
    assert analysis.functions[0].docstring == "Run docs"
    assert analysis.module.docstring == "File docs"


def test_c_clang_projection_emits_fields_only_for_file_scope_records(
    tmp_path: Path,
) -> None:
    """Project source-written C fields with their physical owner identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing the C translation unit and a header.

    Returns
    -------
    None
        The test checks struct/union fields, types, owner IDs, and exclusions.
    """
    source = tmp_path / "sample.c"
    header = tmp_path / "external.h"
    source.write_text(
        "struct StructOwner {\n    int value;\n};\n"
        "union UnionOwner {\n    unsigned code;\n};\n"
        "void local_scope(void) { struct LocalOwner { long hidden; }; }\n",
        encoding="utf-8",
    )
    header.write_text(
        "struct HeaderOwner {\n    int header_field;\n};\n", encoding="utf-8"
    )

    def source_point(path: Path, line: int, column: int) -> SourcePoint:
        """Build a physical, nonmacro source location for one fixture row.

        Parameters
        ----------
        path : pathlib.Path
            Physical source file containing the declaration.
        line : int
            One-based source line.
        column : int
            One-based source column.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Spelling and expansion positions at the same source coordinate.
        """
        position = SourcePosition(
            path=str(path), line=line, column=column, offset=line * 10 + column
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=False)

    def declaration(
        *,
        usr: str,
        kind: str,
        name: str,
        qualified_name: str,
        decl_kind: str,
        location: SourcePoint,
        is_file_scope: bool,
        type_text: str | None = None,
        owner_usr: str | None = None,
        owner_name: str | None = None,
        owner_kind: str | None = None,
    ) -> FrontendDeclaration:
        """Build one minimal typed Clang declaration fixture row.

        Parameters
        ----------
        usr : str
            Compiler identity for the row.
        kind, name, qualified_name, decl_kind : str
            Normalized and Clang declaration labels.
        location : codira_clang_frontend.SourcePoint
            Physical declaration location.
        is_file_scope : bool
            Whether this row belongs to the translation-unit scope.
        type_text : str or None, optional
            Clang-reported declaration type.
        owner_usr, owner_name, owner_kind : str or None, optional
            Compiler-reported semantic owner facts for fields.

        Returns
        -------
        codira_clang_frontend.FrontendDeclaration
            Immutable source-written declaration fixture.
        """
        native_row = {
            "identity": {"usr": usr, "provenance": "source_written"},
            "entity_kind": "variable" if decl_kind == "Field" else kind,
            "name": name,
            "qualified_name": qualified_name,
            "decl_kind": decl_kind,
            "type": type_text,
            "is_definition": True,
            "location": asdict(location),
            "owner_usr": owner_usr,
            "owner_name": owner_name,
            "owner_kind": owner_kind,
            "is_file_scope": is_file_scope,
        }
        decoded, _, _ = _decode_entities({"non_function_declarations": [native_row]})
        if decl_kind == "Field":
            assert decoded[0].kind == "variable"
            assert decoded[0].decl_kind == "Field"
        return decoded[0]

    struct_usr = "c:@S@StructOwner"
    union_usr = "c:@U@UnionOwner"
    local_usr = "c:@S@LocalOwner"
    declarations = (
        declaration(
            usr=struct_usr,
            kind="struct",
            name="StructOwner",
            qualified_name="StructOwner",
            decl_kind="Record",
            location=source_point(source, 1, 8),
            is_file_scope=True,
        ),
        declaration(
            usr="c:@S@StructOwner@FI@value",
            kind="field",
            name="value",
            qualified_name="StructOwner::value",
            decl_kind="Field",
            location=source_point(source, 2, 9),
            is_file_scope=False,
            type_text="int",
            owner_usr=struct_usr,
            owner_name="StructOwner",
            owner_kind="Record",
        ),
        declaration(
            usr=union_usr,
            kind="union",
            name="UnionOwner",
            qualified_name="UnionOwner",
            decl_kind="Record",
            location=source_point(source, 4, 7),
            is_file_scope=True,
        ),
        declaration(
            usr="c:@U@UnionOwner@FI@code",
            kind="field",
            name="code",
            qualified_name="UnionOwner::code",
            decl_kind="Field",
            location=source_point(source, 5, 14),
            is_file_scope=False,
            type_text="unsigned int",
            owner_usr=union_usr,
            owner_name="UnionOwner",
            owner_kind="Record",
        ),
        declaration(
            usr=local_usr,
            kind="struct",
            name="LocalOwner",
            qualified_name="LocalOwner",
            decl_kind="Record",
            location=source_point(source, 6, 31),
            is_file_scope=False,
        ),
        declaration(
            usr="c:@S@LocalOwner@FI@hidden",
            kind="field",
            name="hidden",
            qualified_name="LocalOwner::hidden",
            decl_kind="Field",
            location=source_point(source, 6, 50),
            is_file_scope=False,
            type_text="long",
            owner_usr=local_usr,
            owner_name="LocalOwner",
            owner_kind="Record",
        ),
        declaration(
            usr="c:@S@HeaderOwner@FI@header_field",
            kind="field",
            name="header_field",
            qualified_name="HeaderOwner::header_field",
            decl_kind="Field",
            location=source_point(header, 2, 9),
            is_file_scope=False,
            type_text="int",
            owner_usr="c:@S@HeaderOwner",
            owner_name="HeaderOwner",
            owner_kind="Record",
        ),
    )
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=declarations,
        callables=(),
        dependency_closure=None,
        profile_identity="test-profile",
        toolchain_identity=None,
        cache_fingerprint="test-fingerprint",
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
    )

    analysis = _analysis_from_clang_result(source, tmp_path, result)

    assert analysis is not None
    variables = [item for item in analysis.declarations if item.kind == "variable"]
    assert [
        (item.name, item.type_text, item.owner_name, item.lineno) for item in variables
    ] == [
        ("StructOwner::value", "int", "StructOwner", 2),
        ("UnionOwner::code", "unsigned int", "UnionOwner", 5),
    ]
    owner_ids = {item.name: item.stable_id for item in analysis.declarations}
    assert variables[0].owner_stable_id == owner_ids["StructOwner"]
    assert variables[1].owner_stable_id == owner_ids["UnionOwner"]
    assert all(item.access is None for item in variables)


def test_c_clang_projection_uses_spelling_for_macro_arguments_and_expansion_for_replacement(
    tmp_path: Path,
) -> None:
    """Keep source-written macro arguments at their spelling coordinates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C translation unit.

    Returns
    -------
    None
        The test checks call columns for argument and replacement origins.
    """
    source = tmp_path / "calls.c"
    source.write_text(
        "int invoke(void) { return argument_call() + replacement_call(); }\n",
        encoding="utf-8",
    )

    def point(spelling_column: int, expansion_column: int) -> SourcePoint:
        """Build a macro-derived source point with distinct origins.

        Parameters
        ----------
        spelling_column : int
            One-based spelling coordinate for the call token.
        expansion_column : int
            One-based macro expansion coordinate for the call token.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Source point retaining both native coordinates.
        """
        spelling = SourcePosition(
            path=str(source), line=1, column=spelling_column, offset=spelling_column
        )
        expansion = SourcePosition(
            path=str(source), line=1, column=expansion_column, offset=expansion_column
        )
        return SourcePoint(spelling=spelling, expansion=expansion, is_macro=True)

    callable_item = FrontendCallable(
        usr="c:@F@invoke",
        kind="function",
        name="invoke",
        qualified_name="invoke",
        lexical_owner=None,
        decl_kind="Function",
        signature="int invoke(void)",
        function_type="int (void)",
        parameters=(),
        has_prototype=True,
        is_definition=True,
        is_public=True,
        provenance="source_written",
        location=point(5, 5),
        span=None,
        calls=(
            FrontendCall(
                target="argument_call",
                qualified_target="argument_call",
                target_usr="c:@F@argument_call",
                caller_usr="c:@F@invoke",
                caller_name="invoke",
                caller_qualified_name="invoke",
                origin="macro_argument",
                location=point(30, 11),
                span=None,
            ),
            FrontendCall(
                target="replacement_call",
                qualified_target="replacement_call",
                target_usr="c:@F@replacement_call",
                caller_usr="c:@F@invoke",
                caller_name="invoke",
                caller_qualified_name="invoke",
                origin="macro_replacement",
                location=point(50, 61),
                span=None,
            ),
        ),
    )
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=(),
        callables=(callable_item,),
        dependency_closure=None,
        profile_identity="test-profile",
        toolchain_identity=None,
        cache_fingerprint="test-fingerprint",
        stdout_path=None,
        stdout_sha256=None,
        stderr_path=None,
        stderr_sha256=None,
    )

    analysis = _analysis_from_clang_result(source, tmp_path, result)

    assert analysis is not None
    assert [(call.target, call.col_offset) for call in analysis.functions[0].calls] == [
        ("argument_call", 29),
        ("replacement_call", 60),
    ]


def test_c_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply C analyzer documentation, import, and macro toggles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured options prune optional C artifacts.
    """

    source = tmp_path / "src" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        "/// Module docs.\n"
        "#include <stdio.h>\n"
        "#define VALUE 1\n"
        "/// Function docs.\n"
        "int run(void) { return VALUE; }\n",
        encoding="utf-8",
    )

    analyzer = CAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "include_paths": ["src"],
            "use_leading_comments": False,
            "emit_doxygen_documentation": False,
            "include_system_includes": False,
            "emit_macros": False,
        }
    )
    analysis = analyzer.analyze_file(source, tmp_path)

    assert "emit_macros" in properties
    assert analyzer.allows_path(source, tmp_path) is True
    assert analysis.module.docstring is None
    assert analysis.imports == ()
    assert analysis.documentation == ()
    assert all(declaration.kind != "macro" for declaration in analysis.declarations)


def test_c_analyzer_emits_doxygen_documentation_only(tmp_path: Path) -> None:
    """
    Keep C documentation artifacts scoped to explicit Doxygen comments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts Doxygen comments produce documentation artifacts while
        ordinary comments do not.
    """
    source = tmp_path / "sample.c"
    source.write_text(
        "\n".join(
            (
                "/// Adds one to the value.",
                "int documented(int value) { return value + 1; }",
                "",
                "// Ordinary implementation note.",
                "int undocumented(int value) { return value; }",
            )
        ),
        encoding="utf-8",
    )

    analysis = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (doc.title, doc.source_format, doc.owner_kind) for doc in analysis.documentation
    ] == [("documented", "doxygen", "function")]
    assert analysis.documentation[0].text == "Adds one to the value."
    assert analysis.documentation[0].attachment_confidence == "explicit"


def test_c_clang_projection_persists_observed_macro_callable_evidence(
    tmp_path: Path,
) -> None:
    """Persist matched macro callable evidence without token reconstruction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing one C translation unit.

    Returns
    -------
    None
        The test checks source/profile facts, invocation bytes, callable identity,
        calls, and physical invocation coordinates.
    """
    source = tmp_path / "macro.c"
    source.write_text(
        "void helper(void);\n"
        "#define C_GENERATE(name, label) int name(void) { return helper(); }\n"
        'C_GENERATE(generated, "café")\n',
        encoding="utf-8",
    )
    source_bytes = source.read_bytes()
    invocation_text = 'C_GENERATE(generated, "café")'
    invocation_bytes = invocation_text.encode("utf-8")
    invocation_start = source_bytes.index(invocation_bytes)
    invocation_end = invocation_start + len(invocation_bytes) - 1
    name_offset = source_bytes.index(b"generated")
    helper_offset = source_bytes.index(b"helper")

    def source_point(offset: int) -> SourcePoint:
        """Build one source point from a known fixture byte offset.

        Parameters
        ----------
        offset : int
            Zero-based byte offset in the translation unit.

        Returns
        -------
        codira_clang_frontend.SourcePoint
            Physical spelling and expansion positions at the requested byte.
        """
        prefix = source_bytes[:offset]
        line = prefix.count(b"\n") + 1
        column = offset - prefix.rfind(b"\n")
        position = SourcePosition(
            path=str(source), line=line, column=column, offset=offset
        )
        return SourcePoint(spelling=position, expansion=position, is_macro=False)

    invocation_point = source_point(invocation_start)
    callable_location = SourcePoint(
        spelling=source_point(name_offset).spelling,
        expansion=invocation_point.expansion,
        is_macro=True,
    )
    call_location = SourcePoint(
        spelling=source_point(helper_offset).spelling,
        expansion=invocation_point.expansion,
        is_macro=True,
    )
    body_start = source_point(source_bytes.index(b"int name"))
    body_end = source_point(source_bytes.index(b"}", source_bytes.index(b"int name")))
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
    event = FrontendPreprocessorEvent(
        kind="macro_expansion",
        name="C_GENERATE",
        replacement=(),
        replacement_truncated=False,
        function_like=True,
        parameters=("name", "label"),
        source_text=None,
        condition=None,
        result=None,
        macro_defined=None,
        invocation=invocation_text,
        location=invocation_point,
        span=SourceSpan(
            begin=invocation_point,
            end=source_point(invocation_end),
        ),
    )
    callable_item = FrontendCallable(
        usr="c:@F@generated",
        kind="function",
        name="generated",
        qualified_name="generated",
        lexical_owner=None,
        decl_kind="Function",
        signature="int generated(void)",
        function_type="int (void)",
        parameters=(),
        has_prototype=True,
        is_definition=True,
        is_public=True,
        provenance="macro_argument",
        location=callable_location,
        span=callable_span,
        calls=(
            FrontendCall(
                target="helper",
                qualified_target="helper",
                target_usr="c:@F@helper",
                caller_usr="c:@F@generated",
                caller_name="generated",
                caller_qualified_name="generated",
                origin="macro_replacement",
                location=call_location,
                span=None,
            ),
        ),
    )
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    result = FrontendResult(
        status="parsed",
        coverage_state="complete",
        reasons=(),
        diagnostics=(),
        declarations=(),
        callables=(callable_item,),
        dependency_closure=DependencyClosure(
            status="complete",
            files=(DependencyInput(path=source, sha256=source_sha256),),
            sha256="f" * 64,
        ),
        profile_identity="clang-profile-r1",
        toolchain_identity=None,
        cache_fingerprint="inner-frontend-cache-fingerprint",
        stdout_path=None,
        stdout_sha256="a" * 64,
        stderr_path=None,
        stderr_sha256="b" * 64,
        preprocessing=(event,),
    )
    context_identity = '{"schema":"files-input-fingerprint-v1","id":"captured"}'

    analysis = _analysis_from_clang_result(
        source,
        tmp_path,
        result,
        context_identity=context_identity,
    )

    assert analysis is not None
    assert analysis.status is not None
    assert analysis.status.omitted_categories == ()
    function = analysis.functions[0]
    assert function.lineno == 3
    assert function.semantic_identity is not None
    assert function.semantic_identity.value == "c:@F@generated"
    assert isinstance(function.generated, CompilerObservedCallableProvenance)
    assert function.generated.origin == "macro_argument"
    assert function.generated.role == "definition"
    assert function.generated.source_sha256 == source_sha256
    assert function.generated.context_identity == context_identity
    assert function.generated.invocation is not None
    assert function.generated.invocation.name == "C_GENERATE"
    assert function.generated.invocation.path == "macro.c"
    assert function.generated.invocation.byte_range == (
        invocation_start,
        invocation_start + len(invocation_bytes),
    )
    assert function.generated.invocation.text == invocation_text
    assert function.generated.receipt_namespace == (
        "clang.frontend.callable-observation.v1"
    )
    assert (
        json.loads(function.generated.receipt_json)["context"]["cache_fingerprint"]
        == result.cache_fingerprint
    )
    callable_receipt = json.loads(function.generated.receipt_json)["callable"]
    assert callable_receipt["span"]["begin"]["spelling"]["path"] == str(source)
    assert callable_receipt["span"]["begin"]["spelling"]["line"] == 2
    assert callable_receipt["span"]["begin"]["spelling"][
        "offset"
    ] == source_bytes.index(b"int name")
    assert callable_receipt["span"]["begin"]["expansion"]["offset"] == (
        invocation_start
    )
    assert callable_receipt["span"]["end"]["spelling"]["offset"] == source_bytes.index(
        b"}", source_bytes.index(b"int name")
    )
    generated_rows = generated_provenance_rows(analysis)
    assert len(generated_rows) == 1
    assert generated_provenance_payload(generated_rows[0][1])["context_identity"] == (
        context_identity
    )
    assert len(function.calls) == 1
    assert function.calls[0].target_identity is not None
    assert function.calls[0].target_identity.value == "c:@F@helper"


def test_c_clang_header_owner_selection_config_is_strict() -> None:
    """Accept only normalized repository-relative explicit profile selections.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test verifies the additive Clang header selection contract.
    """
    analyzer = CAnalyzer()
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
            CAnalyzer().configure(
                {"frontend": "clang", "clang_header_owner_profiles": invalid}
            )


def test_c_clang_header_without_captured_owner_is_not_claimed_and_is_held(
    tmp_path: Path,
) -> None:
    """Keep an unowned header explicit and prevent speculative C extraction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test verifies unresolved Clang headers are not indexed as C facts.
    """
    header = tmp_path / "include" / "api.h"
    header.parent.mkdir()
    header.write_text("int declared(void);\n", encoding="utf-8")
    analyzer = CAnalyzer()
    analyzer.configure({"frontend": "clang"})

    result = analyzer.analyze_file(header, tmp_path)

    assert analyzer.allows_path(header, tmp_path) is False
    assert result.index_symbols is False
    assert result.functions == ()
    assert result.declarations == ()
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
