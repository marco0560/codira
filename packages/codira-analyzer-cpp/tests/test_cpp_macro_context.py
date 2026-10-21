"""Check reaching definitions across source conditions and captured includes.

Parameters
----------
None

Returns
-------
None
    Source-order, ambiguity, provenance, literal and bounded failure controls.
"""

from __future__ import annotations

import pytest

from codira_analyzer_cpp.cpp_macro_context import (
    MacroBinding,
    MacroOrigin,
    MacroSelection,
    _ContextWalk,
    _Environment,
    _controlling_guard,
    _directives,
    _merge,
    select_macro_environments,
)
from codira_analyzer_cpp.cpp_macro_expansion import (
    _MacroDefinition,
    _expand_macro_tokens,
)


def _end(
    source: bytes, initial: dict[bytes, _MacroDefinition | None] | None = None
) -> MacroSelection:
    """Select the final state of one captured source without filesystem access.

    Parameters
    ----------
    source : bytes
        Exact test translation-unit bytes.
    initial : dict[bytes, _MacroDefinition | None] | None, optional
        Explicit initial macro states.

    Returns
    -------
    MacroSelection
        End-of-file environment after every conditional is balanced.
    """
    return select_macro_environments(
        "main.cpp", (len(source),), {"main.cpp": source}, {}, initial or {}
    )[len(source)]


def test_single_outcome_merge_preserves_independent_state() -> None:
    """Copy one proven branch without rebuilding origins or sharing mutable state.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Bindings, uncertainty and once-state remain equal and independently owned.
    """
    original = _Environment(
        {b"M": MacroBinding(_MacroDefinition(None, b"x"), (MacroOrigin(None, None),))},
        {b"UNKNOWN"},
        {"a.h"},
        {"b.h"},
    )
    merged = _merge([original])
    assert merged == original and merged is not original
    merged.bindings.clear()
    merged.uncertain.clear()
    merged.once.clear()
    merged.maybe_once.clear()
    assert b"M" in original.bindings and original.uncertain == {b"UNKNOWN"}
    assert original.once == {"a.h"} and original.maybe_once == {"b.h"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"#define M x\n", _MacroDefinition(None, b"x")),
        (b"/* prefix */ #define M x\n", _MacroDefinition(None, b"x")),
        (b"#/* hash */define M x\n", _MacroDefinition(None, b"x")),
        (b"#define /* name */ M x\n", _MacroDefinition(None, b"x")),
        (b"#define /* multi\n line */ M x\n", _MacroDefinition(None, b"x")),
        (
            b"#define M /* multi\n line */ x\n",
            _MacroDefinition(None, b"/* multi\n line */ x"),
        ),
        (b"#define M\n", _MacroDefinition(None, b"")),
        (b"#define M() x\n", _MacroDefinition((), b"x")),
        (b"#define M(x) x+1\n", _MacroDefinition((b"x",), b"x+1")),
        (b"#define M (x)\n", _MacroDefinition(None, b"(x)")),
        (b"#define M/**/(x)\n", _MacroDefinition(None, b"/**/(x)")),
        (b"#define M(/*)*/ x) x\n", _MacroDefinition((b"x",), b"x")),
        (b"#define M(...) __VA_ARGS__\n", _MacroDefinition((), b"__VA_ARGS__", True)),
        (
            b"#define M(x, ...) x __VA_ARGS__\n",
            _MacroDefinition((b"x",), b"x __VA_ARGS__", True),
        ),
        (b"#define M(x) \\\n x+1\n", _MacroDefinition((b"x",), b"x+1")),
        (b"#def\\\nine M x\n", _MacroDefinition(None, b"x")),
        (b"#define M x\n#undef M\n", None),
        (b"#define M x\n#define M y\n", _MacroDefinition(None, b"y")),
    ],
)
def test_source_macro_shapes(source: bytes, expected: _MacroDefinition | None) -> None:
    """Preserve replacement bytes, arity, explicit undefinition and splicing.

    Parameters
    ----------
    source : bytes
        Original definition sequence.
    expected : _MacroDefinition | None
        Reaching definition, or known undefined state.

    Returns
    -------
    None
        Checks definition shape and physical origin containment.
    """
    selection = _end(source)
    binding = dict(selection.bindings)[b"M"]
    assert binding.definition == expected
    assert b"M" not in selection.uncertain
    assert len(binding.origins) == 1
    origin = binding.origins[0]
    assert origin.source_path == "main.cpp" and origin.span is not None
    assert source[origin.span[0] : origin.span[1]].lstrip().startswith(b"#")


