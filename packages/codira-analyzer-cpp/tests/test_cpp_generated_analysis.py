"""Check production declaration-macro profiles, artifacts and conservative holds.

Parameters
----------
None

Returns
-------
None
    Synthetic controls; original-file qualification is independent.
"""

from __future__ import annotations

import json
from pathlib import Path
import hashlib
from dataclasses import asdict
from typing import Literal

import pytest

from codira_clang_frontend import FrontendCallable, FrontendPreprocessorEvent
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp import _clang_alias_or_prototype_evidence
from codira_analyzer_cpp import _clang_distinct_prototype_rows
from codira.generated import (
    CompilerObservedCallableProvenance,
    CompilerObservedMacroInvocation,
    CompilerObservedSourceCoordinate,
    GeneratedCallableProvenance,
    generated_provenance_payload,
)

_DEFINITIONS = b"""#ifndef H
#define H
#if PUBLIC
#define WRAP(T,N,A) decltype(NS::N) impl_##N asm(#N); decltype(NS::N) N [[gnu::alias(#N)]]; T impl_##N A
#else
#define WRAP(T,N,A) T N A
#endif
"""
_SOURCE = b'#include "h.h"\nnamespace NS {\nWRAP(double, f, (double x)) { return target(x); }\n}\n'


def _analyzer(public: bool) -> CppAnalyzer:
    """Configure an explicit synthetic profile with known guard and namespace facts.

    Parameters
    ----------
    public : bool
        Public alias/prototype or simple-definition variant.

    Returns
    -------
    CppAnalyzer
        Production analyzer with no native/compiler dependency.
    """
    analyzer = CppAnalyzer()
    analyzer.configure(
        {"preprocessor_definitions": {"H": False, "PUBLIC": public, "NS": "ns"}}
    )
    return analyzer


