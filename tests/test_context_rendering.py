"""Regression tests for context rendering quality.

Responsibilities
----------------
- Assert snippet extraction, docstring cleanup, and enriched block layout remain consistent.
- Verify file-role classification, scoring rules, and fallback symbols for context_for.
- Cover scoring adjustments that influence prompt rendering.

Design principles
-----------------
Tests use deterministic fixtures and explicit expectations so prompt rendering regressions are easy to interpret.

Architectural role
------------------
This module belongs to the **context rendering verification layer** that keeps textual output precise for agents, QA, and CLI consumers.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from codira.query.classifier import build_retrieval_plan, classify_query
from codira.query.context import (
    PRIMARY_SYMBOL_SCORING_RULES,
    _append_main_context_sections,
    _apply_scoring_rules,
    _classify_file_role,
    _extract_candidate_score_features,
    _path_bias,
    _snippet_from_node,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_snippet_from_node_removes_docstring_and_collapses_blank_lines() -> None:
    """
    Ensure extracted snippets remain compact after docstring removal.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts normalized snippet output.
    """
    source = (
        "def demo(x):\n"
        '    """Example docstring."""\n'
        "\n"
        "    value = x + 1\n"
        "\n"
        "    return value\n"
    )
    tree = ast.parse(source)
    node = tree.body[0]

    snippet = _snippet_from_node(node, source.splitlines())

    assert snippet == [
        "def demo(x):",
        "",
        "    value = x + 1",
        "",
        "    return value",
    ]


def test_append_main_context_sections_separates_enriched_blocks(tmp_path: Path) -> None:
    """
    Ensure plain-text context keeps enriched symbol blocks visually separated.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used to create fixture files.

    Returns
    -------
    None
        The test asserts visual separation between enriched context blocks.
    """
    first = tmp_path / "alpha.py"
    second = tmp_path / "beta.py"

    first.write_text(
        "def alpha():\n" '    """Alpha docstring."""\n' "    return 1\n",
        encoding="utf-8",
    )
    second.write_text(
        "def beta():\n" '    """Beta docstring."""\n' "    return 2\n",
        encoding="utf-8",
    )

    top_matches = [
        ("function", "alpha", "alpha", "alpha.py", 1),
        ("function", "beta", "beta", "beta.py", 1),
    ]

    lines: list[str] = []
    _append_main_context_sections(lines, tmp_path, top_matches, [], [], [])

    rendered = "\n".join(lines)

    assert "function alpha()" in rendered
    assert "function beta()" in rendered
    assert "    Alpha docstring.\n\nfunction beta()" in rendered


def test_classify_file_role_distinguishes_core_query_roles() -> None:
    """
    Keep the deterministic file-role classifier explicit for retrieval.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts stable role classification for implementation,
        interface, test, and tooling files.
    """
    assert _classify_file_role("src/pkg/core.py", "pkg.core") == "implementation"
    assert _classify_file_role("include/pkg/core.h", "pkg.core") == "interface"
    assert _classify_file_role("tests/test_core.py", "tests.test_core") == "test"
    assert _classify_file_role("scripts/build_index.py", "scripts.build_index") == (
        "tooling"
    )


def test_path_bias_flips_test_preference_when_query_is_test_related() -> None:
    """
    Prefer implementation files by default but tests when explicitly asked.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts intent-aware role bias for implementation and test
        paths.
    """
    default_intent = classify_query("cache invalidation")
    test_intent = classify_query("cache invalidation tests")

    implementation_bias = _path_bias(
        "src/pkg/core.py",
        "pkg.core",
        intent=default_intent,
    )
    test_bias = _path_bias(
        "tests/test_core.py",
        "tests.test_core",
        intent=default_intent,
    )
    explicit_test_bias = _path_bias(
        "tests/test_core.py",
        "tests.test_core",
        intent=test_intent,
    )

    assert implementation_bias > test_bias
    assert explicit_test_bias > implementation_bias


def test_table_driven_symbol_scoring_applies_weighted_features() -> None:
    """
    Preserve deterministic weighted lexical scoring under the rule-table model.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts extracted features produce the expected weighted score.
    """
    intent = classify_query("cache invalidation")
    query_tokens = sorted(["cache", "invalidation"])
    symbol = (
        "function",
        "pkg.core",
        "cache_invalidation",
        "src/pkg/core.py",
        10,
    )
    features = _extract_candidate_score_features(
        query_tokens,
        symbol,
        intent=intent,
        raw_query="cache invalidation",
        target_symbol="cache_invalidation",
    )

    assert features.exact_target_symbol_match == 1
    assert features.path_bias == 3
    assert features.implementation_module_bonus == 1
    assert features.strong_token_hit == 1
    assert (
        _apply_scoring_rules(features, PRIMARY_SYMBOL_SCORING_RULES)
        == 20 + 5 + 3 + 10 + 4 + 2
    )


def test_classify_query_assigns_primary_intent_families() -> None:
    """
    Keep the Phase 17 primary intent families deterministic.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts stable family assignment for the initial planner
        categories.
    """
    assert classify_query("cache invalidation").primary_intent == "behavior"
    assert classify_query("cache invalidation tests").primary_intent == "test"
    assert classify_query("cli configuration flags").primary_intent == "configuration"
    assert classify_query("public API symbol").primary_intent == "api_surface"
    assert classify_query("architecture graph overview").primary_intent == (
        "architecture"
    )


def test_build_retrieval_plan_routes_channels_and_graph_policy() -> None:
    """
    Build a deterministic retrieval plan from the classified query family.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts routing and policy toggles for behavior, test,
        configuration, and architecture queries.
    """
    behavior_plan = build_retrieval_plan(classify_query("cache invalidation"))
    test_plan = build_retrieval_plan(classify_query("cache invalidation tests"))
    config_plan = build_retrieval_plan(classify_query("cli configuration flags"))
    architecture_plan = build_retrieval_plan(
        classify_query("architecture graph overview")
    )

    assert behavior_plan.channels == ("symbol", "embedding", "semantic")
    assert behavior_plan.include_doc_issues is True
    assert behavior_plan.include_include_graph is True

    assert test_plan.channels == ("test", "symbol", "embedding", "semantic")
    assert test_plan.include_doc_issues is False
    assert test_plan.include_include_graph is False

    assert config_plan.channels == ("script", "symbol", "embedding", "semantic")
    assert config_plan.include_doc_issues is False
    assert config_plan.include_include_graph is False

    assert architecture_plan.channels == ("symbol", "semantic", "embedding")
    assert architecture_plan.include_include_graph is True
