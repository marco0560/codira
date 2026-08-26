"""Core exact similarity index backed by authoritative vector snapshots.

Responsibilities
----------------
- Provide the always-available exact similarity-index implementation.
- Score every row in one durable snapshot deterministically.
- Cache immutable decoded vectors by repository, index identity, and revision.

Architectural role
------------------
This module belongs to the derived similarity-index layer. It never persists or
mutates authoritative vector-store state.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from codira.contracts import (
    SimilarityCandidate,
    SimilarityIndexIdentity,
    SimilarityIndexIncompatibleError,
    SimilarityIndexSpec,
    SimilarityIndexUnsafeOwnershipError,
    SimilarityPurgeRequest,
    SimilarityPurgeResult,
    SimilarityQueryProvenance,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import VectorSnapshot

EXACT_INDEX_FORMAT_VERSION = "1"
EXACT_INDEX_VERSION = "1"


def _decode_vector(payload: bytes, dimension: int) -> tuple[float, ...]:
    """Decode one little-endian float32 vector with exact dimension checks.

    Parameters
    ----------
    payload : bytes
        Serialized float32 payload.
    dimension : int
        Expected vector dimension.

    Returns
    -------
    tuple[float, ...]
        Decoded vector values.

    Raises
    ------
    ValueError
        If payload length does not match the authoritative dimension.
    """

    expected = dimension * 4
    if dimension <= 0 or len(payload) != expected:
        raise SimilarityIndexIncompatibleError(
            "Stored vector payload does not match its declared dimension."
        )
    return struct.unpack(f"<{dimension}f", payload)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Return cosine similarity with deterministic zero-vector handling.

    Parameters
    ----------
    left : tuple[float, ...]
        Candidate vector.
    right : tuple[float, ...]
        Query vector.

    Returns
    -------
    float
        Cosine similarity, or ``0.0`` for a zero-norm vector.
    """

    if len(left) != len(right):
        raise SimilarityIndexIncompatibleError(
            "Query vector dimension does not match the stored vector."
        )
    numerator = sum(first * second for first, second in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


@dataclass
class ExactSimilarityIndex:
    """Always-available exhaustive cosine similarity implementation."""

    name: str = "exact"
    version: str = EXACT_INDEX_VERSION
    _cache: dict[
        tuple[str, str, int, str], tuple[tuple[str, tuple[float, ...]], ...]
    ] = field(default_factory=dict)

    def spec(self, config: Mapping[str, object]) -> SimilarityIndexSpec:
        """Return the configuration-independent exact-index identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Exact index configuration, which has no build-time settings.

        Returns
        -------
        SimilarityIndexSpec
            Stable exact implementation specification.
        """

        del config
        return SimilarityIndexSpec(
            index=self.name,
            index_version=self.version,
            format_version=EXACT_INDEX_FORMAT_VERSION,
            build_fingerprint="exact-cosine-v1",
        )

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """Validate the exact index has no unsupported configuration.

        Parameters
        ----------
        root : pathlib.Path
            Repository root selecting this index.
        config : collections.abc.Mapping[str, object]
            Exact index configuration.

        Returns
        -------
        None
            The in-memory implementation requires no persisted initialization.

        Raises
        ------
        ValueError
            If configuration supplies unsupported keys other than ``enabled``.
        """

        del root
        unsupported = sorted(set(config) - {"enabled"})
        if unsupported:
            raise ValueError(
                "Core exact similarity index does not accept configuration keys: "
                + ", ".join(unsupported)
            )

    def rebuild(
        self, snapshot: VectorSnapshot, identity: SimilarityIndexIdentity
    ) -> None:
        """Populate the revision-keyed decoded-vector cache from a snapshot.

        Parameters
        ----------
        snapshot : VectorSnapshot
            Authoritative rows and source revision.
        identity : SimilarityIndexIdentity
            Selected root-bound index identity.

        Returns
        -------
        None
            The immutable runtime cache is replaced for this exact revision.
        """

        self._cache[self._cache_key(identity, snapshot)] = self._decode_snapshot(
            snapshot
        )

    def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        """Exhaustively score a snapshot with stable score/tie ordering.

        Parameters
        ----------
        request : SimilaritySearchRequest
            Identity, snapshot, query vector, profile, and threshold.

        Returns
        -------
        SimilaritySearchResult
            Candidate-limited cosine scores with deterministic core provenance.
        """

        key = self._cache_key(request.identity, request.snapshot)
        rows = self._cache.get(key)
        if rows is None:
            rows = self._decode_snapshot(request.snapshot)
            self._cache[key] = rows
        query = tuple(float(value) for value in request.query_vector)
        candidates = [
            SimilarityCandidate(stable_id=stable_id, score=_cosine(vector, query))
            for stable_id, vector in rows
        ]
        return SimilaritySearchResult(
            query=SimilarityQueryProvenance(
                plugin_name=self.name,
                plugin_version=self.version,
                object_type=request.snapshot.metadata.object_type,
                source_revision=request.snapshot.metadata.revision,
                profile_name=request.profile.name,
                candidate_limit=request.profile.candidate_limit,
            ),
            candidates=tuple(
                candidate
                for candidate in sorted(
                    candidates,
                    key=lambda item: (-item.score, item.stable_id),
                )
                if candidate.score >= request.min_score
            )[: request.profile.candidate_limit],
        )

    def purge(self, request: SimilarityPurgeRequest) -> SimilarityPurgeResult:
        """Remove cached rows for one root-bound derived identity.

        Parameters
        ----------
        request : SimilarityPurgeRequest
            Explicit preview or confirmed cache cleanup request.

        Returns
        -------
        SimilarityPurgeResult
            Empty artifact inventory because exact has no persisted artifacts.

        Raises
        ------
        SimilarityIndexUnsafeOwnershipError
            If the requested cleanup root differs from the index identity root.
        """

        root_key = str(request.root.resolve())
        if root_key != str(request.identity.root.resolve()):
            raise SimilarityIndexUnsafeOwnershipError(
                "Exact purge root does not match its index identity."
            )
        index_key = self._identity_key(request.identity)
        if not request.preview:
            for key in [key for key in self._cache if key[:2] == (root_key, index_key)]:
                del self._cache[key]
        return SimilarityPurgeResult(index=self.name, preview=request.preview)

    def reset_runtime_caches(self) -> None:
        """Discard every decoded-vector runtime cache entry.

        Parameters
        ----------
        None

        Returns
        -------
        None
            No authoritative or persisted state is changed.
        """

        self._cache.clear()

    def _cache_key(
        self,
        identity: SimilarityIndexIdentity,
        snapshot: VectorSnapshot,
    ) -> tuple[str, str, int, str]:
        """Return a cache key including root, build identity, revision, and type.

        Parameters
        ----------
        identity : SimilarityIndexIdentity
            Selected derived index.
        snapshot : VectorSnapshot
            Authoritative source metadata.

        Returns
        -------
        tuple[str, str, int, str]
            Immutable cache key.
        """

        return (
            str(identity.root.resolve()),
            self._identity_key(identity),
            snapshot.metadata.revision,
            snapshot.metadata.object_type,
        )

    def _identity_key(self, identity: SimilarityIndexIdentity) -> str:
        """Serialize the non-root identity parts into one deterministic cache key.

        Parameters
        ----------
        identity : SimilarityIndexIdentity
            Derived index identity.

        Returns
        -------
        str
            Deterministic identity key.
        """

        engine = identity.vector_set.engine
        store = identity.vector_set.vector_store
        index = identity.index
        return ":".join(
            (
                engine.engine,
                engine.engine_version,
                engine.model,
                engine.model_version,
                str(engine.dimension),
                engine.precision,
                store.store,
                store.store_version,
                store.format_version,
                index.index,
                index.index_version,
                index.format_version,
                index.build_fingerprint,
            )
        )

    def _decode_snapshot(
        self,
        snapshot: VectorSnapshot,
    ) -> tuple[tuple[str, tuple[float, ...]], ...]:
        """Decode snapshot rows while enforcing their deterministic order.

        Parameters
        ----------
        snapshot : VectorSnapshot
            Authoritative source rows.

        Returns
        -------
        tuple[tuple[str, tuple[float, ...]], ...]
            Stable-ID keyed decoded vectors.

        Raises
        ------
        ValueError
            If row metadata or order is inconsistent with the snapshot.
        """

        if snapshot.metadata.row_count != len(snapshot.rows):
            raise SimilarityIndexIncompatibleError(
                "Vector snapshot row count does not match its metadata."
            )
        ordered = tuple(
            sorted(snapshot.rows, key=lambda row: (row.object_type, row.stable_id))
        )
        if ordered != snapshot.rows:
            raise SimilarityIndexIncompatibleError(
                "Vector snapshot rows must be ordered by object type and stable ID."
            )
        if any(
            row.object_type != snapshot.metadata.object_type for row in snapshot.rows
        ):
            raise SimilarityIndexIncompatibleError(
                "Vector snapshot rows do not match the requested object type."
            )
        return tuple(
            (row.stable_id, _decode_vector(row.vector, row.dimension))
            for row in snapshot.rows
        )


def build_similarity_index() -> ExactSimilarityIndex:
    """Build the core exact similarity-index plugin.

    Parameters
    ----------
    None

    Returns
    -------
    ExactSimilarityIndex
        Fresh exact index implementation.
    """

    return ExactSimilarityIndex()
