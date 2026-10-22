"""Verify bounded opt in C declaration macro analysis.

Parameters
----------
None

Returns
-------
None
    Exercises generated callable roles, source provenance and conservative holds.
"""

from pathlib import Path

import pytest

from codira_analyzer_c import CAnalyzer
from codira_analyzer_c.c_declaration_macros import (
    MacroDefinition,
    MacroToken,
    _ExpansionIndex,
    _Expander,
    _directive_rows,
    _include_guard,
)
import codira_analyzer_c.c_declaration_macros as declaration_macros


def _fixture(root: Path, header: str, source: str) -> Path:
    """Write one contained C source and its declaration macro header.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root.
    header : str
        Exact captured macro definitions.
    source : str
        Original translation unit.

    Returns
    -------
    pathlib.Path
        C translation unit under the supplied root.
    """
    (root / "include").mkdir(exist_ok=True)
    (root / "include/api.h").write_text(header, encoding="utf-8")
    path = root / "module.c"
    path.write_text(source, encoding="utf-8")
    return path


def test_opt_in_expands_generated_callable_with_source_provenance(
    tmp_path: Path,
) -> None:
    """Recover generated roles while retaining invocation argument origins.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The generated definition, prototype, calls and argument byte spans agree.
    """
    source = (
        '#include "api.h"\n'
        "struct Data { const char *name; const char *version; };\n"
        'DECLARE_API(argument_call(1, 2), .name = "module", .version = "1");\n'
    )
    path = _fixture(
        tmp_path,
        "#ifndef API_H\n#define API_H\n"
        "#define DECLARE_API(call_arg, ...) extern int generated_entry(void); "
        "int generated_entry(void) { static const struct Data data = { __VA_ARGS__ }; "
        "return generated_call(call_arg); }\n"
        "#endif\n",
        source,
    )

    default = CAnalyzer().analyze_file(path, tmp_path)
    assert not default.index_symbols
    assert not any(item.generated is not None for item in default.functions)

    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )
    result = analyzer.analyze_file(path, tmp_path)

    generated = [item for item in result.functions if item.generated is not None]
    assert result.index_symbols
    assert {
        (item.name, item.generated.role)
        for item in generated
        if item.generated is not None
    } == {("generated_entry", "definition")}
    definition = generated[0]
    assert definition.generated is not None
    assert definition.generated.invocation_span == (
        source.index("DECLARE_API"),
        source.index(";", source.index("DECLARE_API")),
    )
    assert {call.target for call in definition.calls} == {
        "generated_call",
        "argument_call",
    }
    invocation_column = (
        source.index("DECLARE_API")
        - source.rfind("\n", 0, source.index("DECLARE_API"))
        - 1
    )
    argument_column = (
        source.index("argument_call")
        - source.rfind("\n", 0, source.index("argument_call"))
        - 1
    )
    assert {
        (call.target, call.lineno, call.col_offset) for call in definition.calls
    } == {
        ("generated_call", 3, invocation_column),
        ("argument_call", 3, argument_column),
    }
    assert any(
        token.spelling == "argument_call" and token.physical_spelling_span is not None
        for token in definition.generated.tokens
    )
    assert {item.name for item in definition.generated.inputs} == {"DECLARE_API"}
    assert definition.generated.source_sha256
    assert definition.generated.context_identity


def test_source_redefinition_and_undef_are_selected_per_invocation(
    tmp_path: Path,
) -> None:
    """Use the latest unambiguous source definition separately at each site.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The first prototype and later definition retain their own macro inputs.
    """
    source = (
        "#define DECLARE(name) int name(void);\n"
        "DECLARE(first_entry);\n"
        "#undef DECLARE\n"
        "#define DECLARE(name) int name(void) { return 1; }\n"
        "DECLARE(second_entry);\n"
    )
    path = _fixture(tmp_path, "", source)
    analyzer = CAnalyzer()
    analyzer.configure({"expand_declaration_macros": True})

    result = analyzer.analyze_file(path, tmp_path)

    generated = [item for item in result.functions if item.generated is not None]
    assert result.index_symbols
    assert [
        (item.name, item.generated.role)
        for item in generated
        if item.generated is not None
    ] == [
        ("first_entry", "prototype"),
        ("second_entry", "definition"),
    ]
    assert generated[0].generated is not None
    assert generated[1].generated is not None
    assert generated[0].generated.inputs[0].replacement_sha256 != (
        generated[1].generated.inputs[0].replacement_sha256
    )