def test_late_definitions_do_not_reach_earlier_queries() -> None:
    """Snapshot each invocation before later source overrides or undefinitions.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks three immutable reaching states under the same original source.
    """
    source = b"FIRST\n#define M one\nSECOND\n#undef M\nTHIRD\n#define M late\n"
    offsets = tuple(source.index(token) for token in (b"FIRST", b"SECOND", b"THIRD"))
    initial = {b"M": _MacroDefinition(None, b"initial")}
    results = select_macro_environments(
        "a.cpp", offsets, {"a.cpp": source}, {}, initial
    )
    assert [dict(results[offset].bindings)[b"M"].definition for offset in offsets] == [
        initial[b"M"],
        _MacroDefinition(None, b"one"),
        None,
    ]
    first = dict(results[offsets[0]].bindings)[b"M"].origins[0]
    assert first.source_path is None and first.span is None
    assert initial == {b"M": _MacroDefinition(None, b"initial")}


@pytest.mark.parametrize(
    ("source", "expected", "uncertain", "origins"),
    [
        (
            b"#if CFG\n#define M x\n#else\n#define M x\n#endif\n",
            _MacroDefinition(None, b"x"),
            False,
            2,
        ),
        (b"#if CFG\n#define M x\n#else\n#define M y\n#endif\n", None, True, 0),
        (b"#if CFG\n#define M x\n#endif\n", None, True, 0),
        (b"#if CFG\n#undef M\n#else\n#undef M\n#endif\n", None, False, 2),
        (
            b"#if CFG\n#define M x\n#elif 1\n#define M x\n#else\n#define M y\n#endif\n",
            _MacroDefinition(None, b"x"),
            False,
            2,
        ),
        (
            b"#if 0\n#define M x\n#elif 1\n#define M y\n#endif\n",
            _MacroDefinition(None, b"y"),
            False,
            1,
        ),
        (
            b"#if 1\n#define M x\n#elif UNPROVEN\n#define M y\n#endif\n",
            _MacroDefinition(None, b"x"),
            False,
            1,
        ),
        (
            b"#if 0\n#if UNKNOWN\n#define M wrong\n#endif\n#endif\n#define M right\n",
            _MacroDefinition(None, b"right"),
            False,
            1,
        ),
    ],
)
def test_possible_branch_merge(
    source: bytes, expected: _MacroDefinition | None, uncertain: bool, origins: int
) -> None:
    """Agree across all possible branches or preserve an explicit uncertainty.

    Parameters
    ----------
    source : bytes
        Balanced known/unknown conditional definitions.
    expected : _MacroDefinition | None
        Agreed state, when any.
    uncertain : bool
        Whether the macro must remain unresolved.
    origins : int
        Distinct actual directive origins supporting an agreed state.

    Returns
    -------
    None
        No branch is selected merely to obtain a usable definition.
    """
    selection = _end(source)
    assert (b"M" in selection.uncertain) is uncertain
    binding = dict(selection.bindings).get(b"M")
    if uncertain:
        assert binding is None
    else:
        assert binding is not None and binding.definition == expected
        assert len(binding.origins) == origins


@pytest.mark.parametrize("setting", [True, False, None])
def test_query_activity_and_unrelated_uncertainty(setting: bool | None) -> None:
    """Distinguish inactive, active and conditional invocation positions.

    Parameters
    ----------
    setting : bool | None
        Known defined, explicitly undefined or missing flag.

    Returns
    -------
    None
        Preserves unrelated known macros after the unresolved branch.
    """
    source = b"#ifdef CFG\nHERE\n#define CHOICE one\n#else\n#define CHOICE two\n#endif\nEND\n"
    initial: dict[bytes, _MacroDefinition | None] = {
        b"STABLE": _MacroDefinition(None, b"constant")
    }
    if setting is not None:
        initial[b"CFG"] = _MacroDefinition(None, b"1") if setting else None
    offset = source.index(b"HERE")
    end = source.index(b"END")
    results = select_macro_environments(
        "a.cpp", (offset, end), {"a.cpp": source}, {}, initial
    )
    assert results[offset].active is setting
    assert results[end].active is True
    assert dict(results[end].bindings)[b"STABLE"].definition == initial[b"STABLE"]
    assert (b"CHOICE" in results[end].uncertain) is (setting is None)


