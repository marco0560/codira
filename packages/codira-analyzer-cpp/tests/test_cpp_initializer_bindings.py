"""Verify lexical value and type bindings for ambiguous C++ initializers.

Parameters
----------
None

Returns
-------
None
    Exercises production call extraction across lexical declaration boundaries.
"""

import json
from pathlib import Path

import pytest

from codira_analyzer_cpp import (
    CppAnalyzer,
    _initializer_header_macro_namespaces,
    _initializer_namespace_matches,
    _initializer_header_value_bindings_from_walk,
    _initializer_header_value_query_plan,
)
from codira_analyzer_cpp.cpp_generated_analysis import _query_resolver
from codira_analyzer_cpp.cpp_include_context import read_include_context
from codira_analyzer_cpp.cpp_macro_context import _ContextWalk
from codira_analyzer_cpp.cpp_macro_context import MacroBinding, MacroSelection
from codira_analyzer_cpp.cpp_macro_expansion import _MacroDefinition
from codira_analyzer_cpp.cpp_namespace_bindings import _parse_with_namespace_bindings


@pytest.mark.parametrize(
    ("prefix", "initializer", "expected"),
    [
        ("void run(int token) {", "Reader r(token, wrap(get()));", ["wrap", "get"]),
        (
            "void run() { int token = 1;",
            "{ Reader r(token, wrap(get())); }",
            ["wrap", "get"],
        ),
        (
            "void run(int token) { int outer = 1;",
            "{ Reader r(outer, wrap(get())); }",
            ["wrap", "get"],
        ),
    ],
)
def test_initializer_calls_require_visible_value_bindings(
    tmp_path: Path, prefix: str, initializer: str, expected: list[str]
) -> None:
    """Recover calls only when an earlier lexical binding proves the first argument.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    prefix : str
        Function declaration and any outer-scope value binding.
    initializer : str
        Parenthesized declaration-shaped initializer.
    expected : list[str]
        Source-ordered nested calls licensed by the visible value.

    Returns
    -------
    None
        Calls retain original locations and the constructor variable stays absent.
    """
    source = f"{prefix} {initializer} }}"
    path = tmp_path / "bindings.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "run")
    assert [call.target for call in function.calls] == expected
    assert all(call.target != "r" for call in function.calls)


def test_qualified_function_proof_disambiguates_parenthesized_call(
    tmp_path: Path,
) -> None:
    """Use an active captured function declaration to license a qualified call.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        The same primary include walk proves the qualified callable declaration.
    """
    (tmp_path / "values.hpp").write_text("namespace vendor { int begin(int*); }\n")
    path = tmp_path / "qualified-call.cpp"
    path.write_text(
        '#include "values.hpp"\nvoid run() { int arr[2]; '
        "X result(vendor::begin(arr), work()); }"
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    result = analyzer.analyze_file(path, tmp_path)
    function = next(item for item in result.functions if item.name == "run")
    assert [call.target for call in function.calls] == ["begin", "work"]


def test_outer_value_does_not_reclassify_qualified_most_vexing_parse(
    tmp_path: Path,
) -> None:
    """Keep a qualified type declarator when its parameter name shadows a value.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        A visible outer value cannot license a nested type-shaped declarator.
    """
    (tmp_path / "types.hpp").write_text("namespace ns { struct Type {}; }\n")
    path = tmp_path / "qualified-type.cpp"
    path.write_text(
        '#include "types.hpp"\nstruct Foo {}; void run() { int arr = 1; '
        "Foo m(ns::Type(arr)); }"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    function = next(item for item in result.functions if item.name == "run")
    assert not function.calls


@pytest.mark.parametrize(
    "source",
    [
        "void run(int token) { { using token = int; Reader r(token, work()); } }",
        "void run() { using token = int; Reader r(token, work()); }",
        "void run() { Reader r(token, work()); int token = 1; }",
        "void run(int token) { auto nested = [] { Reader r(token, work()); }; }",
        "void run() { Reader r(token, work()); }",
    ],
)
def test_initializer_keeps_ambiguous_or_unavailable_bindings_conservative(
    tmp_path: Path, source: str
) -> None:
    """Preserve type shadows, source ordering and unavailable lexical evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    source : str
        Declaration without a usable value binding at the initializer site.

    Returns
    -------
    None
        No nested call is fabricated when the initializer remains ambiguous.
    """
    path = tmp_path / "ambiguous.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    function = next(item for item in result.functions if item.name == "run")
    assert not function.calls


def _captured_initializer_bindings(
    analyzer: CppAnalyzer, path: Path, root: Path
) -> tuple[dict[str, tuple[int, ...]], str]:
    """Run the same one-walk proof path used by generated analysis.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Configured analyzer with explicit macro state.
    path : pathlib.Path
        Original translation unit.
    root : pathlib.Path
        Containing repository root.

    Returns
    -------
    tuple[dict[str, tuple[int, ...]], str]
        Qualified facts and their original source offsets, plus the captured
        source identity used by stale-input checks.
    """
    context = read_include_context(path, root)
    source = context.source
    identity = json.loads(context.identity)
    key = identity["source_path"]
    captures = {
        key: source,
        **{
            header.path.relative_to(root).as_posix(): header.source
            for header in context.headers
        },
    }
    root_syntax = _parse_with_namespace_bindings(source)
    plan = _initializer_header_value_query_plan(
        analyzer, root_syntax, source, context, root
    )
    resolutions = {
        (owner, spelling, quoted): target if status == "resolved" else None
        for owner, spelling, quoted, status, target in identity["lookups"]
        if quoted is not None
    }
    answers = _query_resolver(analyzer, key, context, captures)
    assert analyzer._preprocessor_definitions is not None
    walk = _ContextWalk(
        captures,
        resolutions,
        analyzer._preprocessor_definitions,
        query_offsets=plan.header_query_offsets,
        query_resolver=None if answers is None else answers.resolve,
        feature_resolver=None if answers is None else answers.expand_feature,
    )
    walk.walk(key, offsets=plan.root_offsets)
    return (
        _initializer_header_value_bindings_from_walk(
            analyzer, root_syntax, source, context, root, captures, walk, plan
        ),
        analyzer.analysis_input_fingerprint(path, root),
    )


def test_header_value_proof_is_tied_to_primary_visit_and_rejects_alias_shadow(
    tmp_path: Path,
) -> None:
    """Prove only declarations reached through the primary include walk.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root with a literal contained header.

    Returns
    -------
    None
        Active header declarations license only their exact physical candidate;
        a visible namespace alias shadows the qualified header spelling.
    """
    header = tmp_path / "values.hpp"
    header.write_text(
        "#if FEATURE\nnamespace std { inline constexpr int from_range{}; }\n#endif\n"
    )
    path = tmp_path / "unit.cpp"
    source = (
        '#include "values.hpp"\nvoid run() { std::map x(std::from_range, Range()); }\n'
    )
    path.write_text(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {"FEATURE": True}})

    bindings, fingerprint = _captured_initializer_bindings(analyzer, path, tmp_path)
    declaration_offset = source.index("std::map")
    assert bindings == {"std::from_range": (declaration_offset,)}
    result = analyzer.analyze_file(path, tmp_path)
    function = next(item for item in result.functions if item.name == "run")
    assert [call.target for call in function.calls] == ["Range"]

    shadowed = source.replace("void run()", "namespace std = fake;\nvoid run()")
    path.write_text(shadowed)
    shadowed_bindings, _ = _captured_initializer_bindings(analyzer, path, tmp_path)
    assert not shadowed_bindings
    shadowed_result = analyzer.analyze_file(path, tmp_path)
    shadowed_function = next(
        item for item in shadowed_result.functions if item.name == "run"
    )
    assert not shadowed_function.calls

    path.write_text(source)
    header.write_text("namespace other { inline constexpr int from_range{}; }\n")
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, fingerprint)
    changed_bindings, _ = _captured_initializer_bindings(analyzer, path, tmp_path)
    assert not changed_bindings
    changed_result = analyzer.analyze_file(path, tmp_path)
    changed_function = next(
        item for item in changed_result.functions if item.name == "run"
    )
    assert not changed_function.calls


@pytest.mark.parametrize("namespace_alias", ["std", "vendor"])
def test_qualified_header_binding_rejects_alias_for_requested_root(
    tmp_path: Path, namespace_alias: str
) -> None:
    """Reject aliases for any written qualified namespace root.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root with a literal header.
    namespace_alias : str
        Qualified name root rebound by a visible namespace alias.

    Returns
    -------
    None
        Alias-shadowed values do not license nested initializer calls.
    """
    header = tmp_path / "values.hpp"
    header.write_text(
        f"namespace {namespace_alias} {{ inline constexpr int tag{{}}; }}\n"
    )
    path = tmp_path / "unit.cpp"
    alias_target = "std::fake" if namespace_alias == "std" else "other"
    source = (
        f'#include "values.hpp"\nnamespace {namespace_alias} = {alias_target};\n'
        f"void run() {{ X result({namespace_alias}::tag, nested()); }}\n"
    )
    path.write_text(source)
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})
    bindings, _fingerprint = _captured_initializer_bindings(analyzer, path, tmp_path)
    assert not bindings
    result = analyzer.analyze_file(path, tmp_path)
    function = next(item for item in result.functions if item.name == "run")
    assert not function.calls