def test_shared_expansion_index_preserves_availability_and_undef_order() -> None:
    """Select invocation-local definitions from shared name indexes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Later availability, undefinition and conditional rules remain exact.
    """

    def definition(
        name: bytes,
        spelling: bytes,
        *,
        available: int,
        order: int,
        conditional: bool = False,
    ) -> MacroDefinition:
        """Create a minimal captured definition for index behavior checks.

        Parameters
        ----------
        name : bytes
            Macro identifier.
        spelling : bytes
            Single replacement token.
        available : int
            Translation-unit byte offset where the definition becomes visible.
        order : int
            Captured directive order.
        conditional : bool, optional
            Whether the definition is unresolved conditional evidence.

        Returns
        -------
        MacroDefinition
            Synthetic immutable definition with a unique source span.
        """
        return MacroDefinition(
            name=name,
            parameters=None,
            variadic=False,
            replacement=(MacroToken(spelling),),
            source_path="include/api.h",
            source_sha256="0" * 64,
            source_order=order,
            conditional=conditional,
            replacement_sha256="1" * 64,
            span=(order * 10, order * 10 + 5),
            available_after=available,
        )

    definitions = (
        definition(b"VALUE", b"early", available=0, order=1),
        definition(b"VALUE", b"late", available=40, order=3),
        definition(b"VALUE", b"branch", available=0, order=4, conditional=True),
        definition(b"LATE_ANNOTATION", b"1", available=45, order=5),
        definition(b"FUTURE_ONLY", b"1", available=100, order=7),
    )
    undefs = (
        (b"VALUE", 30, "module.c", 30, 2),
        (b"UNRESOLVED", 40, "@unresolved", 40, 6),
    )
    index = _ExpansionIndex.build(definitions, undefs)
    assert sum(len(items) for items in index.definitions_by_name.values()) == len(
        definitions
    )
    assert sum(len(items) for items in index.undef_keys_by_name.values()) == len(undefs)
    annotations = {b"LATE_ANNOTATION": 0, b"UNRESOLVED": 0}

    before_undef = _Expander(index, 20, annotations)
    after_undef = _Expander(index, 35, annotations)
    after_redefinition = _Expander(index, 50, annotations)

    assert before_undef._definitions[b"VALUE"].replacement[0].spelling == b"early"
    assert b"VALUE" not in before_undef._unsafe_names
    assert b"FUTURE_ONLY" not in before_undef._unsafe_names
    assert b"VALUE" not in after_undef._definitions
    assert b"VALUE" in after_undef._unsafe_names
    assert after_redefinition._definitions[b"VALUE"].replacement[0].spelling == b"late"
    assert b"branch" not in {
        item.replacement[0].spelling
        for item in after_redefinition._definitions.values()
    }
    assert before_undef._annotation_inputs[b"LATE_ANNOTATION"] == ()
    assert len(after_redefinition._annotation_inputs[b"LATE_ANNOTATION"]) == 1
    assert b"UNRESOLVED" in after_undef._annotations
    assert b"UNRESOLVED" not in after_redefinition._annotations


def test_unresolved_conditional_definition_keeps_original_error(
    tmp_path: Path,
) -> None:
    """Hold definitions whose source branch cannot be selected safely.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The original macro error remains partial and no generated callable appears.
    """
    path = _fixture(
        tmp_path,
        "#if FEATURE_LEVEL\n#define DECLARE(...) int generated_entry(void);\n#endif\n",
        '#include "api.h"\nstruct Data { const char *name; const char *version; };\n'
        'DECLARE(.name = "module", .version = "1");\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert not result.index_symbols
    assert any(item.generated is not None for item in result.functions) is False
    assert result.status is not None


def test_include_guard_proof_requires_exact_outer_structure() -> None:
    """Accept canonical whole-file guards but reject branch ambiguity.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Nested alternatives are permitted while outer guard alternatives are not.
    """
    nested = (
        b"/* header */\n#ifndef API_H\n#define API_H\n"
        b"#if FEATURE\n#define VALUE 1\n#else\n#define VALUE 2\n#endif\n"
        b"#endif /* API_H */\n"
    )
    ambiguous = (
        b"#ifndef API_H\n#define API_H\n#define VALUE 1\n"
        b"#else\n#define VALUE 2\n#endif\n"
    )

    assert _include_guard(nested, _directive_rows(nested)) == b"API_H"
    assert _include_guard(ambiguous, _directive_rows(ambiguous)) is None
    assert (
        _include_guard(
            b"#ifndef API_H\n#define API_H 1\n#define VALUE 1\n#endif\n",
            _directive_rows(
                b"#ifndef API_H\n#define API_H 1\n#define VALUE 1\n#endif\n"
            ),
        )
        is None
    )


def test_directive_scanner_ignores_spliced_continuation_lines() -> None:
    """Do not treat continuation text as a new preprocessor directive.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A line-leading directive-like token in a continued line is ignored.
    """
    rows = _directive_rows(
        b"int value = 1 + \\\n+#define NOT_A_DIRECTIVE 1\n#define REAL_DIRECTIVE 1\n"
    )

    assert [(kind, payload.strip()) for _, _, kind, payload in rows] == [
        (b"define", b"REAL_DIRECTIVE 1")
    ]


def test_opt_in_configuration_requires_a_boolean() -> None:
    """Reject truthy strings instead of silently enabling expansion.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The opt-in cannot be enabled by a non-boolean value.
    """
    analyzer = CAnalyzer()

    try:
        analyzer.configure({"expand_declaration_macros": "false"})
    except ValueError as error:
        assert "must be a boolean" in str(error)
    else:
        raise AssertionError("non-boolean expansion configuration was accepted")


def test_public_analysis_marks_macro_token_budget_rejection_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain the ordinary parse while recording bounded macro rejection.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.
    monkeypatch : pytest.MonkeyPatch
        Lower the private token limit to exercise the public boundary cheaply.

    Returns
    -------
    None
        The parser result survives, and status reports incomplete expansion.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(name) int name(void);\n",
        '#include "api.h"\nDECLARE(generated_entry);\n'
        "int ordinary(void) { return 0; }\n",
    )
    baseline = CAnalyzer().analyze_file(path, tmp_path)
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )
    monkeypatch.setattr(declaration_macros, "_MAX_TOKENS", 2)

    result = analyzer.analyze_file(path, tmp_path)

    assert result.functions == baseline.functions
    assert result.declarations == baseline.declarations
    assert result.imports == baseline.imports
    assert baseline.index_symbols
    assert not result.index_symbols
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    baseline_diagnostics = (
        baseline.status.diagnostics if baseline.status is not None else ()
    )
    assert (
        result.status.diagnostics[: len(baseline_diagnostics)] == baseline_diagnostics
    )
    assert any(
        item.category == "declaration_macro_expansion"
        and "macro token bound exceeded" in item.message
        for item in result.status.diagnostics
    )


