"""Check source-proven loop-prefix recovery and written call preservation.

Parameters
----------
None

Returns
-------
None
    Public-analyzer controls for source evidence, scope and original positions.
"""

from pathlib import Path

import pytest

from codira_analyzer_c import CAnalyzer
from codira_analyzer_c.c_parser import _new_parser
from codira_analyzer_c.c_statement_macros import (
    statement_argument_macro_source,
    type_argument_macro_source,
)

_LOOP = b"#define ITERATE(cell, list) for (int cell = 0; cell < 3; cell++)\n"


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_loop_prefix_preserves_arguments_body_calls_and_positions(
    tmp_path: Path, ending: bytes
) -> None:
    """Retain written calls without emitting replacement-body helper calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    ending : bytes
        Physical source line ending.

    Returns
    -------
    None
        Checks complete parse, original signature, UTF-8 coordinates and calls.
    """
    source = (
        b"#define ITERATE(cell, list) for (int cell = setup(list); cell < 3; cell++)\n"
        b"int items(void);\nvoid sink(int cell);\nint sample(void) {\n"
        b"\t/* \xc3\xa9 */ ITERATE(cell, items()) { sink(cell); }\nreturn 0;\n}\n"
    ).replace(b"\n", ending)
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "sample")
    assert function.signature == "int sample(void)"
    assert function.parameters == ()
    assert (function.lineno, function.end_lineno) == (4, 7)
    assert [call.target for call in function.calls] == ["ITERATE", "items", "sink"]
    for call in function.calls:
        line = source.splitlines()[call.lineno - 1]
        assert line[call.col_offset :].startswith(call.target.encode() + b"(")
    assert path.read_bytes() == source
    assert "setup" not in {function.name for function in result.functions}


def test_forwarded_nested_loop_headers_and_included_availability(
    tmp_path: Path,
) -> None:
    """Use a contained reaching definition for a fixed-arity forwarding macro.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Preserves the source wrapper and body calls without expanded locals.
    """
    header = tmp_path / "include" / "loops.h"
    header.parent.mkdir()
    header.write_text(
        "#define EACH_INTERNAL(type, pointer, var, list, accessor) "
        "for(type pointer var=0; var<1; var++) for(int state=0; state<1; state++)\n"
        "#define EACH_POINTER(type, var, list) EACH_INTERNAL(type, *, var, list, read)\n"
    )
    path = tmp_path / "sample.c"
    path.write_text(
        '#include "loops.h"\n'
        "int sample(void) { EACH_POINTER(Item, cursor, items()) { touch(cursor); } return 0; }\n"
    )
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    identity = analyzer.analysis_input_fingerprint(path, tmp_path)
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [call.target for call in result.functions[0].calls] == [
        "EACH_POINTER",
        "items",
        "touch",
    ]
    assert analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    header.write_text(
        header.read_text().replace("for(int state=0; state<1; state++)", "return")
    )
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    assert not analyzer.analyze_file(path, tmp_path).index_symbols


def test_loop_prefix_keeps_dangling_else_and_nested_statement_scope(
    tmp_path: Path,
) -> None:
    """Preserve statement attachment for unbraced and nested macro bodies.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Recovers nested loops and keeps their written calls in source order.
    """
    path = tmp_path / "sample.c"
    path.write_bytes(
        _LOOP + b"void sample(int condition) { if (condition) ITERATE(a, list) "
        b"ITERATE(b, other) sink(a,b); else fallback(); }\n"
    )
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [call.target for call in result.functions[0].calls] == [
        "ITERATE",
        "ITERATE",
        "sink",
        "fallback",
    ]


def test_forwarded_type_argument_preserves_written_calls_and_coordinates(
    tmp_path: Path,
) -> None:
    """Project a proven forwarded type role while retaining written calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        The parser view recovers while source calls and their physical spans stay.
    """
    source = (
        b"#define ALLOC(ctx,type) ((type *)malloc(sizeof(type)))\n"
        b"#define WRAP(ctx,kind) ALLOC(ctx,kind)\n"
        b"int *factory(void);\nint *consume(void *);\n"
        b"int *sample(void *ctx) {\n"
        b"  return consume(WRAP(factory(), struct item *));\n"
        b"}\n"
    )
    path = tmp_path / "sample.c"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    sample = next(
        function for function in result.functions if function.name == "sample"
    )
    assert [call.target for call in sample.calls] == ["consume", "WRAP", "factory"]
    factory = next(call for call in sample.calls if call.target == "factory")
    assert factory.lineno == 6
    assert source.splitlines()[factory.lineno - 1][factory.col_offset :].startswith(
        b"factory("
    )
    assert all(call.target != "malloc" for call in sample.calls)
    assert path.read_bytes() == source


