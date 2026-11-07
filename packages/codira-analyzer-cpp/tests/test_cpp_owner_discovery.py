"""Verify source-proven exclusions avoid redundant C++ header owner discovery.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from codira.models import AnalysisCoverageState

import codira_analyzer_cpp as cpp


@pytest.mark.parametrize(
    "source",
    [
        "namespace api { int run(int x) { return x; } long run(long x) { return x; } }",
        "namespace outer { namespace api { int run() { return 1; } } }",
        "using Alias = int; int Alias::run() { return 1; }",
    ],
)
def test_source_excluded_owners_skip_header_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    """Preserve qualified free functions and overload identities without lookup.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.
    monkeypatch : pytest.MonkeyPatch
        Guard against invoking unnecessary header owner discovery.
    source : str
        Written namespace or alias conflict excluding every requested owner.

    Returns
    -------
    None
    """
    (tmp_path / "owner.h").write_text("struct Other { int method(); };\n")
    path = tmp_path / "unit.cpp"
    path.write_text('#include "owner.h"\n' + source + "\n")
    discovery = Mock(side_effect=AssertionError("source already excludes owners"))
    monkeypatch.setattr(cpp, "_external_method_owners", discovery)
    result = cpp.CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert result.functions
    assert all("::run" in f.name and not f.is_method for f in result.functions)
    assert len({f.stable_id for f in result.functions}) == len(result.functions)
    assert all(f.owner_name is None for f in result.functions)
    discovery.assert_not_called()


@pytest.mark.parametrize("with_unqualified", [False, True])
def test_namespace_prefix_does_not_exclude_header_defined_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_unqualified: bool
) -> None:
    """Retain header class ownership and member calls beside namespace functions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.
    monkeypatch : pytest.MonkeyPatch
        Observe actual header owner discovery.
    with_unqualified : bool
        Include an additional global free function.

    Returns
    -------
    None
    """
    (tmp_path / "owner.h").write_text(
        "namespace api { class Owner { public: int method(); int helper(); }; }\n"
    )
    path = tmp_path / "unit.cpp"
    path.write_text(
        '#include "owner.h"\n'
        "namespace api { int free_function() { return 1; } }\n"
        "int api::Owner::method() { return helper(); }\n"
        + ("int global_function() { return 2; }\n" if with_unqualified else "")
    )
    discovery = Mock(wraps=cpp._external_method_owners)
    monkeypatch.setattr(cpp, "_external_method_owners", discovery)
    result = cpp.CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    method = next(f for f in result.functions if f.name == "method")
    assert method.is_method and method.owner_name == "api::Owner"
    assert method.owner_stable_id == "cpp:class:owner.h:api::Owner"
    assert [(c.target, c.kind, c.base) for c in method.calls] == [
        ("helper", "attribute", "api::Owner")
    ]
    header_result = cpp.CppAnalyzer().analyze_file(tmp_path / "owner.h", tmp_path)
    helper = next(
        method
        for item in header_result.classes
        for method in item.methods
        if method.name == "helper"
    )
    assert method.calls[0].target_identity == helper.semantic_identity
    assert method.calls[0].resolution_mode == "exact"
    assert any(f.name == "api::free_function" for f in result.functions)
    discovery.assert_called_once()


@pytest.mark.parametrize(
    ("header", "definition"),
    [
        (
            "class Widget { public: int helper(); int helper(int); };\n",
            "int Widget::run() { return helper(); }\n",
        ),
        (
            "#if PLATFORM_A\nclass Widget { public: int helper(); };\n"
            "#else\nclass Widget { public: int helper(); };\n#endif\n",
            "int Widget::run() { return helper(); }\n",
        ),
        (
            "class Widget { public: int helper(); };\n",
            "int Widget::run(int (*helper)()) { return helper(); }\n",
        ),
        (
            "class Base { public: int helper(int); };\n"
            "class Widget : public Base { public: using Base::helper; "
            "int helper(); };\n",
            "int Widget::run() { return helper(); }\n",
        ),
        (
            "#define helper() 0\nclass Widget { public: int helper(); };\n",
            "int Widget::run() { return helper(); }\n",
        ),
        (
            "#define DECLARE_EXTRA int helper(int = 0);\n"
            "class Widget { public: int helper(); DECLARE_EXTRA; };\n",
            "int Widget::run() { return helper(); }\n",
        ),
        (
            "class Widget { public: int helper(); int helper; };\n",
            "int Widget::run() { return helper(); }\n",
        ),
    ],
    ids=[
        "overloads",
        "conditional-owners",
        "parameter-shadow",
        "inheritance-using",
        "macro-shadow",
        "macro-declared-overload",
        "same-name-data-member",
    ],
)
def test_external_member_call_stays_unresolved_for_ambiguous_header_methods(
    tmp_path: Path, header: str, definition: str
) -> None:
    """Do not select a method identity across competing lexical bindings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.
    header : str
        Header containing multiple same-name method occurrences.
    definition : str
        Out-of-class definition with an ambiguous call or parameter shadow.

    Returns
    -------
    None
        Written calls retain their name but exact target resolution remains unset.
    """
    (tmp_path / "owner.h").write_text(header)
    source = tmp_path / "unit.cpp"
    source.write_text('#include "owner.h"\n' + definition)

    result = cpp.CppAnalyzer().analyze_file(source, tmp_path)

    method = next(function for function in result.functions if function.name == "run")
    call = method.calls[0]
    assert method.owner_name == "Widget"
    assert call.target == "helper"
    assert call.target_identity is None
    assert call.resolution_mode == "exact"
    if "#if" in header:
        assert method.owner_stable_id is None


def test_unresolved_include_keeps_external_member_call_unresolved(
    tmp_path: Path,
) -> None:
    """Do not prove member identity while an unavailable header can alter lookup.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.

    Returns
    -------
    None
        Missing include context leaves the call unresolved and marks coverage partial.
    """
    (tmp_path / "owner.h").write_text("class Widget { public: int helper(); };\n")
    source = tmp_path / "unit.cpp"
    source.write_text(
        "#include <unknown_missing_header.h>\n"
        '#include "owner.h"\n'
        "int Widget::run() { return helper(); }\n"
    )

    result = cpp.CppAnalyzer().analyze_file(source, tmp_path)

    method = next(function for function in result.functions if function.name == "run")
    call = method.calls[0]
    assert call.target == "helper"
    assert call.target_identity is None
    assert call.resolution_mode == "exact"
    assert result.status is not None
    assert result.status.coverage_state == AnalysisCoverageState.PARTIAL
    assert "include_context" in result.status.omitted_categories
    assert any(
        diagnostic.category == "include_context"
        for diagnostic in result.status.diagnostics
    )


def test_mixed_global_and_excluded_namespace_retains_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the existing discovery contract when any owner is not excluded.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    monkeypatch : pytest.MonkeyPatch
        Observe actual header owner discovery.

    Returns
    -------
    None
    """
    path = tmp_path / "mixed.cpp"
    path.write_text("namespace api { void run() {} }\nvoid global_function() {}\n")
    discovery = Mock(wraps=cpp._external_method_owners)
    monkeypatch.setattr(cpp, "_external_method_owners", discovery)
    result = cpp.CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert {f.name for f in result.functions} == {"api::run", "global_function"}
    discovery.assert_called_once()