def test_unrelated_syntax_error_remains_partial_after_macro_recovery(
    tmp_path: Path,
) -> None:
    """Keep unrelated parser failures visible when one macro is proven.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The generated callable is retained while file coverage remains partial.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(...) int generated_entry(void);\n",
        '#include "api.h"\nDECLARE(.name = "module");\nint broken( {\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert not result.index_symbols
    assert any(
        item.name == "generated_entry" and item.generated is not None
        for item in result.functions
    )
    assert result.status is not None


def test_unsupported_token_pasting_keeps_original_macro_diagnostic(
    tmp_path: Path,
) -> None:
    """Reject unsupported replacement operators without hiding source errors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        No generated artifact is emitted for an unsupported paste operation.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(...) int generated_##entry(void);\n",
        '#include "api.h"\nDECLARE(.name = "module");\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert not any(item.generated is not None for item in result.functions)
    assert result.status is not None


def test_nested_unknown_macro_state_rejects_outer_expansion(
    tmp_path: Path,
) -> None:
    """Do not treat an unresolved nested macro name as a literal identifier.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The outer invocation remains unexpanded and partial.
    """
    path = _fixture(
        tmp_path,
        "#define INNER(name) int other_entry(void)\n"
        "#if UNKNOWN_FEATURE\n"
        "#undef INNER\n"
        "#endif\n"
        "#define DECLARE(...) int INNER(__VA_ARGS__);\n",
        '#include "api.h"\nDECLARE(.name = "module");\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert not result.index_symbols
    assert not any(item.generated is not None for item in result.functions)
    assert result.status is not None


def test_call_like_macro_inside_function_is_not_a_declaration_site(
    tmp_path: Path,
) -> None:
    """Leave ordinary call expressions outside file-scope expansion.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The source function and its ordinary macro-named call are retained.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(value) int generated_entry(void);\n",
        "int caller(void) { return DECLARE(7); }\n",
    )
    analyzer = CAnalyzer()
    analyzer.configure({"expand_declaration_macros": True})

    result = analyzer.analyze_file(path, tmp_path)

    caller = next(item for item in result.functions if item.name == "caller")
    assert caller.generated is None
    assert any(call.target == "DECLARE" for call in caller.calls)


def test_generated_parameter_pointer_and_function_declarators_are_exact(
    tmp_path: Path,
) -> None:
    """Retain pointer, qualifier and nested function declarator syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        Provenance parameter types preserve full written declarator structure.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(name, ...) int name(__VA_ARGS__) { return 0; }\n",
        '#include "api.h"\n'
        "DECLARE(generated_entry, int *ptr, const char *label, "
        "void (*callback)(int));\n",
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    generated = next(item for item in result.functions if item.generated is not None)
    assert generated.generated is not None
    assert generated.generated.parameter_names == ("ptr", "label", "callback")
    assert generated.generated.parameter_types == (
        "int *",
        "const char *",
        "void ( * ) ( int )",
    )


def test_top_level_generated_constant_cannot_be_dropped_by_blanking(
    tmp_path: Path,
) -> None:
    """Reject a callable-free expansion that would lose a modeled constant.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        The original invocation remains and no unsupported generated artifact
        is emitted.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(name) int generated_entry(void); "
        "static const int generated_value = 1;\n",
        '#include "api.h"\nDECLARE(generated_value);\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "expand_declaration_macros": True}
    )

    result = analyzer.analyze_file(path, tmp_path)

    assert not any(item.generated is not None for item in result.functions)
    assert not any(item.name == "generated_value" for item in result.declarations)


def test_line_spliced_argument_token_is_held_instead_of_falsely_located(
    tmp_path: Path,
) -> None:
    """Hold tokens whose physical spelling is split across a line splice.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.

    Returns
    -------
    None
        No noncontiguous spelling is claimed as one physical token span.
    """
    path = _fixture(
        tmp_path,
        "#define DECLARE(call) int generated_entry(void) { return call; }\n",
        "DECLARE(generated_\\\ncall());\n",
    )
    analyzer = CAnalyzer()
    analyzer.configure({"expand_declaration_macros": True})

    result = analyzer.analyze_file(path, tmp_path)

    assert not any(item.generated is not None for item in result.functions)
    assert result.status is not None


@pytest.mark.parametrize("outer_first", [False, True])
def test_nested_headers_follow_directive_execution_order(
    tmp_path: Path, outer_first: bool
) -> None:
    """Resolve definitions on either side of a nested include.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.
    outer_first : bool
        Whether the outer definition precedes the nested include.

    Returns
    -------
    None
        Generated identity follows preprocessing order rather than header paths.
    """
    prefix = "#ifndef A_H\n#define A_H\n"
    definition = "#undef DECL\n#define DECL(...) int outer(void) { return 1; } extern int marker\n"
    include = '#include "z.h"\n'
    (tmp_path / "a.h").write_text(
        prefix
        + (definition + include if outer_first else include + definition)
        + "#endif\n"
    )
    (tmp_path / "z.h").write_text(
        "#ifndef Z_H\n#define Z_H\n#undef DECL\n#define DECL(...) int inner(void) { return 2; } extern int marker\n#endif\n"
    )
    path = tmp_path / "module.c"
    path.write_text('#include "a.h"\nDECL(.x = 1);\n')
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["."], "expand_declaration_macros": True}
    )
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert [item.name for item in result.functions] == [
        "inner" if outer_first else "outer"
    ]


@pytest.mark.parametrize("reset_guard", [False, True])
def test_repeated_header_respects_guard_and_source_undef(
    tmp_path: Path, reset_guard: bool
) -> None:
    """Replay a guarded header only when its guard has been undefined.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.
    reset_guard : bool
        Whether the source clears the captured guard before reinclusion.

    Returns
    -------
    None
        Later source redefinitions survive skipped headers and not reexecution.
    """
    (tmp_path / "a.h").write_text(
        "#ifndef A_H\n#define A_H\n#undef DECL\n#define DECL(...) int header(void) { return 1; } extern int marker\n#endif\n"
    )
    path = tmp_path / "module.c"
    path.write_text(
        '#include "a.h"\n#undef DECL\n#define DECL(...) int source(void) { return 2; } extern int marker\n'
        + ("#undef A_H\n" if reset_guard else "")
        + '#include "a.h"\nDECL(.x = 1);\n'
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["."], "expand_declaration_macros": True}
    )
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert [item.name for item in result.functions] == [
        "header" if reset_guard else "source"
    ]


@pytest.mark.parametrize("annotation", [False, True])
def test_uncaptured_include_invalidates_known_macro_state(
    tmp_path: Path, annotation: bool
) -> None:
    """Hold expansions when an uncaptured include can alter their definitions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository.
    annotation : bool
        Whether the affected macro was previously a proven neutral annotation.

    Returns
    -------
    None
        Unknown include effects cannot be bypassed by annotation projection.
    """
    macro = "#define ATTR\n" if annotation else ""
    body = (
        "ATTR int entry(void) { return 1; }"
        if annotation
        else "int entry(void) { return 1; }"
    )
    path = tmp_path / "module.c"
    path.write_text(
        macro
        + "#define DECL(...) "
        + body
        + ' extern int marker\n#include "missing.h"\n'
        + (
            "#undef DECL\n#define DECL(...) " + body + " extern int marker\n"
            if annotation
            else ""
        )
        + "DECL(.x = 1);\n"
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["."], "expand_declaration_macros": True}
    )
    result = analyzer.analyze_file(path, tmp_path)
    assert not result.index_symbols
    assert not any(item.generated is not None for item in result.functions)