def test_type_argument_projection_requires_unambiguous_type_role() -> None:
    """Keep mixed, undefined, ordinary-call and call-containing cases intact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Only source-proven, call-free type arguments may be projected.
    """
    parser = _new_parser()
    cases = (
        b"int call(int, int);\nvoid f(void) { call(1, struct item); }\n",
        b"#define ALLOC(ctx,type) ((type *)malloc(sizeof(type)))\n"
        b"#undef ALLOC\nvoid f(void *ctx) { ALLOC(ctx, struct item); }\n",
        b"#define MIX(ctx,type) ((type *)malloc(sizeof(type)) + (type))\n"
        b"void f(void *ctx) { MIX(ctx, struct item); }\n",
        b"#define ALLOC(ctx,type) ((type *)malloc(sizeof(type)))\n"
        b"void f(void *ctx) { ALLOC(ctx, __typeof__(factory())); }\n",
        b"#define SIZEOF(value) sizeof(value)\nvoid f(void) { SIZEOF(object); }\n",
        b"#if HOST\n"
        b"#define ALLOC(ctx,type) ((type *)malloc(sizeof(type)))\n"
        b"#else\n#define ALLOC(ctx,type) ordinary(ctx,type)\n#endif\n"
        b"void f(void *ctx) { ALLOC(ctx, struct item); }\n",
    )
    for source in cases:
        root = parser.parse(source).root_node
        assert type_argument_macro_source(source, root, parser) == source


def test_type_argument_projection_rejects_keywords_and_invalid_type_spellings() -> None:
    """Reject non-type keywords and malformed specifier groups conservatively.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Keyword and invalid type spellings stay byte-for-byte in the parser view.
    """
    parser = _new_parser()
    prefix = (
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"void *helper(unsigned long);\n"
    )
    invalid_types = (
        b"return",
        b"goto",
        b"if",
        b"struct",
        b"union",
        b"enum",
        b"sizeof",
        b"unsigned unsigned",
        b"struct int",
        b"struct const item",
        b"enum volatile state",
        b"union restrict item",
        b"nullptr",
        b"true",
        b"false",
        b"thread_local",
        b"static_assert",
        b"typeof",
        b"typeof_unqual",
        b"_BitInt",
        b"alignas",
        b"alignof",
        b"constexpr",
        b"struct nullptr",
        b"enum true",
        b"union thread_local",
    )
    for spelling in invalid_types:
        source = (
            prefix + b"int sample(void) { return ALLOC(" + spelling + b") != 0; }\n"
        )
        root = parser.parse(source).root_node
        assert type_argument_macro_source(source, root, parser) == source


def test_analyzer_preserves_source_calls_for_invalid_type_role_tokens(
    tmp_path: Path,
) -> None:
    """Keep invalid token spellings out of projected type arguments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        The written invocation stays visible at its original source coordinate.
    """
    parser = _new_parser()
    prefix = (
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"void *helper(unsigned long);\n"
    )
    for spelling in (
        b"return",
        b"goto",
        b"if",
        b"struct",
        b"enum",
        b"unsigned unsigned",
        b"struct int",
        b"struct const item",
        b"enum volatile state",
        b"union restrict item",
        b"nullptr",
        b"true",
        b"false",
        b"thread_local",
        b"static_assert",
        b"typeof",
        b"typeof_unqual",
        b"_BitInt",
    ):
        source = (
            prefix + b"int sample(void) { return ALLOC(" + spelling + b") != 0; }\n"
        )
        path = tmp_path / "sample.c"
        path.write_bytes(source)
        result = CAnalyzer().analyze_file(path, tmp_path)
        sample = next(
            function for function in result.functions if function.name == "sample"
        )
        assert len(sample.calls) == 1
        call = sample.calls[0]
        assert call.target == "ALLOC"
        assert call.lineno == 3
        assert source.splitlines()[call.lineno - 1][call.col_offset :].startswith(
            b"ALLOC("
        )
        assert path.read_bytes() == source
        assert (
            type_argument_macro_source(source, parser.parse(source).root_node, parser)
            == source
        )


def test_type_argument_projection_keeps_valid_type_spellings() -> None:
    """Continue projecting supported built-in, typedef and tagged type names.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Valid source-proven type-role spellings retain the bounded projection.
    """
    parser = _new_parser()
    prefix = (
        b"typedef unsigned long word_t;\n"
        b"struct item { int value; };\n"
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"void *helper(unsigned long);\n"
    )
    valid_types = (
        b"int",
        b"bool",
        b"int unsigned",
        b"long int unsigned",
        b"word_t",
        b"struct item",
        b"const struct item *",
        b"struct item const *",
        b"volatile struct item *",
        b"const volatile unsigned long *",
        b"word_t const *",
    )
    for spelling in valid_types:
        source = (
            prefix + b"int sample(void) { return ALLOC(" + spelling + b") != 0; }\n"
        )
        root = parser.parse(source).root_node
        assert type_argument_macro_source(source, root, parser) != source


def test_c23_keyword_ambiguity_preserves_c17_typedef_source(
    tmp_path: Path,
) -> None:
    """Keep a C17 identifier spelling intact when it is a C23 keyword.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Ambiguous source is retained without selecting a C dialect.
    """
    parser = _new_parser()
    source = (
        b"typedef int nullptr;\n"
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"void *helper(unsigned long);\n"
        b"int sample(void) { return ALLOC(nullptr) != 0; }\n"
    )
    root = parser.parse(source).root_node
    assert type_argument_macro_source(source, root, parser) == source
    path = tmp_path / "c17-ambiguous.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    sample = next(
        function for function in result.functions if function.name == "sample"
    )
    assert result.index_symbols
    assert [call.target for call in sample.calls] == ["ALLOC"]


def test_included_type_macro_requires_reaching_header_definition(
    tmp_path: Path,
) -> None:
    """Apply type-role proof from a captured header only after its include.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        The reaching header macro recovers syntax and preserves written calls.
    """
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    (include_dir / "allocation.h").write_text(
        "#define ALLOC(ctx,type) ((type *)malloc(sizeof(type)))\n"
    )
    source = (
        '#include "allocation.h"\n'
        "int *factory(void);\nvoid use(void *);\n"
        "void sample(void *ctx) { use(ALLOC(factory(), struct item *)); }\n"
    )
    path = tmp_path / "sample.c"
    path.write_text(source)
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})

    result = analyzer.analyze_file(path, tmp_path)

    assert result.index_symbols
    sample = next(
        function for function in result.functions if function.name == "sample"
    )
    assert [call.target for call in sample.calls] == ["use", "ALLOC", "factory"]
    assert (include_dir / "allocation.h").read_text().startswith("#define ALLOC")


@pytest.mark.parametrize(
    ("definitions", "invocation", "suffix"),
    [
        (b"", b"ITERATE(a, list)", b""),
        (_LOOP + b"#undef ITERATE\n", b"ITERATE(a, list)", b""),
        (_LOOP + b"#define ITERATE something\n", b"ITERATE(a, list)", b""),
        (
            b"#if HOST\n"
            + _LOOP
            + b"#else\n#define ITERATE(a,b) ordinary(a,b)\n#endif\n",
            b"ITERATE(a, list)",
            b"",
        ),
        (b"#define ITERATE(a,b) for (a)\n", b"ITERATE(a, list)", b""),
        (b"#define ITERATE(a,b) for (;;) return\n", b"ITERATE(a, list)", b""),
        (_LOOP, b"ITERATE(a + 1)", b""),
        (_LOOP, b"ITERATE(a, list, third)", b""),
        (_LOOP + b"#define while other\n", b"ITERATE(a, list)", b""),
        (_LOOP + b"#define for other\n", b"ITERATE(a, list)", b""),
        (_LOOP + b"#undef for\n", b"ITERATE(a, list)", b""),
        (b"", b"ITERATE(a, list)", _LOOP),
        (b"#define ITERATE(a,b) ITERATE(a,b)\n", b"ITERATE(a, list)", b""),
        (
            b"#define ITERATE(a,b) OTHER_LOOP(a,b)\n#define OTHER_LOOP(a,b) ITERATE(a,b)\n",
            b"ITERATE(a, list)",
            b"",
        ),
        (b"#define ITERATE(a,...) for (;;)\n", b"ITERATE(a, list)", b""),
        (b"#define LOOP(a,b) for (;;)\n", b"LOOP(a, list)", b""),
        (b"#define ITERATE(a,b) for (a; b; a] )\n", b"ITERATE(a, list)", b""),
        (b"#define ITERATE(a,b,) for (;;)\n", b"ITERATE(a, list)", b""),
        (b"#define ITERATE(a,a) for (;;)\n", b"ITERATE(a, list)", b""),
    ],
)
def test_unsupported_loop_prefixes_remain_partial(
    tmp_path: Path, definitions: bytes, invocation: bytes, suffix: bytes
) -> None:
    """Hold absent, late, conflicting or unsupported source proof.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    definitions : bytes
        Leading directives.
    invocation : bytes
        Candidate statement prefix.
    suffix : bytes
        Trailing directives, unavailable at the invocation.

    Returns
    -------
    None
        Keeps parser diagnostics for unsupported syntax and context.
    """
    path = tmp_path / "sample.c"
    path.write_bytes(
        definitions
        + b"void sample(void) { "
        + invocation
        + b" { sink(); } }\n"
        + suffix
    )
    assert not CAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_loop_recovery_does_not_hide_unrelated_errors_or_orphan_else(
    tmp_path: Path,
) -> None:
    """Require the entire recovered tree to remain valid.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Preserves independent malformed expressions and invalid statement scope.
    """
    path = tmp_path / "sample.c"
    for body in (
        b"ITERATE(a,list) { sink(); } return +;",
        b"ITERATE(a,list) sink(); else other();",
    ):
        path.write_bytes(_LOOP + b"void sample(void) { " + body + b" }\n")
        assert not CAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_statement_argument_macro_keeps_written_calls_and_physical_positions(
    tmp_path: Path,
) -> None:
    """Recover a source statement argument while retaining its written calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Keeps the macro invocation, nested argument call and following body call.
    """
    source = (
        "#define REPORT(ctx) generated_report(ctx)\n"
        "#define FAIL(ctx, code) do { REPORT(ctx); code; } while (0)\n"
        "int nested(int); int after(void);\n"
        "int sample(int ctx) {\n"
        "    /* é */ FAIL(ctx, return nested(ctx)); after(); return 0;\n"
        "}\n"
    )
    path = tmp_path / "sample.c"
    path.write_text(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "sample")
    assert [call.target for call in function.calls] == ["FAIL", "nested", "after"]
    nested_call = next(call for call in function.calls if call.target == "nested")
    line = source.splitlines()[nested_call.lineno - 1]
    assert line.encode()[nested_call.col_offset :].startswith(b"nested(")
    assert nested_call.lineno == 5


@pytest.mark.parametrize(
    ("argument", "target", "baseline_clean"),
    [
        (b"return\xc3\xa9()", "returné", True),
        (b"return\xce\xb1()", "returnα", True),
        (b"return\\u00e9()", "return\\u00e9", True),
        (b"goto$label()", "goto$label", True),
        (b"return\\\nvalue()", "returnvalue", False),
    ],
)
def test_statement_keyword_boundary_preserves_ambiguous_call_spellings(
    tmp_path: Path, argument: bytes, target: str, baseline_clean: bool
) -> None:
    """Keep non-ASCII, extension and spliced identifiers intact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    argument : bytes
        Physical call spelling supplied as the macro's statement argument.
    target : str
        Expected call name when the current parser represents the spelling.
    baseline_clean : bool
        Whether the current parser can retain a complete function syntax tree.

    Returns
    -------
    None
        Ambiguous token boundaries remain unchanged and written calls survive.
    """
    parser = _new_parser()
    declarations = {
        "returné": b"int return\xc3\xa9(void);\n",
        "returnα": b"int return\xce\xb1(void);\n",
        "return\\u00e9": b"int return\\u00e9(void);\n",
        "goto$label": b"int goto$label(void);\n",
        "returnvalue": b"int returnvalue(void);\n",
    }
    source = (
        b"#define FAIL(ctx, code) do { code; } while (0)\n"
        + declarations[target]
        + b"int sample(void) { FAIL(0, "
        + argument
        + b"); return 0; }\n"
    )
    root = parser.parse(source).root_node
    assert statement_argument_macro_source(source, root, parser) == source
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols is baseline_clean
    assert path.read_bytes() == source
    if baseline_clean:
        sample = next(
            function for function in result.functions if function.name == "sample"
        )
        assert [call.target for call in sample.calls] == ["FAIL", target]
    else:
        sample = next(
            function for function in result.functions if function.name == "sample"
        )
        assert [call.target for call in sample.calls] == ["FAIL", "value"]


