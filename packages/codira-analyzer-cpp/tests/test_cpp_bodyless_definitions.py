"""Verify explicit default/delete definitions without fabricating executable bodies.

Parameters
----------
None

Returns
-------
None
    Checks definition ranges, redeclarations and lexical-call isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


def test_cpp_explicit_bodyless_definitions_and_declarations(tmp_path: Path) -> None:
    """Distinguish definitions from pure virtual and ordinary declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Checks exact source ranges, signatures and empty executable metadata.
    """
    path = tmp_path / "methods.cpp"
    path.write_text(
        "struct Box {\n"
        "  Box() = default;\n"
        "  Box(const Box&) = default;\n"
        "  Box(Box&&) = default;\n"
        "  Box& operator=(const Box&) = default;\n"
        "  virtual ~Box() = default;\n"
        "  void removed() = delete;\n"
        "  virtual void pure() = 0;\n"
        "  void declaration();\n"
        "};\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    methods = result.classes[0].methods
    assert len(methods) == 8
    assert {m.lineno: m.end_lineno for m in methods} == {
        2: 2,
        3: 3,
        4: 4,
        5: 5,
        6: 6,
        7: 7,
        8: None,
        9: None,
    }
    assert all(not m.calls and not m.returns_value and not m.raises for m in methods)
    assert len({m.stable_id for m in methods}) == 8
    assert (
        next(m for m in methods if m.lineno == 7).signature
        == "void removed() = delete;"
    )


def test_cpp_out_of_class_default_definition_supersedes_declaration(
    tmp_path: Path,
) -> None:
    """Retain the actual definition and class owner after a forward declaration.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Checks definition preference, source lines and unchanged stable identity.
    """
    path = tmp_path / "methods.cpp"
    path.write_text(
        "namespace api {\nstruct Box {Box(); ~Box();};\n"
        "Box::Box() = default;\nBox::~Box() = default;\n}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert not result.functions
    cls = result.classes[0]
    assert cls.name == "api::Box"
    assert {(m.name, m.lineno, m.end_lineno) for m in cls.methods} == {
        ("Box", 3, 3),
        ("~Box", 4, 4),
    }
    assert all(m.is_method and not m.calls for m in cls.methods)
    assert result == CppAnalyzer().analyze_file(path, tmp_path)


def test_cpp_multiline_clause_metadata_preserves_original_bytes(tmp_path: Path) -> None:
    """Keep UTF-8/CRLF lines and comments around the definition clause.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Verifies inclusive range and the written signature.
    """
    path = tmp_path / "methods.cpp"
    path.write_bytes(
        "// café\r\nstruct Box {\r\nBox()\r\n = /* keep */ default;\r\n};\r\n".encode()
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    method = result.classes[0].methods[0]
    assert (method.lineno, method.end_lineno) == (3, 4)
    assert method.signature == "Box() = /* keep */ default;"
    assert not method.calls


def test_cpp_deleted_free_function_and_real_body_calls(tmp_path: Path) -> None:
    """Keep bodyless free definitions separate from normal executable bodies.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Verifies deleted function metadata and existing body/parameter extraction.
    """
    path = tmp_path / "methods.cpp"
    path.write_text(
        'const char* text = "= default";\n'
        "void removed(int value) = delete;\n"
        "int helper(int value);\n"
        "int run(int value) {return helper(value);}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    functions = {f.name: f for f in result.functions}
    assert functions["removed"].end_lineno == 2
    assert functions["removed"].parameters == ("value",)
    assert not functions["removed"].calls
    assert functions["helper"].end_lineno is None
    assert functions["run"].end_lineno == 4
    assert [(c.target, c.lineno) for c in functions["run"].calls] == [("helper", 4)]


@pytest.mark.parametrize(
    ("source", "clean"),
    [
        ("int (*pointer)() = delete;", False),
        ("void a() = delete, b() = delete;", False),
        ("#define delete answer\nvoid f() = delete;", False),
        ("void f(int value = delete);", False),
        ("void f() = delete[];", False),
        ("void f() = delete;\nint broken(;", False),
        ("void f(int* value) {delete value;}", True),
    ],
)
def test_cpp_delete_recovery_guards(tmp_path: Path, source: str, clean: bool) -> None:
    """Keep variable initializers, overrides and unrelated errors outside recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.
    source : str
        Candidate declaration or executable expression.
    clean : bool
        Expected complete parser coverage.

    Returns
    -------
    None
        Verifies conservative recovery without manufacturing callable bodies.
    """
    path = tmp_path / "methods.cpp"
    path.write_text(source)
    assert CppAnalyzer().analyze_file(path, tmp_path).index_symbols is clean


def test_cpp_deleted_template_in_namespace_projection(tmp_path: Path) -> None:
    """Compose deleted free-function syntax with template and namespace recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Checks original ownership, parameters, source lines and comments.
    """
    path = tmp_path / "methods.cpp"
    path.write_bytes(
        b"#define BEGIN namespace api {\r\n#define END }\r\nBEGIN\r\n"
        + "template<class T> void removed(T value)\r\n = /* café */ delete\r\n ;\r\nEND\r\n".encode()
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = result.functions[0]
    assert function.name == "api::removed"
    assert function.parameters == ("value",)
    assert (function.lineno, function.end_lineno) == (4, 6)
    assert "/* café */ delete" in function.signature
    assert not function.calls


def test_cpp_deleted_keyword_override_in_contained_header(tmp_path: Path) -> None:
    """Preserve a partial parse when captured headers redefine the keyword.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Verifies include-backed override protection.
    """
    (tmp_path / "defs.h").write_text("#define delete answer\n")
    path = tmp_path / "methods.cpp"
    path.write_text('#include "defs.h"\nvoid removed() = delete;\n')
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols
