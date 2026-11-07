"""Check function-derived object annotations without general macro expansion.

Parameters
----------
None

Returns
-------
None
    Exercises compatible compiler markup, invalidations and original positions.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_preprocessing import _macro_call_arguments, _nodes
from codira_analyzer_cpp.cpp_syntax import _new_parser


def test_named_return_misparsed_as_qualified_name(tmp_path: Path) -> None:
    """Preserve the written callable when a return type is mistaken for a scope.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks the callable name and partial coverage.
    """
    path = tmp_path / "math.h"
    path.write_text(
        "namespace math {\n"
        "LIBC_INLINE DoubleDouble calculate(const DoubleDouble &x) { return x; }\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert [function.name for function in result.functions] == ["math::calculate"]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_annotated_template_return_preserves_name_and_constraints(
    tmp_path: Path,
) -> None:
    """Keep written names and distinct return-constrained overloads.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks source names, lines and distinct callable identities.
    """
    path = tmp_path / "math.cpp"
    path.write_text(
        "namespace math {\n"
        "template<class T> API typename std::enable_if<P<T>::value,int>::type run(T x) { return x; }\n"
        "template<class T> API typename std::enable_if<!P<T>::value,int>::type run(T x) { return x; }\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    functions = [
        function for function in result.functions if function.name == "math::run"
    ]
    assert [function.lineno for function in functions] == [2, 3]
    assert len({function.stable_id for function in functions}) == 2
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_named_return_declaration_misparsed_as_scope(tmp_path: Path) -> None:
    """Keep the callable name in a source declaration with an annotation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks the written declaration name and partial coverage.
    """
    path = tmp_path / "api.h"
    path.write_text("API Result calculate(int value);\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert [function.name for function in result.functions] == ["calculate"]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_named_return_with_written_qualified_name(tmp_path: Path) -> None:
    """Keep an explicit callable qualifier after an unknown annotation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks the exact source-written qualified callable name.
    """
    path = tmp_path / "math.cpp"
    path.write_text("LIBC_INLINE DoubleDouble math::calculate() { return {}; }\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert [function.name for function in result.functions] == ["math::calculate"]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_unknown_annotation_named_return_preserves_written_name(tmp_path: Path) -> None:
    """Retain a source-backed function with a named return type.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks the name and partial coverage.
    """
    path = tmp_path / "unit.h"
    path.write_text(
        "namespace LIBC_NAMESPACE_DECL { namespace math {\n"
        "LIBC_INLINE bfloat16 calculate(double x) { return x; }\n"
        "}}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    functions = [*result.functions, *(m for cls in result.classes for m in cls.methods)]
    names = {function.name for function in functions}
    assert "LIBC_NAMESPACE_DECL::math::calculate" in names
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_unknown_annotation_conversion_is_not_named_after_type(tmp_path: Path) -> None:
    """Do not mistake a conversion operator's type for a function name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source directory.

    Returns
    -------
    None
        Checks that the return type is not indexed as a function.
    """
    path = tmp_path / "conversion.h"
    path.write_text(
        "class S {\npublic:\n  LIBC_INLINE operator bool() const { return true; }\n};\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    functions = [*result.functions, *(m for cls in result.classes for m in cls.methods)]
    assert "bool" not in {function.name for function in functions}


@pytest.mark.parametrize(
    ("definitions", "clean"),
    [
        (
            "#define VIS() __attribute__((unused))\n#define API VIS(/* empty */)\n",
            False,
        ),
        ("#define VIS() __attribute__((unused))\n#define API VIS()\n", True),
        (
            "#define VIS(v) __attribute__((unused))\n#define API VIS(std::pair<int,int>)\n",
            False,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#define API VIS("hidden")\n',
            True,
        ),
        (
            '#define LEAF(v) __attribute__((visibility(v)))\n#define VIS(v) LEAF(v)\n#define API VIS("hidden")\n',
            True,
        ),
        (
            '#if HOST\n#define VIS(v) __attribute__((visibility(v)))\n#else\n#define VIS(v)\n#endif\n#define API VIS("hidden")\n',
            True,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#define API VIS("hid,den")\n',
            True,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#define API VIS("hidden", "default")\n',
            False,
        ),
        (
            '#define VIS(a,b) __attribute__((annotate("tag")))\n#define API VIS(std::pair<int,int>)\n',
            True,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#undef VIS\n#define API VIS("hidden")\n',
            False,
        ),
        ("#define VIS(v) v\n#define API VIS(int)\n", False),
        ('#define VIS(v) extern "C"\n#define API VIS("hidden")\n', False),
        (
            '#if HOST\n#define VIS(v) __attribute__((visibility(v)))\n#else\n#define VIS(v) int\n#endif\n#define API VIS("hidden")\n',
            False,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#define VIS int\n#define API VIS("hidden")\n',
            False,
        ),
        (
            '#define VIS(...) __attribute__((unused))\n#define API VIS("hidden")\n',
            False,
        ),
        (
            '#define VIS(v) __attribute__((visibility(v)))\n#define VIS(v,...) __attribute__((unused))\n#define API VIS("hidden")\n',
            False,
        ),
        ('#define A(v) B(v)\n#define B(v) A(v)\n#define API A("hidden")\n', False),
        (
            '#define VIS(v) inline\n#define inline int\n#define API VIS("hidden")\n',
            False,
        ),
        ("#define EMPTY(v)\n#define API EMPTY(ignored)\n", False),
    ],
)
def test_function_annotation_alternatives(
    tmp_path: Path, definitions: str, clean: bool
) -> None:
    """Require annotation-only alternatives and preserve source artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source/header boundary.
    definitions : str
        Compatible macro alternatives or a specific unsupported replacement.
    clean : bool
        Whether source-backed annotation recovery is justified.

    Returns
    -------
    None
        Status, original signature, parameters and UTF-8 call columns match.
    """
    (tmp_path / "api.h").write_text(definitions)
    path = tmp_path / "unit.cpp"
    source = '#include "api.h"\nint helper(int value);\nAPI int run(int value) { /* café */ return helper(value); }\n'
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    if clean:
        assert result.index_symbols
        assert result.status is None
        function = next(f for f in result.functions if f.name == "run")
        assert function.signature == "API int run(int value)"
        assert function.parameters == ("value",)
        assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
            ("helper", 3, source.encode().splitlines()[2].index(b"helper"))
        ]
    else:
        assert result.index_symbols
        assert result.status is not None
        assert result.status.coverage_state.value == "partial"
        assert [function.name for function in result.functions] == ["helper", "run"]
        function = next(f for f in result.functions if f.name == "run")
        assert function.signature == "API int run(int value)"
        assert function.parameters == ("value",)
        assert [call.target for call in function.calls] == ["helper"]
        assert all(call.target_identity is None for call in function.calls)


@pytest.mark.parametrize("before", [True, False])
def test_function_annotation_availability(tmp_path: Path, before: bool) -> None:
    """Propagate the latest reaching function definition through object aliases.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source boundary.
    before : bool
        Whether the object alias is used before its function dependency exists.

    Returns
    -------
    None
        A late definition does not hide the written function or prove its expansion.
    """
    definition = "#define VIS(v) __attribute__((visibility(v)))\n"
    function = "API int run(int value) { return value; }\n"
    path = tmp_path / "unit.cpp"
    path.write_text(
        '#define API VIS("hidden")\n'
        + (function + definition if before else definition + function)
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [function.name for function in result.functions] == ["run"]
    if before:
        assert result.status is not None
        assert result.status.coverage_state.value == "partial"


def test_macro_argument_comment_is_preprocessing_whitespace() -> None:
    """Count comment-only parentheses as an empty preprocessing argument list.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The argument splitter handles comments independently of the provider's
        separate, still-held commented-directive parsing limitation.
    """
    source = b"VIS(/* empty */)"
    call = next(
        node
        for node in _nodes(_new_parser().parse(source).root_node)
        if node.type == "call_expression"
    )
    arguments = call.child_by_field_name("arguments")
    assert arguments is not None
    assert _macro_call_arguments(source, arguments) == ()