def test_ordered_transitive_includes_and_reinclusion() -> None:
    """Use actual include order and replay unguarded headers after state changes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Verifies source order despite inverse lexical header names.
    """
    source = (
        b'#include "z.h"\n#include "a.h"\nFIRST\n#define FLAG 1\n#include "z.h"\nLAST\n'
    )
    captures = {
        "main.cpp": source,
        "z.h": b'#include "nested.h"\n#ifdef FLAG\n#define M changed\n#else\n#define M initial\n#endif\n',
        "nested.h": b"#define N nested\n",
        "a.h": b"#define M second\n",
    }
    resolutions = {
        ("main.cpp", "z.h", True): "z.h",
        ("main.cpp", "a.h", True): "a.h",
        ("z.h", "nested.h", True): "nested.h",
    }
    first, last = source.index(b"FIRST"), source.index(b"LAST")
    results = select_macro_environments(
        "main.cpp", (first, last), captures, resolutions, {b"FLAG": None}
    )
    assert dict(results[first].bindings)[b"M"].definition == _MacroDefinition(
        None, b"second"
    )
    assert dict(results[last].bindings)[b"M"].definition == _MacroDefinition(
        None, b"changed"
    )
    assert dict(results[last].bindings)[b"N"].origins[0].source_path == "nested.h"
    assert [observation.source_path for observation in results[last].observations] == [
        "main.cpp",
        "z.h",
        "main.cpp",
        "main.cpp",
        "z.h",
    ]


@pytest.mark.parametrize("guard", [b"#pragma once\n", b"#ifndef G\n#define G\n"])
def test_once_and_macro_guards(guard: bytes) -> None:
    """Keep first-include values when an explicit guard prevents reprocessing.

    Parameters
    ----------
    guard : bytes
        Pragma-once or conventional source guard.

    Returns
    -------
    None
        Later source undefinition is preserved across the guarded re-include.
    """
    source = b'#include "h.h"\n#undef M\n#include "h.h"\nEND\n'
    header = (
        guard
        + b"#define M value\n"
        + (b"#endif\n" if guard.startswith(b"#ifndef") else b"")
    )
    result = select_macro_environments(
        "a.cpp",
        (len(source),),
        {"a.cpp": source, "h.h": header},
        {("a.cpp", "h.h", True): "h.h"},
        {b"G": None},
    )[len(source)]
    assert dict(result.bindings)[b"M"].definition is None


def test_possibly_visited_once_header_does_not_invent_a_definition() -> None:
    """Preserve the correlation between conditional once visits and re-inclusion.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Holds a macro that is undefined on the previously visited path.
    """
    source = b'#if UNKNOWN\n#include "h.h"\n#endif\n#undef M\n#include "h.h"\n'
    result = select_macro_environments(
        "a.cpp",
        (len(source),),
        {"a.cpp": source, "h.h": b"#pragma once\n#define M value\n"},
        {("a.cpp", "h.h", True): "h.h"},
        {},
    )[len(source)]
    assert b"M" in result.uncertain and b"M" not in dict(result.bindings)
    assert any(observation.active is None for observation in result.observations)


