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
from unittest.mock import Mock

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
    assert [f.name for f in result.functions] == ["entry", "other", "after"]
    functions = {function.name: function for function in result.functions}
    assert [call.target for call in functions["entry"].calls] == (
        ["CHECK", "chosen"] if statement else ["chosen"]
    )
    assert [call.target for call in functions["other"].calls] == ["alternate"]
    assert {"entry", "other"} == set(functions) - {"after"}
    after = functions["after"]
    assert after.signature == "template<class T> void after()"
    assert after.lineno == 7 and [c.target for c in after.calls] == ["tail"]
    assert path.read_bytes() == source


def test_source_first_retains_clean_symbols_with_malformed_other_branch(
    tmp_path: Path,
) -> None:
    """Keep independently parsed source symbols and report partial coverage.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing one conditional source file.

    Returns
    -------
    None
    """
    source = (
        b"#if ENABLED\n"
        b"void selected() { first(); }\n"
        b"#else\n"
        b"malformed !\n"
        b"#endif\n"
        b"void outside() { last(); }\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {"ENABLED": True}})

    result = analyzer.analyze_file(path, tmp_path)

    assert result.index_symbols is True
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert {function.name for function in result.functions} == {"selected", "outside"}


def test_source_facts_survive_generated_context_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep clean source symbols when optional macro expansion reaches a bound.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing a source-only translation unit.
    monkeypatch : pytest.MonkeyPatch
        Forces optional generated expansion to report a bounded failure.

    Returns
    -------
    None
    """
    source = b"void entry() { source_call(); }\n"
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    monkeypatch.setattr(
        "codira_analyzer_cpp.cpp_generated_analysis.analyze_generated_file",
        Mock(side_effect=ValueError("macro binding limit exceeded")),
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert [function.name for function in result.functions] == ["entry"]
    assert result.functions[0].calls[0].target == "source_call"
    assert result.functions[0].calls[0].resolution_mode == "exact"


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
    assert result.index_symbols is True
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
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
    assert result.index_symbols is True
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
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


def test_source_first_branches_preserve_occurrences_and_unproven_calls(
    tmp_path: Path,
) -> None:
    """Index source branches without profiles and keep uncertain calls unresolved.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing only the source translation unit.

    Returns
    -------
    None
    """
    source = (
        b"#if defined(PLATFORM_A)\n"
        b"namespace platform_a { class Renderer { public: void draw() { a(); } }; }\n"
        b"void render() { platform_a_only(); }\n"
        b"#else\n"
        b"namespace platform_b { class Renderer { public: void draw() { b(); } }; }\n"
        b"void render() { platform_b_only(); }\n"
        b"#endif\n"
        b"void dispatch() { render(); }\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols and result.status is None, result
    assert path.read_bytes() == source
    assert {item.name for item in result.classes} == {
        "platform_a::Renderer",
        "platform_b::Renderer",
    }
    assert {
        (method.name, method.lineno, method.calls[0].target)
        for item in result.classes
        for method in item.methods
    } == {("draw", 2, "a"), ("draw", 5, "b")}
    renderers = [function for function in result.functions if function.name == "render"]
    assert [(function.lineno, function.calls[0].target) for function in renderers] == [
        (3, "platform_a_only"),
        (6, "platform_b_only"),
    ]
    assert len({function.stable_id for function in renderers}) == 2
    dispatch = next(
        function for function in result.functions if function.name == "dispatch"
    )
    ambiguous = dispatch.calls[0]
    assert ambiguous.target == "render"
    assert ambiguous.target_identity is None
    assert ambiguous.resolution_mode == "exact"
    assert ambiguous.external_target_kind is None
    assert ambiguous.external_target_name == "render"
    assert source.splitlines()[0] in path.read_bytes()


def test_same_name_class_occurrences_keep_branch_ownership(tmp_path: Path) -> None:
    """Keep class extents and method owners distinct across alternatives.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing two alternative class definitions.

    Returns
    -------
    None
    """
    source = (
        b"#if PLATFORM_A\n"
        b"namespace api { struct Renderer { void draw() { branch_a(); } }; }\n"
        b"#else\n"
        b"namespace api { struct Renderer { void draw() { branch_b(); } }; }\n"
        b"#endif\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols and result.status is None
    assert len(result.classes) == 2
    assert {item.name for item in result.classes} == {"api::Renderer"}
    assert [item.end_lineno for item in result.classes] == [2, 4]
    assert len({item.stable_id for item in result.classes}) == 2
    methods = [item.methods[0] for item in result.classes]
    assert [method.calls[0].target for method in methods] == ["branch_a", "branch_b"]
    assert len({method.stable_id for method in methods}) == 2
    assert [method.owner_stable_id for method in methods] == [
        item.stable_id for item in result.classes
    ]


def test_unproven_uppercase_call_is_not_classified_as_macro(tmp_path: Path) -> None:
    """Keep uppercase spelling without inventing a macro classification.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing a source-only translation unit.

    Returns
    -------
    None
    """
    path = tmp_path / "unit.cpp"
    path.write_text("void entry() { API(); }\n")

    result = CppAnalyzer().analyze_file(path, tmp_path)

    call = result.functions[0].calls[0]
    assert call.target == "API"
    assert call.resolution_mode == "exact"
    assert call.external_target_name == "API"
    assert call.external_target_kind is None


def test_out_of_branch_method_does_not_create_ambiguous_class_owner(
    tmp_path: Path,
) -> None:
    """Keep an out-of-class definition without fabricating a third class.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository containing alternative class definitions.

    Returns
    -------
    None
    """
    source = (
        b"#if PLATFORM_A\n"
        b"class C { public: void first() {} };\n"
        b"#else\n"
        b"class C { public: void second() {} };\n"
        b"#endif\n"
        b"void C::outside() {}\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols and result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert "class_method_ownership" in result.status.omitted_categories
    assert [(item.name, item.lineno) for item in result.classes] == [
        ("C", 2),
        ("C", 4),
    ]
    assert [method.name for item in result.classes for method in item.methods] == [
        "first",
        "second",
    ]
    assert len(result.functions) == 1
    outside = result.functions[0]
    assert outside.name == "outside"
    assert outside.signature == "void C::outside()"
    assert outside.is_method == 0
    assert outside.owner_name is None and outside.owner_stable_id is None


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
    assert result.index_symbols is True
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert [f.name for f in result.functions] == ["entry", "after"]
    assert [c.target for c in result.functions[0].calls] == (
        ["left", "right"] if outer else ["left"]
    )


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
