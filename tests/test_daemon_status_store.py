"""Tests for repository-local durable daemon observability records.

Responsibilities
----------------
- Verify current daemon status snapshots round-trip atomically.
- Verify activity history records reconstructable status transitions.

Design principles
-----------------
The test uses deterministic timestamps and no operating-system service.

Architectural role
-----------------
This module belongs to the daemon observability verification layer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from codira.daemon import DaemonScheduler, DaemonState, DaemonStatus, DaemonStatusStore
from codira.storage import override_storage_root

if TYPE_CHECKING:
    from pathlib import Path


def test_status_store_round_trips_snapshot_and_activity(tmp_path: Path) -> None:
    """Persist one status snapshot and its activity record below ``.codira``.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts status and activity payloads are stable and complete.
    """
    timestamp = datetime(2026, 8, 6, tzinfo=UTC)
    store = DaemonStatusStore(tmp_path, clock=lambda: timestamp)
    expected = DaemonStatus(
        state=DaemonState.WATCHING,
        last_reconciled_commit="abc123",
        last_success_at=timestamp,
    )

    store.record(expected)

    assert store.read() == expected
    activity = json.loads(store.activity_path.read_text(encoding="utf-8"))
    assert activity == {
        "kind": "status_snapshot",
        "recorded_at": "2026-08-06T00:00:00+00:00",
        "schema_version": 1,
        "status": {
            "last_error": None,
            "last_failure_at": None,
            "last_reconciled_commit": "abc123",
            "last_success_at": "2026-08-06T00:00:00+00:00",
            "pending_reconciliation": False,
            "schema_version": 1,
            "state": "watching",
        },
    }


def test_status_store_returns_none_before_daemon_records_status(tmp_path: Path) -> None:
    """Report no status before this repository's daemon first starts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts absent daemon state is distinguishable from failure.
    """
    assert DaemonStatusStore(tmp_path).read() is None


def test_status_store_uses_the_effective_codira_storage_root(tmp_path: Path) -> None:
    """Write daemon records below an explicit CLI output directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary target repository root provided by pytest.

    Returns
    -------
    None
        The test asserts daemon records follow the shared storage override.
    """
    output_root = tmp_path / "output"
    with override_storage_root(tmp_path, output_root):
        store = DaemonStatusStore(tmp_path)
        store.record(DaemonStatus(state=DaemonState.STOPPED))

        assert store.status_path == output_root / ".codira" / "daemon-status.json"
        assert store.activity_path == output_root / ".codira" / "daemon-activity.jsonl"
        assert store.read() == DaemonStatus(state=DaemonState.STOPPED)


def test_scheduler_persists_transitions_through_status_observer(tmp_path: Path) -> None:
    """Append watching, indexing, and stopped scheduler snapshots in order.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts the durable activity record reconstructs daemon work.
    """
    timestamp = datetime(2026, 8, 6, tzinfo=UTC)
    store = DaemonStatusStore(tmp_path, clock=lambda: timestamp)
    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=lambda root: None,
        read_head=lambda root: "head",
        clock=lambda: timestamp,
        status_observer=store.record,
    )

    scheduler.start()
    scheduler.reconcile_pending()
    scheduler.stop()

    rows = [
        json.loads(line)
        for line in store.activity_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["status"]["state"] for row in rows] == [
        "watching",
        "indexing",
        "watching",
        "stopped",
    ]
    durable_status = store.read()
    assert durable_status is not None
    assert durable_status.state is DaemonState.STOPPED
