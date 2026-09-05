"""Tests for durable-vector to derived-similarity lifecycle coordination."""

from __future__ import annotations

import json
import struct
from argparse import Namespace
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from codira.cli import _run_embedding_reset_command
from codira.config import ConfigError
from codira.contracts import (
    EmbeddingEngineSpec,
    SimilarityIndexSpec,
    StoredVectorRow,
    VectorSetIdentity,
    VectorSnapshot,
    VectorSnapshotMetadata,
    VectorSnapshotRequest,
    VectorStoreSpec,
)
from codira.similarity_lifecycle import rebuild_active_similarity_index
from codira.storage import get_codira_dir

if TYPE_CHECKING:
    from pathlib import Path


def _snapshot(object_type: str, revision: int) -> VectorSnapshot:
    """Return one minimal durable snapshot for lifecycle tests.

    Parameters
    ----------
    object_type : str
        Owner kind whose derived artifact is being rebuilt.
    revision : int
        Durable vector-set revision.

    Returns
    -------
    codira.contracts.VectorSnapshot
        One deterministic vector snapshot.
    """

    identity = VectorSetIdentity(
        engine=EmbeddingEngineSpec("test", "1", "test", "1", 2),
        vector_store=VectorStoreSpec("test", "1", "1"),
    )
    return VectorSnapshot(
        VectorSnapshotMetadata(identity, revision, object_type, 1),
        (
            StoredVectorRow(
                object_type,
                f"{object_type}-row",
                "source",
                2,
                struct.pack("<2f", 1.0, 0.0),
            ),
        ),
    )


@dataclass
class _FakeStore:
    """Record vector snapshot reads issued by the lifecycle coordinator."""

    snapshots: dict[str, list[VectorSnapshot]]
    calls: list[str] = field(default_factory=list)

    def vector_snapshot(self, request: VectorSnapshotRequest) -> VectorSnapshot:
        """Return the next planned snapshot for one owner type.

        Parameters
        ----------
        request : codira.contracts.VectorSnapshotRequest
            Vector snapshot request for one owner type.

        Returns
        -------
        codira.contracts.VectorSnapshot
            Planned durable snapshot.
        """

        object_type = request.object_type
        self.calls.append(object_type)
        return self.snapshots[object_type].pop(0)


@dataclass
class _FakeIndex:
    """Record lifecycle calls without owning persistence."""

    name: str = "fake"
    initialized: list[tuple[Path, dict[str, object]]] = field(default_factory=list)
    rebuilt: list[VectorSnapshot] = field(default_factory=list)

    def initialize(self, root: Path, config: dict[str, object]) -> None:
        """Record validated initialization input.

        Parameters
        ----------
        root : pathlib.Path
            Repository root passed to the selected plugin.
        config : dict[str, object]
            Validated plugin-scoped configuration.

        Returns
        -------
        None
            The initialization call is recorded.
        """

        self.initialized.append((root, config))

    def spec(self, config: dict[str, object]) -> SimilarityIndexSpec:
        """Return a stable fake derived-index identity.

        Parameters
        ----------
        config : dict[str, object]
            Plugin configuration ignored by this deterministic fake.

        Returns
        -------
        codira.contracts.SimilarityIndexSpec
            Constant identity used by the coordinator test.
        """

        del config
        return SimilarityIndexSpec("fake", "1", "1", "test-build")

    def rebuild(self, snapshot: VectorSnapshot, identity: object) -> None:
        """Record one rebuild request.

        Parameters
        ----------
        snapshot : codira.contracts.VectorSnapshot
            Durable snapshot presented to the fake index.
        identity : object
            Derived-index identity not inspected by this fake.

        Returns
        -------
        None
            The rebuild call is recorded.
        """

        del identity
        self.rebuilt.append(snapshot)


@dataclass(frozen=True)
class _FakeContext:
    """Minimal active vector-store context used by the coordinator."""

    store: _FakeStore
    identity: VectorSetIdentity
    config: object


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    store: _FakeStore,
    index: _FakeIndex,
) -> None:
    """Replace active plugin selection with deterministic lifecycle fakes."""

    identity = _snapshot("symbol", 1).metadata.identity
    context = _FakeContext(store, identity, object())
    monkeypatch.setattr(
        "codira.similarity_lifecycle.active_vector_store_context",
        lambda root: context,
    )
    monkeypatch.setattr(
        "codira.similarity_lifecycle.active_similarity_index",
        lambda *, root: index,
    )
    monkeypatch.setattr(
        "codira.similarity_lifecycle.active_similarity_index_config",
        lambda *, root: {},
    )


