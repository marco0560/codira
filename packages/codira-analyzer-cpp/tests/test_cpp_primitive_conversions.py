"""Verify primitive conversions preserve operand calls and source coordinates.

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
    "type_name",
    [
        "int",
        "bool",
        "char",
        "short",
        "long",
        "float",
        "double",
        "signed",
        "unsigned",
        "wchar_t",
        "char16_t",
        "char32_t",
    ],
)
def test_primitive_conversion_keeps_only_operand_call(
    tmp_path: Path, type_name: str
) -> None:
    """Exclude conversions while retaining their actual nested call positions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    type_name : str
        Native-verified C++17 fundamental conversion spelling.

    Returns
    -------
    None
    """
    path = tmp_path / "unit.cpp"
    source = f"int argument();\nvoid entry() {{ (void){type_name}(argument()); }}\n"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert [(c.kind, c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("name", "argument", 2, source.splitlines()[1].index("argument"))
    ]


def test_conversions_do_not_erase_indirect_calls_or_class_construction(
    tmp_path: Path,
) -> None:
    """Preserve unresolved indirect calls and ordinary named construction sites.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "struct Object { Object(int); };\n"
        "int argument();\n"
        "void entry(int (*fn)(int)) {\n"
        "  (void)int(argument());\n"
        "  (void)Object(argument());\n"
        "  (void)(*fn)(1);\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert [(c.kind, c.target, c.lineno) for c in function.calls] == [
        ("name", "argument", 4),
        ("name", "Object", 5),
        ("name", "argument", 5),
        ("unresolved", "", 6),
    ]
