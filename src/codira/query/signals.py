"""Typed retrieval signals for the capability-driven query pipeline.

Responsibilities
----------------
- Define the normalized signal objects that carry retrieval evidence without embedding final ranking policy.
- Preserve producer and capability attribution for explain-mode and future aggregation.
- Provide deterministic ordering helpers so signal collections remain reproducible.

Design principles
-----------------
Signals stay explicit, immutable, and score-free. They represent evidence, not final merge outcomes.

Architectural role
------------------
This module belongs to the **retrieval normalization layer** that sits between capability-aware producers and future core aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from codira.types import SymbolRow

RetrievalSignalKind = Literal[
    "exact_symbol",
    "text_match",
    "embedding_similarity",
    "relation",
    "proximity",
    "repeated_evidence",
]
RetrievalSignalFamily = Literal["lexical", "semantic", "task", "graph", "issue"]


@dataclass(frozen=True)
class RetrievalSignal:
    """
    Normalized retrieval evidence emitted before score aggregation.

    Parameters
    ----------
    kind : codira.query.signals.RetrievalSignalKind
        Stable signal category.
    family : codira.query.signals.RetrievalSignalFamily
        Higher-level evidence family used for future aggregation and explain
        grouping.
    target : codira.types.SymbolRow
        Symbol row supported by this signal.
    producer_name : str
        Stable retrieval producer identifier.
    producer_version : str
        Producer implementation version.
    capability_name : str
        Declared capability responsible for this signal.
    capability_version : str
        Capability-contract version understood by the producer.
    source_symbol : codira.types.SymbolRow | None, optional
        Optional source symbol that led to the target evidence.
    channel_name : str | None, optional
        Legacy channel attribution retained during migration.
    rank : int | None, optional
        Rank within one producer-local result list when applicable.
    strength : float | None, optional
        Raw evidence magnitude emitted by the producer.
    distance : int | None, optional
        Raw graph or proximity distance where relevant.
    """

    kind: RetrievalSignalKind
    family: RetrievalSignalFamily
    target: SymbolRow
    producer_name: str
    producer_version: str
    capability_name: str
    capability_version: str
    source_symbol: SymbolRow | None = None
    channel_name: str | None = None
    rank: int | None = None
    strength: float | None = None
    distance: int | None = None


def signal_sort_key(signal: RetrievalSignal) -> tuple[object, ...]:
    """
    Return a deterministic ordering key for one retrieval signal.

    Parameters
    ----------
    signal : codira.query.signals.RetrievalSignal
        Signal to order deterministically.

    Returns
    -------
    tuple[object, ...]
        Tuple suitable for stable sorting across mixed signal families.
    """
    return (
        signal.target,
        signal.kind,
        signal.family,
        signal.producer_name,
        signal.producer_version,
        signal.capability_name,
        signal.capability_version,
        signal.channel_name or "",
        signal.rank if signal.rank is not None else 10**9,
        signal.distance if signal.distance is not None else 10**9,
        -(signal.strength if signal.strength is not None else float("-inf")),
        signal.source_symbol or ("", "", "", "", -1),
    )