def test_clang_alias_and_generated_prototype_keep_exact_v3_facts() -> None:
    """Map native alias operands and explicit labels into V3 provenance.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks exact target identity and distinguishes the alias operand from
        an explicit assembler label.
    """
    source_coordinate = CompilerObservedSourceCoordinate("main.cpp", 0)
    invocation = CompilerObservedMacroInvocation("WRAP", "main.cpp", (0, 4), "WRAP")
    receipt = {
        "schema": "clang.frontend.callable-observation.v1",
        "context": {
            "profile_identity": "profile",
            "cache_fingerprint": "cache",
            "analyzer_context_identity": "context",
            "source_sha256": "a" * 64,
            "stdout_sha256": "b" * 64,
        },
        "callable": {"usr": "alias-usr"},
        "macro_expansion": {"name": "WRAP", "byte_range": [0, 4]},
    }
    base = CompilerObservedCallableProvenance(
        origin="macro_argument",
        role="definition",
        source_sha256="a" * 64,
        context_identity="context",
        spelling_location=source_coordinate,
        expansion_location=source_coordinate,
        invocation=invocation,
        receipt_namespace="clang.frontend.callable-observation.v1",
        receipt_json=json.dumps(receipt, sort_keys=True, separators=(",", ":")),
    )

    def callable_row(
        *,
        usr: str,
        name: str,
        qualified_name: str,
        is_definition: bool,
        has_body: bool,
        alias_target_symbol: str | None = None,
        alias_target_usr: str | None = None,
        alias_binding_status: Literal[
            "not_alias", "resolved", "unresolved", "ambiguous"
        ] = "not_alias",
        linker_symbol: str | None = None,
        explicit_linkage_label: str | None = None,
        linkage_label_inherited: bool | None = None,
    ) -> FrontendCallable:
        return FrontendCallable(
            usr=usr,
            kind="function",
            name=name,
            qualified_name=qualified_name,
            lexical_owner="ns",
            decl_kind="FunctionDecl",
            signature="double ns::f(double)",
            function_type="double (double)",
            parameters=(),
            has_prototype=True,
            is_definition=is_definition,
            is_public=True,
            provenance="macro_argument",
            location=None,
            span=None,
            calls=(),
            has_body=has_body,
            alias_target_symbol=alias_target_symbol,
            alias_target_usr=alias_target_usr,
            alias_binding_status=alias_binding_status,
            linker_symbol=linker_symbol,
            explicit_linkage_label=explicit_linkage_label,
            linkage_label_inherited=linkage_label_inherited,
        )

    alias = _clang_alias_or_prototype_evidence(
        callable_row(
            usr="alias-usr",
            name="f",
            qualified_name="ns::f",
            is_definition=True,
            has_body=False,
            alias_target_symbol="f",
            alias_target_usr="impl-usr",
            alias_binding_status="resolved",
        ),
        base,
        role="alias",
    )
    assert alias is not None
    assert alias.role == "alias"
    target_identity = alias.alias_target_identity
    assert target_identity is not None
    assert target_identity.namespace == "clang.usr.v1"
    assert target_identity.value == "impl-usr"
    assert alias.linkage_name is None
    generated_provenance_payload(json.dumps(asdict(alias), sort_keys=True))
    alias_receipt = json.loads(alias.receipt_json)
    assert alias_receipt["callable"]["native_observation"]["alias_target_symbol"] == "f"

    unresolved_alias = _clang_alias_or_prototype_evidence(
        callable_row(
            usr="alias-usr",
            name="f",
            qualified_name="ns::f",
            is_definition=True,
            has_body=False,
            alias_target_symbol="f",
            alias_binding_status="unresolved",
        ),
        base,
        role="alias",
    )
    assert unresolved_alias is not None
    assert unresolved_alias.alias_target_identity is None
    generated_provenance_payload(json.dumps(asdict(unresolved_alias), sort_keys=True))

    prototype = _clang_alias_or_prototype_evidence(
        callable_row(
            usr="impl-usr",
            name="impl_f",
            qualified_name="ns::impl_f",
            is_definition=False,
            has_body=False,
            linker_symbol="f",
            explicit_linkage_label="f",
            linkage_label_inherited=False,
        ),
        base,
        role="prototype",
    )
    assert prototype is not None
    assert prototype.role == "prototype"
    assert prototype.alias_target_identity is None
    assert prototype.linkage_name is None
    generated_provenance_payload(json.dumps(asdict(prototype), sort_keys=True))
    prototype_receipt = json.loads(prototype.receipt_json)
    assert (
        prototype_receipt["callable"]["native_observation"]["explicit_linkage_label"]
        == "f"
    )

    event = FrontendPreprocessorEvent(
        kind="macro_expansion",
        name="WRAP",
        replacement=(),
        replacement_truncated=False,
        function_like=True,
        parameters=(),
        source_text=None,
        condition=None,
        result=None,
        macro_defined=None,
        invocation="WRAP",
        location=None,
        span=None,
    )
    canonical_prototype = callable_row(
        usr="impl-usr",
        name="impl_f",
        qualified_name="ns::impl_f",
        is_definition=False,
        has_body=False,
    )
    repeated_prototype = callable_row(
        usr="impl-usr",
        name="impl_f",
        qualified_name="ns::impl_f",
        is_definition=False,
        has_body=False,
    )
    only_prototype_rows = ((canonical_prototype, base, event),)
    assert (
        _clang_distinct_prototype_rows(canonical_prototype, only_prototype_rows) == ()
    )
    repeated_rows = (
        *only_prototype_rows,
        (repeated_prototype, base, event),
    )
    assert _clang_distinct_prototype_rows(canonical_prototype, repeated_rows) == (
        (repeated_prototype, base, event),
    )


@pytest.mark.parametrize("public", [False, True])
def test_generated_callables_keep_roles_provenance_and_body_coordinates(
    tmp_path: Path, public: bool
) -> None:
    """Emit actual generated names, unnamed declarations and physical lexical calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.
    public : bool
        Selected packaging variant.

    Returns
    -------
    None
        Checks generated definitions, prototypes, aliases and physical body calls.
    """
    (tmp_path / "h.h").write_bytes(
        _DEFINITIONS + b"namespace NS { double f(double x); }\n#endif\n"
    )
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    analyzer = _analyzer(public)
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    names = {f.name: f for f in result.functions}
    implementation = names["ns::impl_f" if public else "ns::f"]
    assert implementation.parameters == ("x",)
    assert isinstance(implementation.generated, GeneratedCallableProvenance)
    assert implementation.generated.role == "definition"
    assert implementation.generated.parameter_names == ("x",)
    assert implementation.generated.parameter_types == ("double",)
    assert implementation.lineno == 3 and implementation.end_lineno == 3
    assert [(c.target, c.lineno, c.col_offset) for c in implementation.calls] == [
        ("target", 3, _SOURCE.splitlines()[2].index(b"target"))
    ]
    assert (
        implementation.generated.context_identity
        == analyzer.analysis_input_fingerprint(path, tmp_path)
    )
    assert analyzer.analysis_input_fingerprint_matches(
        path, tmp_path, implementation.generated.context_identity
    )
    assert any(
        i.name == "WRAP" and i.source_path == "h.h"
        for i in implementation.generated.inputs
    )
    if public:
        alias = names["ns::f"]
        generated = alias.generated
        assert isinstance(generated, GeneratedCallableProvenance)
        assert generated.role == "alias"
        assert alias.calls == () and alias.parameters == () and alias.end_lineno is None
        assert generated.alias_target == "ns::impl_f" and generated.linkage_name == "f"
        assert generated.parameter_names == (None,)
        assert len(implementation.overloads) == 1
        prototype = implementation.overloads[0]
        assert isinstance(prototype.generated, GeneratedCallableProvenance)
        assert prototype.generated.role == "prototype"
        assert prototype.generated.parameter_names == (None,)
        assert any(
            t.operation == "paste" and t.physical_spelling_span is None
            for t in implementation.generated.tokens
        )
        assert any(
            t.operation == "stringify" and t.physical_spelling_span is None
            for t in generated.tokens
        )
    else:
        assert len(names) == 1 and implementation.overloads == ()


