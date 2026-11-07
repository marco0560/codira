"""Verify complete conditional statements and written C signature alternatives.

Parameters
----------
None

Returns
-------
None
    Source preservation, unique identities and malformed-input controls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from codira_analyzer_c import CAnalyzer, _new_parser
from codira_analyzer_c.c_conditionals import _conditionals, c_parse_views
from codira_analyzer_c.c_preprocessing import _parse_c_source

if TYPE_CHECKING:
    from pathlib import Path


def test_directives_in_comments_do_not_change_conditional_groups() -> None:
    """Ignore directive-shaped comment text while retaining real branches.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks the number of groups and their real source boundaries.
    """
    source = (
        b"/*\n#if NOT_A_DIRECTIVE\n*/\n#if FEATURE\nint a;\n#else\nint b;\n#endif\n"
    )
    parser = _new_parser()
    groups = _conditionals(source, parser.parse(source).root_node, parser)
    assert groups is not None
    assert len(groups) == 1
    assert groups[0].start == source.index(b"#if FEATURE")
    assert len(groups[0].branches) == 2


def test_shared_body_retains_signatures_coordinates_and_calls(tmp_path: Path) -> None:
    """Preserve both headers and the shared body without concatenating signatures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Both written parameter lists, source lines and identities survive.
    """
    source = b"#if WITH_LINE\nint handler(int value, int line)\n#else\nint handler(int value)\n#endif\n{ return helper(value); }\nint helper(int value) { return value; }\n"
    path = tmp_path / "shared.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    handlers = [f for f in result.functions if f.name == "handler"]
    assert [(f.lineno, f.end_lineno, f.parameters) for f in handlers] == [
        (2, 6, ("value", "line")),
        (4, 6, ("value",)),
    ]
    assert [f.signature for f in handlers] == [
        "int handler(int value, int line)",
        "int handler(int value)",
    ]
    assert len({f.stable_id for f in result.functions}) == 3
    assert all(
        [(c.target, c.lineno) for c in f.calls] == [("helper", 6)] for f in handlers
    )
    assert result.module.docstring is None and path.read_bytes() == source


def test_unknown_macro_branches_keep_same_name_symbols_and_unresolved_calls(
    tmp_path: Path,
) -> None:
    """Index each written alternative without resolving name-only calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source-only repository without build metadata.

    Returns
    -------
    None
        Branch occurrences keep source lines and unique IDs; calls remain lexical.
    """
    source = b"""#if !defined(NATIVE_ABI)
int convert(int value) { return value; }
int dispatch(int value) { return convert(value); }
#elif defined(LEGACY_ABI)
long convert(long value) { return value; }
int dispatch(long value) { return (int) convert(value); }
#else
double convert(double value) { return value; }
int dispatch(double value) { return (int) convert(value); }
#endif
"""
    path = tmp_path / "branches.c"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    variants = [function for function in result.functions if function.name == "convert"]
    assert [(item.lineno, item.signature) for item in variants] == [
        (2, "int convert(int value)"),
        (5, "long convert(long value)"),
        (8, "double convert(double value)"),
    ]
    assert len({item.stable_id for item in variants}) == 3
    dispatches = [
        function for function in result.functions if function.name == "dispatch"
    ]
    assert [item.lineno for item in dispatches] == [3, 6, 9]
    calls = [call for function in dispatches for call in function.calls]
    assert [
        (
            call.target,
            call.target_identity,
            call.resolution_mode,
            call.external_target_kind,
            call.external_target_name,
        )
        for call in calls
    ] == [
        ("convert", None, "exact", None, "convert"),
        ("convert", None, "exact", None, "convert"),
        ("convert", None, "exact", None, "convert"),
    ]
    assert b"#if !defined(NATIVE_ABI)" in path.read_bytes()
    assert not (tmp_path / "compile_commands.json").exists()


@pytest.mark.parametrize(
    "source",
    [
        "static int helper(int value) { return value; }\n"
        "int api(int (*helper)(int)) { return helper(1); }\n",
        "static int helper(int value) { return value; }\n"
        "int api(int value) { int (*helper)(int) = 0; return helper(value); }\n",
        "static int helper(int value) { return value; }\n"
        "#define DECLARE_LOCAL_HELPER int (*helper)(int) = 0\n"
        "int api(int value) { DECLARE_LOCAL_HELPER; return helper(value); }\n",
        "static int helper(int value) { return value; }\n"
        "#define helper(value) (value)\n"
        "int api(int value) { return helper(value); }\n",
        "#if ABI_A\n"
        "static int helper(int value) { return value; }\n"
        "#else\n"
        "static long helper(long value) { return value; }\n"
        "#endif\n"
        "int api(int value) { return helper(value); }\n",
    ],
    ids=[
        "parameter-shadow",
        "local-function-pointer",
        "macro-generated-shadow",
        "macro-shadow",
        "branches",
    ],
)
def test_static_call_identity_stays_unresolved_when_binding_is_ambiguous(
    tmp_path: Path, source: str
) -> None:
    """Keep static calls exact-unresolved when lexical binding is not proven.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source-only repository.
    source : str
        C source containing a shadow, macro, or conditional target ambiguity.

    Returns
    -------
    None
        The written call name remains available without a guessed identity.
    """
    path = tmp_path / "ambiguous.c"
    path.write_text(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    api = next(function for function in result.functions if function.name == "api")
    call = next(call for call in api.calls if call.target == "helper")
    assert call.target_identity is None
    assert call.resolution_mode == "exact"


def test_static_call_identity_stays_unresolved_with_missing_include(
    tmp_path: Path,
) -> None:
    """Do not bind source calls when an unresolved include may define macros.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository without the referenced system header.

    Returns
    -------
    None
        The written call remains exact-unresolved without complete macro input.
    """
    path = tmp_path / "missing_include.c"
    path.write_text(
        "#include <missing_codira_test_header.h>\n"
        "static int helper(int value) { return value; }\n"
        "int api(int value) { return helper(value); }\n"
    )

    result = CAnalyzer().analyze_file(path, tmp_path)
    api = next(function for function in result.functions if function.name == "api")
    call = next(call for call in api.calls if call.target == "helper")

    assert call.target_identity is None
    assert call.resolution_mode == "exact"


def test_static_call_identity_respects_captured_header_macros(
    tmp_path: Path,
) -> None:
    """Keep calls unresolved when a captured header defines their written name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository with a local macro header.

    Returns
    -------
    None
        The macro call remains source-visible without a function identity.
    """
    (tmp_path / "macros.h").write_text("#define helper(value) (value)\n")
    path = tmp_path / "captured_macro.c"
    path.write_text(
        "static int helper(int value) { return value; }\n"
        '#include "macros.h"\n'
        "int api(int value) { return helper(value); }\n"
    )

    result = CAnalyzer().analyze_file(path, tmp_path)
    api = next(function for function in result.functions if function.name == "api")
    call = next(call for call in api.calls if call.target == "helper")

    assert call.target_identity is None
    assert call.resolution_mode == "exact"


def test_same_name_type_alternatives_keep_unique_source_occurrences(
    tmp_path: Path,
) -> None:
    """Retain duplicate type names and enum members from both written arms.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source-only repository.

    Returns
    -------
    None
        Type and enumerator occurrences retain distinct physical identities;
        uppercase ordinary calls have no guessed macro or external label.
    """
    source = b"""#if PLATFORM_A
