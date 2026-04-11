"""Regression tests for the Phase 3 retrieval signal model.

Responsibilities
----------------
- Validate the normalized signal schema introduced for capability-driven retrieval.
- Keep deterministic signal ordering explicit before aggregation migrates to the new substrate.
- Ensure producer and capability attribution survive as first-class signal fields.

Design principles
-----------------
Tests stay small and structural so later adapter and aggregation phases can evolve against a stable contract.

Architectural role
------------------
This module belongs to the **retrieval normalization verification layer** that protects the signal schema before it is wired into ranking.
"""

from __future__ import annotations

from codira.query.producers import CALL_GRAPH_RETRIEVAL_PRODUCER
from codira.query.signals import RetrievalSignal, signal_sort_key


def _symbol(
    symbol_type: str,
    module_name: str,
    name: str,
    file_path: str,
    lineno: int,
) -> tuple[str, str, str, str, int]:
    """
    Create one compact symbol row for signal tests.

    Parameters
    ----------
    symbol_type : str
        Symbol kind stored in the row.
    module_name : str
        Dotted module name owning the symbol.
    name : str
        Symbol name.
    file_path : str
        Repository-relative source path for the symbol.
    lineno : int
        Defining line number for the symbol.

    Returns
    -------
    tuple[str, str, str, str, int]
        Compact symbol row used by retrieval-signal fixtures.
    """
    return (symbol_type, module_name, name, file_path, lineno)


def test_signal_sort_key_orders_by_target_then_rank_then_strength() -> None:
    """
    Keep mixed signals reproducibly ordered before score aggregation exists.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts deterministic ordering across rank and strength
        variations for the same target symbol.
    """
    target = _symbol("function", "pkg.alpha", "run", "src/a.py", 10)
    signals = [
        RetrievalSignal(
            kind="text_match",
            family="semantic",
            target=target,
            producer_name="query-channel-semantic",
            producer_version="1",
            capability_name="semantic_text",
            capability_version="1",
            channel_name="semantic",
            rank=2,
            strength=3.0,
        ),
        RetrievalSignal(
            kind="text_match",
            family="semantic",
            target=target,
            producer_name="query-channel-semantic",
            producer_version="1",
            capability_name="semantic_text",
            capability_version="1",
            channel_name="semantic",
            rank=1,
            strength=2.0,
        ),
        RetrievalSignal(
            kind="text_match",
            family="semantic",
            target=target,
            producer_name="query-channel-semantic",
            producer_version="1",
            capability_name="semantic_text",
            capability_version="1",
            channel_name="semantic",
            rank=2,
            strength=4.0,
        ),
    ]

    ordered = sorted(signals, key=signal_sort_key)

    assert ordered == [signals[1], signals[2], signals[0]]


def test_signal_preserves_versioned_producer_and_capability_attribution() -> None:
    """
    Keep producer identity first-class on normalized retrieval evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts versioned producer and capability metadata survive on
        the signal object without requiring final-score fields.
    """
    source = _symbol("function", "pkg.beta", "caller", "src/b.py", 20)
    target = _symbol("function", "pkg.alpha", "callee", "src/a.py", 10)
    signal = RetrievalSignal(
        kind="relation",
        family="graph",
        target=target,
        producer_name="query-enrichment-references",
        producer_version="1",
        capability_name="graph_relations",
        capability_version="1",
        source_symbol=source,
        distance=1,
    )

    assert signal.producer_name == "query-enrichment-references"
    assert signal.producer_version == "1"
    assert signal.capability_name == "graph_relations"
    assert signal.capability_version == "1"
    assert signal.source_symbol == source
    assert not hasattr(signal, "merge_score")


def test_graph_retrieval_producer_builds_normalized_relation_signal() -> None:
    """
    Keep graph signal construction routed through the native producer surface.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the call-graph producer emits the normalized graph
        signal shape used by explain-mode enrichment.
    """
    source = _symbol("function", "pkg.beta", "caller", "src/b.py", 20)
    target = _symbol("function", "pkg.alpha", "callee", "src/a.py", 10)

    signal = CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
        kind="relation",
        target=target,
        source_symbol=source,
        distance=1,
    )

    assert signal == RetrievalSignal(
        kind="relation",
        family="graph",
        target=target,
        producer_name="query-enrichment-call-graph",
        producer_version="1",
        capability_name="graph_relations",
        capability_version="1",
        source_symbol=source,
        distance=1,
    )
