"""Package-local tests for the first-party C analyzer distribution."""

from __future__ import annotations

from dataclasses import asdict
import tomllib
from pathlib import Path

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

    assert project["project"]["version"] == "2.0.16"
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
    assert analyzer.version == "25"


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