struct Widget { int a; };
union Storage { int left; };
enum Mode { MODE_A, MODE_SHARED };
#else
struct Widget { long b; };
union Storage { long right; };
enum Mode { MODE_B, MODE_SHARED };
#endif
void API(void) {}
void caller(void) { API(); }
"""
    path = tmp_path / "types.c"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols and result.status is None
    for kind, name, lines in (
        ("struct", "Widget", (2, 6)),
        ("union", "Storage", (3, 7)),
        ("enum", "Mode", (4, 8)),
    ):
        variants = [
            item
            for item in result.declarations
            if item.kind == kind and item.name == name
        ]
        assert [item.lineno for item in variants] == list(lines)
        assert len({item.stable_id for item in variants}) == 2

    enum_variants = [
        item
        for item in result.declarations
        if item.kind == "enum" and item.name == "Mode"
    ]
    members = [member for item in enum_variants for member in item.enum_members]
    assert [(member.name, member.lineno) for member in members] == [
        ("MODE_A", 4),
        ("MODE_SHARED", 4),
        ("MODE_B", 8),
        ("MODE_SHARED", 8),
    ]
    assert len({member.stable_id for member in members}) == 4
    assert {
        (member.parent_stable_id, item.stable_id)
        for item in enum_variants
        for member in item.enum_members
    } == {(item.stable_id, item.stable_id) for item in enum_variants}

    call = next(
        call
        for function in result.functions
        if function.name == "caller"
        for call in function.calls
    )
    assert call.target == "API"
    assert call.target_identity is None and call.resolution_mode == "exact"
    assert call.external_target_kind is None
    assert call.external_target_name == "API"


def test_independent_unsupported_branches_preserve_c_arms_with_partial_coverage(
    tmp_path: Path,
) -> None:
    """Retain parseable declarations without claiming exhaustive combinations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable header repository without a captured compiler profile.

    Returns
    -------
    None
        Both C alternatives remain queryable and combination coverage is partial.
    """
    source = b"""#ifdef __cplusplus
