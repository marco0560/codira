"""Tests for the daemon declaration contract.

These tests intentionally avoid watchers, subprocesses, and service-manager
integration; those behaviors belong to later implementation slices.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from codira.daemon import DaemonScheduler, DaemonState, DaemonStatus

if TYPE_CHECKING:
    from pathlib import Path


def test_daemon_status_defaults_to_no_pending_reconciliation() -> None:
    """Declare an idle status without runtime-owned timestamps.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the declaration has deterministic defaults.
    """

    status = DaemonStatus(state=DaemonState.WATCHING)

    assert status.state is DaemonState.WATCHING
    assert status.pending_reconciliation is False
    assert status.last_reconciled_commit is None
    assert status.last_success_at is None
    assert status.last_failure_at is None
    assert status.last_error is None


def test_scheduler_coalesces_events_received_during_reconciliation(
    tmp_path: Path,
) -> None:
    """Run one follow-up pass after an event arrives during indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts event coalescing preserves one serial follow-up run.
    """
    heads = ["first", "first", "first", "first", "first"]
    calls: list[Path] = []
    scheduler: DaemonScheduler

    def read_head(root: Path) -> str | None:
        """Return deterministic test Git state.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        str | None
            Next configured Git commit identity.
        """
        del root
        return heads.pop(0)

    def reconcile(root: Path) -> None:
        """Record reconciliation and queue one event from the first pass.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The first call queues one follow-up reconciliation.
        """
        calls.append(root)
        if len(calls) == 1:
            scheduler.request_reconciliation()

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=read_head,
        clock=lambda: datetime(2026, 8, 6, tzinfo=UTC),
    )

    assert scheduler.start().pending_reconciliation is True
    status = scheduler.reconcile_pending()

    assert calls == [tmp_path.resolve(), tmp_path.resolve()]
    assert status.state is DaemonState.WATCHING
    assert status.pending_reconciliation is False
    assert status.last_reconciled_commit == "first"
    assert status.last_success_at == datetime(2026, 8, 6, tzinfo=UTC)


def test_scheduler_reconciles_a_branch_change_observed_during_indexing(
    tmp_path: Path,
) -> None:
    """Queue a second pass when Git ``HEAD`` changes during a successful run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts the final status records the branch reconciled by the
        follow-up pass.
    """
    heads = ["before", "before", "after", "after", "after"]
    calls: list[Path] = []

    def read_head(root: Path) -> str | None:
        """Return a deterministic Git-HEAD transition.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        str | None
            Next configured Git commit identity.
        """
        del root
        return heads.pop(0)

    def reconcile(root: Path) -> None:
        """Record each index coordination call.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The call is recorded for follow-up assertions.
        """
        calls.append(root)

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=read_head,
    )

    scheduler.start()
    status = scheduler.reconcile_pending()

    assert calls == [tmp_path.resolve(), tmp_path.resolve()]
    assert status.state is DaemonState.WATCHING
    assert status.pending_reconciliation is False
    assert status.last_reconciled_commit == "after"


def test_scheduler_queues_a_checked_out_branch_without_file_events(
    tmp_path: Path,
) -> None:
    """Reconcile a later ``HEAD`` transition even when a watcher is silent.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts periodic Git observation schedules an incremental
        reconciliation after a branch checkout.
    """
    heads = ["main", "main", "main", "feature", "feature", "feature", "feature"]
    calls: list[Path] = []

    def read_head(root: Path) -> str | None:
        """Return deterministic branch identities for scheduler observation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        str | None
            Next configured Git commit identity.
        """
        del root
        return heads.pop(0)

    def reconcile(root: Path) -> None:
        """Record each incremental reconciliation request.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The call is recorded for follow-up assertions.
        """
        calls.append(root)

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=read_head,
    )

    scheduler.start()
    assert scheduler.reconcile_pending().last_reconciled_commit == "main"
    assert scheduler.observe_head().pending_reconciliation is True
    status = scheduler.reconcile_pending()

    assert calls == [tmp_path.resolve(), tmp_path.resolve()]
    assert status.state is DaemonState.WATCHING
    assert status.pending_reconciliation is False
    assert status.last_reconciled_commit == "feature"


def test_scheduler_marks_expected_index_failure_for_retry(tmp_path: Path) -> None:
    """Retain failed work until a later notification retries it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts failure remains observable without losing pending
        reconciliation work.
    """
    failure_time = datetime(2026, 8, 6, tzinfo=UTC)

    def reconcile(root: Path) -> None:
        """Raise the runtime error handled by the scheduler.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            Always raised to exercise daemon failure reporting.
        """
        del root
        message = "index backend unavailable"
        raise RuntimeError(message)

    def read_head(root: Path) -> str | None:
        """Return one deterministic Git commit identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        str | None
            Stable commit identity for the failed reconciliation.
        """
        del root
        return "head"

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=read_head,
        clock=lambda: failure_time,
    )

    scheduler.start()
    status = scheduler.reconcile_pending()

    assert status.state is DaemonState.FAILED
    assert status.pending_reconciliation is True
    assert status.last_failure_at == failure_time
    assert status.last_error == "index backend unavailable"


def test_scheduler_recovers_after_indexing_status_observer_failure(
    tmp_path: Path,
) -> None:
    """Keep pending work retryable when publishing the indexing state fails.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts the reentrancy guard resets and a repaired observer
        permits the retained reconciliation to run.
    """
    calls: list[Path] = []
    fail_indexing = True

    def reconcile(root: Path) -> None:
        """Record one reconciliation invocation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The invocation is recorded for retry assertions.
        """
        calls.append(root)

    def observe(status: DaemonStatus) -> None:
        """Fail only while publishing the initial indexing transition.

        Parameters
        ----------
        status : codira.daemon.models.DaemonStatus
            Newly published scheduler state.

        Returns
        -------
        None
            The status is accepted unless the deterministic fault is active.

        Raises
        ------
        OSError
            If the test fault is active for the indexing transition.
        """
        if fail_indexing and status.state is DaemonState.INDEXING:
            message = "status store unavailable"
            raise OSError(message)

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=lambda root: "main",
        status_observer=observe,
    )
    scheduler.start()

    failed = scheduler.reconcile_pending()

    assert failed.state is DaemonState.FAILED
    assert failed.pending_reconciliation is True
    assert calls == []

    fail_indexing = False
    recovered = scheduler.reconcile_pending()

    assert recovered.state is DaemonState.WATCHING
    assert recovered.pending_reconciliation is False
    assert calls == [tmp_path.resolve()]
