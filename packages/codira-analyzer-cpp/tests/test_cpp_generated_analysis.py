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

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer

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
    assert implementation.generated is not None
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
        assert generated is not None and generated.role == "alias"
        assert alias.calls == () and alias.parameters == () and alias.end_lineno is None
        assert generated.alias_target == "ns::impl_f" and generated.linkage_name == "f"
        assert generated.parameter_names == (None,)
        assert len(implementation.overloads) == 1
        prototype = implementation.overloads[0]
        assert (
            prototype.generated is not None and prototype.generated.role == "prototype"
        )
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
