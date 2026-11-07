"""Verify value-parameter disambiguation of local initializer argument calls.

Parameters
----------
None

Returns
-------
None
    Exercises production extraction and its declaration/scope boundaries.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    ("initializer", "targets"),
    [
        ("Reader reader(buffer, api::Limits<unsigned long>::max());", ["max"]),
        ("Reader reader(buffer, get());", ["get"]),
        ("Reader reader(/* value */ buffer, get());", ["get"]),
        ("Reader reader(buffer, wrap(get()));", ["wrap", "get"]),
        ("Reader reader(buffer, static_cast<int>(get()));", ["get"]),
    ],
)
def test_initializer_keeps_nested_calls(
    tmp_path: Path, initializer: str, targets: list[str]
) -> None:
    """Retain argument calls without inventing a call to the declared variable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    initializer : str
        Direct initializer whose first argument is a known value parameter.
    targets : list[str]
        Source-ordered nested expression targets.

    Returns
    -------
    None
        Production extraction keeps surrounding order and original byte positions.
    """
    source = (
        "void run(const char *buffer) {\r\n"
        "  before();\r\n"
        f"  /* café */ {initializer}\r\n"
        "  after();\r\n}\r\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source.encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "run")
    assert [c.target for c in function.calls] == ["before", *targets, "after"]
    line = source.encode().splitlines()[2]
    for call in function.calls[1:-1]:
        written = b"api::Limits" if call.target == "max" else call.target.encode()
        assert (call.lineno, call.col_offset) == (3, line.index(written))
    assert all(c.target != "reader" for c in function.calls)


@pytest.mark.parametrize(
    "source",
    [
        "void run() { Reader reader(buffer, Limits<int>::max()); }",
        "void run(int value) { Reader reader(buffer, Limits<int>::max()); }",
        "void run(int buffer) { { using buffer = int; "
        "Reader reader(buffer, Limits<int>::max()); } }",
        "void run(int buffer) { auto nested = [] { "
        "Reader reader(buffer, Limits<int>::max()); }; }",
        "void run(int buffer) { Reader reader(int buffer, Limits<int>::max()); }",
    ],
)
def test_initializer_preserves_unproven_declarations(
    tmp_path: Path, source: str
) -> None:
    """Keep type, shadowing and nested-scope declarations free of fabricated calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    source : str
        Declaration without a direct value-parameter disambiguation proof.

    Returns
    -------
    None
        Unsupported ambiguity retains the existing conservative extraction.
    """
    path = tmp_path / "declarations.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "run")
    assert not function.calls


def test_initializer_maps_multiline_argument_positions(tmp_path: Path) -> None:
    """Map a reparsed callee after CRLF and UTF-8 text to its physical source.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The callee line, byte column, qualifier and target match original text.
    """
    source = (
        "void run(const char *buffer) {\r\n"
        "  Reader reader(buffer,\r\n"
        "    /* café */ api::Limits<unsigned long>::max());\r\n}\r\n"
    )
    path = tmp_path / "multiline.cpp"
    path.write_bytes(source.encode())
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "run")
    assert len(function.calls) == 1
    call = function.calls[0]
    assert (call.kind, call.base, call.target) == (
        "name",
        "api::Limits<unsigned long>",
        "max",
    )
    assert (call.lineno, call.col_offset) == (
        3,
        source.encode().splitlines()[2].index(b"api::Limits"),
    )