def test_rebuilds_symbol_and_documentation_from_verified_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Build both object-type artifacts and record their durable revisions.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture that replaces active plugin selection with deterministic fakes.
    tmp_path : pathlib.Path
        Temporary repository root passed to the lifecycle coordinator.

    Returns
    -------
    None
        The test asserts both owner types are built and rechecked.
    """

    symbol = _snapshot("symbol", 4)
    documentation = _snapshot("documentation", 7)
    store = _FakeStore(
        {"symbol": [symbol, symbol], "documentation": [documentation, documentation]}
    )
    index = _FakeIndex()
    _install_fakes(monkeypatch, store, index)

    result = rebuild_active_similarity_index(tmp_path)

    assert result.index == "fake"
    assert result.source_revisions == {"symbol": 4, "documentation": 7}
    assert [snapshot.metadata.object_type for snapshot in index.rebuilt] == [
        "symbol",
        "documentation",
    ]
    assert store.calls == ["symbol", "symbol", "documentation", "documentation"]


def test_rejects_source_revision_changed_during_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed rather than reporting a stale derived artifact as current.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture that replaces active plugin selection with deterministic fakes.
    tmp_path : pathlib.Path
        Temporary repository root passed to the lifecycle coordinator.

    Returns
    -------
    None
        The test asserts a changing durable revision prevents publication.
    """

    symbol = _snapshot("symbol", 4)
    store = _FakeStore(
        {
            "symbol": [symbol, _snapshot("symbol", 5)],
            "documentation": [_snapshot("documentation", 7)] * 2,
        }
    )
    index = _FakeIndex()
    _install_fakes(monkeypatch, store, index)

    with pytest.raises(ValueError, match="codira emb rebuild"):
        rebuild_active_similarity_index(tmp_path)
    assert [snapshot.metadata.object_type for snapshot in index.rebuilt] == ["symbol"]


def test_reset_recovers_when_selected_similarity_plugin_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep explicit reset usable when the selected plugin cannot load.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture that makes configured similarity-index discovery fail.
    tmp_path : pathlib.Path
        Temporary root containing removable derived semantic state.

    Returns
    -------
    None
        The test asserts reset removes derived state without a fallback index.
    """

    derived = get_codira_dir(tmp_path) / "similarity-indexes"
    derived.mkdir(parents=True)
    (derived / "sentinel").write_text("derived", encoding="utf-8")
    monkeypatch.setattr(
        "codira.cli.active_similarity_index",
        lambda *, root: (_ for _ in ()).throw(ValueError("plugin unavailable")),
    )
    args = Namespace(
        yes=True,
        stale=False,
        all_sets=False,
        dry_run=False,
        backend=None,
        older_than=None,
        keep=None,
        json=True,
    )

    assert _run_embedding_reset_command(args, tmp_path) == 0
    assert not derived.exists()


def test_reset_requires_orphan_acknowledgement_after_qdrant_index_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retain Qdrant ownership evidence after switching to the exact index.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to capture reset JSON output and forbid wrong-plugin purge.
    tmp_path : pathlib.Path
        Temporary root containing prior Qdrant ownership evidence.

    Returns
    -------
    None
        The test asserts reset fails closed without acknowledgement and reports
        opaque Qdrant artifact hashes when orphaning is explicitly accepted.
    """
    ledger = (
        get_codira_dir(tmp_path) / "similarity-indexes" / "qdrant" / "ownership.json"
    )
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        json.dumps(
            {
                "records": [
                    {"retained_collections": [{"artifact_hash": "opaque-qdrant"}]}
                ]
            }
        ),
        encoding="utf-8",
    )
    args = Namespace(
        yes=True,
        stale=False,
        all_sets=False,
        dry_run=False,
        backend=None,
        older_than=None,
        keep=None,
        json=True,
        allow_remote_orphans=False,
    )
    monkeypatch.setattr(
        "codira.cli.purge_active_similarity_index",
        lambda root, *, preview: (_ for _ in ()).throw(
            AssertionError("Qdrant purge must not use the exact index")
        ),
    )

    with pytest.raises(ConfigError, match="Qdrant ownership remains"):
        _run_embedding_reset_command(args, tmp_path)
    assert ledger.exists()

    emitted: list[dict[str, object]] = []
    monkeypatch.setattr("codira.cli._emit_json", emitted.append)
    args.allow_remote_orphans = True

    assert _run_embedding_reset_command(args, tmp_path) == 0
    assert emitted[0]["remote_orphan_artifact_hashes"] == ("opaque-qdrant",)
