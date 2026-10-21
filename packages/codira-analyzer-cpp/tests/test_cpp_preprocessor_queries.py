"""Check explicit operator answers, source overrides and search-context identity.

Parameters
----------
None

Returns
-------
None
    Product controls only; actual benchmark admission requires native/index proof.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from codira.config import (
    load_effective_config,
    override_repo_config_path,
    profile_config,
    render_config_toml,
)
from codira.models import AnalysisResult
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_cpp.cpp_include_context import read_include_context


def _feature_config(value: str = "1") -> dict[str, object]:
    """Supply explicit native-like prefix answers for an isolated control.

    Parameters
    ----------
    value : str, optional
        Exact feature integer spelling.

    Returns
    -------
    dict[str, object]
        Bounded opt-in compiler feature profile.
    """
    return {
        "preprocessor_definitions": {
            "__has_builtin": {"defined": True},
            "__builtin_unreachable": False,
            "__has_cpp_attribute": {"defined": True},
            "nodiscard": False,
        },
        "preprocessor_features": {
            "__has_builtin(__builtin_unreachable)": value,
            "__has_cpp_attribute(nodiscard)": "201907L",
        },
    }


def _analyze(
    tmp_path: Path, source: bytes, config: dict[str, object]
) -> AnalysisResult:
    """Run the production analyzer with one complete explicit profile.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted control root.
    source : bytes
        Original physical bytes.
    config : dict[str, object]
        Explicit profile inputs.

    Returns
    -------
    AnalysisResult
        Unmodified production result and diagnostics.
    """
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    return analyzer.analyze_file(path, tmp_path)


@pytest.mark.parametrize(
    "value,expected", [("1", "int entry()"), ("0", "void entry()")]
)
def test_exact_feature_answers_select_source_definitions(
    tmp_path: Path, value: str, expected: str
) -> None:
    """Use exact intrinsic values while still evaluating the whole expression.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.
    value, expected : str
        Feature answer and selected source signature.

    Returns
    -------
    None
    """
    source = (
        b"#if __has_builtin(__builtin_unreachable) && __has_cpp_attribute(nodiscard) >= 201907L\n"
        b"#define DECLARE(N) int N()\n#else\n#define DECLARE(N) void N()\n#endif\n"
        b"DECLARE(entry) {}\n"
    )
    result = _analyze(tmp_path, source, _feature_config(value))
    assert result.index_symbols and result.status is None
    assert result.functions[0].signature == expected


def test_source_operator_override_wins(tmp_path: Path) -> None:
    """Use a reaching source definition rather than an old opaque operator answer.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
    """
    source = (
        b"#undef __has_builtin\n#define __has_builtin(X) 0\n"
        b"#if __has_builtin(__builtin_unreachable)\n#define DECLARE(N) int N()\n"
        b"#else\n#define DECLARE(N) void N()\n#endif\nDECLARE(entry) {}\n"
    )
    result = _analyze(tmp_path, source, _feature_config())
    assert result.index_symbols and result.status is None
    assert result.functions[0].signature == "void entry()"


@pytest.mark.parametrize(
    "prefix,condition",
    [
        (
            b"#define __builtin_unreachable changed\n",
            b"__has_builtin(__builtin_unreachable)",
        ),
        (b"#undef __has_builtin\n", b"__has_builtin(__builtin_unreachable)"),
        (b"", b"__has_builtin(unobserved_builtin)"),
        (b"", b"__has_builtin(__builtin_unreachable) ? 1 : 0"),
    ],
)
def test_feature_observations_do_not_guess_unsupported_conditions(
    tmp_path: Path, prefix: bytes, condition: bytes
) -> None:
    """Hold changed operands, missing answers and unsupported expression grammar.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.
    prefix : bytes
        Source override or empty source.
    condition : bytes
        Conditional requiring unsupported or stale evidence.

    Returns
    -------
    None
    """
    result = _analyze(
        tmp_path,
        prefix + b"#if " + condition + b"\n#define DECLARE(N) int N()\n"
        b"#else\n#error unavailable implementation\n#endif\nDECLARE(entry) {}\n",
        _feature_config(),
    )
    assert not result.index_symbols and result.status is not None


@pytest.mark.parametrize(
    "value", [True, "1U", "-1", "1 + 0", "18446744073709551616", "bad"]
)
def test_invalid_feature_literals_fail_configuration(value: object) -> None:
    """Reject truth collapse, unsigned width assumptions and invented expressions.

    Parameters
    ----------
    value : object
        Invalid answer instead of one exact supported native literal.

    Returns
    -------
    None
    """
    config = _feature_config()
    config["preprocessor_features"] = {"__has_builtin(__builtin_unreachable)": value}
    with pytest.raises(ValueError, match="integer literal"):
        CppAnalyzer().configure(config)


def _header_config(tmp_path: Path, source: bytes | None = None) -> dict[str, object]:
    """Construct a control observation bound to the exact contained input graph.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing trusted root for the control files.
    source : bytes or None, optional
        Original translation unit; defaults to one literal include.

    Returns
    -------
    dict[str, object]
        Complete source/profile-bound observation profile.
    """
    source = (
        source if source is not None else b'#include "probe.h"\nDECLARE(entry) {}\n'
    )
    path = tmp_path / "unit.cpp"
    path.write_bytes(source)
    raw = (
        b"#if __has_include_next(<sdk.h>)\n#define DECLARE(N) int N()\n"
        b"#else\n#error required external SDK unavailable\n#endif\n"
    )
    (tmp_path / "probe.h").write_bytes(raw)
    config: dict[str, object] = {
        "preprocessor_definitions": {"__has_include_next": {"defined": True}}
    }
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    context = read_include_context(path, tmp_path)
    first = raw.index(b"__has_include_next")
    config["preprocessor_header_queries"] = {
        "unit.cpp": {
            "context_sha256": hashlib.sha256(context.identity.encode()).hexdigest(),
            "profile_fingerprint": analyzer.configuration_fingerprint,
            "queries": [
                {
                    "path": "probe.h",
                    "span": [first, first + len(b"__has_include_next(<sdk.h>)")],
                    "include_stack": [["unit.cpp", 0]],
                    "expression": "__has_include_next(<sdk.h>)",
                    "value": True,
                }
            ],
        }
    }
    return config


def test_header_query_is_offline_and_source_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """License one witnessed query without resolving or invoking the external SDK.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted control root.
    monkeypatch : pytest.MonkeyPatch
        Replaces subprocess execution with a failing control.

    Returns
    -------
    None
    """
    config = _header_config(tmp_path)
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=AssertionError("external process"))
    )
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    result = analyzer.analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert result.index_symbols and result.status is None
    assert result.functions[0].name == "entry"


def test_header_query_survives_repository_toml_loading(tmp_path: Path) -> None:
    """Accept TOML integer wrappers without accepting Boolean source offsets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted control root containing physical query and configuration files.

    Returns
    -------
    None
    """
    config = _header_config(tmp_path)
    payload = profile_config("default")
    plugins = payload["plugins"]
    assert isinstance(plugins, dict)
    plugins["analyzer-cpp"] = config
    path = tmp_path / "config.toml"
    path.write_text(render_config_toml(payload), encoding="utf-8")
    with override_repo_config_path(path):
        loaded = load_effective_config(root=tmp_path).plugins.configs
        assert loaded is not None
        analyzer = CppAnalyzer()
        analyzer.configure(loaded["analyzer-cpp"])
        result = analyzer.analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert result.index_symbols and result.status is None
    assert result.functions[0].name == "entry"


@pytest.mark.parametrize(
    "mutation",
    ["source", "header", "profile", "path", "span", "stack", "expression", "unit"],
)
def test_stale_header_observations_remain_partial(
    tmp_path: Path, mutation: str
) -> None:
    """Reject stale context, profile, owner, expression and include-position facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.
    mutation : str
        One independently changed evidence dimension.

    Returns
    -------
    None
    """
    config = _header_config(tmp_path)
    data = deepcopy(config["preprocessor_header_queries"])
    assert isinstance(data, dict)
    row = data["unit.cpp"]["queries"][0]
    if mutation == "source":
        with (tmp_path / "unit.cpp").open("ab") as stream:
            stream.write(b"// new physical input\n")
    elif mutation == "header":
        with (tmp_path / "probe.h").open("ab") as stream:
            stream.write(b"// changed dependency\n")
    elif mutation == "profile":
        config["emit_macros"] = False
    elif mutation == "path":
        row["path"] = "other.h"
    elif mutation == "span":
        row["span"][0] += 1
    elif mutation == "stack":
        row["include_stack"][0][1] += 1
    elif mutation == "expression":
        row["expression"] = "__has_include_next(<other.h>)"
    else:
        data["other.cpp"] = data.pop("unit.cpp")
    config["preprocessor_header_queries"] = data
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    result = analyzer.analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert not result.index_symbols and result.status is not None


def test_header_query_does_not_cover_another_include_site(tmp_path: Path) -> None:
    """Keep a second unobserved visit unknown even when its header bytes match.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
    """
    config = _header_config(
        tmp_path, b'#include "probe.h"\n#include "probe.h"\nDECLARE(entry) {}\n'
    )
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    result = analyzer.analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert not result.index_symbols and result.status is not None


def test_header_answers_change_cache_identity(tmp_path: Path) -> None:
    """Invalidate configured reuse when a native observation answer changes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
    """
    config = _header_config(tmp_path)
    analyzer = CppAnalyzer()
    analyzer.configure(config)
    original = analyzer.configuration_fingerprint
    changed = deepcopy(config["preprocessor_header_queries"])
    assert isinstance(changed, dict)
    changed["unit.cpp"]["queries"][0]["value"] = False
    config["preprocessor_header_queries"] = changed
    analyzer.configure(config)
    assert analyzer.configuration_fingerprint != original
    result = analyzer.analyze_file(tmp_path / "unit.cpp", tmp_path)
    assert not result.index_symbols and result.status is not None


@pytest.mark.parametrize(
    "mutation",
    [
        "absolute",
        "parent",
        "boolean_offset",
        "boolean_include_offset",
        "reversed",
        "digest",
        "fingerprint",
        "stack_parent",
        "nonboolean",
        "dynamic_header",
        "duplicate",
        "extra",
    ],
)
def test_invalid_header_profiles_fail_configuration(
    tmp_path: Path, mutation: str
) -> None:
    """Reject malformed or conflicting observations before analysis starts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted control root.
    mutation : str
        Invalid input shape or conflicting observation.

    Returns
    -------
    None
    """
    config = _header_config(tmp_path)
    data = deepcopy(config["preprocessor_header_queries"])
    assert isinstance(data, dict)
    entry = data["unit.cpp"]
    row = entry["queries"][0]
    if mutation == "absolute":
        row["path"] = "/outside/probe.h"
    elif mutation == "parent":
        row["path"] = "../probe.h"
    elif mutation == "boolean_offset":
        row["span"][0] = True
    elif mutation == "boolean_include_offset":
        row["include_stack"][0][1] = True
    elif mutation == "reversed":
        row["span"] = [31, 4]
    elif mutation == "digest":
        entry["context_sha256"] = "not-a-digest"
    elif mutation == "fingerprint":
        entry["profile_fingerprint"] = "not-a-fingerprint"
    elif mutation == "stack_parent":
        row["include_stack"][0][0] = "../unit.cpp"
    elif mutation == "nonboolean":
        row["value"] = 1
    elif mutation == "dynamic_header":
        row["expression"] = "__has_include_next(HEADER)"
    elif mutation == "duplicate":
        other = deepcopy(row)
        other["value"] = False
        entry["queries"].append(other)
    else:
        row["whole_branch_value"] = True
    config["preprocessor_header_queries"] = data
    with pytest.raises(ValueError):
        CppAnalyzer().configure(config)


def test_spliced_feature_query_keeps_original_function_coordinates(
    tmp_path: Path,
) -> None:
    """Use physical directive spans while preserving UTF-8 and CRLF source rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
    """
    source = (
        "// π\r\n#if __has_builtin(\\\r\n__builtin_unreachable)\r\n".encode()
        + b"#define DECLARE(N) int N()\r\n#else\r\n#error unsupported\r\n#endif\r\n"
        b"DECLARE(entry) {}\r\n"
    )
    result = _analyze(tmp_path, source, _feature_config())
    assert result.index_symbols and result.status is None
    assert (result.functions[0].name, result.functions[0].lineno) == ("entry", 8)


@pytest.mark.parametrize("operand", [b"__builtin_unreachable", b"SOURCE_BUILTIN"])
def test_feature_answers_survive_captured_alias_prescan(
    tmp_path: Path, operand: bytes
) -> None:
    """Resolve a pure intrinsic after ordinary source-backed alias substitution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted control root.
    operand : bytes
        Written intrinsic identifier or an explicitly captured argument macro.

    Returns
    -------
    None
    """
    source = (
        b"#define SOURCE_BUILTIN __builtin_unreachable\n"
        b"#define TEST_HAS_FEATURE(X) __has_builtin(X)\n"
        b"#if TEST_HAS_FEATURE(" + operand + b")\n#define DECLARE(N) int N()\n"
        b"#else\n#error unavailable builtin\n#endif\nDECLARE(entry) {}\n"
    )
    result = _analyze(tmp_path, source, _feature_config())
    assert result.index_symbols and result.status is None
    assert result.functions[0].signature == "int entry()"


def test_warning_feature_uses_exact_literal_operand(tmp_path: Path) -> None:
    """Use a witnessed compiler warning query without treating it as a macro name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
    """
    config = _feature_config()
    definitions = config["preprocessor_definitions"]
    features = config["preprocessor_features"]
    assert isinstance(definitions, dict) and isinstance(features, dict)
    definitions["__has_warning"] = {"defined": True}
    features['__has_warning("-Wunused-result")'] = "1"
    (tmp_path / "warnings.h").write_bytes(
        b"#define TEST_WARNING(X) __has_warning(X)\n"
        b'#if TEST_WARNING("-Wunused-result")\n#define DECLARE(N) int N()\n'
        b"#else\n#error unknown warning\n#endif\n"
    )
    result = _analyze(
        tmp_path,
        b'#include "warnings.h"\nDECLARE(entry) {}\n',
        config,
    )
    assert result.index_symbols and result.status is None


def test_known_warning_query_does_not_suppress_original_grammar_errors(
    tmp_path: Path,
) -> None:
    """Retain the separate provider gap for string operands in a root directive.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Trusted root.

    Returns
    -------
    None
        Query facts license definitions without masking unrelated grammar recovery.
    """
    config = _feature_config()
    definitions = config["preprocessor_definitions"]
    features = config["preprocessor_features"]
    assert isinstance(definitions, dict) and isinstance(features, dict)
    definitions["__has_warning"] = {"defined": True}
    features['__has_warning("-Wunused-result")'] = "1"
    result = _analyze(
        tmp_path,
        b'#if __has_warning("-Wunused-result")\n#define DECLARE(N) int N()\n'
        b"#else\n#error unknown warning\n#endif\nDECLARE(entry) {}\n",
        config,
    )
    assert not result.index_symbols and result.status is not None
    assert any("Tree-sitter recovered" in d.message for d in result.status.diagnostics)
    assert not any(
        "active error directive" in d.message for d in result.status.diagnostics
    )


def test_intrinsic_answer_rescan_retains_substitution_bound() -> None:
    """Reject a faulty opaque resolver that makes no progress during rescanning.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    from codira_analyzer_cpp.cpp_macro_expansion import (
        _MacroDefinition,
        _MacroExpander,
        _macro_tokens,
    )

    expander = _MacroExpander(
        {b"INTRINSIC": _MacroDefinition(None, b"", opaque=True)},
        opaque_resolver=lambda invocation: invocation,
    )
    with pytest.raises(ValueError, match="substitution limit"):
        expander.expand(_macro_tokens(b"INTRINSIC(value)"))