def test_statement_keyword_boundary_still_projects_return_call() -> None:
    """Continue projecting an unambiguous leading C return statement.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The real return keyword is blanked only at a proven token boundary.
    """
    parser = _new_parser()
    source = (
        b"#define FAIL(ctx, code) do { code; } while (0)\n"
        b"int nested(void);\n"
        b"int sample(void) { FAIL(0, return nested()); return 0; }\n"
    )
    root = parser.parse(source).root_node
    assert statement_argument_macro_source(source, root, parser) != source


@pytest.mark.parametrize(
    "prefix",
    [
        b"\xce\xb1",
        b"x$",
        b"\\u03b1",
        b"alpha\\\n",
        b"alpha\\\r\n",
    ],
)
def test_macro_scanners_require_whole_preprocessing_identifiers(
    tmp_path: Path, prefix: bytes
) -> None:
    """Do not project an ASCII macro suffix inside a larger identifier.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository used by the whole-analyzer check.
    prefix : bytes
        UTF-8, dollar, universal-character-name or spliced identifier prefix.

    Returns
    -------
    None
        Both projections leave uncertain macro-name boundaries intact.
    """
    source = (
        b"#define FAIL(ctx, code) do { code; } while (0)\n"
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"int nested(void);\n"
        b"int sample(void) {\n"
        b"    int *item = "
        + prefix
        + b"ALLOC(int);\n    "
        + prefix
        + b"FAIL(0, return nested());\n    return item != 0;\n}\n"
    )
    parser = _new_parser()
    root = parser.parse(source).root_node
    assert type_argument_macro_source(source, root, parser) == source
    assert statement_argument_macro_source(source, root, parser) == source

    path = tmp_path / "sample.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert not result.index_symbols
    assert path.read_bytes() == source


def test_macro_scanners_still_project_whole_identifiers(tmp_path: Path) -> None:
    """Keep ordinary unambiguous type and statement macro names projectable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository used by the whole-analyzer check.

    Returns
    -------
    None
        Whole-name macro calls recover their source syntax and calls.
    """
    parser = _new_parser()
    source = (
        b"#define FAIL(ctx, code) do { code; } while (0)\n"
        b"#define ALLOC(TYPE) ((TYPE *)helper(sizeof(TYPE)))\n"
        b"int nested(void);\n"
        b"int sample(void) { ALLOC(int); FAIL(0, return nested()); return 0; }\n"
    )
    root = parser.parse(source).root_node
    assert type_argument_macro_source(source, root, parser) != source
    assert statement_argument_macro_source(source, root, parser) != source
    path = tmp_path / "sample.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "sample")
    assert [call.target for call in function.calls] == ["ALLOC", "FAIL", "nested"]


def test_forwarded_statement_argument_macro_keeps_nested_source_calls(
    tmp_path: Path,
) -> None:
    """Resolve a fixed-arity forwarding chain without emitting helper calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Preserves only written invocation, argument and following-body calls.
    """
    path = tmp_path / "sample.c"
    path.write_text(
        "#define FAIL(ctx, code) do { generated_report(ctx); code; } while (0)\n"
        "#define ASSERT4(ctx, test, code, err) do { if (test) break; FAIL(ctx, code); } while (0)\n"
        "#define ASSERT(ctx, test, code) ASSERT4(ctx, test, code, 0)\n"
        "int nested(int); int after(void);\n"
        "int sample(int ctx, int condition) {\n"
        "    ASSERT(ctx, condition, return nested(ctx)); after(); return 0;\n"
        "}\n"
    )
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "sample")
    assert [call.target for call in function.calls] == ["ASSERT", "nested", "after"]
    assert "generated_report" not in {call.target for call in function.calls}


