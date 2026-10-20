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
    assert any(f.name == "api::free_function" for f in result.functions)
    discovery.assert_called_once()


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