@pytest.mark.parametrize(
    "declaration",
    [b"int f;", b"#if UNKNOWN\ndouble f(double x);\n#endif", b"double f(int x);"],
)
def test_unproven_decltype_callables_are_held(
    tmp_path: Path, declaration: bytes
) -> None:
    """Reject variable, conditional and incompatible referenced entity types.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.
    declaration : bytes
        Source that cannot prove the required callable type.

    Returns
    -------
    None
        An explicit macro-context diagnostic preserves the partial result.
    """
    (tmp_path / "h.h").write_bytes(
        _DEFINITIONS + b"namespace NS {\n" + declaration + b"\n}\n#endif\n"
    )
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    result = _analyzer(True).analyze_file(path, tmp_path)
    assert not result.index_symbols and result.status is not None
    assert any(d.category == "macro_context" for d in result.status.diagnostics)


def test_later_function_declaration_cannot_supply_earlier_decltype(
    tmp_path: Path,
) -> None:
    """Preserve source order even when no directive separates root declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.

    Returns
    -------
    None
        A future declaration does not reach an earlier generated prototype.
    """
    (tmp_path / "h.h").write_bytes(_DEFINITIONS + b"#endif\n")
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE.replace(b"\n}\n", b"\ndouble f(double x);\n}\n"))
    result = _analyzer(True).analyze_file(path, tmp_path)
    assert not result.index_symbols and result.status is not None


@pytest.mark.parametrize("redefine", [False, True])
def test_header_type_macros_use_their_earlier_state_and_origins(
    tmp_path: Path, redefine: bool
) -> None:
    """Prove expanded types from earlier macro bindings despite later changes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.
    redefine : bool
        Whether the root changes the underlying type macro after the header.

    Returns
    -------
    None
        All generated roles retain the earlier chained type macro origins.
    """
    header = (
        _DEFINITIONS
        + b"#define BASE double\n#define RET BASE\n#define ARG BASE\n"
        + b"namespace NS { RET f(ARG x); }\n#endif\n"
    )
    (tmp_path / "h.h").write_bytes(header)
    source = _SOURCE
    if redefine:
        source = source.replace(
            b"namespace NS", b"#undef BASE\n#define BASE int\nnamespace NS"
        )
    path = tmp_path / "main.cpp"
    path.write_bytes(source)
    result = _analyzer(True).analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    names = {function.name: function for function in result.functions}
    implementation = names["ns::impl_f"]
    for artifact in (implementation, implementation.overloads[0], names["ns::f"]):
        assert isinstance(artifact.generated, GeneratedCallableProvenance)
        assert artifact.generated.parameter_types == ("double",)
        inputs = {
            item.name: item
            for item in artifact.generated.inputs
            if item.name in {"BASE", "RET", "ARG"}
        }
        assert set(inputs) == {"BASE", "RET", "ARG"}
        for item in inputs.values():
            assert item.source_path == "h.h"
            assert item.source_sha256 == hashlib.sha256(header).hexdigest()
            assert item.span is not None
        base_span = inputs["BASE"].span
        assert base_span is not None
        first, last = base_span
        assert header[first:last].strip() == b"#define BASE double"


