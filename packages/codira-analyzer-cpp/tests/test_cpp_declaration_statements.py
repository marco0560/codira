"""Exercise bounded declaration-forwarding statement macro projection.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

from codira.models import AnalysisResult
from codira_analyzer_cpp import CppAnalyzer


def _analyze(
    tmp_path: Path, source: bytes, definitions: dict[str, str | bool] | None = None
) -> AnalysisResult:
    """Analyze original bytes with explicit preprocessing facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted root.
    source : bytes
        Original physical translation unit.
    definitions : dict[str, str or bool] or None, optional
        Known initial macro replacements or definedness states.

    Returns
    -------
    AnalysisResult
        Production analysis with original physical call coordinates.
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": definitions or {}})
    return analyzer.analyze_file(path, tmp_path)


def test_forwarded_declaration_keeps_local_scope_and_nested_calls(
    tmp_path: Path,
) -> None:
    """Project only the declaration while preserving source-spelled calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The declaration remains owned by its method and nested calls retain
        their physical line and column positions.
    """
    source = (
        b"#define FORWARD(...) __VA_ARGS__\r\n"
        b"struct Item { explicit Item(int); };\r\n"
        b"int make();\r\n"
        b"struct Owner { void run() { FORWARD(int value = make()); after(); } };\r\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    owner = next(item for item in result.classes if item.name == "Owner")
    method = owner.methods[0]
    assert [call.target for call in method.calls] == ["FORWARD", "make", "after"]
    assert [(call.lineno, call.col_offset) for call in method.calls] == [
        (4, source.splitlines()[3].index(b"FORWARD")),
        (4, source.splitlines()[3].index(b"make")),
        (4, source.splitlines()[3].index(b"after")),
    ]


def test_forwarded_declaration_preserves_template_comma_and_crlf_offsets(
    tmp_path: Path,
) -> None:
    """Keep variadic declaration spelling and offsets across UTF-8 source.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Nested template commas remain one macro argument and source calls map
        back through CRLF and multibyte text.
    """
    source = (
        "// π\r\n"
        "#define FORWARD(...) __VA_ARGS__\r\n"
        "template<class A, class B> struct Pair {};\r\n"
        "void entry() { FORWARD(Pair<int, long> value); after(); }\r\n"
    ).encode()
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "entry")
    assert [item.target for item in function.calls] == ["FORWARD", "after"]
    call = function.calls[1]
    assert (call.target, call.lineno, call.col_offset) == (
        "after",
        4,
        source.splitlines()[3].index(b"after"),
    )


def test_known_empty_redefinition_erases_only_its_statement(tmp_path: Path) -> None:
    """Honor an ordered empty definition after a declaration-capable branch.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Known selected empty replacement leaves later source calls intact.
    """
    source = (
        b"#if OMIT_DECLARATION\n"
        b"#define FORWARD(...)\n"
        b"#else\n"
        b"#define FORWARD(...) __VA_ARGS__\n"
        b"#endif\n"
        b"void entry() { FORWARD(Type value); after(); }\n"
    )
    result = _analyze(tmp_path, source, {"OMIT_DECLARATION": True})
    assert result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    function = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in function.calls] == ["FORWARD", "after"]


def test_empty_replacement_keeps_macro_hint_and_lexical_expression_calls(
    tmp_path: Path,
) -> None:
    """Keep macro and nested call sites when an expression statement is erased.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Expression-position wrappers remain ordinary source syntax; local
        declaration wrappers keep a macro hint even when their expansion is empty.
    """
    source = (
        b"#if OMIT_DECLARATION\n"
        b"#define FORWARD(...)\n"
        b"#else\n"
        b"#define FORWARD(...) __VA_ARGS__\n"
        b"#endif\n"
        b"int target();\n"
        b"void entry() { FORWARD(Type value); FORWARD(target()); }\n"
        b"int returned() { return FORWARD(target()); }\n"
    )
    result = _analyze(tmp_path, source, {"OMIT_DECLARATION": True})
    assert result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    entry = next(item for item in result.functions if item.name == "entry")
    returned = next(item for item in result.functions if item.name == "returned")
    assert [call.target for call in entry.calls] == [
        "FORWARD",
        "FORWARD",
        "target",
    ]
    assert [call.target for call in returned.calls] == ["FORWARD", "target"]
    assert entry.calls[0].col_offset == source.splitlines()[6].index(b"FORWARD")
    assert returned.calls[0].col_offset == source.splitlines()[7].index(b"FORWARD")


def test_macro_hint_column_counts_same_line_utf8_bytes(tmp_path: Path) -> None:
    """Map declaration macro hints by physical byte column after UTF-8 text.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The wrapper hint retains the byte column from the original source line.
    """
    source = (
        "#define FORWARD(...) __VA_ARGS__\n"
        "void entry() { /* π */ FORWARD(Type value); after(); }\n"
    ).encode()
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "entry")
    wrapper = next(call for call in function.calls if call.target == "FORWARD")
    assert wrapper.col_offset == source.splitlines()[1].index(b"FORWARD")


def test_forwarder_wins_when_captured_statement_name_is_inactive(
    tmp_path: Path,
) -> None:
    """Resolve one invocation by its reaching definition across candidate kinds.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        A stale captured assertion shape cannot block a selected declaration.
    """
    (tmp_path / "support.h").write_bytes(
        b'#if 0\n#define BOTH(...) static_assert(true, "inactive")\n#endif\n'
    )
    source = (
        b'#include "support.h"\n'
        b"#define BOTH(...) __VA_ARGS__\n"
        b"struct Item {};\n"
        b"void entry() { BOTH(Item value); after(); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in function.calls] == ["BOTH", "after"]


def test_unknown_conditional_forwarder_remains_partial(tmp_path: Path) -> None:
    """Keep ambiguous macro state visible instead of selecting either branch.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Unknown profile state does not license declaration projection.
    """
    source = (
        b"#if OMIT_DECLARATION\n"
        b"#define FORWARD(...)\n"
        b"#else\n"
        b"#define FORWARD(...) __VA_ARGS__\n"
        b"#endif\n"
        b"void entry() { FORWARD(Type value); after(); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.status is not None


def test_redefinition_does_not_project_an_unsupported_later_body(
    tmp_path: Path,
) -> None:
    """Use the reaching replacement at each call and retain unsupported syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        A later non-forwarding definition stays visible to ordinary diagnostics.
    """
    source = (
        b"#define FORWARD(...) __VA_ARGS__\n"
        b"struct Item {};\n"
        b"void first() { FORWARD(Item value); }\n"
        b"#undef FORWARD\n"
        b"#define FORWARD(...) unsupported + replacement\n"
        b"void second() { FORWARD(Item value); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.status is not None


def test_non_declaration_macro_replacement_is_not_projected(tmp_path: Path) -> None:
    """Leave expression-like or unsupported replacements to ordinary parsing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        A macro without a captured declaration-forwarding definition is held.
    """
    source = b"#define FORWARD(...) ((void)0)\nvoid entry() { FORWARD(Type value); }\n"
    result = _analyze(tmp_path, source)
    assert result.status is not None


def test_empty_declaration_wrapper_preserves_template_and_member_calls(
    tmp_path: Path,
) -> None:
    """Keep nested template calls visible when a declaration wrapper erases them.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Template, member-template, nested and parenthesized call spellings remain
        in original syntax with the declaration macro hint.
    """
    cases = (
        ("template", b"target<int>()", ("target<int>",)),
        ("member", b"object.template member<int>()", ("template member<int>",)),
        ("nested", b"outer(target<int>())", ("outer", "target<int>")),
        ("parenthesized", b"(target<int>())", ("target<int>",)),
    )
    for name, operand, expected in cases:
        root = tmp_path / name
        root.mkdir()
        source = (
            b"#if OMIT_DECLARATION\n"
            b"#define FORWARD(...)\n"
            b"#else\n"
            b"#define FORWARD(...) __VA_ARGS__\n"
            b"#endif\n"
            b"void entry() { FORWARD(" + operand + b"); }\n"
        )
        result = _analyze(root, source, {"OMIT_DECLARATION": True})
        assert result.index_symbols and result.status is None
        function = next(item for item in result.functions if item.name == "entry")
        targets = [call.target for call in function.calls]
        assert targets == ["FORWARD", *expected]
        assert function.calls[0].col_offset == source.splitlines()[-1].index(b"FORWARD")


def test_empty_declaration_wrapper_holds_calling_initializer(tmp_path: Path) -> None:
    """Do not return a clean parse after erasing a declaration initializer call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Unsupported declaration-shaped call operands remain held and visible.
    """
    source = (
        b"#if OMIT_DECLARATION\n"
        b"#define FORWARD(...)\n"
        b"#else\n"
        b"#define FORWARD(...) __VA_ARGS__\n"
        b"#endif\n"
        b"struct Item {}; int make();\n"
        b"void entry() { FORWARD(Item value = make()); }\n"
    )
    result = _analyze(tmp_path, source, {"OMIT_DECLARATION": True})
    assert result.status is not None
    function = next(item for item in result.functions if item.name == "entry")
    assert function.calls == ()
