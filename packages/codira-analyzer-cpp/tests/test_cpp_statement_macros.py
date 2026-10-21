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


def _analyze(
    tmp_path: Path, source: bytes, definitions: dict[str, str | bool] | None = None
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

    Returns
    -------
    AnalysisResult
        Production analyzer result, including conservative diagnostics.
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": definitions or {}})
    return analyzer.analyze_file(path, tmp_path)


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
    assert not result.index_symbols and result.status is not None
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
    assert not result.index_symbols and result.status is not None
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
    assert not result.index_symbols and result.status is not None
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
    assert result.index_symbols is known
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
    assert not result.index_symbols and result.status is not None


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
