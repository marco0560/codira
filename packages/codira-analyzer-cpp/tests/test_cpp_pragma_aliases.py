"""Verify source-proven pragma aliases and string-only pragma operands.

Parameters
----------
None

Returns
-------
None
    Exercises compiler markup without evaluating conditional alternatives.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    ("definitions", "clean"),
    [
        (
            '#define S(x) #x\n#define PUSH _Pragma("clang diagnostic push")\n'
            "#define IGNORE(x) _Pragma(S(clang diagnostic ignored x))\n"
            '#define API PUSH IGNORE("-Wunused") IGNORE("-Wextra")\n',
            True,
        ),
        ('#define API _Pragma("clang diagnostic push")\n', True),
        (
            "#define S1(x) #x\n#define S(x) S1(x)\n#define API _Pragma(S(clang diagnostic push))\n",
            True,
        ),
        (
            '#define S(x) #x\n#define IGNORE(x) _Pragma(S(clang diagnostic ignored x))\n#define API IGNORE("-Wunused")\n',
            True,
        ),
        (
            '#if HOST\n#define API _Pragma("clang diagnostic push")\n#else\n#define API\n#endif\n',
            True,
        ),
        ("#define API __pragma(warning(push))\n", True),
        ("#define S(x) x\n#define API _Pragma(S(clang diagnostic push))\n", False),
        (
            "#define S(x) #x\n#undef S\n#define API _Pragma(S(clang diagnostic push))\n",
            False,
        ),
        ("#define S(x) #x\n#define API _Pragma(S(first,second))\n", False),
        (
            "#define S(x) OTHER(x)\n#define OTHER(x) S(x)\n#define API _Pragma(S(push))\n",
            False,
        ),
        (
            '#define _Pragma(x) int\n#define API _Pragma("clang diagnostic push")\n',
            False,
        ),
        ('#define API _Pragma("clang diagnostic push") int\n', False),
        ('#define API _Pragma("clang diagnostic push") extern "C"\n', False),
    ],
)
def test_pragma_aliases(tmp_path: Path, definitions: str, clean: bool) -> None:
    """Recover only complete markup and preserve original source coordinates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository boundary.
    definitions : str
        Captured definitions with supported or invalidated alternatives.
    clean : bool
        Expected complete grammar recovery.

    Returns
    -------
    None
        Signatures, parameter names and call columns retain original text.
    """
    (tmp_path / "api.h").write_text(definitions)
    source = '#include "api.h"\nint helper(int x);\nAPI int run(int x) { /* café */ return helper(x); }\n'
    path = tmp_path / "unit.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    if clean:
        assert result.index_symbols
        assert result.status is None
        function = next(f for f in result.functions if f.name == "run")
        assert function.signature == "API int run(int x)"
        assert function.parameters == ("x",)
        assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
            ("helper", 3, source.encode().splitlines()[2].index(b"helper"))
        ]
    else:
        assert result.index_symbols
        assert result.status is not None
        assert result.status.coverage_state.value == "partial"
        assert [function.name for function in result.functions] == ["helper"]


def test_stringifier_availability(tmp_path: Path) -> None:
    """Reject a use preceding the stringifier needed by its pragma operand.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source boundary.

    Returns
    -------
    None
        The late definition cannot license an earlier compiler operator.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "#define API _Pragma(S(clang diagnostic push))\nAPI int run() { return 0; }\n#define S(x) #x\n"
    )
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols
