"""Verify exception-alias recovery without expanding prefixes or body expressions.

Parameters
----------
None

Returns
-------
None
    Defines suffix, availability and conservative-fallback regressions.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_preprocessing import _exception_suffix_source
from codira_analyzer_cpp.cpp_syntax import _new_parser


@pytest.mark.parametrize(
    "definitions",
    [
        "#define API throw()\n",
        "#define API throw(int)\n",
        "#define API noexcept\n",
        "#define API noexcept(true)\n",
        "#define API noexcept(CONDITION)\n#define CONDITION 1\n",
        "#define EXC throw()\n#define API EXC\n",
        "#define API EXC\n#define EXC throw()\n",
        "#if HOST\n#define API throw()\n#else\n#define API\n#endif\n",
        "#if HOST\n#define API throw()\n#else\n#define API noexcept\n#endif\n",
        '#define NAME int\n#define API noexcept("NAME")\n',
        "#define API throw() /* marker */\n",
    ],
)
def test_exception_suffix_alias_preserves_artifacts(
    tmp_path: Path, definitions: str
) -> None:
    """Recover compatible alternatives while retaining signatures and byte columns.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    definitions : str
        Captured exception-only alternatives and aliases.

    Returns
    -------
    None
        Function metadata and original operand calls remain exact.
    """
    path = tmp_path / "unit.cpp"
    source = (
        definitions + "int run(int value) API { /* café */ return helper(value); }\n"
    )
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = result.functions[0]
    assert function.name == "run"
    assert function.signature == "int run(int value) API"
    assert function.parameters == ("value",)
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        (
            "helper",
            len(source.splitlines()),
            source.encode().splitlines()[-1].index(b"helper"),
        )
    ]


def test_exception_suffix_covers_methods_and_constructors(tmp_path: Path) -> None:
    """Preserve cv-qualified methods, constructor initializers and prototypes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Suffix recovery keeps each original callable identity.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "#define API throw()\nstruct Box {\n"
        " Box() API : value(1) {}\n"
        " int run() const API { return helper(); }\n"
        " int prototype() volatile API;\n int value;\n};\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    methods = {method.name: method for cls in result.classes for method in cls.methods}
    assert set(methods) == {"Box", "run", "prototype"}
    assert "API" in methods["Box"].signature
    assert methods["run"].calls[0].target == "helper"


@pytest.mark.parametrize(
    "definitions",
    [
        "#define API int\n",
        '#define API extern "C"\n',
        "#define API const\n",
        "#define API throw() noexcept\n",
        "#if HOST\n#define API throw()\n#else\n#define API int\n#endif\n",
        "#define API OTHER\n#define OTHER API\n",
        "#define API throw()\n#undef API\n",
        "#define throw(x) int\n#define API throw()\n",
        "#define API(x) throw()\n",
    ],
)
def test_unproven_exception_aliases_remain_partial(
    tmp_path: Path, definitions: str
) -> None:
    """Hold incompatible, cyclic, undefined or non-object exception replacements.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    definitions : str
        Unsupported source declarations or alternatives.

    Returns
    -------
    None
        Incomplete proof cannot clear the file's diagnostics.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(definitions + "int run() API { return 1; }\n")
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_exception_alias_cannot_be_used_as_prefix(tmp_path: Path) -> None:
    """Keep malformed prefix use diagnosed beside a valid suffix use.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Recovery does not turn exception-only aliases into general annotations.
    """
    path = tmp_path / "unit.cpp"
    path.write_text("#define API throw()\nint valid() API {}\nAPI int broken() {}\n")
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_exception_suffix_does_not_rewrite_body(tmp_path: Path) -> None:
    """Keep opaque macro expressions and calls outside suffix recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Only the declarator occurrence changes in the syntax view.
    """
    source = b"#define API throw()\nint run() API { API; API(); return helper(); }\n"
    parser = _new_parser()
    view = _exception_suffix_source(source, parser.parse(source).root_node, parser, ())
    assert b"run()     { API; API();" in view
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [c.target for c in result.functions[0].calls] == ["API", "helper"]


def test_exception_alias_dependencies_must_reach_use(tmp_path: Path) -> None:
    """Hold an alias whose exception replacement becomes available too late.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Recursive resolution carries the latest dependency definition boundary.
    """
    path = tmp_path / "unit.cpp"
    path.write_text("#define API EXC\nint run() API {}\n#define EXC throw()\n")
    assert not CppAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_exception_alias_late_include_survives_scope_expansion(tmp_path: Path) -> None:
    """Keep original include boundaries when an earlier scope wrapper grows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.

    Returns
    -------
    None
        Namespace projection cannot license an alias before its source include.
    """
    (tmp_path / "exception.h").write_text("#define API throw()\n")
    path = tmp_path / "unit.cpp"
    path.write_text(
        "#define B namespace a_very_long_namespace { inline namespace ABI {\n"
        "#define E }}\nB\nint before() API {}\n"
        '#include "exception.h"\nint after() API {}\nE\n'
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"namespace_macro_definitions": {"ABI": "__1"}})
    assert not analyzer.analyze_file(path, tmp_path).index_symbols


def test_exception_aliases_cannot_accumulate_across_projections(tmp_path: Path) -> None:
    """Retain two incompatible suffix clauses under repeated recovery attempts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Each recovery stage sees the unsupported pair rather than erasing both.
    """
    path = tmp_path / "unit.cpp"
    path.write_text(
        "#define A throw()\n#define C noexcept\n"
        "#define B namespace outer { inline namespace ABI {\n#define E }}\n"
        "B\nint run() A C {}\nE\n"
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"namespace_macro_definitions": {"ABI": "__1"}})
    assert not analyzer.analyze_file(path, tmp_path).index_symbols
