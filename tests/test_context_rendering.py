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
from typing import TYPE_CHECKING, cast

from codira.query.classifier import build_retrieval_plan, classify_query
from codira.query.context import (
    PRIMARY_SYMBOL_AGGREGATION_RULES,
    ExplainSectionsRequest,
    MainContextSectionsRequest,
    _aggregate_candidate_signals,
    _append_explain_signal_sections,
    _append_main_context_sections,
    _candidate_has_signal,
    _candidate_retrieval_signals,
    _candidate_signal_strength,
    _classify_file_role,
    _find_references,
    _format_symbol,
    _load_cached_python_file,
    _load_reference_scan_file,
    _path_bias,
    _rank_signals_with_provenance,
    _ReferenceScanFile,
    _retrieve_documentation_candidates,
    _snippet_from_node,
    _top_matches_payload,
)
from codira.query.signals import RetrievalSignal

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

    from codira.contracts import (
        BackendDocumentationCandidatesRequest,
        BackendQueryConnection,
    )
    from codira.types import DocumentationChannelResults, ReferenceSearchRow


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


def test_load_reference_scan_file_caches_non_import_lines(tmp_path: Path) -> None:
    """
    Cache decoded file text together with reusable non-import scan lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used to create the fixture file.

    Returns
    -------
    None
        The test asserts import lines are excluded from the reusable scan view
        and the same cached object is returned on repeated loads.
    """
    source = tmp_path / "sample.py"
    source.write_text(
        "import helper\nfrom pkg import thing\nvalue = helper\nhelper()\n",
        encoding="utf-8",
    )
    cache: dict[Path, _ReferenceScanFile] = {}

    first = _load_reference_scan_file(source, cache)
    second = _load_reference_scan_file(source, cache)

    assert first is not None
    assert second is first
    assert first.text.count("helper") == 3
    assert first.searchable_lines == (
        (3, "value = helper"),
        (4, "helper()"),
    )


def test_find_references_filters_stored_reference_rows() -> None:
    """
    Filter stored reference-search rows with stable substring semantics.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts matching rows are preserved deterministically.
    """
    rows: list[ReferenceSearchRow] = [
        ("/tmp/alpha.py", 2, "helper()"),
        ("/tmp/alpha.py", 3, "other()"),
        ("/tmp/beta.py", 1, "value = other"),
        ("/tmp/beta.py", 2, "other()"),
    ]
    helper_refs = _find_references("helper", rows)
    other_refs = _find_references("other", rows)

    assert helper_refs == [("/tmp/alpha.py", 2)]
    assert other_refs == [
        ("/tmp/alpha.py", 3),
        ("/tmp/beta.py", 1),
        ("/tmp/beta.py", 2),
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
        'def alpha():\n    """Alpha docstring."""\n    return 1\n',
        encoding="utf-8",
    )
    second.write_text(
        'def beta():\n    """Beta docstring."""\n    return 2\n',
        encoding="utf-8",
    )

    top_matches = [
        ("function", "alpha", "alpha", "alpha.py", 1),
        ("function", "beta", "beta", "beta.py", 1),
    ]

    lines: list[str] = []
    _append_main_context_sections(
        MainContextSectionsRequest(
            lines=lines,
            root=tmp_path,
            top_matches=top_matches,
            doc_issues=[],
            expanded=[],
            unique_refs=[],
        )
    )

    rendered = "\n".join(lines)

    assert "function alpha()" in rendered
    assert "function beta()" in rendered
    assert "    Alpha docstring.\n\nfunction beta()" in rendered


def test_load_cached_python_file_caches_syntax_error_sources(tmp_path: Path) -> None:
    """
    Cache unreadable-AST Python sources after a syntax error.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root used to create a syntax-error fixture.

    Returns
    -------
    None
        The test asserts syntax-error source text is cached with a ``None`` AST.
    """

    source_path = tmp_path / "broken.py"
    source_path.write_text("def broken(:\n", encoding="utf-8")
    cache: dict[Path, tuple[str, list[str], ast.Module | None]] = {}

    first = _load_cached_python_file(source_path, cache)
    source_path.write_text("def fixed():\n    return 1\n", encoding="utf-8")
    second = _load_cached_python_file(source_path, cache)

    assert first == ("def broken(:\n", ["def broken(:"], None)
    assert second == first
    assert cache[source_path] == first


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


def test_symbol_signal_aggregation_applies_weighted_evidence() -> None:
    """
    Preserve deterministic weighted lexical scoring through signal aggregation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts candidate signals produce the expected weighted score.
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
    signals = _candidate_retrieval_signals(
        query_tokens,
        symbol,
        intent=intent,
        raw_query="cache invalidation",
        target_symbol="cache_invalidation",
    )

    assert _candidate_signal_strength(signals, "exact_target_symbol_match") == 1
    assert _candidate_signal_strength(signals, "path_bias") == 3
    assert _candidate_signal_strength(signals, "implementation_module_bonus") == 1
    assert _candidate_has_signal(signals, "strong_token_hit")
    assert (
        _aggregate_candidate_signals(signals, PRIMARY_SYMBOL_AGGREGATION_RULES)
        == 20 + 5 + 3 + 10 + 4 + 2
    )


def test_symbol_signal_aggregation_preserves_exact_match_dominance() -> None:
    """
    Keep exact symbol evidence above partial lexical evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts signal aggregation keeps exact-name dominance
        explicit for symbol-channel candidates.
    """
    intent = classify_query("cache")
    query_tokens = ["cache"]
    exact_symbol = (
        "function",
        "pkg.core",
        "cache",
        "src/pkg/core.py",
        10,
    )
    partial_symbol = (
        "function",
        "pkg.core",
        "cache_worker",
        "src/pkg/core.py",
        20,
    )
    exact_signals = _candidate_retrieval_signals(
        query_tokens,
        exact_symbol,
        intent=intent,
        raw_query="cache",
        target_symbol="cache",
    )
    partial_signals = _candidate_retrieval_signals(
        query_tokens,
        partial_symbol,
        intent=intent,
        raw_query="cache",
        target_symbol="cache",
    )

    assert _candidate_has_signal(exact_signals, "exact_name_match")
    assert not _candidate_has_signal(partial_signals, "exact_name_match")
    assert _aggregate_candidate_signals(
        exact_signals,
        PRIMARY_SYMBOL_AGGREGATION_RULES,
    ) > _aggregate_candidate_signals(
        partial_signals,
        PRIMARY_SYMBOL_AGGREGATION_RULES,
    )


def test_retrieve_documentation_candidates_renders_explicit_provenance(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Convert documentation backend rows into explicit context top matches.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the active backend.
    tmp_path : pathlib.Path
        Temporary directory used for relative rendering.

    Returns
    -------
    None
        The test asserts docs-channel rows keep documentation provenance in
        text and JSON rendering.
    """

    class _FakeBackend:
        def documentation_candidates(
            self,
            request: BackendDocumentationCandidatesRequest,
        ) -> DocumentationChannelResults:
            del request
            return [
                (
                    0.91,
                    (
                        "doc:section:docs/architecture.md:plugin-loading:1",
                        "section",
                        "markdown_section",
                        str(tmp_path / "docs" / "architecture.md"),
                        7,
                        12,
                        "Plugin Loading",
                        ("Plugin Loading",),
                        "Plugin Loading\nPlugins are discovered through entry points.",
                    ),
                )
            ]

    monkeypatch.setattr(
        "codira.query.context.active_index_backend",
        lambda: _FakeBackend(),
    )

    results = _retrieve_documentation_candidates(
        tmp_path,
        "plugin loading docs",
        cast("BackendQueryConnection", object()),
        classify_query("architecture plugin loading docs"),
        None,
    )

    assert results == [
        (
            0.91,
            (
                "documentation",
                "markdown_section",
                "Plugin Loading",
                str(tmp_path / "docs" / "architecture.md"),
                7,
            ),
        )
    ]
    rendered = _format_symbol(tmp_path, results[0][1], include_path=True)
    assert rendered == (
        "documentation: Plugin Loading:7 [markdown_section] (docs/architecture.md)"
    )
    assert _top_matches_payload([results[0][1]], None) == [
        {
            "type": "documentation",
            "module": "markdown_section",
            "name": "Plugin Loading",
            "file": str(tmp_path / "docs" / "architecture.md"),
            "lineno": 7,
            "confidence": 1.0,
            "source_format": "markdown_section",
            "provenance": "markdown_section",
        }
    ]


def test_rank_signals_boosts_documentation_under_docs_path(tmp_path: Path) -> None:
    """
    Give documentation artifacts under ``docs/`` a small deterministic boost.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to build stable absolute candidate paths.

    Returns
    -------
    None
        The test asserts the boost only affects docs-channel documentation
        artifacts whose file path is under a ``docs`` directory.
    """
    process_symbol = (
        "documentation",
        "markdown_section",
        "Release Process",
        str(tmp_path / "docs" / "process" / "release.md"),
        1,
    )
    readme_symbol = (
        "documentation",
        "markdown_section",
        "README",
        str(tmp_path / "README.md"),
        1,
    )
    docs_symbol = (
        "documentation",
        "markdown_section",
        "Architecture",
        str(tmp_path / "docs" / "architecture.md"),
        1,
    )
    root_symbol = (
        "documentation",
        "markdown_section",
        "Architecture",
        str(tmp_path / "architecture.md"),
        1,
    )
    signals = [
        RetrievalSignal(
            kind="embedding_similarity",
            family="semantic",
            target=process_symbol,
            producer_name="query-channel-docs",
            producer_version="1",
            capability_name="embedding_similarity",
            capability_version="1",
            channel_name="docs",
            rank=1,
            strength=0.9,
        ),
        RetrievalSignal(
            kind="embedding_similarity",
            family="semantic",
            target=readme_symbol,
            producer_name="query-channel-docs",
            producer_version="1",
            capability_name="embedding_similarity",
            capability_version="1",
            channel_name="docs",
            rank=1,
            strength=0.9,
        ),
        RetrievalSignal(
            kind="embedding_similarity",
            family="semantic",
            target=docs_symbol,
            producer_name="query-channel-docs",
            producer_version="1",
            capability_name="embedding_similarity",
            capability_version="1",
            channel_name="docs",
            rank=1,
            strength=0.9,
        ),
        RetrievalSignal(
            kind="embedding_similarity",
            family="semantic",
            target=root_symbol,
            producer_name="query-channel-docs",
            producer_version="1",
            capability_name="embedding_similarity",
            capability_version="1",
            channel_name="docs",
            rank=1,
            strength=0.9,
        ),
    ]

    ranked, diagnostics = _rank_signals_with_provenance(
        signals,
        intent=classify_query("architecture overview"),
    )

    assert [symbol for symbol, _score in ranked] == [
        process_symbol,
        readme_symbol,
        docs_symbol,
        root_symbol,
    ]
    assert diagnostics[process_symbol]["docs_path_bonus"] == 0.2
    assert diagnostics[readme_symbol]["docs_path_bonus"] == 0.18
    assert diagnostics[docs_symbol]["docs_path_bonus"] == 0.1
    assert "docs_path_bonus" not in diagnostics[root_symbol]


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

    assert behavior_plan.channels == ("symbol", "embedding", "semantic", "docs")
    assert behavior_plan.include_doc_issues is True
    assert behavior_plan.include_include_graph is True

    assert test_plan.channels == ("test", "symbol", "embedding", "semantic", "docs")
    assert test_plan.include_doc_issues is False
    assert test_plan.include_include_graph is False

    assert config_plan.channels == (
        "script",
        "docs",
        "symbol",
        "embedding",
        "semantic",
    )
    assert config_plan.include_doc_issues is False
    assert config_plan.include_include_graph is False

    assert architecture_plan.channels == ("docs", "symbol", "semantic", "embedding")
    assert architecture_plan.include_include_graph is True


def test_append_explain_signal_sections_renders_overload_evidence() -> None:
    """
    Render overload-derived evidence explicitly in explain sections.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts signal preview and merge sections expose overload
        evidence details deterministically.
    """
    preview = [
        {
            "kind": "text_match",
            "family": "semantic",
            "producer_name": "query-enrichment-overloads",
            "capability_name": "semantic_text",
            "type": "function",
            "module": "pkg.alpha",
            "name": "run",
            "lineno": 10,
            "channel_name": "overloads",
            "rank": 1,
            "strength": 0.5,
            "evidence_detail": "overload_signature:run(value, mode)",
        }
    ]
    merge = [
        {
            "type": "function",
            "module": "pkg.alpha",
            "name": "run",
            "lineno": 10,
            "signal_count": 2,
            "families": {"lexical": 1, "semantic": 1},
            "capabilities": {"semantic_text": 1, "symbol_lookup": 1},
            "evidence": {"overload_signature": 1},
            "producers": ["query-channel-symbol", "query-enrichment-overloads"],
        }
    ]

    lines: list[str] = []
    _append_explain_signal_sections(
        ExplainSectionsRequest(
            lines=lines,
            explain=True,
            intent=None,
            plan=None,
            enabled_channels=None,
            channel_priority=None,
            ordered_channels=None,
            producers=None,
            signal_collection=None,
            signal_preview=preview,
            signal_merge=merge,
            bundles=None,
            provenance=None,
            diversity=None,
            expansion=None,
            top_matches=[],
        )
    )

    rendered = "\n".join(lines)

    assert "channel=overloads rank=1 strength=0.5" in rendered
    assert "evidence=overload_signature:run(value, mode)" in rendered
    assert "evidence={'overload_signature': 1}" in rendered