@pytest.mark.parametrize(
    ("header", "expected_bindings", "expected_calls"),
    [
        (
            "namespace n { struct Token {}; struct Owner { static int Token; }; }\n",
            set(),
            [],
        ),
        (
            "namespace n { struct Token {}; inline void helper() { int Token = 1; } }\n",
            set(),
            [],
        ),
        (
            "namespace n { int Token(int); }\n",
            {"n::Token"},
            ["Token", "Other"],
        ),
    ],
    ids=[
        "class-member-is-not-ns-value",
        "function-local-is-not-ns-value",
        "ns-function-remains-value",
    ],
)
def test_header_value_proof_requires_namespace_visible_declarations(
    tmp_path: Path,
    header: str,
    expected_bindings: set[str],
    expected_calls: list[str],
) -> None:
    """Exclude class and function-local names while retaining namespace values.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root with one captured header.
    header : str
        Candidate declaration at class, function or namespace scope.
    expected_bindings : set[str]
        Qualified values that may be licensed by the header.
    expected_calls : list[str]
        Native-call-shaped spellings expected in the test function.

    Returns
    -------
    None
        Non-namespace declarations cannot turn a valid prototype into calls.
    """
    (tmp_path / "api.h").write_text(header)
    path = tmp_path / "case.cpp"
    path.write_text(
        '#include "api.h"\n'
        "int Other(); struct Box { Box(int, int); }; "
        "void f() { int arg = 1; Box value(n::Token(arg), Other()); }\n"
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"preprocessor_definitions": {}})

    bindings, _fingerprint = _captured_initializer_bindings(analyzer, path, tmp_path)
    assert set(bindings) == expected_bindings
    result = analyzer.analyze_file(path, tmp_path)
    function = next(item for item in result.functions if item.name == "f")
    assert [call.target for call in function.calls] == expected_calls


def test_header_macro_namespace_paths_preserve_nested_and_inline_components() -> None:
    """Do not collapse nested macro namespace paths to their final component.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Nested names require their whole path, while inline elision remains valid.
    """
    source = b"OPEN\nint tag{};\n"
    selected = MacroSelection(
        bindings=(
            (
                b"OPEN",
                MacroBinding(_MacroDefinition(None, b"namespace one::two {"), ()),
            ),
        ),
        uncertain=frozenset(),
        active=True,
        observations=(),
    )
    scopes = _initializer_header_macro_namespaces(
        source.index(b"int"), source, {0}, {0: selected}
    )
    assert scopes == (("one", False), ("two", False))
    assert not _initializer_namespace_matches(scopes, ("two",))
    assert _initializer_namespace_matches(scopes, ("one", "two"))

    inline_source = b"OPEN\nint tag{};\n"
    inline_selected = MacroSelection(
        bindings=(
            (
                b"OPEN",
                MacroBinding(
                    _MacroDefinition(None, b"namespace std { inline namespace __1 {"),
                    (),
                ),
            ),
        ),
        uncertain=frozenset(),
        active=True,
        observations=(),
    )
    inline_scopes = _initializer_header_macro_namespaces(
        inline_source.index(b"int"), inline_source, {0}, {0: inline_selected}
    )
    assert inline_scopes == (("std", False), ("__1", True))
    assert _initializer_namespace_matches(inline_scopes, ("std",))

    attributed_selected = MacroSelection(
        bindings=(
            (
                b"OPEN",
                MacroBinding(
                    _MacroDefinition(
                        None,
                        b'namespace __attribute__((__type_visibility__("default"))) std { inline namespace __1 {',
                    ),
                    (),
                ),
            ),
        ),
        uncertain=frozenset(),
        active=True,
        observations=(),
    )
    attributed_scopes = _initializer_header_macro_namespaces(
        inline_source.index(b"int"), inline_source, {0}, {0: attributed_selected}
    )
    assert attributed_scopes == (("std", False), ("__1", True))
    assert _initializer_namespace_matches(attributed_scopes, ("std",))