namespace modern { int first(void); }
#else
int first(void);
#endif
#ifdef __cplusplus
namespace legacy { int second(void); }
#else
int second(void);
#endif
"""
    path = tmp_path / "independent.h"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [(item.name, item.lineno) for item in result.functions] == [
        ("first", 4),
        ("second", 9),
    ]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert any(
        "combinations were enumerated" in diagnostic.message
        for diagnostic in result.status.diagnostics
    )


def test_partial_translation_unit_keeps_independently_clean_function(
    tmp_path: Path,
) -> None:
    """Index a clean file-scope subtree beside an unrelated syntax error.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository containing one valid definition and one malformed.

    Returns
    -------
    None
        The valid function remains indexable while file coverage stays partial.
    """
    source = b"int valid(void) { return 1; }\nint broken( {\n"
    path = tmp_path / "partial.c"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [(item.name, item.lineno) for item in result.functions] == [("valid", 1)]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert "unparsed_source_subtrees" in result.status.omitted_categories


def test_partial_translation_unit_keeps_independently_clean_type_declarations(
    tmp_path: Path,
) -> None:
    """Index complete file-scope types beside an unrelated malformed function.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source-only repository.

    Returns
    -------
    None
        Complete struct and enum artifacts survive with their enum members;
        the malformed callable is not emitted and source coverage stays partial.
    """
    source = (
        b"struct Stable { int value; };\nenum Mode { MODE_A, MODE_B };\nint broken( {\n"
    )
    path = tmp_path / "partial-types.c"
    path.write_bytes(source)

    result = CAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [(item.kind, item.name, item.lineno) for item in result.declarations] == [
        ("struct", "Stable", 1),
        ("enum", "Mode", 2),
    ]
    assert [item.name for item in result.functions] == []
    mode = next(item for item in result.declarations if item.name == "Mode")
    assert [item.name for item in mode.enum_members] == ["MODE_A", "MODE_B"]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert "parseable_source_subtrees" in result.status.reliable_categories
    assert "unparsed_source_subtrees" in result.status.omitted_categories


def test_multiple_headers_have_linear_covering_views(tmp_path: Path) -> None:
    """Cover all independent choices without Cartesian growth.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Three two-way headers need four views and retain all six variants.
    """
    source = b"".join(
        f"#if MODE_{i}\nint f{i}(int value)\n#else\nint f{i}(void)\n#endif\n{{ return {i}; }}\n".encode()
        for i in range(3)
    )
    views = list(c_parse_views(source, _new_parser()))
    assert len(views) == 4 and all(not v.root.has_error for v in views)
    path = tmp_path / "linear.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and len(result.functions) == 6
    assert len({f.stable_id for f in result.functions}) == 6


def test_conditional_else_if_keeps_all_written_calls(tmp_path: Path) -> None:
    """Retain lexical calls from complete optional statement continuations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        All branch calls keep their original physical source lines.
    """
    source = b"int run(int value) {\nif (value == 1) { first(); }\n#if EXTRA\nelse if (value == 2) { second(); }\n#endif\nelse { last(); }\nreturn value;\n}\n"
    path = tmp_path / "chain.c"
    path.write_bytes(source)
    assert _parse_c_source(source, _new_parser()).has_error
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [(c.target, c.lineno) for c in result.functions[0].calls] == [
        ("first", 2),
        ("second", 4),
        ("last", 6),
    ]


@pytest.mark.parametrize(
    "source",
    [
        b"#if MODE\nint good(int value)\n#else\nint bad(\n#endif\n{ return 1; }\n",
        b"#if MODE\nint good(int value)\n#else\nint other(void)\n#else\nint bad(void)\n#endif\n{ return 1; }\n",
        b"#if MODE\nint good(int value)\n#else\nint other(void)\n{ return 1; }\n",
        b"int run(void) {\n#if (\nfirst();\n#endif\nreturn 0; }\n",
        b"int run(void) {\n#if MODE\nfirst();\n#else\nlast( ;\n#endif\nreturn 0; }\n",
        b"#if MODE\nint\n#else\nunsigned\n#endif\nrun(void) { return 0; }\n",
    ],
)
def test_invalid_views_and_incomplete_fragments_stay_partial(
    tmp_path: Path, source: bytes
) -> None:
    """Prevent a valid alternative or concatenated type from hiding an error.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    source : bytes
        Malformed directives, branch or unsupported split type.

    Returns
    -------
    None
        Partial input keeps its diagnostic status.
    """
    path = tmp_path / "bad.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    if result.index_symbols:
        assert result.status is not None
        assert result.status.coverage_state.value == "partial"


def test_documentation_owners_follow_final_variant_ids(tmp_path: Path) -> None:
    """Remap branch documentation to final callable identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Variant docs have unique real owners and do not become module docs.
    """
    source = b"#if MODE\n/// First form.\nint run(int value)\n#else\n/// Second form.\nint run(void)\n#endif\n{ return 1; }\n"
    path = tmp_path / "docs.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.module.docstring is None
    ids = {f.stable_id for f in result.functions}
    assert len(ids) == 2
    docs = [d for d in result.documentation if d.owner_kind == "function"]
    assert len(docs) == 2 and {d.owner_stable_id for d in docs} == ids
    assert len({d.stable_id for d in docs}) == 2


def test_incomplete_branch_preserves_clean_original_definitions(tmp_path: Path) -> None:
    """Retain independently written functions from an unparseable branch view.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Repository with clean definitions and a malformed conditional sibling.

    Returns
    -------
    None
        Both written alternatives survive, the malformed declaration is omitted,
        and the written call is not given an unproven target identity.
    """
    source = (
        "#if FEATURE\n"
        "int shown(void) { return helper(); }\n"
        "void broken( {\n"
        "#else\n"
        "int other(void) { return 2; }\n"
        "#endif\n"
    )
    path = tmp_path / "conditional.c"
    path.write_text(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert [(item.name, item.lineno) for item in result.functions] == [
        ("shown", 2),
        ("other", 5),
    ]
    assert [call.target for call in result.functions[0].calls] == ["helper"]
    assert result.functions[0].calls[0].target_identity is None
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"


def test_source_recovery_retains_written_names_without_broken_calls(
    tmp_path: Path,
) -> None:
    """Recover written names without promoting calls from malformed bodies.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Repository with syntax errors in both conditional alternatives.

    Returns
    -------
    None
        Written names survive, calls on error lines do not, and coverage is partial.
    """
    path = tmp_path / "partial.c"
    path.write_text(
        "#if FEATURE\n"
        "int shown(void) { return 1; }\n"
        "int broken(void) { return helper( ? ); }\n"
        "#else\n"
        "int other(void) { return helper( ? ); }\n"
        "#endif\n"
    )
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert [(item.name, item.lineno) for item in result.functions] == [
        ("shown", 2),
        ("broken", 3),
        ("other", 5),
    ]
    assert all(not item.calls for item in result.functions)
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
