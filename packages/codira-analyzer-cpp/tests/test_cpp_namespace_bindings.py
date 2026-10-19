"""Verify explicit namespace profiles, source aliases and reuse identity.

Parameters
----------
None

Returns
-------
None
    Defines profile validation and source-position regressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


def test_namespace_profile_preserves_positions_and_invalidates_reuse(
    tmp_path: Path,
) -> None:
    """Resolve attribute-compatible header aliases in the supplied namespace.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.

    Returns
    -------
    None
        Namespace ownership changes while original signatures and calls remain.
    """
    header = tmp_path / "scope.h"
    header.write_text(
        '#if CLANG\n#define NS [[gnu::visibility("hidden")]] ROOT\n'
        "#else\n#define NS ROOT\n#endif\n"
    )
    source = tmp_path / "scope.cpp"
    source.write_text(
        '#include "scope.h"\nnamespace NS {\nint run(int x) { return callee(x); }\n}\n'
    )
    default = CppAnalyzer()
    before = default.analyze_file(source, tmp_path)
    configured = CppAnalyzer()
    configured.configure({"namespace_macro_definitions": {"ROOT": "__one"}})
    identity = configured.analysis_input_fingerprint(source, tmp_path)
    after = configured.analyze_file(source, tmp_path)
    assert after.index_symbols
    assert before.functions[0].name == "NS::run"
    assert after.functions[0].name == "__one::run"
    assert after.functions[0].lineno == before.functions[0].lineno == 3
    assert after.functions[0].signature == before.functions[0].signature
    assert after.functions[0].parameters == before.functions[0].parameters
    assert after.functions[0].calls == before.functions[0].calls
    assert configured.analysis_input_fingerprint_matches(source, tmp_path, identity)
    assert not default.analysis_input_fingerprint_matches(source, tmp_path, identity)
    configured.configure({"namespace_macro_definitions": {"ROOT": "__two"}})
    assert not configured.analysis_input_fingerprint_matches(source, tmp_path, identity)
    assert configured.analyze_file(source, tmp_path).functions[0].name == "__two::run"
    configured.configure({"namespace_macro_definitions": {"ROOT": "__one"}})
    header.write_text("#define NS OTHER\n")
    assert not configured.analysis_input_fingerprint_matches(source, tmp_path, identity)


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {"N": "namespace"},
        {"class": "n"},
        {"N": "a::b"},
        {"N": "a b"},
        {"N": "x\ny"},
        {"N": 3},
        {3: "n"},
    ],
)
def test_namespace_profile_rejects_invalid_identifiers(invalid: object) -> None:
    """Reject non-object profiles, non-string values and provider keyword tokens.

    Parameters
    ----------
    invalid : object
        Invalid namespace binding configuration.

    Returns
    -------
    None
        Invalid configuration fails before any source analysis.
    """
    with pytest.raises(ValueError, match="namespace_macro_definitions"):
        CppAnalyzer().configure({"namespace_macro_definitions": invalid})


@pytest.mark.parametrize(
    "directives",
    [
        "#define ROOT other\n",
        "#undef ROOT\n",
        "#define __one other\n",
        "#define namespace other\n",
        "#define inline other\n",
    ],
)
def test_namespace_profile_rejects_source_overrides(
    tmp_path: Path, directives: str
) -> None:
    """Expose source directives contradicting explicit namespace assumptions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    directives : str
        Conflicting source definitions or undefinitions.

    Returns
    -------
    None
        Explicit assumptions cannot silently override captured source.
    """
    path = tmp_path / "conflict.cpp"
    path.write_text(directives + "namespace ROOT { int run() {} }\n")
    analyzer = CppAnalyzer()
    analyzer.configure({"namespace_macro_definitions": {"ROOT": "__one"}})
    with pytest.raises(ValueError, match="conflicts"):
        analyzer.analyze_file(path, tmp_path)


def test_namespace_profile_alias_order_and_unresolved_branches(tmp_path: Path) -> None:
    """Respect reaching definitions and hold incompatible namespace alternatives.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and header directory.

    Returns
    -------
    None
        Early literal scopes remain intact and ambiguous aliases fail explicitly.
    """
    header = tmp_path / "scope.h"
    header.write_text("#define NS ROOT\n")
    path = tmp_path / "scope.cpp"
    path.write_text(
        'namespace NS { int before() {} }\n#include "scope.h"\n'
        "namespace NS { int after() {} }\n"
    )
    analyzer = CppAnalyzer()
    analyzer.configure({"namespace_macro_definitions": {"ROOT": "__one"}})
    assert {f.name for f in analyzer.analyze_file(path, tmp_path).functions} == {
        "NS::before",
        "__one::after",
    }
    header.write_text("#if BUILD\n#define NS ROOT\n#else\n#define NS OTHER\n#endif\n")
    with pytest.raises(ValueError, match="cannot resolve namespace alias NS"):
        analyzer.analyze_file(path, tmp_path)