def test_equivalent_header_type_proofs_preserve_distinct_macro_origins(
    tmp_path: Path,
) -> None:
    """Keep both definitions when repeated declarations prove one callable type.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.

    Returns
    -------
    None
        Equal expanded types do not erase different contributing source origins.
    """
    header = (
        _DEFINITIONS
        + b"#define RET double\nnamespace NS { RET f(RET x); }\n"
        + b"#undef RET\n#define RET double\nnamespace NS { RET f(RET x); }\n"
        + b"#endif\n"
    )
    (tmp_path / "h.h").write_bytes(header)
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    result = _analyzer(True).analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    for function in result.functions:
        assert isinstance(function.generated, GeneratedCallableProvenance)
        origins = [item for item in function.generated.inputs if item.name == "RET"]
        assert len(origins) == 2
        assert origins[0].span != origins[1].span
        assert all(item.source_path == "h.h" for item in origins)


@pytest.mark.parametrize(
    "declaration",
    [
        b"#define RET int\nnamespace NS { RET f(double x); }",
        b"#define ARG int\nnamespace NS { double f(ARG x); }",
        b"#if UNKNOWN\n#define RET double\n#else\n#define RET int\n#endif\n"
        b"namespace NS { RET f(double x); }",
        b"#define RET BASE\n#if UNKNOWN\n#define BASE double\n"
        b"#else\n#define BASE int\n#endif\nnamespace NS { RET f(double x); }",
    ],
)
def test_incompatible_or_uncertain_expanded_header_types_remain_held(
    tmp_path: Path, declaration: bytes
) -> None:
    """Reject incompatible types and branch-dependent type replacements.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.
    declaration : bytes
        Header fragment without a compatible, unambiguous expanded type.

    Returns
    -------
    None
        The analyzer preserves an explicit partial result.
    """
    (tmp_path / "h.h").write_bytes(_DEFINITIONS + declaration + b"\n#endif\n")
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    result = _analyzer(True).analyze_file(path, tmp_path)
    assert not result.index_symbols and result.status is not None
    assert any(d.category == "macro_context" for d in result.status.diagnostics)


def test_opaque_header_type_macro_remains_held(tmp_path: Path) -> None:
    """Reject a required type macro with known definedness but no replacement.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.

    Returns
    -------
    None
        Definedness alone does not prove the generated callable's type.
    """
    (tmp_path / "h.h").write_bytes(
        _DEFINITIONS + b"namespace NS { RET f(double x); }\n#endif\n"
    )
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    analyzer = CppAnalyzer()
    analyzer.configure(
        {
            "preprocessor_definitions": {
                "H": False,
                "PUBLIC": True,
                "NS": "ns",
                "RET": {"defined": True},
            }
        }
    )
    result = analyzer.analyze_file(path, tmp_path)
    assert not result.index_symbols and result.status is not None
    assert any(d.category == "macro_context" for d in result.status.diagnostics)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"bad-name": True},
        {"defined": True},
        {"X": 1},
        {"X": {"defined": False}},
        {"X": {"defined": True, "extra": 1}},
        {"X": "a\nb"},
        {"X": "/*"},
    ],
)
def test_invalid_preprocessing_profiles_fail_configuration(value: object) -> None:
    """Reject invalid names, value types and unsupported replacement syntax.

    Parameters
    ----------
    value : object
        Invalid explicit configuration value.

    Returns
    -------
    None
        No invalid profile reaches indexing.
    """
    with pytest.raises(ValueError):
        CppAnalyzer().configure({"preprocessor_definitions": value})


def test_profile_context_changes_invalidate_cached_artifacts(tmp_path: Path) -> None:
    """Bind packaging, explicit undefined states, header bytes and include outcomes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.

    Returns
    -------
    None
        Reuse rejects changed profile or source/header context.
    """
    header = tmp_path / "h.h"
    header.write_bytes(_DEFINITIONS + b"namespace NS { double f(double x); }\n#endif\n")
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    analyzer = _analyzer(False)
    identity = analyzer.analysis_input_fingerprint(path, tmp_path)
    assert analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    assert not _analyzer(True).analysis_input_fingerprint_matches(
        path, tmp_path, identity
    )
    header.write_bytes(header.read_bytes() + b"// changed\n")
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)


def test_absent_profile_preserves_original_syntax_only_behavior(tmp_path: Path) -> None:
    """Keep ordinary syntax-only analysis unless a profile is explicitly present.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Synthetic contained repository.

    Returns
    -------
    None
        A macro wrapper is not silently rewritten without configuration.
    """
    (tmp_path / "h.h").write_bytes(_DEFINITIONS + b"#endif\n")
    path = tmp_path / "main.cpp"
    path.write_bytes(_SOURCE)
    analyzer = CppAnalyzer()
    analyzer.configure({})
    result = analyzer.analyze_file(path, tmp_path)
    assert not result.index_symbols
    assert not any(f.generated is not None for f in result.functions)
