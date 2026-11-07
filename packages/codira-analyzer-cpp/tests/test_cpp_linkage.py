"""Verify extraction through C++ language-linkage declarations.

Parameters
----------
None

Returns
-------
None
    Defines behavioral regressions for both linkage syntax forms.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize("language", ["C", "C++"])
def test_single_linkage_declarations_keep_signatures_and_calls(
    tmp_path: Path, language: str
) -> None:
    """Extract explicit linkage declarations and definitions from original bytes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    language : str
        Language-linkage spelling.

    Returns
    -------
    None
        Comments, annotation prefixes, coordinates and calls survive traversal.
    """
    source = (
        '#define API __attribute__((visibility("default")))\n'
        f'extern "{language}" API int declared(int x);\n'
        "// Read a value.\n"
        f'extern "{language}" API int run(int x) {{ return callee(x); }}\n'
    ).encode()
    path = tmp_path / "linkage.cpp"
    path.write_bytes(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    functions = {function.name: function for function in result.functions}
    assert set(functions) == {"declared", "run"}
    declared = functions["declared"]
    assert declared.signature == f'extern "{language}" API int declared(int x);'
    assert declared.lineno == 2
    assert declared.end_lineno is None
    function = functions["run"]
    assert function.signature == f'extern "{language}" API int run(int x)'
    assert function.lineno == 4
    assert function.docstring == "Read a value."
    assert len(function.calls) == 1
    assert function.calls[0].target == "callee"
    assert function.calls[0].lineno == 4
    assert function.calls[0].col_offset == source.splitlines()[3].index(b"callee")
    assert path.read_bytes() == source


def test_linkage_blocks_keep_namespace_class_and_conditional_context(
    tmp_path: Path,
) -> None:
    """Visit linkage blocks without adding a namespace or flattening scopes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Nested classes and out-of-class definitions share their original owner.
    """
    path = tmp_path / "nested.cpp"
    path.write_text(
        "namespace outer {\n"
        'extern "C++" {\n'
        "class Widget { public: int run(); };\n"
        'extern "C" {\n'
        "// Branch declaration.\n"
        "#if FEATURE\n"
        "int first();\n"
        "#else\n"
        "int second();\n"
        "#endif\n"
        "}\n"
        "int Widget::run() { return callee(); }\n"
        "}\n"
        "}\n"
        'void local() { const char* text = R"(extern "C" int fake();)"; }\n'
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert {function.name for function in result.functions} == {
        "outer::first",
        "outer::second",
        "local",
    }
    assert [cls.name for cls in result.classes] == ["outer::Widget"]
    methods = result.classes[0].methods
    assert len(methods) == 1
    assert methods[0].name == "run"
    assert methods[0].end_lineno == 12
    assert methods[0].is_method == 1
    assert [call.target for call in methods[0].calls] == ["callee"]
    namespaces = [item.name for item in result.declarations if item.kind == "namespace"]
    assert namespaces == ["outer"]


def test_linkage_recovery_preserves_unrelated_syntax_errors(tmp_path: Path) -> None:
    """Keep malformed declarations partial while visiting their enclosing linkage.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Traversal does not promote a malformed tree to complete symbol indexing.
    """
    path = tmp_path / "broken.cpp"
    path.write_text('extern "C" { int good(); int broken( ; }\n')
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is not None
    assert [(item.name, item.signature) for item in result.functions] == [
        ("good", "int good();")
    ]
