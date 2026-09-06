"""Tests for ADR-004 Phase 3 contract and normalization models.

Responsibilities
----------------
- Verify analyzer and backend contracts using fake implementations that hook into the existing registry.
- Ensure normalization from parser output produces the expected AnalysisResult artifacts and deterministic module data.
- Validate registry discovery, analyzer selection, and backend initialization invariants.

Design principles
-----------------
Tests rely on stub analyzers/backends and explicit fixtures so contract violations surface as deterministic failures.

Architectural role
------------------
This module belongs to the **contract verification layer** and enforces the ADR-004 Phase 3 language analyzer and backend APIs.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from codira_analyzer_bash import BashAnalyzer
from codira_analyzer_c import CAnalyzer, _disambiguate_function_stable_ids
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_python import PythonAnalyzer
from codira_backend_sqlite import SQLiteIndexBackend
from codira_backend_sqlite.schema import SCHEMA_VERSION
from codira_backend_sqlite.sqlite_storage import get_db_path

import codira.contracts_backend_requests as backend_requests_module
import codira.registry as registry_module
from codira.contracts import (
    BackendDocumentationCandidatesRequest,
    BackendEmbeddingCandidatesRequest,
    BackendPersistAnalysisRequest,
    BackendRelationQueryRequest,
    BackendResolveDocumentationScoresRequest,
    BackendResolveEmbeddingScoresRequest,
    BackendRuntimeInventoryRequest,
)
from codira.indexer import (
    _collect_indexed_file_analyses,
    _select_language_analyzer,
    index_repo,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    DocumentationArtifact,
    EnumMemberArtifact,
    FileMetadataSnapshot,
    FunctionArtifact,
    ModuleArtifact,
)
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.registry import (
    _instantiate_language_analyzers,
    active_index_backend,
    active_language_analyzers,
)
from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EMBEDDING_VERSION,
)
from codira.vector_store import active_vector_store_context

if TYPE_CHECKING:
    from types import ModuleType

    from pytest import MonkeyPatch


def _load_workspace_registry_module() -> ModuleType:
    """
    Load the workspace `src/codira/registry.py` module under a unique name.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Freshly loaded workspace registry module.

    Raises
    ------
    AssertionError
        Raised when the workspace registry module cannot be loaded.
    """
    module_path = Path(__file__).resolve().parents[1] / "src" / "codira" / "registry.py"
    spec = importlib.util.spec_from_file_location(
        f"workspace_codira_registry_{id(module_path)}",
        module_path,
    )
    if spec is None or spec.loader is None:
        msg = f"failed to load workspace codira registry module from {module_path}"
        raise AssertionError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backend_request_records_remain_available_from_contracts_facade() -> None:
    """
    Preserve backend request imports while isolating their record family.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the contracts facade re-exports the extracted records.
    """
    assert (
        BackendRelationQueryRequest
        is backend_requests_module.BackendRelationQueryRequest
    )
    assert (
        BackendEmbeddingCandidatesRequest
        is backend_requests_module.BackendEmbeddingCandidatesRequest
    )
    assert (
        BackendDocumentationCandidatesRequest
        is backend_requests_module.BackendDocumentationCandidatesRequest
    )
    assert (
        BackendResolveEmbeddingScoresRequest
        is backend_requests_module.BackendResolveEmbeddingScoresRequest
    )
    assert (
        BackendResolveDocumentationScoresRequest
        is backend_requests_module.BackendResolveDocumentationScoresRequest
    )
    assert (
        BackendRuntimeInventoryRequest
        is backend_requests_module.BackendRuntimeInventoryRequest
    )


class _FakeAnalyzer:
    """Small analyzer stub used to validate the protocol surface."""

    name = "fake-python"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def supports_path(self, path: Path) -> bool:
        """
        Report support for Python files.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for Python files.
        """
        return path.suffix == ".py"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one file through the existing Python parser path.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root used for module resolution.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        return PythonAnalyzer().analyze_file(path, root)


def test_c_analyzer_normalizes_functions_and_includes(tmp_path: Path) -> None:
    """
    Validate the Phase 9 C analyzer proof against normalized artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic module, include, and function output.
    """
    source = tmp_path / "pkg" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        '#include "pkg/sample.h"\n'
        "#include <stdio.h>\n"
        "\n"
        "static int helper(int value) {\n"
        "    return value;\n"
        "}\n"
        "\n"
        "int public_api(void) {\n"
        "    return helper(1);\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "pkg.sample"
    assert tuple(import_row.name for import_row in result.imports) == (
        "pkg/sample.h",
        "stdio.h",
    )
    assert tuple(import_row.kind for import_row in result.imports) == (
        "include_local",
        "include_system",
    )
    assert tuple(function.name for function in result.functions) == (
        "helper",
        "public_api",
    )
    assert result.functions[0].parameters == ("value",)
    assert result.functions[0].is_public == 0
    assert result.functions[1].parameters == ()
    assert result.functions[1].is_public == 1


def test_cpp_analyzer_normalizes_namespaces_classes_and_aliases(
    tmp_path: Path,
) -> None:
    """
    Normalize core C++ declarations into deterministic artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic namespace, class, alias, enum, import,
        and free-function extraction.
    """
    source = tmp_path / "pkg" / "api.cpp"
    source.parent.mkdir()
    source.write_text(
        "// Module summary.\n"
        "#include <vector>\n"
        '#include "pkg/api.hpp"\n'
        "\n"
        "// Namespace summary.\n"
        "namespace outer::inner {\n"
        "\n"
        "// API class.\n"
        "class Widget {\n"
        "public:\n"
        "    // Operates on input.\n"
        "    int run(int value) const;\n"
        "};\n"
        "\n"
        "// Type alias.\n"
        "using Value = long;\n"
        "\n"
        "// Available modes.\n"
        "enum Mode { Fast, Slow };\n"
        "\n"
        "// Free helper.\n"
        "int helper(double input);\n"
        "\n"
        "}  // namespace outer::inner\n",
        encoding="utf-8",
    )

    result = CppAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "pkg.api"
    assert result.module.stable_id == "cpp:module:pkg/api.cpp"
    assert result.module.docstring == "Module summary."
    assert tuple(import_row.name for import_row in result.imports) == (
        "vector",
        "pkg/api.hpp",
    )
    assert tuple(import_row.kind for import_row in result.imports) == (
        "include_system",
        "include_local",
    )
    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [
        ("namespace", "outer::inner", 6),
        ("type_alias", "outer::inner::Value", 16),
        ("enum", "outer::inner::Mode", 19),
    ]
    assert result.declarations[0].docstring == "Namespace summary."
    assert result.declarations[1].docstring == "Type alias."
    assert result.declarations[2].docstring == "Available modes."
    assert result.declarations[2].enum_members == (
        EnumMemberArtifact(
            stable_id="cpp:enum_member:pkg/api.cpp:outer::inner::Mode:1",
            parent_stable_id="cpp:enum:pkg/api.cpp:outer::inner::Mode",
            ordinal=1,
            name="Fast",
            signature="Fast",
            lineno=19,
        ),
        EnumMemberArtifact(
            stable_id="cpp:enum_member:pkg/api.cpp:outer::inner::Mode:2",
            parent_stable_id="cpp:enum:pkg/api.cpp:outer::inner::Mode",
            ordinal=2,
            name="Slow",
            signature="Slow",
            lineno=19,
        ),
    )
    assert len(result.classes) == 1
    assert result.classes[0].name == "outer::inner::Widget"
    assert result.classes[0].stable_id == "cpp:class:pkg/api.cpp:outer::inner::Widget"
    assert result.classes[0].docstring == "API class."
    assert [
        (method.name, method.parameters, method.docstring)
        for method in result.classes[0].methods
    ] == [
        ("run", ("value",), "Operates on input."),
    ]
    assert [
        (function.name, function.parameters, function.docstring)
        for function in result.functions
    ] == [
        ("outer::inner::helper", ("input",), "Free helper."),
    ]


def test_cpp_analyzer_prefers_method_definitions_over_duplicate_declarations(
    tmp_path: Path,
) -> None:
    """
    Keep one canonical method artifact when declaration and definition coexist.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts method declarations collapse onto the richer
        definition artifact.
    """
    source = tmp_path / "pkg" / "widget.cpp"
    source.parent.mkdir()
    source.write_text(
        "namespace outer {\n"
        "class Widget {\n"
        "public:\n"
        "    int run(int value) const;\n"
        "};\n"
        "\n"
        "int helper(int value) {\n"
        "    return value;\n"
        "}\n"
        "}  // namespace outer\n"
        "\n"
        "int outer::Widget::run(int value) const {\n"
        "    return helper(value);\n"
        "}\n",
        encoding="utf-8",
    )

    result = CppAnalyzer().analyze_file(source, tmp_path)

    assert len(result.classes) == 1
    assert [
        (method.name, method.parameters) for method in result.classes[0].methods
    ] == [
        ("run", ("value",)),
    ]
    method = result.classes[0].methods[0]
    assert method.end_lineno == 14
    assert method.returns_value == 1
    assert [(call.target, call.kind, call.lineno) for call in method.calls] == [
        ("helper", "name", 13),
    ]


def test_c_analyzer_extracts_top_level_declarations(tmp_path: Path) -> None:
    """
    Normalize top-level C type declarations into module-level symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic constant, macro, struct, union, enum,
        and typedef extraction.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "/* Stable internal constants. */\n"
        "static const int LIMIT = 3;\n"
        'static const char *NAME2 = "codira";\n'
        "const int LIMIT2 = 3;\n"
        "extern const int SIZE = 3;\n"
        "static const int A = 1, B = 2;\n"
        "static const int VALUE = 1 + 2;\n"
        "static const int VALUES[] = {1, 2};\n"
        "const int DECL_ONLY;\n"
        "extern const int DECL_EXT;\n"
        "const int fn(void);\n"
        "const int (*fp)(void);\n"
        "\n"
        "/* Stable exported macros. */\n"
        "#define PORT 8080\n"
        '#define NAME "codira"\n'
        "#define CALL(x) ((x) + 1)\n"
        "\n"
        "/* Node representation for graph edges. */\n"
        "typedef struct Node { int value; } Node;\n"
        "\n"
        "// Available palette values.\n"
        "enum Color { RED, BLUE };\n"
        "\n"
        "union Value { int i; float f; };\n"
        "\n"
        "struct Pair { int left; int right; };\n"
        "\n"
        "/* Stable integer alias. */\n"
        "typedef unsigned long size_t;\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [
        ("constant", "LIMIT", 2),
        ("constant", "NAME2", 3),
        ("constant", "LIMIT2", 4),
        ("constant", "SIZE", 5),
        ("constant", "A", 6),
        ("constant", "B", 6),
        ("constant", "VALUE", 7),
        ("constant", "VALUES", 8),
        ("constant", "DECL_ONLY", 9),
        ("constant", "DECL_EXT", 10),
        ("macro", "PORT", 15),
        ("macro", "NAME", 16),
        ("macro", "CALL", 17),
        ("struct", "Node", 20),
        ("typedef", "Node", 20),
        ("enum", "Color", 23),
        ("union", "Value", 25),
        ("struct", "Pair", 27),
        ("typedef", "size_t", 30),
    ]
    assert result.declarations[0].signature == "static const int LIMIT = 3;"
    assert result.declarations[1].signature == 'static const char *NAME2 = "codira";'
    assert result.declarations[2].signature == "const int LIMIT2 = 3;"
    assert result.declarations[3].signature == "extern const int SIZE = 3;"
    assert result.declarations[4].signature == "static const int A = 1, B = 2;"
    assert result.declarations[5].signature == "static const int A = 1, B = 2;"
    assert result.declarations[6].signature == "static const int VALUE = 1 + 2;"
    assert result.declarations[0].docstring == "Stable internal constants."
    assert result.declarations[1].docstring is None
    assert result.declarations[2].docstring is None
    assert result.declarations[3].docstring is None
    assert result.declarations[4].docstring is None
    assert result.declarations[5].docstring is None
    assert result.declarations[6].docstring is None
    assert result.declarations[7].docstring is None
    assert result.declarations[8].docstring is None
    assert result.declarations[9].docstring is None
    assert result.declarations[10].docstring == "Stable exported macros."
    assert result.declarations[11].docstring is None
    assert result.declarations[12].docstring is None
    assert result.declarations[13].docstring == "Node representation for graph edges."
    assert result.declarations[14].docstring == "Node representation for graph edges."
    assert result.declarations[15].docstring == "Available palette values."
    assert result.declarations[16].docstring is None
    assert result.declarations[17].docstring is None
    assert result.declarations[18].docstring == "Stable integer alias."
    assert result.declarations[15].enum_members == (
        EnumMemberArtifact(
            stable_id="c:enum_member:native/types.h:Color:1",
            parent_stable_id="c:enum:native/types.h:Color",
            ordinal=1,
            name="RED",
            signature="RED",
            lineno=23,
        ),
        EnumMemberArtifact(
            stable_id="c:enum_member:native/types.h:Color:2",
            parent_stable_id="c:enum:native/types.h:Color",
            ordinal=2,
            name="BLUE",
            signature="BLUE",
            lineno=23,
        ),
    )
    assert result.declarations[16].signature == "union Value { int i; float f; }"
    assert result.declarations[16].stable_id == "c:union:native/types.h:Value"


