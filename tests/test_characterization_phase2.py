"""ADR-004 Phase 2 characterization tests for stable query ordering.

Responsibilities
----------------
- Create fixtures with duplicate symbols to validate deterministic ordering of index decisions and query picks.
- Confirm retrieval plans honor file-role priorities and merge order across contexts.

Design principles
-----------------
Fixtures remain minimal but deterministic so query ordering regressions surface immediately.

Architectural role
------------------
This module belongs to the **verification layer** that protects characterization requirements from ADR-004 Phase 2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from codira.indexer import index_repo
from codira.query.context import ContextRequest, context_for
from codira.query.exact import find_symbol
from codira.storage import init_db

if TYPE_CHECKING:
    from pathlib import Path


def _write_phase2_fixture(root: Path) -> None:
    """
    Write a small duplicate-symbol fixture for characterization tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files are created under ``root``.
    """
    pkg = root / "pkg"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "zeta.py").write_text(
        '"""Late-sorted duplicate symbol fixture."""\n'
        "\n"
        "def shared_symbol():\n"
        '    """Return the zeta duplicate."""\n'
        "    return 2\n",
        encoding="utf-8",
    )
    (pkg / "alpha.py").write_text(
        '"""Early-sorted duplicate symbol fixture."""\n'
        "\n"
        "def shared_symbol():\n"
        '    """Return the alpha duplicate."""\n'
        "    return 1\n",
        encoding="utf-8",
    )


def _write_phase12_role_fixture(root: Path) -> None:
    """
    Write a small implementation-and-test fixture for role-aware retrieval.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files are created under ``root``.
    """
    pkg = root / "pkg"
    tests_dir = root / "tests"
    pkg.mkdir()
    tests_dir.mkdir()

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")

    (pkg / "core.py").write_text(
        '"""Cache invalidation implementation module."""\n'
        "\n"
        "def cache_flow():\n"
        '    """Cache invalidation engine for production writes."""\n'
        "    return True\n",
        encoding="utf-8",
    )
    (tests_dir / "test_core.py").write_text(
        '"""Cache invalidation tests module."""\n'
        "\n"
        "def cache_flow_test():\n"
        '    """Cache invalidation tests for regression coverage."""\n'
        "    return True\n",
        encoding="utf-8",
    )


def test_index_report_decisions_are_sorted_deterministically(tmp_path: Path) -> None:
    """
    Preserve deterministic per-file decision ordering in index reports.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stable decision ordering independent of file creation
        order.
    """
    _write_phase2_fixture(tmp_path)
    init_db(tmp_path)

    report = index_repo(tmp_path)

    assert [(row.action, row.path, row.reason) for row in report.decisions] == [
        ("indexed", str(tmp_path / "pkg" / "__init__.py"), "new file"),
        ("indexed", str(tmp_path / "pkg" / "alpha.py"), "new file"),
        ("indexed", str(tmp_path / "pkg" / "zeta.py"), "new file"),
    ]


def test_find_symbol_orders_duplicate_matches_by_module(tmp_path: Path) -> None:
    """
    Preserve deterministic ordering for duplicate exact-symbol matches.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts the exact-match ordering contract used by callers and
        CLI rendering.
    """
    _write_phase2_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    assert find_symbol(tmp_path, "shared_symbol") == [
        (
            "function",
            "pkg.alpha",
            "shared_symbol",
            str(tmp_path / "pkg" / "alpha.py"),
            3,
        ),
        (
            "function",
            "pkg.zeta",
            "shared_symbol",
            str(tmp_path / "pkg" / "zeta.py"),
            3,
        ),
    ]


def test_context_for_json_is_stable_across_repeated_runs(tmp_path: Path) -> None:
    """
    Preserve deterministic JSON ordering for repeated context retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts repeated JSON output remains byte-for-byte equivalent
        after parsing and that ranked matches retain a stable order.
    """
    _write_phase2_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    first = json.loads(
        context_for(ContextRequest(root=tmp_path, query="shared_symbol", as_json=True))
    )
    second = json.loads(
        context_for(ContextRequest(root=tmp_path, query="shared_symbol", as_json=True))
    )

    assert first == second
    assert [row["module"] for row in first["top_matches"]] == [
        "pkg.alpha",
        "pkg.zeta",
    ]


def test_context_for_prefers_implementation_unless_tests_are_requested(
    tmp_path: Path,
) -> None:
    """
    Preserve the Phase 12 implementation-first ranking contract.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts implementation files rank ahead of tests by default
        and that explicit test queries flip that preference.
    """
    _write_phase12_role_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    default_context = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="cache invalidation",
                as_json=True,
            )
        )
    )
    test_context = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="cache invalidation tests",
                as_json=True,
            )
        )
    )

    assert default_context["top_matches"][0]["module"] == "pkg.core"
    assert test_context["top_matches"][0]["module"] == "tests.test_core"


def test_context_for_explain_reports_phase_17_retrieval_plan(tmp_path: Path) -> None:
    """
    Expose the deterministic Phase 17 retrieval plan in explain output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts explain output reflects the planner for test and
        architecture-oriented queries.
    """
    _write_phase12_role_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    test_payload = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="cache invalidation tests",
                as_json=True,
                explain=True,
            )
        )
    )
    architecture_payload = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="architecture graph cache flow",
                as_json=True,
                explain=True,
            )
        )
    )

    test_explain = test_payload["explain"]
    assert test_explain["intent"]["primary_intent"] == "test"
    assert test_explain["planner"] == {
        "primary_intent": "test",
        "channels": ["test", "symbol", "embedding", "semantic"],
        "include_doc_issues": False,
        "include_include_graph": False,
        "include_references": True,
    }

    architecture_explain = architecture_payload["explain"]
    assert architecture_explain["intent"]["primary_intent"] == "architecture"
    assert architecture_explain["planner"]["channels"] == [
        "symbol",
        "semantic",
        "embedding",
    ]
    assert architecture_explain["planner"]["include_include_graph"] is True
    assert test_explain["retrieval_producers"] == [
        {
            "producer_name": "query-channel-test",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "test",
            "declared_capabilities": ["symbol_lookup", "task_specialization"],
            "known_capabilities": ["symbol_lookup", "task_specialization"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-channel-symbol",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "symbol",
            "declared_capabilities": ["symbol_lookup"],
            "known_capabilities": ["symbol_lookup"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-channel-embedding",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "embedding",
            "declared_capabilities": [
                "embedding_similarity",
                "diagnostics_metadata",
            ],
            "known_capabilities": [
                "embedding_similarity",
                "diagnostics_metadata",
            ],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-channel-semantic",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "semantic",
            "declared_capabilities": ["semantic_text"],
            "known_capabilities": ["semantic_text"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-enrichment-call-graph",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "enrichment",
            "source_name": "call_graph",
            "declared_capabilities": ["graph_relations"],
            "known_capabilities": ["graph_relations"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-enrichment-references",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "enrichment",
            "source_name": "references",
            "declared_capabilities": ["graph_relations"],
            "known_capabilities": ["graph_relations"],
            "unknown_capabilities": [],
        },
    ]
    test_signal_collection = test_explain["signal_collection"]
    test_signal_preview = test_explain["signals"]
    test_signal_merge = test_explain["signal_merge"]
    assert test_signal_collection["total_signals"] > 0
    assert set(test_signal_collection["families"]) <= {"lexical", "semantic", "task"}
    assert "symbol_lookup" in test_signal_collection["capabilities"]
    assert "semantic_text" in test_signal_collection["capabilities"]
    assert "query-channel-symbol" in test_signal_collection["used_producers"]
    assert "query-channel-semantic" in test_signal_collection["used_producers"]
    assert "query-enrichment-call-graph" in test_signal_collection["ignored_producers"]
    assert "query-enrichment-references" in test_signal_collection["ignored_producers"]
    assert test_signal_preview
    assert {
        "kind",
        "family",
        "producer_name",
        "capability_name",
        "type",
        "module",
        "name",
        "lineno",
    } <= set(test_signal_preview[0])
    assert test_signal_merge
    assert {
        "type",
        "module",
        "name",
        "lineno",
        "signal_count",
        "families",
        "capabilities",
        "producers",
    } <= set(test_signal_merge[0])
    assert architecture_explain["retrieval_producers"] == [
        {
            "producer_name": "query-channel-symbol",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "symbol",
            "declared_capabilities": ["symbol_lookup"],
            "known_capabilities": ["symbol_lookup"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-channel-semantic",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "semantic",
            "declared_capabilities": ["semantic_text"],
            "known_capabilities": ["semantic_text"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-channel-embedding",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "channel",
            "source_name": "embedding",
            "declared_capabilities": [
                "embedding_similarity",
                "diagnostics_metadata",
            ],
            "known_capabilities": [
                "embedding_similarity",
                "diagnostics_metadata",
            ],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-enrichment-call-graph",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "enrichment",
            "source_name": "call_graph",
            "declared_capabilities": ["graph_relations"],
            "known_capabilities": ["graph_relations"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-enrichment-references",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "enrichment",
            "source_name": "references",
            "declared_capabilities": ["graph_relations"],
            "known_capabilities": ["graph_relations"],
            "unknown_capabilities": [],
        },
        {
            "producer_name": "query-enrichment-include-graph",
            "producer_version": "1",
            "capability_version": "1",
            "source_kind": "enrichment",
            "source_name": "include_graph",
            "declared_capabilities": ["graph_relations"],
            "known_capabilities": ["graph_relations"],
            "unknown_capabilities": [],
        },
    ]
    architecture_signal_collection = architecture_explain["signal_collection"]
    architecture_signal_preview = architecture_explain["signals"]
    architecture_signal_merge = architecture_explain["signal_merge"]
    assert architecture_signal_collection["total_signals"] > 0
    assert set(architecture_signal_collection["families"]) <= {
        "lexical",
        "semantic",
        "task",
    }
    assert "symbol_lookup" in architecture_signal_collection["capabilities"]
    assert "semantic_text" in architecture_signal_collection["capabilities"]
    assert "query-channel-symbol" in architecture_signal_collection["used_producers"]
    assert "query-channel-semantic" in architecture_signal_collection["used_producers"]
    assert (
        "query-enrichment-call-graph"
        in architecture_signal_collection["ignored_producers"]
    )
    assert (
        "query-enrichment-references"
        in architecture_signal_collection["ignored_producers"]
    )
    assert (
        "query-enrichment-include-graph"
        in architecture_signal_collection["ignored_producers"]
    )
    assert architecture_signal_preview
    assert architecture_signal_merge
