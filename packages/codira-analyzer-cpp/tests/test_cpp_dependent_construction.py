"""Verify dependent construction recovery and preservation of type contexts.

Parameters
----------
None

Returns
-------
None
    Exercises the public analyzer and conservative recovery boundaries.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    "statement",
    [
        "sink(typename T::type());",
        "return typename T::type();",
        "typename T::type value = typename T::type();",
        "typename T::type value; value = typename T::type();",
        "sink(typename /* construction */ T::type());",
        "sink(typename T::type{});",
    ],
)
def test_dependent_construction_expression(tmp_path: Path, statement: str) -> None:
    """Recover expression forms while preserving raw types and byte positions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository boundary.
    statement : str
        Construction expression in a body context.

    Returns
    -------
    None
        Complete analysis retains original target identity and source coordinates.
    """
    path = tmp_path / "unit.cpp"
    source = (
        "void sink(...);\r\n"
        "template<class T> typename T::type run(){\r\n"
        f" /* café */ {statement}\r\n}}\r\n"
    )
    path.write_bytes(source.encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "run")
    assert "typename T::type" in function.signature
    if "{}" not in statement:
        construction = next(c for c in function.calls if c.target == "type")
        assert construction.base == "T"
        assert construction.lineno == 3
        assert construction.col_offset == source.encode().splitlines()[2].rindex(
            b"T::type"
        )
    else:
        assert [c.target for c in function.calls] == ["sink"]


def test_dependent_construction_preserves_declarations(tmp_path: Path) -> None:
    """Keep type declarations and sizeof function types beside a recovered call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Declaration syntax cannot acquire a fabricated construction call.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "void sink(...);\n"
        "template<class T> void run(){\n"
        " typename T::type(value);\n"
        " (void)sizeof(typename T::type());\n"
        " sink(typename T::type());\n}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "run")
    assert [(c.target, c.lineno) for c in function.calls] == [("sink", 5), ("type", 5)]


def test_dependent_construction_preserves_literals_and_directives(
    tmp_path: Path,
) -> None:
    """Leave fake keyword directives and constructions inside opaque text intact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Literal content and macro bodies cannot license or acquire calls.
    """
    path = tmp_path / "unit.cpp"
    source = (
        '#define TEXT "typename T::type()"\n'
        'const char* text=R"(#define typename fake)";\n'
        "void sink(...);\ntemplate<class T> void run(){sink(typename T::type());}\n"
    )
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [c.target for f in result.functions for c in f.calls] == ["sink", "type"]


@pytest.mark.parametrize(
    "directive",
    ["#define typename fake\n", "#undef typename\n", "#undef/**/typename\n"],
)
def test_dependent_construction_holds_keyword_overrides(
    tmp_path: Path, directive: str
) -> None:
    """Reject captured definitions or undefinitions of the adapted keyword.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.
    directive : str
        Invalidating directive in a contained header.

    Returns
    -------
    None
        No complete recovery is claimed under an overridden keyword.
    """
    (tmp_path / "keyword.h").write_text(directive)
    path = tmp_path / "unit.cpp"
    path.write_text(
        '#include "keyword.h"\nvoid sink(...);\n'
        "template<class T> void run(){sink(typename T::type());}\n"
    )
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_dependent_construction_composes_namespace_wrappers(tmp_path: Path) -> None:
    """Recover a construction and an explicit ABI scope in one projection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Qualified ownership and original construction positions survive wrappers.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "#define BEGIN namespace outer { inline namespace ABI {\n"
        "#define END }}\nBEGIN\nvoid sink(...);\n"
        "template<class T> void run(){sink(typename T::type());}\nEND\n"
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"namespace_macro_definitions": {"ABI": "__1"}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(f for f in result.functions if f.name == "outer::__1::run")
    assert [(c.target, c.lineno) for c in function.calls] == [("sink", 5), ("type", 5)]


def test_dependent_construction_keeps_unrelated_errors(tmp_path: Path) -> None:
    """Require whole-file grammar recovery before clearing diagnostics.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        An unrelated malformed declaration keeps the file partial.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "void sink(...); template<class T> void run(){sink(typename T::type());}\n"
        "int broken( {\n"
    )
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols
