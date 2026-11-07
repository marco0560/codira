"""Exercise source-backed statement macro selection and physical call metadata.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

import pytest

from codira.models import AnalysisResult
from codira_analyzer_cpp import CppAnalyzer


def _assert_partial_source_entry(result: AnalysisResult) -> None:
    """Require a retained source entry with uncertain calls unresolved.

    Parameters
    ----------
    result : codira.models.AnalysisResult
        Source-first analysis after an unsupported generated expansion.

    Returns
    -------
    None
    """
    assert result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert any(function.name == "entry" for function in result.functions)
    assert all(
        call.target_identity is not None or call.resolution_mode == "exact"
        for call in result.iter_call_sites()
    )


def _analyze(
    tmp_path: Path,
    source: bytes,
    definitions: dict[str, str | bool] | None = None,
    features: dict[str, str] | None = None,
) -> AnalysisResult:
    """Analyze original bytes with explicit preprocessing facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted root.
    source : bytes
        Original physical source.
    definitions : dict[str, str or bool] or None, optional
        Known initial macro replacements or undefined states.
    features : dict[str, str] or None, optional
        Exact supported compiler query answers for this test profile.

    Returns
    -------
    AnalysisResult
        Production analyzer result, including conservative diagnostics.
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    config: dict[str, object] = {"preprocessor_definitions": dict(definitions or {})}
    if features:
        config["preprocessor_definitions"] = {
            **dict(definitions or {}),
            "__is_identifier": {"defined": True},
        }
        config["preprocessor_features"] = features
    analyzer.configure(config)
    return analyzer.analyze_file(path, tmp_path)


@pytest.mark.parametrize(
    "prefix",
    [
        "MARK ",
        "MARK\r\n",
        '_Pragma("GCC diagnostic push")\r\nMARK ',
        "MARK /* boundary */ ",
    ],
)
def test_statement_projection_retains_original_header_boundaries(
    tmp_path: Path, prefix: str
) -> None:
    """Preserve annotation, comment and pragma boundaries after statement mapping.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root for original source controls.
    prefix : str
        Physical header prefix, including multiline and pragma cases.

    Returns
    -------
    None
        Projection matches direct syntax without moving source call coordinates.
    """
    source = (
        "// café\r\n#define MARK constexpr\r\n"
        "#define CHECK(X) static_assert(X)\r\n"
        f"{prefix}bool entry() {{ CHECK(true); return true; }}\r\n"
    ).encode()
    direct = _analyze(tmp_path, source.replace(b"CHECK(true)", b"static_assert(true)"))
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    assert direct.index_symbols and direct.status is None
    function, expected = result.functions[0], direct.functions[0]
    assert (function.signature, function.lineno, function.end_lineno) == (
        expected.signature,
        expected.lineno,
        expected.end_lineno,
    )
    if "boundary" not in prefix:
        assert function.signature == "MARK bool entry()"
    call = function.calls[0]
    offset = source.index(b"CHECK(true)")
    assert (call.target, call.lineno, call.col_offset) == (
        "CHECK",
        source[:offset].count(b"\n") + 1,
        offset - source.rfind(b"\n", 0, offset) - 1,
    )


def test_statement_projection_preserves_other_callable_annotation_prefixes(
    tmp_path: Path,
) -> None:
    """Retain original method and unrelated function headers across one projection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root containing unchanged physical source.

    Returns
    -------
    None
        One assertion expansion cannot strip another callable's leading annotation.
    """
    source = (
        b"#define MARK constexpr\n#define CHECK(X) static_assert(X)\n"
        b"struct Item { MARK bool empty() const {return true;} };\n"
        b"MARK bool entry() {CHECK(true);return true;}\n"
        b"MARK bool other() {return false;}\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    assert [f.signature for f in result.functions] == [
        "MARK bool entry()",
        "MARK bool other()",
    ]
    assert result.classes[0].methods[0].signature == "MARK bool empty() const"


@pytest.mark.parametrize("name", ["ASSERT_TYPES", "assert_types"])
def test_variadic_type_assertion_retains_macro_hint(tmp_path: Path, name: str) -> None:
    """Accept template commas while preserving the physical source invocation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    name : str
        Arbitrary source-defined macro name.

    Returns
    -------
    None
    """
    source = (
        "template<class... T> struct same { static constexpr bool value = true; };\n"
        "template<class A, class B> struct pair {};\n"
        f"#define {name}(...) static_assert((same<__VA_ARGS__>::value))\n"
        f"void entry() {{ {name}(pair<int,int>, pair<int,int>); after(); }}\n"
    ).encode()
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert function.generated is None and function.signature == "void entry()"
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        (name, 4, 15),
        ("after", 4, source.splitlines()[3].index(b"after")),
    ]
    assert function.calls[0].external_target_kind == "C++:<macro>"


@pytest.mark.parametrize(
    "replacement",
    ["static_assert((X))", "static_assert((X) && (X))", "static_assert(noexcept(X))"],
)
def test_argument_calls_keep_utf8_crlf_coordinates(
    tmp_path: Path, replacement: str
) -> None:
    """Preserve one lexical site when expansion duplicates a multiline argument.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    replacement : str
        Assertion using its argument once or twice.

    Returns
    -------
    None
    """
    source = (
        f"#define CHECK(X) {replacement}\r\n"
        "constexpr bool okay() noexcept { return true; }\r\n"
        "void entry() { /* π */ CHECK(\r\n"
        "    okay()\r\n"
        "  ); after();\r\n"
        "}\r\n"
    ).encode()
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert (function.lineno, function.end_lineno) == (3, 6)
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("CHECK", 3, source.splitlines()[2].index(b"CHECK")),
        ("okay", 4, 4),
        ("after", 5, 5),
    ]


def test_method_argument_and_following_call_keep_ownership(tmp_path: Path) -> None:
    """Attach statement hints and physical operand calls to their class method.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\n"
        b"constexpr bool okay() { return true; }\n"
        b"struct Owner {\n"
        b"  void entry() { CHECK(okay()); after(); }\n"
        b"};\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    method = next(c for c in result.classes if c.name == "Owner").methods[0]
    assert [c.target for c in method.calls] == ["CHECK", "okay", "after"]
    assert all(c.lineno == 4 for c in method.calls)


@pytest.mark.parametrize("ndebug", [False, True])
def test_configured_statement_macro_keeps_written_calls_not_replacement_calls(
    tmp_path: Path, ndebug: bool
) -> None:
    """Keep lexical operand calls across debug and erased native expansions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    ndebug : bool
        Select the source-defined no-op branch when true.

    Returns
    -------
    None
        Source-written calls and the macro hint survive; implementation calls do not.
    """
    source = (
        b"#define DEBUG_WITH_TYPE(T, ...) do { replacement_only(); __VA_ARGS__; } while(false)\n"
        b"#ifdef NDEBUG\n"
        b"#define TRACE(...) do { } while(false)\n"
        b"#else\n"
        b'#define TRACE(...) DEBUG_WITH_TYPE("trace", __VA_ARGS__)\n'
        b"#endif\n"
        b"void entry() { TRACE(first(); second()); after(); }\n"
    )
    definitions: dict[str, str | bool] = {"NDEBUG": ndebug}
    result = _analyze(tmp_path, source, definitions)
    assert result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    function = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in function.calls] == [
        "TRACE",
        "first",
        "second",
        "after",
    ]
    assert [(call.lineno, call.col_offset) for call in function.calls] == [
        (7, source.splitlines()[6].index(b"TRACE")),
        (7, source.splitlines()[6].index(b"first")),
        (7, source.splitlines()[6].index(b"second")),
        (7, source.splitlines()[6].index(b"after")),
    ]
    assert all(call.target != "replacement_only" for call in function.calls)


@pytest.mark.parametrize(
    "replacement",
    [
        "do { consume(#x); } while(false)",
        "do { consume(prefix##x); } while(false)",
    ],
)
def test_statement_macro_holds_transformed_call_arguments(
    tmp_path: Path, replacement: str
) -> None:
    """Do not report calls whose only macro use stringifies or pastes them.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    replacement : str
        Statement replacement that transforms its call-shaped argument.

    Returns
    -------
    None
        The file remains partial instead of inventing a physical call.
    """
    source = (
        f"#define CHECK(x) {replacement}\nvoid entry() {{ CHECK(fake()); }}\n"
    ).encode()
    result = _analyze(tmp_path, source)
    _assert_partial_source_entry(result)
    entry = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in entry.calls] == ["CHECK", "fake"]
    assert result.status is not None
    assert any(
        "erases or transforms call-shaped argument spelling" in diagnostic.message
        for diagnostic in result.status.diagnostics
    )


def test_statement_macro_allows_argument_used_and_stringified(
    tmp_path: Path,
) -> None:
    """Keep a call when its source tokens are both evaluated and stringified.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The source call remains visible while replacement calls stay excluded.
    """
    source = (
        b"#define CHECK(x) do { consume(#x); consume(x); } while(false)\n"
        b"void entry() { CHECK(fake()); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in function.calls] == ["CHECK", "fake"]


def test_statement_macro_keeps_nested_call_through_type_wrapper_expansion(
    tmp_path: Path,
) -> None:
    """Retain a source call when only its enclosing type operator is rewritten.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The nested source call and adjacent runtime assertion remain indexed.
    """
    source = (
        b"#define decltype(...) __decltype(__VA_ARGS__)\n"
        b"#define CHECK(X) static_assert(sizeof(X) > 0)\n"
        b"int fake(); int runtime();\n"
        b"void entry() { CHECK(decltype(fake())); assert(runtime()); }\n"
    )
    result = _analyze(tmp_path, source, features={"__is_identifier(__decltype)": "0"})
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "entry")
    assert [call.target for call in function.calls] == [
        "CHECK",
        "fake",
        "assert",
        "runtime",
    ]


@pytest.mark.parametrize(
    "replacement",
    [
        "injected(__VA_ARGS__)",
        "__decltype(injected(__VA_ARGS__))",
        "__decltype(fake(__VA_ARGS__, 42))",
    ],
)
def test_statement_macro_holds_non_operator_or_modified_type_wrapper(
    tmp_path: Path, replacement: str
) -> None:
    """Reject generated helpers or extra call tokens inside type wrappers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    replacement : str
        Deliberately introduced helper or argument transformation.

    Returns
    -------
    None
        Unsupported expansion remains partial instead of claiming a complete
        source-call projection.
    """
    source = (
        f"#define decltype(...) {replacement}\n"
        "#define CHECK(X) static_assert(sizeof(X) > 0)\n"
        "int fake(); void entry() { CHECK(decltype(fake())); }\n"
    ).encode()
    result = _analyze(tmp_path, source, features={"__is_identifier(__decltype)": "0"})
    _assert_partial_source_entry(result)


def test_statement_macro_holds_type_wrapper_without_native_operator_proof(
    tmp_path: Path,
) -> None:
    """Keep generated operator identity unknown without compiler evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        An unresolved reserved-token query cannot authorize call projection.
    """
    source = (
        b"#define decltype(...) __decltype(__VA_ARGS__)\n"
        b"#define CHECK(X) static_assert(sizeof(X) > 0)\n"
        b"int fake(); void entry() { CHECK(decltype(fake())); }\n"
    )
    result = _analyze(tmp_path, source)
    _assert_partial_source_entry(result)


def test_statement_macro_holds_mixed_lost_and_preserved_calls(
    tmp_path: Path,
) -> None:
    """Reject a macro that preserves one argument call and stringifies another.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        A preserved sibling call does not license a stringified source call.
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(X, Y) do { consume(#X); consume(Y); } while(false)\n"
        b"void entry() { CHECK(lost(), kept()); }\n",
    )
    _assert_partial_source_entry(result)
    assert result.status is not None
    assert any(
        "erases or transforms call-shaped argument spelling" in diagnostic.message
        for diagnostic in result.status.diagnostics
    )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("static_assert(sizeof(#X) > 0)", "erases or transforms"),
        ("static_assert(sizeof(X##suffix) > 0)", "macro paste"),
        ("static_assert(helper(X))", "replacement-introduced call"),
        ("static_assert(X); int extra", "not one static assertion"),
    ],
)
def test_unsupported_statement_expansion_is_explicitly_partial(
    tmp_path: Path, replacement: str, message: str
) -> None:
    """Hold transformed operands, synthetic calls and extra generated declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    replacement : str
        Replacement violating lexical ownership or statement scope.
    message : str
        Required conservative diagnostic fragment.

    Returns
    -------
    None
    """
    source = (
        f"#define CHECK(X) {replacement}\nvoid entry() {{ CHECK(okay()); }}\n"
    ).encode()
    result = _analyze(tmp_path, source)
    _assert_partial_source_entry(result)
    assert result.status is not None
    assert any(message in d.message for d in result.status.diagnostics)


@pytest.mark.parametrize("generated", [False, True])
def test_erased_arguments_keep_physical_calls_and_method_ownership(
    tmp_path: Path, generated: bool
) -> None:
    """Retain erased operands without changing selected declaration syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    generated : bool
        Whether a declaration macro also produces the following function.

    Returns
    -------
    None
    """
    source = (
        b'#define CHECK(...) static_assert(true, "")\r\n'
        b"#define DECLARE(N) void N()\r\n"
        b"struct Owner {\r\n"
        + "void entry(int value) { /* π */ CHECK(\r\n".encode()
        + b"    object.member(value), ns::target<int>()\r\n"
        b"  ); after(); }\r\n};\r\n"
        + (
            b"DECLARE(unrelated) { following(); }\r\n"
            if generated
            else b"void unrelated() { following(); }\r\n"
        )
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    owner = next(c for c in result.classes if c.name == "Owner")
    method = next(m for m in owner.methods if m.name == "entry")
    assert [
        (c.kind, c.base, c.target, c.lineno, c.col_offset) for c in method.calls
    ] == [
        ("name", "", "CHECK", 4, source.splitlines()[3].index(b"CHECK")),
        ("attribute", "object", "member", 5, 11),
        ("name", "ns", "target<int>", 5, 26),
        ("name", "", "after", 6, 5),
    ]
    assert method.calls[0].external_target_kind == "C++:<macro>"
    assert [c.target for c in result.functions[-1].calls] == ["following"]


def test_erased_operands_do_not_add_declarations(tmp_path: Path) -> None:
    """Visit an erased lambda only for lexical calls rather than symbol inventory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(...) static_assert(true)\n"
        b"void entry() { CHECK(([&] { struct Hidden {}; nested(); return true; })()); }\n",
    )
    assert result.index_symbols and result.status is None
    assert [f.name for f in result.functions] == ["entry"]
    assert not result.classes
    assert not any(d.name == "Hidden" for d in result.declarations)
    assert [(c.kind, c.target) for c in result.functions[0].calls] == [
        ("name", "CHECK"),
        ("unresolved", ""),
        ("name", "nested"),
    ]


def test_partial_argument_erasure_remains_partial(tmp_path: Path) -> None:
    """Keep mixed preserved and erased operands outside this supported boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(X,Y) static_assert(X)\n"
        b"void entry() { CHECK(first(), second()); }\n",
    )
    _assert_partial_source_entry(result)
    assert result.status is not None
    assert any("erases or transforms" in d.message for d in result.status.diagnostics)


def test_erased_ambiguous_type_arguments_remain_partial(tmp_path: Path) -> None:
    """Reject an erased invocation whose complete argument syntax is unproven.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(...) static_assert(true)\n"
        b"void entry() { CHECK(int, target()); }\n",
    )
    _assert_partial_source_entry(result)
    assert result.status is not None
    assert any(
        "complete lexical syntax" in d.message for d in result.status.diagnostics
    )


@pytest.mark.parametrize("known", [False, True])
def test_conditional_selection_requires_reaching_definition(
    tmp_path: Path, known: bool
) -> None:
    """Keep conflicting unknown branches partial and honor explicit compiler facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    known : bool
        Whether the branch condition is explicitly supplied.

    Returns
    -------
    None
    """
    source = (
        b"#if FLAG\n#define CHECK(X) static_assert(X)\n"
        b"#else\n#define CHECK(X) static_assert(!(X))\n#endif\n"
        b"void entry() { CHECK(true); }\n"
    )
    result = _analyze(tmp_path, source, {"FLAG": True} if known else {})
    assert result.index_symbols
    if not known:
        assert result.status is not None
        assert any("uncertain reaching" in d.message for d in result.status.diagnostics)


def test_undefined_macro_keeps_ordinary_call(tmp_path: Path) -> None:
    """Preserve a function call after an explicit undef instead of expanding it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\n#undef CHECK\n"
        b"void entry() { CHECK(value()); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    assert [c.target for c in result.functions[0].calls] == ["CHECK", "value"]


def test_later_include_does_not_license_earlier_use(tmp_path: Path) -> None:
    """Respect source-order include boundaries when arguments are type syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    (tmp_path / "assert.h").write_text(
        "#define CHECK(...) static_assert(sizeof(__VA_ARGS__) > 0)\n"
    )
    result = _analyze(
        tmp_path,
        b'void entry() { CHECK(int); }\n#include "assert.h"\n',
        {"CHECK": False},
    )
    original = CppAnalyzer().analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert result == original


def test_comments_literals_and_directives_are_not_invocations(tmp_path: Path) -> None:
    """Expand the real statement without adapting textual lookalikes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\n"
        b"#define OTHER CHECK(int)\n"
        b'const char* text = "CHECK(int)";\n'
        b"// CHECK(int)\n"
        b"void entry() { CHECK(true); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    assert [(c.target, c.lineno) for c in result.functions[0].calls] == [("CHECK", 5)]


def test_unclosed_invocation_remains_partial(tmp_path: Path) -> None:
    """Keep malformed invocations visible instead of masking their syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(X) static_assert(X)\nvoid entry() { CHECK(true; }\n",
    )
    assert result.index_symbols and result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert [item.name for item in result.functions] == ["entry"]
    assert not result.functions[0].calls


def test_qualified_argument_keeps_original_template_spelling(tmp_path: Path) -> None:
    """Keep qualified callee text from physical bytes rather than rendered tokens.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\n"
        b"namespace ns { template<class T> constexpr bool okay() { return true; } }\n"
        b"void entry() { CHECK(ns::okay<\n  int>()); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert [(c.base, c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("", "CHECK", 3, 15),
        ("ns", "okay<\n  int>", 3, 21),
    ]


def test_ordered_redefinition_preserves_both_invocation_hints(tmp_path: Path) -> None:
    """Use the reaching assertion definition while retaining a later expression macro.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\nvoid first() { CHECK(true); }\n"
        b"#undef CHECK\n#define CHECK(X) other(X)\nvoid second() { CHECK(true); }\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    assert [(f.name, [c.target for c in f.calls]) for f in result.functions] == [
        ("first", ["CHECK"]),
        ("second", ["CHECK"]),
    ]


def test_header_snapshot_change_invalidates_statement_reuse(tmp_path: Path) -> None:
    """Bind statement adaptation to included header bytes and explicit guard facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated trusted root.

    Returns
    -------
    None
    """
    header = tmp_path / "assert.h"
    header.write_text(
        "#ifndef ASSERT_H\n#define ASSERT_H\n"
        "#define CHECK(X) static_assert(X)\n#endif\n"
    )
    source = b'#include "assert.h"\nvoid entry() { CHECK(true); }\n'
    result = _analyze(tmp_path, source, {"ASSERT_H": False})
    assert result.index_symbols and result.status is None
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {"ASSERT_H": False}})
    identity = analyzer.analysis_input_fingerprint(tmp_path / "unit.cpp", tmp_path)
    assert identity is not None
    assert analyzer.analysis_input_fingerprint_matches(
        tmp_path / "unit.cpp", tmp_path, identity
    )
    header.write_text(
        header.read_text().replace("static_assert(X)", "static_assert(helper(X))")
    )
    assert not analyzer.analysis_input_fingerprint_matches(
        tmp_path / "unit.cpp", tmp_path, identity
    )


def test_same_line_overload_body_retains_macro_hint(tmp_path: Path) -> None:
    """Use ordinary extraction ownership for separate same-line overloads.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(X) static_assert(X)\n"
        b"void entry(int x) {} void entry(char x) { CHECK(true); }\n",
    )
    assert result.index_symbols and result.status is None
    assert sorted(
        (f.signature, [(c.target, c.lineno, c.col_offset) for c in f.calls])
        for f in result.functions
    ) == [
        ("void entry(char x)", [("CHECK", 2, 42)]),
        ("void entry(int x)", []),
    ]


def test_template_header_owns_statement_macro_body(tmp_path: Path) -> None:
    """Preserve a template header line while finding its underlying function body.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    source = (
        b"#define CHECK(X) static_assert(X)\n"
        b"template<class T>\nvoid entry() {\n  CHECK(sizeof(T) > 0);\n}\n"
    )
    result = _analyze(tmp_path, source)
    assert result.index_symbols and result.status is None
    function = result.functions[0]
    assert (function.name, function.lineno, function.end_lineno) == ("entry", 2, 5)
    assert function.signature == "template<class T> void entry()"
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("CHECK", 4, 2)
    ]


def test_noexcept_operator_keeps_operand_call(tmp_path: Path) -> None:
    """Exclude the language operator while retaining its unevaluated source call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"int argument() noexcept;\nbool entry() { return noexcept(argument()); }\n",
    )
    assert result.index_symbols and result.status is None
    function = next(f for f in result.functions if f.name == "entry")
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("argument", 2, 31)
    ]


def test_type_alias_macro_argument_can_expand_without_inventing_calls(
    tmp_path: Path,
) -> None:
    """Allow type-token substitution when the source argument has no call shape.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define TYPE int\n#define CHECK(...) static_assert(sizeof(__VA_ARGS__) > 0)\n"
        b"void entry() { CHECK(TYPE); }\n",
    )
    assert result.index_symbols and result.status is None
    assert [(c.target, c.lineno) for c in result.functions[0].calls] == [("CHECK", 3)]


def test_declarations_after_multiline_assertion_keep_physical_lines(
    tmp_path: Path,
) -> None:
    """Preserve aliases and methods sharing the assertion's last physical line.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        b"#define CHECK(X) static_assert(X)\nstruct Owner {\n  CHECK(\n    true\n"
        b"  ); using Alias = int; void after() {}\n};\n",
    )
    assert result.index_symbols and result.status is None
    cls = next(c for c in result.classes if c.name == "Owner")
    assert (cls.lineno, cls.end_lineno) == (2, 6)
    assert [(m.name, m.lineno, m.end_lineno, m.calls) for m in cls.methods] == [
        ("after", 5, 5, ())
    ]
    assert next(d for d in result.declarations if d.kind == "type_alias").lineno == 5


def test_large_inactive_include_graph_preserves_statement_analysis(
    tmp_path: Path,
) -> None:
    """Analyze an SDK-sized graph while keeping inactive headers out of the walk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted source and literal include root.

    Returns
    -------
    None
        The active assertion macro and original function ownership are retained.
    """
    (tmp_path / "assert.h").write_text("#define CHECK(X) static_assert(X)\n")
    includes = []
    for i in range(1340):
        (tmp_path / f"unused{i}.h").write_text("#error inactive header\n")
        includes.append(f'#include "unused{i}.h"\n')
    source = (
        '#include "assert.h"\n#if 0\n'
        + "".join(includes)
        + "#endif\nvoid entry() { CHECK(true); }\n"
    ).encode()
    result = _analyze(tmp_path, source)
    assert result.status is None and result.index_symbols
    assert [f.name for f in result.functions] == ["entry"]
    function = result.functions[0]
    assert function.signature == "void entry()"
    assert [c.target for c in function.calls] == ["CHECK"]
    call = function.calls[0]
    assert call.lineno == source[: source.index(b"CHECK(true)")].count(b"\n") + 1
    assert call.col_offset == 15