def test_guarded_include_cycle_terminates() -> None:
    """Follow a recursive captured include only until its source guard is known.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Both guarded definitions remain available without a cycle rejection.
    """
    source = b'#include "one.h"\n'
    captures = {
        "main.cpp": source,
        "one.h": b'#ifndef ONE\n#define ONE\n#include "two.h"\n#define A one\n#endif\n',
        "two.h": b'#ifndef TWO\n#define TWO\n#include "one.h"\n#define B two\n#endif\n',
    }
    resolutions = {
        ("main.cpp", "one.h", True): "one.h",
        ("one.h", "two.h", True): "two.h",
        ("two.h", "one.h", True): "one.h",
    }
    result = select_macro_environments(
        "main.cpp", (len(source),), captures, resolutions, {b"ONE": None, b"TWO": None}
    )[len(source)]
    assert dict(result.bindings)[b"A"].definition == _MacroDefinition(None, b"one")
    assert dict(result.bindings)[b"B"].definition == _MacroDefinition(None, b"two")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"#ifndef G\n#define G\n#endif\n", b"G"),
        (b"/* before */ #ifndef /* name */ G\n#define G\n#endif /* after */\n", b"G"),
        (b"// before\n#ifndef G\n#if X\n#else\n#endif\n#endif\n", b"G"),
        (b"\\\n#ifndef G\n#endif\n\\\n", b"G"),
        (b"#ifndef G\n#endif\nint outside;\n", None),
        (b"int outside;\n#ifndef G\n#endif\n", None),
        (b'"outside"\n#ifndef G\n#endif\n', None),
        (b"#define BEFORE 1\n#ifndef G\n#endif\n", None),
        (b"#ifndef G\n#endif\n#define AFTER 1\n", None),
        (b"#ifndef G\n#else\n#define M alternate\n#endif\n", None),
        (b"#ifndef G\n#elif 1\n#define M alternate\n#endif\n", None),
        (b"#ifndef G\n#elifdef OTHER\n#endif\n", None),
        (b"#ifndef G\n#elifndef OTHER\n#endif\n", None),
        (b"#ifndef G EXTRA\n#endif\n", None),
        (b"#ifndef G\n#if 0\n#else extra\n#endif\n#endif\n", None),
        (b"#ifndef G\n#if 0\n#else\n#else\n#endif\n#endif\n", None),
        (b"#ifndef G\n#if 0\n#else\n#elif 1\n#endif\n#endif\n", None),
        (b"#ifndef G\n#if 0\n#endif extra\n#endif\n", None),
        (b"#ifndef G\n#if 0\n#endif\n", None),
        (b"#ifndef G\n#endif\n#endif\n", None),
        (b"#ifndef G\n", None),
        (b"#if !defined(G)\n#endif\n", None),
        (b"", None),
    ],
)
def test_whole_file_guard_requires_structural_proof(
    source: bytes, expected: bytes | None
) -> None:
    """Require a controlling guard without hiding outside tokens or bad structure.

    Parameters
    ----------
    source : bytes
        Candidate header with positive or negative guard evidence.
    expected : bytes | None
        Proven guard name or absence of proof.

    Returns
    -------
    None
        Invalid and non-controlling forms cannot use the skip optimization.
    """
    assert _controlling_guard(source, _directives(source)) == expected


def test_guarded_revisits_preserve_directive_budget() -> None:
    """Process a large guarded header once across many captured include visits.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Exact event accounting proves skipped bodies are never processed again.
    """
    source = b'#include "h.h"\n' * 100
    header = b"#ifndef G\n#define G\n" + b"#define M value\n" * 100 + b"#endif\n"
    walker = _ContextWalk(
        {"main.cpp": source, "h.h": header},
        {("main.cpp", "h.h", True): "h.h"},
        {b"G": None},
    )
    walker.walk("main.cpp", offsets=(len(source),))
    result = walker.results[len(source)]
    assert walker.events == 203
    assert len(result.observations) == 100
    assert dict(result.bindings)[b"M"].definition == _MacroDefinition(None, b"value")
    assert dict(result.bindings)[b"M"].origins[0].source_path == "h.h"


@pytest.mark.parametrize("guard", [None, _MacroDefinition(None, b"1")])
def test_guard_undefinition_allows_reinclude(guard: _MacroDefinition | None) -> None:
    """Re-evaluate a header after an explicit source undefinition of its guard.

    Parameters
    ----------
    guard : _MacroDefinition | None
        Initially defined or explicitly undefined guard.

    Returns
    -------
    None
        Later re-inclusion restores the header's captured definition.
    """
    source = b'#include "h.h"\n#undef G\n#include "h.h"\n'
    result = select_macro_environments(
        "main.cpp",
        (len(source),),
        {"main.cpp": source, "h.h": b"#ifndef G\n#define G\n#define M value\n#endif\n"},
        {("main.cpp", "h.h", True): "h.h"},
        {b"G": guard},
    )[len(source)]
    assert dict(result.bindings)[b"M"].definition == _MacroDefinition(None, b"value")


def test_unknown_guard_and_root_queries_are_not_skipped() -> None:
    """Keep unknown guard alternatives and snapshot inactive queried root regions.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A missing guard is never treated as defined or undefined.
    """
    header = b"#ifndef G\n#define G\n#define M value\nHERE\n#endif\n"
    assert b"M" in _end(header).uncertain
    offset = header.index(b"HERE")
    result = select_macro_environments(
        "main.cpp",
        (offset,),
        {"main.cpp": header},
        {},
        {b"G": _MacroDefinition(None, b"", opaque=True)},
    )[offset]
    assert result.active is False
    assert b"M" not in dict(result.bindings)