@pytest.mark.parametrize(
    "source",
    [
        (
            "int FAIL(int, int); int nested(void);\n"
            "int sample(void) { FAIL(0, return nested()); return 0; }\n"
        ),
        (
            "#define FAIL(ctx, code) do { code; } while (0)\n"
            "#undef FAIL\n"
            "int nested(void); int FAIL(int, int);\n"
            "int sample(void) { FAIL(0, return nested()); return 0; }\n"
        ),
        (
            "#if TARGET\n"
            "#define FAIL(ctx, code) do { code; } while (0)\n"
            "#else\n"
            "#define FAIL(ctx, code) consume(code)\n"
            "#endif\n"
            "int nested(void); int sample(void) { FAIL(0, return nested()); return 0; }\n"
        ),
        (
            "#define FAIL(ctx, code) do { consume(#code); code; } while (0)\n"
            "int nested(void); int sample(void) { FAIL(0, return nested()); return 0; }\n"
        ),
        (
            "#define FAIL(ctx, code) do { consume(code); code; } while (0)\n"
            "int nested(void); int sample(void) { FAIL(0, return nested()); return 0; }\n"
        ),
    ],
)
def test_unproven_statement_argument_macros_remain_partial(
    tmp_path: Path, source: str
) -> None:
    """Hold ordinary, undefined, conflicting and transformed macro contexts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    source : str
        Control source whose macro state or parameter role is unsupported.

    Returns
    -------
    None
        Does not turn an unproven statement argument into a clean function.
    """
    path = tmp_path / "sample.c"
    path.write_text(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert not result.index_symbols


def test_compatible_conditional_prefixes_do_not_select_branches(tmp_path: Path) -> None:
    """Accept a common statement role while keeping all written alternatives.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Requires compatible arity and role across all captured replacements.
    """
    path = tmp_path / "sample.c"
    path.write_bytes(
        b"#if HOST\n"
        + _LOOP
        + b"#else\n#define ITERATE(a,b) for (;condition(b);)\n#endif\n"
        b"void sample(void) { ITERATE(a,list) { sink(); } }\n"
    )
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [call.target for call in result.functions[0].calls] == ["ITERATE", "sink"]


@pytest.mark.parametrize("include_first", [False, True])
def test_included_loop_definition_must_reach_the_call(
    tmp_path: Path, include_first: bool
) -> None:
    """Keep an otherwise matching header unavailable before its include.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    include_first : bool
        Whether the source include precedes the macro invocation.

    Returns
    -------
    None
        Only a reaching definition permits structural recovery.
    """
    (tmp_path / "loops.h").write_bytes(_LOOP)
    include = b'#include "loops.h"\n'
    body = b"void sample(void) { ITERATE(a,list) { sink(); } }\n"
    path = tmp_path / "sample.c"
    path.write_bytes(include + body if include_first else body + include)
    assert CAnalyzer().analyze_file(path, tmp_path).index_symbols == include_first


@pytest.mark.parametrize("depth", [2, 70])
def test_forwarding_resolution_is_bounded(tmp_path: Path, depth: int) -> None:
    """Hold excessive alias depth rather than performing unbounded resolution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    depth : int
        Forwarding-chain length.

    Returns
    -------
    None
        Normal chains recover; excessive chains retain parser diagnostics.
    """
    path = tmp_path / "sample.c"
    definitions = b"".join(
        f"#define CHAIN_{index}(a,b) CHAIN_{index + 1}(a,b)\n".encode()
        for index in range(depth)
    )
    path.write_bytes(
        definitions
        + f"#define CHAIN_{depth}(a,b) for(;;)\n".encode()
        + b"void sample(void) { CHAIN_0(a,list) { sink(); } }\n"
    )
    assert CAnalyzer().analyze_file(path, tmp_path).index_symbols == (depth < 64)
