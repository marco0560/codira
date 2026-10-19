"""Verify template call identities and named-cast operand calls.

Parameters
----------
None

Returns
-------
None
    Exercises extraction through the production analyzer.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    ("expression", "target", "base"),
    [
        ("f<int>(value)", "f<int>", ""),
        ("api::f<api::Box<int>>(value)", "f<api::Box<int>>", "api"),
        ("api::Box<api::T>::f<int>(value)", "f<int>", "api::Box<api::T>"),
        ("::api::f<int>(value)", "f<int>", "api"),
        ("api::f<(8 >> 1)>(value)", "f<(8 >> 1)>", "api"),
        ('api::f<sizeof("::")>(value)', 'f<sizeof("::")>', "api"),
        ("api :: f < api::T >(value)", "f < api::T >", "api"),
        ("static_casted<int>(value)", "static_casted<int>", ""),
        ("Type<api::T>(value)", "Type<api::T>", ""),
        ("Type(value)", "Type", ""),
    ],
)
def test_template_call_target_preserves_argument_scopes(
    tmp_path: Path, expression: str, target: str, base: str
) -> None:
    """Keep scope separators inside template arguments in their owning target.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    expression : str
        Call expression with an explicit target spelling.
    target : str
        Expected final target including any template arguments.
    base : str
        Expected enclosing scope without template argument namespaces.

    Returns
    -------
    None
        Identity and original UTF-8 byte position match the source expression.
    """
    prefix = "int run(int value) { /* café */ return "
    path = tmp_path / "calls.cpp"
    path.write_bytes((prefix + expression + "; }\r\n").encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "run")
    assert len(function.calls) == 1
    call = function.calls[0]
    assert (call.kind, call.target, call.base) == ("name", target, base)
    assert (call.lineno, call.col_offset) == (1, len(prefix.encode()))


@pytest.mark.parametrize(
    "operator", ["static_cast", "reinterpret_cast", "const_cast", "dynamic_cast"]
)
def test_named_cast_keeps_operand_call_without_operator_call(
    tmp_path: Path, operator: str
) -> None:
    """Exclude each cast keyword while retaining its nested template call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    operator : str
        Reserved named C++ cast keyword.

    Returns
    -------
    None
        Only the real operand call appears at its original byte position.
    """
    prefix = f"int run(int value) {{ return {operator}<int>("
    source = prefix + "get<int>(value)); }\n"
    path = tmp_path / "casts.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "run")
    assert len(function.calls) == 1
    call = function.calls[0]
    assert (call.kind, call.target, call.base) == ("name", "get<int>", "")
    assert (call.lineno, call.col_offset) == (1, len(prefix.encode()))


def test_nested_template_calls_keep_both_original_positions(tmp_path: Path) -> None:
    """Retain nested call order and coordinates inside a mapped namespace.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Both calls retain template targets, owners and original source positions.
    """
    source = (
        "#define OPEN namespace outer { inline namespace abi_v3 {\r\n"
        "#define CLOSE } }\r\n"
        "OPEN\r\n"
        "int run(int value) { /* café */ return f<int>(api::g<api::T>(value)); }\r\n"
        "CLOSE\r\n"
    )
    path = tmp_path / "mapped.cpp"
    path.write_bytes(source.encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name.endswith("::run"))
    assert function.name == "outer::abi_v3::run"
    assert [(c.target, c.base) for c in function.calls] == [
        ("f<int>", ""),
        ("g<api::T>", "api"),
    ]
    line = source.encode().splitlines()[3]
    assert [(c.lineno, c.col_offset) for c in function.calls] == [
        (4, line.index(b"f<int>")),
        (4, line.index(b"api::g")),
    ]