@pytest.mark.parametrize(
    "header",
    [
        b"#ifndef G\n#if 0\n#else extra\n#endif\n#endif\n",
        b"#ifndef G\n#if 0\n#else\n#else\n#endif\n#endif\n",
        b"#ifndef G\n#endif extra\n",
        b"#ifndef G\n#if 0\n#endif\n",
    ],
)
def test_defined_guard_does_not_hide_structural_errors(header: bytes) -> None:
    """Retain structural failures even under a known-defined outer guard.

    Parameters
    ----------
    header : bytes
        Malformed captured header.

    Returns
    -------
    None
        The optimization falls back to the original diagnostic path.
    """
    source = b'#include "h.h"\n'
    with pytest.raises(ValueError):
        select_macro_environments(
            "main.cpp",
            (len(source),),
            {"main.cpp": source, "h.h": header},
            {("main.cpp", "h.h", True): "h.h"},
            {b"G": _MacroDefinition(None, b"1")},
        )


@pytest.mark.parametrize(
    "prefix",
    [
        b"/*\n#define FAKE bad\n*/\n",
        b"// hidden \\\n#define FAKE bad\n",
        b'auto s = R"tag(\n#define FAKE bad\n)tag";\n',
        b'auto s = u8R"tag(\n)ta\\\ng"\n#define FAKE bad\n)tag";\n',
        b'auto s = "\\\n#define FAKE bad";\n',
        b"auto n = 1'000;\n",
    ],
)
def test_directive_text_in_literals_and_comments_is_opaque(prefix: bytes) -> None:
    """Ignore fake directives, including raw-string phase-two reversion cases.

    Parameters
    ----------
    prefix : bytes
        Source literal or comment containing misleading hash lines.

    Returns
    -------
    None
        Only the real final directive supplies the binding's source origin.
    """
    source = prefix + b"#define M good\n"
    selection = _end(source)
    assert b"FAKE" not in dict(selection.bindings)
    assert b"FAKE" not in selection.uncertain
    binding = dict(selection.bindings)[b"M"]
    assert binding.definition == _MacroDefinition(None, b"good")
    assert binding.origins[0].span == (len(prefix), len(source) - 1)


def test_replacement_spacing_survives_prescan_and_stringification() -> None:
    """Avoid normalizing replacement spacing that changes nested stringification.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The selected original replacement yields the written token spacing.
    """
    source = b"#define M a+b\n#define S(x) #x\n#define T(x) S(x)\n"
    definitions = {
        name: binding.definition
        for name, binding in _end(source).bindings
        if binding.definition is not None
    }
    assert [token.spelling for token in _expand_macro_tokens(b"T(M)", definitions)] == [
        b'"a+b"'
    ]


def test_unavailable_include_remains_explicit() -> None:
    """Record missing and macro include context without inventing replacements.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Unavailable headers supply no macros or compiler-equivalence proof.
    """
    source = b"#include <missing.h>\n#include MACRO_HEADER\n#define M own\n"
    result = _end(source)
    assert [observation.status for observation in result.observations] == [
        "unavailable",
        "unsupported-include",
    ]
    assert set(dict(result.bindings)) == {b"M"}


@pytest.mark.parametrize(
    "source",
    [
        b"#else\n",
        b"#elif 1\n",
        b"#endif\n",
        b"#if 1\n",
        b"#if 1\n#else\n#else\n#endif\n",
        b"#if 1\n#else\n#elif 0\n#endif\n",
        b"#ifdef A B\n#endif\n",
        b"#ifndef\n#endif\n",
        b"#if 1\n#else extra\n#endif\n",
        b"#if 1\n#endif extra\n",
        b"#define\n",
        b"#undef A B\n",
        b"#define defined 1\n",
        b"#undef defined\n",
        b"#error failure\n",
        b"/* unterminated",
        b'auto s = R"(unterminated',
        b'auto s = "unterminated',
        b"#if 1\n" * 65 + b"#endif\n" * 65,
        b"#define M 1\n" * 16385,
        b"".join(b"#define M" + str(i).encode() + b" 1\n" for i in range(4097)),
    ],
)
def test_invalid_or_excessive_context_is_rejected(source: bytes) -> None:
    """Fail explicitly for malformed directives, literals and bounded-work limits.

    Parameters
    ----------
    source : bytes
        Invalid or excessive captured input.

    Returns
    -------
    None
        Checks a hold instead of a fabricated reaching state.
    """
    with pytest.raises(ValueError):
        _end(source)