def test_c_analyzer_preserves_suffix_in_declaration_stable_ids(
    tmp_path: Path,
) -> None:
    """
    Keep declaration stable IDs distinct across sibling source suffixes.
    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts `.c` and `.h` siblings do not collide.
    """
    include = tmp_path / "native" / "common.h"
    implementation = tmp_path / "native" / "common.c"
    include.parent.mkdir()
    include.write_text("struct name_info { int value; };\n", encoding="utf-8")
    implementation.write_text("struct name_info { int value; };\n", encoding="utf-8")

    include_result = CAnalyzer().analyze_file(include, tmp_path)
    implementation_result = CAnalyzer().analyze_file(implementation, tmp_path)

    assert include_result.declarations[0].stable_id == (
        "c:struct:native/common.h:name_info"
    )
    assert implementation_result.declarations[0].stable_id == (
        "c:struct:native/common.c:name_info"
    )


def test_c_analyzer_extracts_typedef_wrapped_union_declarations(tmp_path: Path) -> None:
    """
    Normalize typedef-wrapped C unions into explicit declaration artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts typedef-wrapped unions emit both union and typedef
        declarations deterministically.
    """
    source = tmp_path / "native" / "token.h"
    source.parent.mkdir()
    source.write_text(
        "typedef union Token { int kind; char c; } Token;\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [
        ("union", "Token", 1),
        ("typedef", "Token", 1),
    ]
    assert result.declarations[0].signature == "union Token { int kind; char c; }"
    assert (
        result.declarations[1].signature
        == "typedef union Token { int kind; char c; } Token;"
    )
    assert result.declarations[0].stable_id == "c:union:native/token.h:Token"
    assert result.declarations[1].stable_id == "c:typedef:native/token.h:Token"


def test_c_analyzer_keeps_last_duplicate_named_declaration(tmp_path: Path) -> None:
    """
    Keep the last duplicate named C declaration when analysis sees both forms.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts only the final declaration variant is retained.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "struct Foo;\nstruct Foo { int value; };\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (declaration.kind, declaration.name, declaration.lineno)
        for declaration in result.declarations
    ] == [("struct", "Foo", 2)]
    assert result.declarations[0].signature == "struct Foo { int value; }"


def test_c_analyzer_uses_real_name_for_annotated_functions(tmp_path: Path) -> None:
    """
    Recover real C function names from annotation-prefixed declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts annotation wrappers do not replace function names.
    """
    source = tmp_path / "native" / "annotated.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct cairo_xml cairo_xml_t;\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n"
        "\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf_start(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("_cairo_xml_printf", 2),
        ("_cairo_xml_printf_start", 7),
    ]


def test_index_repo_handles_duplicate_c_declaration_redefinitions(
    tmp_path: Path,
) -> None:
    """
    Index duplicate C declarations without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the repository indexes successfully.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "struct Foo;\nstruct Foo { int value; };\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_index_repo_handles_annotated_c_functions(tmp_path: Path) -> None:
    """
    Index annotated C functions without tripping the fallback parser path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts indexing completes without failures.
    """
    source = tmp_path / "native" / "annotated.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct cairo_xml cairo_xml_t;\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n"
        "\n"
        "static void CAIRO_PRINTF_FORMAT (2, 3)\n"
        "_cairo_xml_printf_start(cairo_xml_t *xml, const char *fmt, ...)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_uses_real_name_for_macro_wrapped_functions(
    tmp_path: Path,
) -> None:
    """
    Recover real names from macro-wrapped C function declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts wrapper macros do not leak into function names.
    """
    source = tmp_path / "native" / "compat.c"
    source.parent.mkdir()
    source.write_text(
        "typedef unsigned long mp_limb_t;\n"
        "typedef unsigned long mp_size_t;\n"
        "typedef unsigned long *mp_ptr;\n"
        "typedef const unsigned long *mp_srcptr;\n"
        "mp_limb_t\n"
        "__MPN (divexact_by3) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n"
        "\n"
        "mp_limb_t\n"
        "__MPN (divmod_1) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("divexact_by3", 5),
        ("divmod_1", 11),
    ]


def test_index_repo_handles_macro_wrapped_c_functions(tmp_path: Path) -> None:
    """
    Index macro-wrapped C functions without reporting analyzer failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts one file is indexed successfully.
    """
    source = tmp_path / "native" / "compat.c"
    source.parent.mkdir()
    source.write_text(
        "typedef unsigned long mp_limb_t;\n"
        "typedef unsigned long mp_size_t;\n"
        "typedef unsigned long *mp_ptr;\n"
        "typedef const unsigned long *mp_srcptr;\n"
        "mp_limb_t\n"
        "__MPN (divexact_by3) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n"
        "\n"
        "mp_limb_t\n"
        "__MPN (divmod_1) (mp_ptr dst, mp_srcptr src, mp_size_t size)\n"
        "{\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_handles_latin1_encoded_source(tmp_path: Path) -> None:
    """
    Decode latin-1 C source deterministically during analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts module comment recovery and function extraction.
    """
    source = tmp_path / "native" / "legacy.c"
    source.parent.mkdir()
    source.write_bytes(
        (
            "/* Cr\xe8me legacy comment. */\nint helper(void)\n{\n    return 1;\n}\n"
        ).encode("latin-1")
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.docstring == "Cr\xe8me legacy comment."
    assert [(function.name, function.lineno) for function in result.functions] == [
        ("helper", 2)
    ]


def test_index_repo_handles_latin1_encoded_c_source(tmp_path: Path) -> None:
    """
    Index latin-1 encoded C source without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the file indexes successfully.
    """
    source = tmp_path / "native" / "legacy.c"
    source.parent.mkdir()
    source.write_bytes(
        (
            "/* Cr\xe8me legacy comment. */\nint helper(void)\n{\n    return 1;\n}\n"
        ).encode("latin-1")
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1


def test_c_analyzer_uses_error_recovered_name_for_export_macros(
    tmp_path: Path,
) -> None:
    """
    Recover exported function names when macros disrupt the first parse pass.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the recovered names match the declarations.
    """
    source = tmp_path / "native" / "exported.c"
    source.parent.mkdir()
    source.write_text(
        "typedef struct TestNode TestNode;\n"
        "void T_CTEST_EXPORT2\n"
        "showTests (const TestNode *root)\n"
        "{\n"
        "}\n"
        "\n"
        "void T_CTEST_EXPORT2\n"
        "runTests (const TestNode *root)\n"
        "{\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("showTests", 2),
        ("runTests", 7),
    ]


def test_c_analyzer_ignores_throw_exception_specifier_as_function_name(
    tmp_path: Path,
) -> None:
    """
    Ignore ``throw()`` syntax when recovering the function name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the function name remains ``logger``.
    """
    source = tmp_path / "native" / "face.h"
    source.parent.mkdir()
    source.write_text(
        "class Face { public: json * logger() const throw(); };\n"
        "inline\n"
        "json * Face::logger() const throw()\n"
        "{\n"
        "  return 0;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("logger", 2)
    ]


def test_c_analyzer_uses_error_recovered_name_for_type_like_prefix(
    tmp_path: Path,
) -> None:
    """
    Recover names when type-like prefixes precede C declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts both names are recovered correctly.
    """
    source = tmp_path / "native" / "float_funcs.c"
    source.parent.mkdir()
    source.write_text(
        "static force_inline float\n"
        "minf (float a, float b)\n"
        "{\n"
        "  return a;\n"
        "}\n"
        "\n"
        "static force_inline float\n"
        "maxf (float a, float b)\n"
        "{\n"
        "  return a;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert [(function.name, function.lineno) for function in result.functions] == [
        ("minf", 1),
        ("maxf", 7),
    ]


def test_c_function_stable_ids_are_disambiguated_when_names_repeat() -> None:
    """
    Disambiguate repeated C function stable IDs with deterministic suffixes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts repeated names do not collide.
    """
    functions = (
        FunctionArtifact(
            name="assign",
            stable_id="c:function:native.sample:assign",
            lineno=10,
            end_lineno=12,
            signature="assign(size_t n, const T& u)",
            docstring=None,
            has_docstring=0,
            is_method=0,
            is_public=1,
            parameters=(),
            returns_value=0,
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=(),
            callable_refs=(),
        ),
        FunctionArtifact(
            name="assign",
            stable_id="c:function:native.sample:assign",
            lineno=13,
            end_lineno=15,
            signature="assign(const_iterator first, const_iterator last)",
            docstring=None,
            has_docstring=0,
            is_method=0,
            is_public=1,
            parameters=(),
            returns_value=0,
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=(),
            callable_refs=(),
        ),
    )

    disambiguated = _disambiguate_function_stable_ids(functions)

    assert len({function.stable_id for function in disambiguated}) == 2
    assert all(
        function.stable_id.startswith("c:function:native.sample:assign")
        for function in disambiguated
    )


def test_c_analyzer_extracts_calls_returns_and_module_comment(tmp_path: Path) -> None:
    """
    Preserve Phase 11 C semantic-parity artifacts within the current model.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts call extraction, return detection, and module comment
        capture for C sources.
    """
    source = tmp_path / "native" / "flow.c"
    source.parent.mkdir()
    source.write_text(
        "/* Vector reduction helpers. */\n"
        "\n"
        "static int helper(int value) {\n"
        "    return obj->normalize(value);\n"
        "}\n"
        "\n"
        "int public_api(int input) {\n"
        '    trace("value");\n'
        "    return helper(input);\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert result.module.docstring == "Vector reduction helpers."
    assert result.module.has_docstring == 1
    assert tuple(function.name for function in result.functions) == (
        "helper",
        "public_api",
    )
    assert result.functions[0].returns_value == 1
    assert result.functions[0].calls == (
        CallSite(
            kind="attribute",
            target="normalize",
            lineno=4,
            col_offset=16,
            base="obj",
            external_target_kind="C:<external>",
            external_target_name="normalize",
        ),
    )
    assert result.functions[1].returns_value == 1
    assert tuple(call.target for call in result.functions[1].calls) == (
        "trace",
        "helper",
    )


def test_c_analyzer_ignores_macro_blocks_misparsed_as_functions(
    tmp_path: Path,
) -> None:
    """
    Skip malformed macro blocks that tree-sitter exposes as functions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts only real function definitions are normalized.
    """
    source = tmp_path / "native" / "macro_noise.c"
    source.parent.mkdir()
    source.write_text(
        "#define CTL_PROTO(x) x\n"
        "#define MUTEX_STATS_CTL_PROTO_GEN(n) \\\n"
        "CTL_PROTO(stats_##n##_num_ops) \\\n"
        "CTL_PROTO(stats_##n##_num_wait)\n"
        "\n"
        "typedef int ctl_named_node_t;\n"
        "#define OP(mtx) MUTEX_STATS_CTL_PROTO_GEN(mutexes_##mtx)\n"
        "static const ctl_named_node_t stats_node[] = {\n"
        "    OP(background_thread),\n"
        "};\n"
        "#undef OP\n"
        "\n"
        "int real(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    result = CAnalyzer().analyze_file(source, tmp_path)

    assert tuple(function.name for function in result.functions) == ("real",)
    assert result.functions[0].signature == "int real(void)"


def test_c_import_kinds_persist_through_sqlite_backend(tmp_path: Path) -> None:
    """
    Persist C include-kind metadata through the current SQLite backend.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stored local and system include kinds.
    """
    source = tmp_path / "native" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        '#include "native/sample.h"\n'
        "#include <stdio.h>\n"
        "\n"
        "int demo(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        rows = conn.execute("""
            SELECT i.name, i.kind
            FROM imports i
            JOIN modules m
              ON i.module_id = m.id
            ORDER BY i.lineno, i.name
            """).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("native/sample.h", "include_local"),
        ("stdio.h", "include_system"),
    ]


def test_c_declarations_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist C declaration artifacts into the existing exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts exact symbol lookup for persisted C declarations.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "#define PORT 8080\n"
        '#define NAME "codira"\n'
        "static const int LIMIT = 3;\n"
        'static const char *NAME2 = "codira";\n'
        "const int LIMIT2 = 3;\n"
        "extern const int SIZE = 3;\n"
        "static const int A = 1, B = 2;\n"
        "static const int VALUE = 1 + 2;\n"
        "static const int VALUES[] = {1, 2};\n"
        "const int DECL_ONLY;\n"
        "extern const int DECL_EXT;\n"
        "const int fn(void);\n"
        "const int (*fp)(void);\n"
        "#define CALL(x) ((x) + 1)\n"
        "typedef struct Node { int value; } Node;\n"
        "enum Color { RED, BLUE };\n"
        "union Value { int i; float f; };\n"
        "struct Pair { int left; int right; };\n"
        "typedef unsigned long size_t;\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "LIMIT") == [
        ("constant", "native.types", "LIMIT", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "NAME2") == [
        ("constant", "native.types", "NAME2", str(source), 4),
    ]
    assert backend.find_symbol(tmp_path, "LIMIT2") == [
        ("constant", "native.types", "LIMIT2", str(source), 5),
    ]
    assert backend.find_symbol(tmp_path, "SIZE") == [
        ("constant", "native.types", "SIZE", str(source), 6),
    ]
    assert backend.find_symbol(tmp_path, "A") == [
        ("constant", "native.types", "A", str(source), 7),
    ]
    assert backend.find_symbol(tmp_path, "B") == [
        ("constant", "native.types", "B", str(source), 7),
    ]
    assert backend.find_symbol(tmp_path, "VALUE") == [
        ("constant", "native.types", "VALUE", str(source), 8),
    ]
    assert backend.find_symbol(tmp_path, "VALUES") == [
        ("constant", "native.types", "VALUES", str(source), 9),
    ]
    assert backend.find_symbol(tmp_path, "DECL_ONLY") == [
        ("constant", "native.types", "DECL_ONLY", str(source), 10),
    ]
    assert backend.find_symbol(tmp_path, "DECL_EXT") == [
        ("constant", "native.types", "DECL_EXT", str(source), 11),
    ]
    assert backend.find_symbol(tmp_path, "Node") == [
        ("struct", "native.types", "Node", str(source), 15),
        ("typedef", "native.types", "Node", str(source), 15),
    ]
    assert backend.find_symbol(tmp_path, "PORT") == [
        ("macro", "native.types", "PORT", str(source), 1),
    ]
    assert backend.find_symbol(tmp_path, "NAME") == [
        ("macro", "native.types", "NAME", str(source), 2),
    ]
    assert backend.find_symbol(tmp_path, "CALL") == [
        ("macro", "native.types", "CALL", str(source), 14),
    ]
    assert backend.find_symbol(tmp_path, "fn") == []
    assert backend.find_symbol(tmp_path, "fp") == []
    assert backend.find_symbol(tmp_path, "Color") == [
        ("enum", "native.types", "Color", str(source), 16),
    ]
    assert backend.find_symbol(tmp_path, "Value") == [
        ("union", "native.types", "Value", str(source), 17),
    ]
    assert backend.find_symbol(tmp_path, "size_t") == [
        ("typedef", "native.types", "size_t", str(source), 19),
    ]

    enum_symbol = backend.find_symbol(tmp_path, "Color")[0]
    assert backend.find_symbol_enum_members(tmp_path, enum_symbol) == [
        (
            "c:enum_member:native/types.h:Color:1",
            "c:enum:native/types.h:Color",
            1,
            "RED",
            "RED",
            16,
        ),
        (
            "c:enum_member:native/types.h:Color:2",
            "c:enum:native/types.h:Color",
            2,
            "BLUE",
            "BLUE",
            16,
        ),
    ]


def test_python_type_aliases_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist explicit Python type aliases into the exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts explicit Python type aliases become queryable
        declaration symbols.
    """
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "from typing import TypeAlias\n\ntype UserId = int\nSlug: TypeAlias = str\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "UserId") == [
        ("type_alias", "pkg.sample", "UserId", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "Slug") == [
        ("type_alias", "pkg.sample", "Slug", str(source), 4),
    ]


def test_python_constants_persist_as_exact_symbols(tmp_path: Path) -> None:
    """
    Persist bounded Python constants into the exact-symbol index.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts module-level constant declarations become queryable
        exact symbols while non-constant assignments remain excluded.
    """
    source = tmp_path / "pkg" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        "VALUE = 1\n"
        "TIMEOUT = (1, 2, 3)\n"
        "PORT: int = 8080\n"
        'NAME: str = "codira"\n'
        "ALIAS = VALUE + 1\n"
        "_PRIVATE = 2\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    analysis = PythonAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="constants123",
        mtime=1.0,
        size=source.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    assert backend.find_symbol(tmp_path, "VALUE") == [
        ("constant", "pkg.sample", "VALUE", str(source), 1),
    ]
    assert backend.find_symbol(tmp_path, "TIMEOUT") == [
        ("constant", "pkg.sample", "TIMEOUT", str(source), 2),
    ]
    assert backend.find_symbol(tmp_path, "PORT") == [
        ("constant", "pkg.sample", "PORT", str(source), 3),
    ]
    assert backend.find_symbol(tmp_path, "NAME") == [
        ("constant", "pkg.sample", "NAME", str(source), 4),
    ]
    assert backend.find_symbol(tmp_path, "ALIAS") == []
    assert backend.find_symbol(tmp_path, "_PRIVATE") == []


def test_c_declaration_comments_contribute_to_embedding_candidates(
    tmp_path: Path,
) -> None:
    """
    Include leading declaration comments in C semantic symbol retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts embedding retrieval can match declaration comments.
    """
    source = tmp_path / "native" / "types.h"
    source.parent.mkdir()
    source.write_text(
        "/* Palette lookup for UI themes. */\nenum Color { RED, BLUE };\n",
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    vector_store_context = active_vector_store_context(tmp_path)
    analysis = CAnalyzer().analyze_file(source, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=source,
        sha256="abc123",
        mtime=1.0,
        size=source.stat().st_size,
    )
    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
            vector_store=vector_store_context.store,
            vector_set_identity=vector_store_context.identity,
            vector_store_config=vector_store_context.config,
        )
    )

    results = backend.embedding_candidates(
        BackendEmbeddingCandidatesRequest(
            root=tmp_path,
            query="palette lookup themes",
            limit=5,
            min_score=0.0,
        )
    )

    assert results
    assert ("enum", "native.types", "Color", str(source), 2) in {
        symbol for _score, symbol in results
    }


def test_active_index_backend_rejects_unknown_configured_backend(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Reject unsupported backend configuration deterministically.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to set process-local environment variables.

    Returns
    -------
    None
        The test asserts an informative failure for unsupported backend names.

    Raises
    ------
    ValueError
        Raised when the configured backend name is not registered.
    """
    monkeypatch.setenv("CODIRA_INDEX_BACKEND", "unknown")

    try:
        active_index_backend()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for unsupported backend"
        raise AssertionError(msg)

    assert "Unsupported codira backend 'unknown'" in message
    assert "sqlite" in message


def test_active_index_backend_mentions_first_party_sqlite_package_when_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Mention the extracted SQLite backend package when no backend is available.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to remove backend entry-point discovery.

    Returns
    -------
    None
        The test asserts the default backend error includes the installation
        hint for the first-party SQLite package.
    """
    monkeypatch.setenv(registry_module.INDEX_BACKEND_ENV_VAR, "sqlite")
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    try:
        active_index_backend()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError when no backend plugins are registered"
        raise AssertionError(msg)

    assert "codira-backend-sqlite" in message
    assert "codira-bundle-official" in message


def test_active_index_backend_mentions_first_party_duckdb_package_when_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Mention the extracted DuckDB backend package when it is configured missing.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to remove backend entry-point discovery.

    Returns
    -------
    None
        The test asserts the DuckDB backend error includes the installation
        hint for the first-party package.
    """
    workspace_registry = _load_workspace_registry_module()
    monkeypatch.setenv(workspace_registry.INDEX_BACKEND_ENV_VAR, "duckdb")
    monkeypatch.setattr(
        workspace_registry,
        "_entry_points_for_group",
        lambda group: [],
    )

    try:
        workspace_registry.active_index_backend()
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError when no duckdb backend plugins are registered"
        raise AssertionError(msg)

    assert "codira-backend-duckdb" in message
    assert "codira-bundle-official" in message


def test_instantiating_language_analyzers_requires_a_non_empty_registry() -> None:
    """
    Reject empty analyzer registries with an explicit deterministic error.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the registry failure path used by Phase 8.

    Raises
    ------
    ValueError
        Raised when analyzer instantiation is attempted with an empty
        registry.
    """
    try:
        _instantiate_language_analyzers(())
    except ValueError as exc:
        assert str(exc) == "No language analyzers are registered for codira"
    else:
        msg = "expected ValueError for empty analyzer registry"
        raise AssertionError(msg)


def test_sqlite_index_backend_persists_and_deletes_normalized_analysis(
    tmp_path: Path,
) -> None:
    """
    Exercise the concrete SQLite backend through the Phase 3 contract surface.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts normalized persistence, reusable embedding counting,
        and deletion through `SQLiteIndexBackend`.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo(value):\n    """Return the supplied value."""\n    return value\n',
        encoding="utf-8",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    vector_store_context = active_vector_store_context(tmp_path)

    analysis = PythonAnalyzer().analyze_file(module, tmp_path)
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="abc123",
        mtime=1.0,
        size=module.stat().st_size,
    )

    recomputed, reused = backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
            vector_store=vector_store_context.store,
            vector_set_identity=vector_store_context.identity,
            vector_store_config=vector_store_context.config,
        )
    )
    backend.rebuild_derived_indexes(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        file_hashes = backend.load_existing_file_hashes(tmp_path, conn=conn)
        symbol_rows = conn.execute(
            "SELECT name, type FROM symbol_index ORDER BY name, type"
        ).fetchall()
    finally:
        conn.close()

    assert recomputed == 2
    assert reused == 0
    assert file_hashes == {str(module): "abc123"}
    assert symbol_rows == [
        ("demo", "function"),
        ("pkg.sample", "module"),
    ]
    assert backend.find_symbol(tmp_path, "demo") == [
        (
            "function",
            "pkg.sample",
            "demo",
            str(module),
            1,
        )
    ]
    assert backend.embedding_inventory(tmp_path) == [
        (EMBEDDING_BACKEND, EMBEDDING_VERSION, EMBEDDING_DIM, 2)
    ]
    assert backend.embedding_candidates(
        BackendEmbeddingCandidatesRequest(
            root=tmp_path,
            query="return supplied value",
            limit=5,
            min_score=0.0,
        )
    )
    assert backend.count_reusable_embeddings(tmp_path, paths=[str(module)]) == 2

    backend.delete_paths(tmp_path, paths=[str(module)])
    assert backend.load_existing_file_hashes(tmp_path) == {}


def test_sqlite_index_backend_persists_documentation_without_symbols(
    tmp_path: Path,
) -> None:
    """
    Persist documentation artifacts without blending them into symbol retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts documentation artifacts are stored, embedded, queried
        through the documentation channel, and deleted independently from
        symbols.
    """
    document = tmp_path / "docs" / "architecture.md"
    document.parent.mkdir()
    document.write_text(
        "# Plugin Loading\n\nPlugins are discovered through entry points.\n",
        encoding="utf-8",
    )
    artifact = DocumentationArtifact(
        stable_id="doc:section:docs/architecture.md:plugin-loading:1",
        kind="section",
        source_format="markdown_section",
        source_path=document,
        lineno=1,
        end_lineno=3,
        title="Plugin Loading",
        heading_path=("Plugin Loading",),
        text="Plugin Loading\nPlugins are discovered through entry points.",
        owner_stable_id="doc-owner:docs.architecture",
        owner_kind="section",
        attachment_confidence="explicit",
    )
    analysis = AnalysisResult(
        source_path=document,
        module=ModuleArtifact(
            name="docs.architecture",
            stable_id="module:docs.architecture",
            docstring=None,
            has_docstring=0,
        ),
        classes=(),
        functions=(),
        declarations=(),
        imports=(),
        documentation=(artifact,),
        index_symbols=False,
    )
    snapshot = FileMetadataSnapshot(
        path=document,
        sha256="doc123",
        mtime=1.0,
        size=document.stat().st_size,
        analyzer_name="markdown",
        analyzer_version="1",
    )

    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    vector_store_context = active_vector_store_context(tmp_path)
    recomputed, reused = backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
            vector_store=vector_store_context.store,
            vector_set_identity=vector_store_context.identity,
            vector_store_config=vector_store_context.config,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        symbols = conn.execute("SELECT COUNT(*) FROM symbol_index").fetchone()
        docs = conn.execute(
            """
            SELECT stable_id,
                   kind,
                   source_format,
                   title,
                   heading_path,
                   text,
                   owner_stable_id,
                   owner_kind,
                   attachment_confidence
            FROM documentation_artifacts
            """
        ).fetchall()
    finally:
        conn.close()

    assert recomputed == 1
    assert reused == 0
    assert symbols == (0,)
    assert docs == [
        (
            artifact.stable_id,
            "section",
            "markdown_section",
            "Plugin Loading",
            '["Plugin Loading"]',
            artifact.text,
            "doc-owner:docs.architecture",
            "section",
            "explicit",
        )
    ]
    assert backend.find_symbol(tmp_path, "Plugin Loading") == []
    assert (
        backend.embedding_candidates(
            BackendEmbeddingCandidatesRequest(
                root=tmp_path,
                query="entry point plugin loading",
                limit=5,
                min_score=0.0,
            )
        )
        == []
    )
    documentation_results = backend.documentation_candidates(
        BackendDocumentationCandidatesRequest(
            root=tmp_path,
            query="entry point plugin loading",
            limit=5,
            min_score=0.0,
        )
    )
    assert [row for _score, row in documentation_results] == [
        (
            artifact.stable_id,
            "section",
            "markdown_section",
            str(document),
            1,
            3,
            "Plugin Loading",
            ("Plugin Loading",),
            artifact.text,
        )
    ]
    assert backend.embedding_inventory(tmp_path) == [
        (EMBEDDING_BACKEND, EMBEDDING_VERSION, EMBEDDING_DIM, 1)
    ]
    assert backend.count_reusable_embeddings(tmp_path, paths=[str(document)]) == 1

    backend.delete_paths(tmp_path, paths=[str(document)])
    assert backend.load_existing_file_hashes(tmp_path) == {}
    assert (
        backend.documentation_candidates(
            BackendDocumentationCandidatesRequest(
                root=tmp_path,
                query="entry point plugin loading",
                limit=5,
                min_score=0.0,
            )
        )
        == []
    )


def test_select_language_analyzer_uses_first_supporting_analyzer(
    tmp_path: Path,
) -> None:
    """
    Preserve deterministic analyzer routing order in the Phase 5 orchestrator.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts first-match routing for a supported path.

    Raises
    ------
    AssertionError
        Raised if the rejecting analyzer is called despite not supporting the
        path.
    """

    class _RejectingAnalyzer:
        name = "reject"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.py",)

        def supports_path(self, path: Path) -> bool:
            return False

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            msg = "should not be called"
            raise AssertionError(msg)

    analyzer = _select_language_analyzer(
        tmp_path / "sample.py",
        [_RejectingAnalyzer(), _FakeAnalyzer()],
    )

    assert analyzer is not None
    assert analyzer.name == "fake-python"


def test_collect_indexed_file_analyses_routes_paths_to_analyzers(
    tmp_path: Path,
) -> None:
    """
    Collect normalized analyses through the Phase 5 analyzer-routing helper.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts snapshot conversion and analyzer-produced artifacts.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )

    rows, failures, collected_warnings = _collect_indexed_file_analyses(
        tmp_path,
        [str(module)],
        {
            str(module): {
                "path": str(module),
                "hash": "abc123",
                "mtime": 1.0,
                "size": module.stat().st_size,
            }
        },
        [_FakeAnalyzer()],
    )

    assert failures == []
    assert collected_warnings == []
    assert len(rows) == 1
    path, snapshot, analysis = rows[0]
    assert path == module
    assert snapshot == FileMetadataSnapshot(
        path=module,
        sha256="abc123",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="fake-python",
        analyzer_version="1",
    )
    assert analysis.module.name == "pkg.sample"


def test_sqlite_backend_persists_file_analyzer_ownership(tmp_path: Path) -> None:
    """
    Persist analyzer ownership metadata on file rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts persisted file rows record analyzer name and version.
    """
    backend = SQLiteIndexBackend()
    backend.initialize(tmp_path)
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )
    snapshot = FileMetadataSnapshot(
        path=module,
        sha256="hash-v1",
        mtime=1.0,
        size=module.stat().st_size,
        analyzer_name="python",
        analyzer_version=PythonAnalyzer().version,
    )
    analysis = PythonAnalyzer().analyze_file(module, tmp_path)

    backend.persist_analysis(
        BackendPersistAnalysisRequest(
            root=tmp_path,
            file_metadata=snapshot,
            analysis=analysis,
        )
    )

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            """
            SELECT analyzer_name, analyzer_version
            FROM files
            WHERE path = ?
            """,
            (str(module),),
        ).fetchone()
    finally:
        conn.close()

    assert row == ("python", PythonAnalyzer().version)


def test_sqlite_backend_persists_runtime_inventory(tmp_path: Path) -> None:
    """
    Persist runtime backend and analyzer inventory for one index run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts backend runtime metadata and analyzer inventory are
        stored in the SQLite database.
    """
    module = tmp_path / "pkg" / "sample.py"
    module.parent.mkdir()
    module.write_text(
        'def demo():\n    """Return a constant."""\n    return 1\n',
        encoding="utf-8",
    )

    index_repo(tmp_path)

    backend = SQLiteIndexBackend()
    assert backend.load_runtime_inventory(tmp_path) == (
        "sqlite",
        str(SCHEMA_VERSION),
        1,
    )
    assert backend.load_analyzer_inventory(tmp_path) == [
        (
            analyzer.name,
            analyzer.version,
            analyzer_inventory_discovery_json(analyzer),
        )
        for analyzer in sorted(active_language_analyzers(), key=lambda item: item.name)
    ]


def test_bash_analyzer_extracts_simple_calls(tmp_path: Path) -> None:
    """
    Extract plain shell command calls from one Bash function body.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts simple sequential calls are recorded in order.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo hello\n    make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "echo",
        "make",
    )


def test_bash_analyzer_extracts_pipeline_calls(tmp_path: Path) -> None:
    """
    Extract every command participating in one shell pipeline.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts pipeline commands are recorded left to right.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    cat input.txt | grep foo | sort\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "cat",
        "grep",
        "sort",
    )


def test_bash_analyzer_extracts_subshell_and_substitution_calls(tmp_path: Path) -> None:
    """
    Extract calls nested in subshells and command substitutions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts nested calls are still collected in order.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        'build() {\n    (echo hello; make all)\n    value="$(git rev-parse HEAD)"\n}\n',
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == (
        "echo",
        "make",
        "git",
    )


def test_bash_analyzer_ignores_plain_assignments(tmp_path: Path) -> None:
    """
    Ignore bare variable assignments that do not execute shell commands.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts no calls are collected for plain assignments.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    value=hello\n    PATH=/tmp/bin\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert result.functions[0].calls == ()


def test_bash_analyzer_extracts_env_prefixed_command(tmp_path: Path) -> None:
    """
    Keep the executed command when an environment assignment prefixes it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the prefixed command is still recorded.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    PATH=/tmp/bin make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert tuple(call.target for call in result.functions[0].calls) == ("make",)


def test_bash_analyzer_keeps_last_duplicate_function_definition(
    tmp_path: Path,
) -> None:
    """
    Keep only the last duplicate Bash function definition during analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the final definition and its calls survive.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo one\n}\n\nbuild() {\n    make all\n}\n",
        encoding="utf-8",
    )

    result = BashAnalyzer().analyze_file(source, tmp_path)

    assert [(fn.name, fn.lineno) for fn in result.functions] == [("build", 5)]
    assert tuple(call.target for call in result.functions[0].calls) == ("make",)


def test_index_repo_handles_duplicate_bash_function_redefinitions(
    tmp_path: Path,
) -> None:
    """
    Index duplicate Bash function redefinitions without surfacing a failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the file indexes successfully.
    """
    source = tmp_path / "scripts" / "build.sh"
    source.parent.mkdir()
    source.write_text(
        "build() {\n    echo one\n}\n\nbuild() {\n    make all\n}\n",
        encoding="utf-8",
    )

    report = index_repo(tmp_path)

    assert report.failed == 0
    assert report.indexed == 1
