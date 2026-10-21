"""Check source-evaluated visibility and independent spelling/coordinate proof.

Parameters
----------
None

Returns
-------
None
    Synthetic controls do not admit benchmark originals.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_active_source import project_root_activity
from codira_analyzer_cpp.cpp_macro_context import _ContextWalk
from codira_analyzer_cpp.cpp_macro_expansion import _MacroToken
from codira_analyzer_cpp.cpp_macro_projection import (
    MacroReplacement,
    project_macro_replacements,
)
from codira_analyzer_cpp.cpp_syntax import _new_parser


def test_activity_coordinates_do_not_license_masked_spelling() -> None:
    """Preserve CRLF/UTF8 locations without calling masked bytes original spelling.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source = (
        "// café\r\n#if 0\r\ninvalid syntax !\r\n#endif\r\nvoid entry() {}\r\n".encode()
    )
    walk = _ContextWalk({"unit.cpp": source}, {}, {}, track_root_activity=True)
    walk.walk("unit.cpp")
    projection = project_root_activity(
        project_macro_replacements(source, ()), walk.root_activity
    )
    assert projection.original == source
    assert len(projection.source) == len(source)
    assert [i for i, b in enumerate(projection.source) if b in (10, 13)] == [
        i for i, b in enumerate(source) if b in (10, 13)
    ]
    masked = source.index(b"invalid")
    assert projection.physical_span(masked, masked + 1) is None
    entry = source.index(b"entry")
    assert projection.physical_span(entry, entry + 5) == (entry, entry + 5)
    tree = _new_parser().parse(projection.source).root_node
    assert not tree.has_error
    mapped = projection.syntax_tree(tree)
    function = next(n for n in mapped.named_children if n.type == "function_definition")
    assert function.start_byte == source.index(b"void")
    assert function.start_point == (4, 0)
    assert mapped.text == projection.source


@pytest.mark.parametrize("condition", [b"UNKNOWN", b"0\n#elif UNKNOWN"])
def test_unknown_activity_retains_the_entire_original_view(condition: bytes) -> None:
    """Keep unknown branches conservative, including unknown empty elif arms.

    Parameters
    ----------
    condition : bytes
        Unresolved conditional form.

    Returns
    -------
    None
    """
    source = b"#if " + condition + b"\n#endif\nvoid entry() {}\n"
    walk = _ContextWalk({"unit.cpp": source}, {}, {}, track_root_activity=True)
    walk.walk("unit.cpp")
    original = project_macro_replacements(source, ())
    assert project_root_activity(original, walk.root_activity) is original


def test_activity_rejects_incomplete_and_overlapping_replacement_evidence() -> None:
    """Reject invalid coverage and masks crossing generated replacement bytes.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    original = project_macro_replacements(b"TOKEN", ())
    with pytest.raises(ValueError, match="incomplete"):
        project_root_activity(original, [(0, 4, False, None)])
    with pytest.raises(ValueError, match="invalid"):
        project_root_activity(original, [(1, 5, False, None)])
    generated = project_macro_replacements(
        b"TOKEN", (MacroReplacement((0, 5), (_MacroToken(b"int", 0, 5),)),)
    )
    with pytest.raises(ValueError, match="overlaps"):
        project_root_activity(generated, [(0, 5, False, None)])


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("statement", [False, True])
def test_known_branches_preserve_calls_signatures_and_source(
    tmp_path: Path, enabled: bool, statement: bool
) -> None:
    """Apply one source decision across ordinary and statement-generated syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.
    enabled : bool
        Explicit initial branch fact.
    statement : bool
        Whether active bodies contain selected statement macro expansions.

    Returns
    -------
    None
    """
    body = b"CHECK(true); chosen();" if statement else b"chosen();"
    source = (
        b"#define CHECK(X) static_assert(X)\n#if ENABLED\n"
        b"template<class T> void entry() { " + body + b" }\n"
        b"#else\ntemplate<class T> void other() { alternate(); }\n#endif\n"
        b"template<class T> void after() { tail(); }\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {"ENABLED": enabled}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None, result
    assert [f.name for f in result.functions] == [
        "entry" if enabled else "other",
        "after",
    ]
    first, after = result.functions
    expected = (
        ["CHECK", "chosen"]
        if statement and enabled
        else ["chosen" if enabled else "alternate"]
    )
    assert [c.target for c in first.calls] == expected
    assert after.signature == "template<class T> void after()"
    assert after.lineno == 7 and [c.target for c in after.calls] == ["tail"]
    assert path.read_bytes() == source


def test_unreachable_unknown_and_directive_shaped_literals(tmp_path: Path) -> None:
    """Ignore unreachable inner uncertainty while retaining literal directive text.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.

    Returns
    -------
    None
    """
    source = (
        b"#if 0\n#if UNKNOWN\ninvalid !\n#endif\n#endif\n"
        b'void entry() { const char* text = R"tag(\n#if UNKNOWN\n)tag"; target(); }\n'
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    walk = _ContextWalk({"unit.cpp": source}, {}, {}, track_root_activity=True)
    walk.walk("unit.cpp")
    projection = project_root_activity(
        project_macro_replacements(source, ()), walk.root_activity
    )
    assert b"#if UNKNOWN" in projection.source
    assert b"invalid" not in projection.source
    # The visibility view is lexical; separate existing macro-token limitations
    # must not be hidden by changing string spelling.
    source = source.replace(b'R"tag(\n#if UNKNOWN\n)tag"', b'"#if UNKNOWN"')
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert [f.name for f in result.functions] == ["entry"]
    assert [c.target for c in result.functions[0].calls] == ["target"]


def test_activity_does_not_hide_unrelated_active_grammar_errors(tmp_path: Path) -> None:
    """Retain conservative failure when selected ordinary syntax remains malformed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.

    Returns
    -------
    None
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(b"#if 0\nignored !\n#endif\nvoid entry( { bad ! }\n")
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    result = analyzer.analyze_file(path, tmp_path)
    assert not result.index_symbols


def test_activity_with_generated_namespace_and_statement(tmp_path: Path) -> None:
    """Compose visibility with variable-width namespace and statement expansion.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.

    Returns
    -------
    None
    """
    source = (
        b"#define NS actual_namespace\n#define CHECK(X) static_assert(X)\n"
        b"#if 0\ninvalid !\n#endif\nnamespace NS {\n"
        b"void entry() { CHECK(true); target(); }\n}\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None, result
    function = result.functions[0]
    assert function.name == "actual_namespace::entry"
    assert function.lineno == 7 and function.end_lineno == 7
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("CHECK", 7, 15),
        ("target", 7, 28),
    ]


def test_default_unconfigured_analysis_keeps_both_branches(tmp_path: Path) -> None:
    """Restrict selected-branch visibility to explicitly configured profiles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.

    Returns
    -------
    None
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(b"#if 0\nvoid first() {}\n#else\nvoid second() {}\n#endif\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert [f.name for f in result.functions] == ["first", "second"]


@pytest.mark.parametrize("outer", [False, True])
def test_static_continuation_preserves_only_reachable_enclosing_region(
    tmp_path: Path, outer: bool
) -> None:
    """Retain both runtime arms without resurrecting a wholly inactive function.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.
    outer : bool
        Known activity of the enclosing function region.

    Returns
    -------
    None
    """
    source = (
        b"#if OUTER\nvoid entry(bool flag) {\n if (flag) { left(); }\n"
        b"#if 0\n else { right(); }\n#endif\n}\n#endif\n"
        b"#if 0\ninvalid !\n#endif\nvoid after() { tail(); }\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {"OUTER": outer}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None, result
    assert [f.name for f in result.functions] == (
        ["entry", "after"] if outer else ["after"]
    )
    if outer:
        assert [c.target for c in result.functions[0].calls] == ["left", "right"]


@pytest.mark.parametrize("namespace", [b"plain", b"NS"])
def test_comment_ownership_survives_masked_directive_barriers(
    tmp_path: Path, namespace: bytes
) -> None:
    """Preserve original summaries and Doxygen across ordinary/generated scopes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source root.
    namespace : bytes
        Physical or macro-generated namespace spelling.

    Returns
    -------
    None
    """
    source = (
        b"#define NS actual_namespace\nnamespace " + namespace + b" {\n"
        b"// Outside guard, not a function summary.\n#if 1\nvoid first() {}\n"
        b"#endif // trailing guard comment\nvoid second() {}\n"
        b"/// Direct documentation.\nvoid documented() {}\n}\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None, result
    assert [f.docstring for f in result.functions] == [
        None,
        "trailing guard comment",
        "/ Direct documentation.",
    ]
    assert len(result.documentation) == 1
    assert result.documentation[0].text == "Direct documentation."