def test_unguarded_cycle_is_bounded() -> None:
    """Reject recursive unguarded includes within the traversal depth budget.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Prevents unbounded include recursion without reading any files.
    """
    with pytest.raises(ValueError, match="include depth"):
        select_macro_environments(
            "a.cpp",
            (len(b'#include "a.cpp"\n'),),
            {"a.cpp": b'#include "a.cpp"\n'},
            {("a.cpp", "a.cpp", True): "a.cpp"},
            {},
        )


@pytest.mark.parametrize(
    ("directive", "initial", "expected"),
    [
        (b"elifdef FLAG", {b"FLAG": _MacroDefinition(None, b"1")}, b"second"),
        (b"elifndef FLAG", {b"FLAG": None}, b"second"),
        (b"elifdef FLAG", {b"FLAG": None}, b"last"),
    ],
)
def test_identifier_elif_alternatives(
    directive: bytes, initial: dict[bytes, _MacroDefinition | None], expected: bytes
) -> None:
    """Treat identifier elif forms as real alternatives rather than directives.

    Parameters
    ----------
    directive : bytes
        Elifdef or elifndef alternative.
    initial : dict[bytes, _MacroDefinition | None]
        Explicit flag state.
    expected : bytes
        Replacement in the selected branch.

    Returns
    -------
    None
        Asserts later alternatives cannot overwrite a previously taken branch.
    """
    source = (
        b"#if 0\n#define M first\n#"
        + directive
        + b"\n#define M second\n#else\n#define M last\n#endif\n"
    )
    assert dict(_end(source, initial).bindings)[b"M"].definition == _MacroDefinition(
        None, expected
    )


def test_opaque_definition_retains_definedness_without_a_replacement_guess() -> None:
    """Allow definedness checks on an unavailable compiler/function replacement.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Keeps ordinary declarations independent of unrelated compiler queries.
    """
    initial: dict[bytes, _MacroDefinition | None] = {
        b"__has_attribute": _MacroDefinition(None, b"", opaque=True)
    }
    source = b"#ifndef __has_attribute\n#define __has_attribute(x) 0\n#endif\n#if __has_attribute(weak)\n#define ATTR yes\n#else\n#define ATTR no\n#endif\n#define M own\n"
    selection = _end(source, initial)
    bindings = dict(selection.bindings)
    assert bindings[b"__has_attribute"].definition == initial[b"__has_attribute"]
    assert b"__has_attribute" in selection.uncertain
    assert b"ATTR" in selection.uncertain and b"ATTR" not in bindings
    assert bindings[b"M"].definition == _MacroDefinition(None, b"own")
    definitions = {
        name: binding.definition
        for name, binding in selection.bindings
        if binding.definition is not None
    }
    assert [token.spelling for token in _expand_macro_tokens(b"M", definitions)] == [
        b"own"
    ]
    with pytest.raises(ValueError, match="replacement is unavailable"):
        _expand_macro_tokens(b"__has_attribute(weak)", definitions)


def test_unsupported_source_macro_is_still_known_defined() -> None:
    """Preserve a captured name while rejecting unsupported replacement semantics.

    Parameters
    ----------
    None

    Returns
    -------
    None
        GNU named variadics affect no inferred replacement or fallback branch.
    """
    source = b"#define OPAQUE(args...) args\n#ifdef OPAQUE\n#define M correct\n#else\n#define M wrong\n#endif\n"
    selection = _end(source)
    assert dict(selection.bindings)[b"OPAQUE"].definition is not None
    assert b"OPAQUE" in selection.uncertain
    assert dict(selection.bindings)[b"M"].definition == _MacroDefinition(
        None, b"correct"
    )


@pytest.mark.parametrize("offset", [-1, 1, 100])
def test_invalid_query_positions_are_rejected(offset: int) -> None:
    """Reject source escapes and queries inside a directive's physical span.

    Parameters
    ----------
    offset : int
        Invalid original byte offset.

    Returns
    -------
    None
        No partial or out-of-range environment is returned.
    """
    with pytest.raises(ValueError):
        select_macro_environments(
            "a.cpp", (offset,), {"a.cpp": b"#define M 1\n"}, {}, {}
        )


