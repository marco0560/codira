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
