"""Verify annotation recovery and preservation of unresolved C++ syntax.

Parameters
----------
None

Returns
-------
None
    Defines behavioral tests for the package-local projection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_preprocessing import _parse_cpp_source
from codira_analyzer_cpp.cpp_syntax import _new_parser


@pytest.mark.parametrize(
    "guard", ["ifdef FEATURE", "ifndef FEATURE", "if FEATURE", "if FLAG >= 1"]
)
@pytest.mark.parametrize("defined", [False, True])
@pytest.mark.parametrize("condition", ["cond", "!cond"])
def test_guarded_else_retains_both_static_bodies_and_original_scope(
    tmp_path: Path, guard: str, defined: bool, condition: str
) -> None:
    """Recover a guarded continuation without choosing a compilation branch.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root for original source and artifact coordinates.
    guard : str
        Single-arm conditional directive surrounding the else clause.
    defined : bool
        Explicit initial macro state; static extraction retains both arms.
    condition : str
        Continuation condition, including provider-clean but misparsed syntax.

    Returns
    -------
    None
        If-initializer scope, signatures and byte columns remain source-owned.
    """
    source = (
        "// café\r\nint make(); int left(int); int right(int);\r\n"
        "int entry(bool cond) {\r\n"
        "  if (int value = make(); cond) { return left(value); }\r\n"
        f"#{guard} // opening comment\r\n"
        f"  else if ({condition}) {{ return right(value); }}\r\n"
        "#endif // closing comment\r\n"
        "  return 0;\r\n}\r\n"
    ).encode()
    original = _new_parser().parse(source).root_node
    if condition.startswith("!"):
        assert original.has_error
    parsed = _parse_cpp_source(source)
    assert not parsed.has_error
    assert parsed.text is not None
    assert b"// opening comment" in parsed.text and b"// closing comment" in parsed.text
    function = next(n for n in parsed.named_children if n.type == "function_definition")
    body = function.child_by_field_name("body")
    assert body is not None
    statement = body.named_children[0]
    alternative = statement.child_by_field_name("alternative")
    assert alternative is not None
    assert source[alternative.start_byte : alternative.start_byte + 4] == b"else"
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure(
        {
            "preprocessor_definitions": {
                "FEATURE": "1" if defined else False,
                "FLAG": "1" if defined else False,
            }
        }
    )
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    artifact = next(f for f in result.functions if f.name == "entry")
    assert artifact.signature == "int entry(bool cond)"
    assert [c.target for c in artifact.calls] == ["make", "left", "right"]
    for call in artifact.calls:
        offset = source.index(call.target.encode() + b"(", source.index(b"int entry"))
        assert (call.lineno, call.col_offset) == (
            source[:offset].count(b"\n") + 1,
            offset - source.rfind(b"\n", 0, offset) - 1,
        )
    assert path.read_bytes() == source


@pytest.mark.parametrize(
    "fragment",
    [
        b"#ifdef F\nelse if(!c) {}\n#endif\n",
        b"if(c) {}\nfirst();\n#ifdef F\nelse if(!c) {}\n#endif\n",
        b"if(c) {} else {}\n#ifdef F\nelse if(!c) {}\n#endif\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) {}\n#else\nelse {}\n#endif\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) {\n#ifdef G\nsecond();\n#endif\n}\n#endif\n",
        b"if(c) {}\n#ifdef F EXTRA\nelse if(!c) {}\n#endif\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) {}\n#endif extra();\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) {}\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) {} second();\n#endif\n",
        b"if(c) {}\n#ifdef F\nelse if(!c) { int bad = ; }\n#endif\n",
    ],
)
def test_unproven_else_guards_and_unrelated_errors_remain_visible(
    fragment: bytes,
) -> None:
    """Preserve malformed or unsupported continuations without suppressing errors.

    Parameters
    ----------
    fragment : bytes
        Unpaired, alternative, nested or otherwise malformed conditional suffix.

    Returns
    -------
    None
        The original partial tree and original bytes remain unchanged.
    """
    source = b"void entry(bool c) {\n" + fragment + b"}\n"
    original = _new_parser().parse(source).root_node
    assert original.has_error
    recovered = _parse_cpp_source(source)
    assert recovered.has_error
    assert str(recovered) == str(original)
    assert recovered.text == source


@pytest.mark.parametrize("keyword", [b"if", b"else"])
@pytest.mark.parametrize("directive", [b"define", b"undef"])
def test_conditional_else_keyword_overrides_prevent_recovery(
    keyword: bytes, directive: bytes
) -> None:
    """Hold continuation adaptation when captured headers override its keywords.

    Parameters
    ----------
    keyword : bytes
        Reserved control-flow spelling.
    directive : bytes
        Definition or undefinition invalidating its assumed meaning.

    Returns
    -------
    None
        Header-dependent recovery does not silently reinterpret a keyword macro.
    """
    source = b"void f(bool c) {if(c) {}\n#ifdef F\nelse if(!c) {}\n#endif\n}\n"
    header = (
        b"#"
        + directive
        + b" "
        + keyword
        + (b" value" if directive == b"define" else b"")
        + b"\n"
    )
    root = _parse_cpp_source(source, included_sources=((header, 0),))
    assert root.has_error and root.text == source


def test_missing_guard_name_is_not_a_continuation_recovery_candidate() -> None:
    """Preserve the provider result when its guard name crosses a physical newline.

    Parameters
    ----------
    None

    Returns
    -------
    None
        This adapter does not hide or reinterpret a malformed directive header.
    """
    source = b"void f(bool c) {if(c) {}\n#ifdef\nelse if(!c) {}\n#endif\n}\n"
    original = _new_parser().parse(source).root_node
    recovered = _parse_cpp_source(source)
    assert str(recovered) == str(original)
    assert recovered.text == source


@pytest.mark.parametrize(
    "definition",
    [
        b"#define API\n",
        b'#define API __attribute__((visibility("default")))\n',
        b"#define API __declspec(dllexport)\n",
        b"#define API [[nodiscard]]\n",
        b"#define ATTR [[nodiscard]]\n#define API ATTR\n",
        b"#define API ATTR\n#define ATTR [[nodiscard]]\n",
        b"#if SHARED\n#define API __declspec(dllexport)\n#else\n#define API\n#endif\n",
        b'#define API \\\n  __attribute__((visibility("default")))\n',
        b"#define API /* export marker */\n",
        b"#define API inline\n",
        b"#define API constexpr\n",
        b"#define API inline constexpr\n",
        b"#define API [[nodiscard]] inline constexpr\n",
        b"#define INLINE inline\n#define API INLINE constexpr\n",
        b"#define inline [[nodiscard]]\n#define API inline\n",
        b"#if VERSION\n#define API constexpr\n#else\n#define API\n#endif\n",
    ],
)
def test_local_annotation_definitions_recover_function(definition: bytes) -> None:
    """Recover declarations only from recognized local macro replacements.

    Parameters
    ----------
    definition : bytes
        Source-local object definition and any annotation aliases.

    Returns
    -------
    None
        A clean tree retains the original function and body coordinates.
    """
    source = definition + b"API int run(int x) { return callee(x); }\n"
    assert _new_parser().parse(source).root_node.has_error
    root = _parse_cpp_source(source)
    assert not root.has_error
    function = root.named_children[-1]
    assert function.type == "function_definition"
    assert function.end_byte == len(source) - 1
    body = function.child_by_field_name("body")
    assert body is not None
    assert source[body.start_byte : body.end_byte] == b"{ return callee(x); }"


@pytest.mark.parametrize(
    "source",
    [
        b"API int run() {}\n",
        b'#include "api.h"\nAPI int run() {}\n',
        b"API int run() {}\n#define API\n",
        b"#define API ATTR\nAPI int run() {}\n#define ATTR [[nodiscard]]\n",
        b"#define API [[nodiscard]]\n#undef API\nAPI int run() {}\n",
        b"#define API [[nodiscard]]\n# undef API\nAPI int run() {}\n",
        b"#if SHARED\n#define API [[nodiscard]]\n#else\n#define API Widget\n#endif\nAPI int run() {}\n",
        b"#if SHARED\n#define API [[nodiscard]]\n#else\n#define API(x) x\n#endif\nAPI int run() {}\n",
        b"#define API UNKNOWN\nAPI int run() {}\n",
        b"#define API OTHER\n#define OTHER API\nAPI int run() {}\n",
        b"#define API int\nAPI int run() {}\n",
        b"#define API static\nAPI int run() {}\n",
        b"#define API extern\nAPI int run() {}\n",
        b"#define inline Widget\n#define API inline\nAPI int run() {}\n",
        b"#define constexpr Widget\n#define API constexpr\nAPI int run() {}\n",
        b"#undef inline\n#define API inline\nAPI int run() {}\n",
        b"#define API const\nAPI int run() {}\n",
        b"#define API inline Widget\nAPI int run() {}\n",
        b"#if VERSION\n#define API constexpr\n#else\n#define API Widget\n#endif\nAPI int run() {}\n",
        b"#define API [[nodiscard]]\nAPI int run( { return; }\n",
        b"#define API [[nodiscard]]\nAPI int run() { return ; + }\n",
        b"#define API [[nodiscard]]\nAPI int run() {}\nint broken(\n",
        b"// #define API [[nodiscard]]\nAPI int run() {}\n",
        b'const char* text = "#define API [[nodiscard]]";\nAPI int run() {}\n',
    ],
)
def test_unproven_macros_and_unrelated_errors_remain_visible(source: bytes) -> None:
    """Keep the original diagnostic tree when recovery lacks sufficient proof.

    Parameters
    ----------
    source : bytes
        Unresolved, conflicting or malformed C++ source.

    Returns
    -------
    None
        Recovery retains exactly the original tree and source bytes.
    """
    original = _new_parser().parse(source).root_node
    assert original.has_error
    recovered = _parse_cpp_source(source)
    assert recovered.has_error
    assert str(recovered) == str(original)
    assert recovered.text == source


def test_projection_preserves_directives_literals_and_artifacts(tmp_path: Path) -> None:
    """Extract source signatures and calls after coordinate-preserving recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Methods, macros, literals and call positions retain original source data.
    """
    source = (
        b"#define API __declspec(dllexport)\n"
        b"#ifdef API\n"
        b"// API is an annotation; preserve this comment.\n"
        b"class API Widget { public:\n"
        b'    API int run(int x) { const char* text = "API"; return callee(x); }\n'
        b"};\n"
        b"#endif\n"
    )
    path = tmp_path / "widget.cpp"
    path.write_bytes(source)
    root = _parse_cpp_source(source)
    assert not root.has_error
    assert root.text is not None
    assert b"#ifdef API" in root.text
    assert b"#define API __declspec(dllexport)" in root.text
    assert b'"API"' in root.text
    assert b"// API is an annotation; preserve this comment." in root.text
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.classes) == 1
    assert result.classes[0].name == "Widget"
    method = result.classes[0].methods[0]
    assert method.name == "run"
    assert "API int run(int x)" in method.signature
    assert method.lineno == 5
    assert len(method.calls) == 1
    assert method.calls[0].target == "callee"
    assert method.calls[0].lineno == 5
    assert method.calls[0].col_offset == source.splitlines()[4].index(b"callee")
    assert any(item.name == "API" for item in result.declarations)
    assert path.read_bytes() == source


def test_header_specifiers_preserve_constructors_and_source_artifacts(
    tmp_path: Path,
) -> None:
    """Recover source-defined specifiers without losing signatures or calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Repository containing an explicitly configured support directory.

    Returns
    -------
    None
        The production analyzer retains constructor, function and call locations
        and the original macro spelling in signatures.
    """
    support = tmp_path / "support"
    support.mkdir()
    (support / "api.h").write_text(
        "#define INLINE inline\n#define API INLINE constexpr\n"
    )
    source = (
        '#include "api.h"\n'
        "struct Point { API Point(int value) : value(value) {} int value; };\n"
        "API int identity(int value) { return value; }\n"
        "int caller(int value) { return identity(value); }\n"
    )
    path = tmp_path / "point.cpp"
    path.write_text(source)
    analyzer = CppAnalyzer()
    assert not analyzer.analyze_file(path, tmp_path).index_symbols
    analyzer.configure({"include_search_paths": ["support"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    point = next(item for item in result.classes if item.name == "Point")
    constructor = next(item for item in point.methods if item.name == "Point")
    assert constructor.lineno == 2
    assert constructor.signature == "API Point(int value) : value(value)"
    identity = next(item for item in result.functions if item.name == "identity")
    assert identity.signature == "API int identity(int value)"
    assert identity.lineno == 3
    assert identity.parameters == ("value",)
    caller = next(item for item in result.functions if item.name == "caller")
    call = next(item for item in caller.calls if item.target == "identity")
    assert call.lineno == 4
    assert call.col_offset == source.splitlines()[3].index("identity")
    assert path.read_text() == source


def test_multiline_annotations_keep_original_start_and_utf8_calls(
    tmp_path: Path,
) -> None:
    """Retain the annotation line and UTF-8 byte offsets in recovered artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Original signature, documentation and call coordinates remain intact.
    """
    source = (
        "#define API [[nodiscard]]\n"
        "int callee(int);\n"
        "// Read a value.\n"
        "API\n"
        'int run(int x) { const char* label = "café"; return callee(x); }\n'
    ).encode()
    path = tmp_path / "multiline.cpp"
    path.write_bytes(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    function = next(item for item in result.functions if item.name == "run")
    assert function.lineno == 4
    assert function.signature == "API int run(int x)"
    assert function.docstring == "Read a value."
    assert len(function.calls) == 1
    assert function.calls[0].target == "callee"
    assert function.calls[0].lineno == 5
    assert function.calls[0].col_offset == source.splitlines()[4].index(b"callee")


def test_recovered_anonymous_functions_and_operators_are_not_omitted(
    tmp_path: Path,
) -> None:
    """Extract anonymous-namespace helpers and free or member operator names.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Callables retain separate identities across anonymous and named scopes.
    """
    path = tmp_path / "operators.cpp"
    path.write_text(
        '#define API __attribute__((visibility("default")))\n'
        "namespace demo {\n"
        "API int helper() { return 1; }\n"
        "namespace { API int helper() { return 2; } }\n"
        "namespace { API int second() { return 3; } }\n"
        "class Widget { public: API int operator()() { return 4; } };\n"
        "bool operator==(const Widget&, const Widget&) { return true; }\n"
        "bool operator!=(const Widget&, const Widget&) { return false; }\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    functions = {item.name: item for item in result.functions}
    assert set(functions) == {
        "demo::helper",
        "demo::(anonymous namespace)::helper",
        "demo::(anonymous namespace)::second",
        "demo::operator==",
        "demo::operator!=",
    }
    assert len({item.stable_id for item in functions.values()}) == 5
    assert [method.name for method in result.classes[0].methods] == ["operator()"]


@pytest.mark.parametrize("continuation", [b"", b"\\\n", b"\\\r\n"])
def test_empty_macro_cannot_create_a_preprocessor_directive(
    continuation: bytes,
) -> None:
    """Retain invalid directives even when an empty macro precedes the hash.

    Parameters
    ----------
    continuation : bytes
        Optional physical-line splice.

    Returns
    -------
    None
        Annotation projection cannot manufacture a preprocessing directive.
    """
    source = b"#define DROP\nDROP " + continuation + b"# include <stddef.h>\n"
    assert _parse_cpp_source(source).has_error
