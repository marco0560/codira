"""Verify compile-time pragma parsing and preservation of executable artifacts.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    "pragma",
    [
        "__pragma(warning(push))",
        "__pragma(warning(disable: 4201))",
        '__pragma(comment(lib, "name)with(paren.lib"))',
        '__pragma(message("escaped \\" text"))',
        "__pragma(pack(push, 1))",
        "__pragma(/* comment ) */ warning(\n disable: 4201\n))",
        '__pragma("warning")',
        "__pragma(warning(push);)",
        "__pragma()",
        '_Pragma("GCC diagnostic push")',
        '_Pragma("message(\\"escaped ) text\\")")',
    ],
)
def test_compile_time_pragma_preserves_function_and_call_sites(
    tmp_path: Path, pragma: str
) -> None:
    """Recover pragma operators while preserving written definitions and calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.
    pragma : str
        Balanced compiler pragma operator.

    Returns
    -------
    None
    """
    source = (
        "int helper(int);\n"
        + pragma
        + "\nint target(int value) { return helper(value); }\n"
    )
    path = tmp_path / "sample.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    target = next(f for f in result.functions if f.name == "target")
    line = source[: source.index("int target")].count("\n") + 1
    assert target.lineno == target.end_lineno == line
    assert [(c.target, c.lineno, c.col_offset) for c in target.calls] == [
        ("helper", line, 31)
    ]


def test_clean_body_pragma_is_not_a_runtime_call(tmp_path: Path) -> None:
    """Exclude compiler operators even when the original provider tree is clean.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.

    Returns
    -------
    None
    """
    path = tmp_path / "sample.cpp"
    path.write_text(
        "int helper(int);\nint target(int x) { __pragma(warning(push)); return helper(x); }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [c.target for f in result.functions for c in f.calls] == ["helper"]


@pytest.mark.parametrize(
    "source",
    [
        "_Pragma(bad)\nint target(void) { return 1; }\n",
        '_Pragma("a" "b")\nint target(void) { return 1; }\n',
        "__pragma(warning(push)\nint target(void) { return 1; }\n",
        "__pragma(warning(push)) #define MADE_UP 1\nint target(void) { return 1; }\n",
        'const char *text = "__pragma(warning(push))";\nint broken( {\n',
        "#define WRAPPED __pragma(warning(push))\nint broken( {\n",
        "__pragma(warning(push) // note \\\n)\nint target(void) { return 1; }\n",
    ],
)
def test_malformed_and_directive_promotion_inputs_remain_partial(
    tmp_path: Path, source: str
) -> None:
    """Retain malformed operators, unrelated errors and invalid hash placement.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.
    source : str
        Malformed or unrelated-error input.

    Returns
    -------
    None
    """
    path = tmp_path / "sample.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    recoverable = source.startswith("_Pragma(") or source.startswith(
        "__pragma(warning(push)) #define"
    )
    if recoverable:
        assert result.index_symbols
        assert [item.name for item in result.functions] == ["target"]
        assert not result.functions[0].calls
    else:
        assert not result.index_symbols


@pytest.mark.parametrize("prefix", ["int __pragma(int);", "#define __pragma(x) x"])
def test_source_defined_spelling_is_not_reinterpreted(
    tmp_path: Path, prefix: str
) -> None:
    """Preserve ordinary source definitions of the implementation spelling.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.
    prefix : str
        Ordinary declaration or macro override.

    Returns
    -------
    None
    """
    path = tmp_path / "sample.cpp"
    path.write_text(
        prefix
        + "\nint warning(int); int push;\nint target(void) { return __pragma(warning(push)); }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    target = next(f for f in result.functions if f.name == "target")
    assert {c.target for c in target.calls} == {"__pragma", "warning"}


def test_pragma_before_source_annotation_keeps_annotation_identity(
    tmp_path: Path,
) -> None:
    """Exclude standalone pragmas while retaining source-backed API annotation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.

    Returns
    -------
    None
    """
    path = tmp_path / "sample.cpp"
    path.write_text(
        "#define API\n__pragma(warning(push))\nAPI\nint target(void) { return 1; }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    target = next(f for f in result.functions if f.name == "target")
    assert target.lineno == 3
    assert target.signature.startswith("API")
    assert "__pragma" not in target.signature


@pytest.mark.parametrize("operator", ["__pragma", "_Pragma"])
def test_captured_header_override_preserves_unexpanded_call(
    tmp_path: Path, operator: str
) -> None:
    """Honor pragma redefinitions in captured include inputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository containing a literal include.
    operator : str
        Reserved spelling overridden by that header.

    Returns
    -------
    None
    """
    (tmp_path / "override.h").write_text("#define " + operator + "(x) helper(x)\n")
    path = tmp_path / "sample.cpp"
    path.write_text(
        'int helper(int);\n#include "override.h"\nint target(void) { return '
        + operator
        + "(41); }\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    target = next(f for f in result.functions if f.name == "target")
    assert [c.target for c in target.calls] == [operator]