@pytest.mark.parametrize("path", ["../escape.h", "/absolute.h", ""])
def test_noncontained_capture_keys_are_rejected(path: str) -> None:
    """Require repository-relative capture identities before walking any input.

    Parameters
    ----------
    path : str
        Invalid capture path.

    Returns
    -------
    None
        The selector remains independent of arbitrary filesystem paths.
    """
    with pytest.raises(ValueError, match="contained relative"):
        select_macro_environments(path, (0,), {path: b""}, {}, {})


def test_crlf_utf8_origins_remain_physical() -> None:
    """Map spliced logical directives back to exact UTF-8/CRLF byte positions.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks the retained physical directive range includes its splice.
    """
    prefix = "// café\r\n".encode()
    directive = b"#define M(x) \\\r\n x+1\r"
    source = prefix + directive + b"\nCALL\r\n"
    selection = select_macro_environments(
        "a.cpp", (source.index(b"CALL"),), {"a.cpp": source}, {}, {}
    )[source.index(b"CALL")]
    binding = dict(selection.bindings)[b"M"]
    assert binding.definition == _MacroDefinition((b"x",), b"x+1")
    assert binding.origins[0].span == (len(prefix), len(prefix) + len(directive))


def test_cached_guard_skips_do_not_charge_unread_header_bytes() -> None:
    """Skip proven reentries before spending traversal and source-byte budgets.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Root include directives remain charged; skipped header bodies are not.
    """
    from codira_analyzer_cpp.cpp_macro_context import _ContextWalk

    header = b"#ifndef G\n#define G\n#define VALUE 7\n#endif\n" + b" " * 9000
    source = b'#include "guard.h"\n' * 1100 + b"QUERY\n"
    walk = _ContextWalk(
        {"unit.cpp": source, "guard.h": header},
        {("unit.cpp", "guard.h", True): "guard.h"},
        {b"G": None},
    )
    offset = source.index(b"QUERY")
    walk.walk("unit.cpp", offsets=(offset,))
    assert walk.visits == 2
    assert walk.bytes == len(source) + len(header)
    assert walk.events == 1104
    assert dict(walk.results[offset].bindings)[b"VALUE"].definition == _MacroDefinition(
        None, b"7"
    )


@pytest.mark.parametrize("guarded", [False, True])
def test_include_attempts_and_real_reentries_stay_bounded(guarded: bool) -> None:
    """Retain directive limits for guarded attempts and visit limits for real work.

    Parameters
    ----------
    guarded : bool
        Whether only source directives or actual header reentries consume work.

    Returns
    -------
    None
        Existing bounds still reject an excessive input.
    """
    from codira_analyzer_cpp.cpp_macro_context import _ContextWalk

    header = b"#ifndef G\n#define G\n#endif\n" if guarded else b"#undef VALUE\n"
    source = b'#include "header.h"\n' * (16400 if guarded else 1100)
    walk = _ContextWalk(
        {"unit.cpp": source, "header.h": header},
        {("unit.cpp", "header.h", True): "header.h"},
        {b"G": None},
    )
    with pytest.raises(
        ValueError,
        match="directive or binding limit" if guarded else "include traversal limit",
    ):
        walk.walk("unit.cpp")


def test_uncached_source_bytes_remain_bounded() -> None:
    """Charge a first read even when its guard was initially supplied as defined.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A cached-guard optimization cannot hide an oversized new buffer.
    """
    from codira_analyzer_cpp.cpp_macro_context import _ContextWalk

    header = b"#ifndef G\n#define G\n#endif\n" + b" " * (8 * 1024 * 1024)
    walk = _ContextWalk(
        {"unit.cpp": b'#include "large.h"\n', "large.h": header},
        {("unit.cpp", "large.h", True): "large.h"},
        {b"G": _MacroDefinition(None, b"1")},
    )
    with pytest.raises(ValueError, match="include traversal limit"):
        walk.walk("unit.cpp")


def test_valid_directive_population_above_former_limit() -> None:
    """Admit measured SDK-sized work while retaining the new finite event bound.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The final source definition still reaches the original query exactly.
    """
    source = b"#define M 1\n" * 9000 + b"#define M 7\nQUERY\n"
    selection = select_macro_environments(
        "main.cpp", (source.index(b"QUERY"),), {"main.cpp": source}, {}, {}
    )[source.index(b"QUERY")]
    assert dict(selection.bindings)[b"M"].definition == _MacroDefinition(None, b"7")
