"""Runtime-neutral reconciliation scheduling for Codira's optional daemon.

Responsibilities
----------------
- Coalesce filesystem and Git-HEAD reconciliation requests.
- Invoke the shared public indexing coordinator serially.
- Publish deterministic lifecycle and reconciliation status.

Design principles
-----------------
The scheduler owns no watcher, thread, process, or service-manager state. It
turns notifications into bounded serial indexing work so all runtime adapters
share one reconciliation policy.

Architectural role
------------------
This module belongs to the daemon runtime layer and delegates index mutation
coordination to ``codira.indexer.index_repo``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from codira.daemon.models import DaemonState, DaemonStatus
from codira.git import read_head_commit
from codira.indexer import index_repo

Reconciler = Callable[[Path], object]
HeadReader = Callable[[Path], str | None]
Clock = Callable[[], datetime]
StatusObserver = Callable[[DaemonStatus], None]


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp.

    Parameters
    ----------
    None

    Returns
    -------
    datetime
        Current UTC timestamp for daemon status reporting.
    """
    return datetime.now(UTC)


class DaemonScheduler:
    """Coalesce daemon reconciliation requests into serial index operations.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose working-tree index is reconciled.
    reconcile : collections.abc.Callable[[pathlib.Path], object], optional
        Shared public index coordinator. The return value is intentionally not
        interpreted because daemon status is independent of report rendering.
    read_head : collections.abc.Callable[[pathlib.Path], str | None], optional
        Git ``HEAD`` reader used to detect branch transitions.
    clock : collections.abc.Callable[[], datetime.datetime], optional
        Time source used for observable status timestamps.

    Returns
    -------
    None

    Notes
    -----
    Callers invoke ``request_reconciliation()`` for filesystem events and
    ``observe_head()`` on their periodic loop. A successful reconciliation
    records the post-index Git ``HEAD``. If an event or a ``HEAD`` transition
    occurs during indexing, this scheduler runs exactly one subsequent pass
    before returning to ``WATCHING`` unless a further change arrives.
    """

    def __init__(
        self,
        root: Path,
        *,
        reconcile: Reconciler = index_repo,
        read_head: HeadReader = read_head_commit,
        clock: Clock = _utc_now,
        status_observer: StatusObserver | None = None,
    ) -> None:
        """Initialize a stopped scheduler for one repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root whose working-tree index is reconciled.
        reconcile : collections.abc.Callable[[pathlib.Path], object], optional
            Shared public index coordinator.
        read_head : collections.abc.Callable[[pathlib.Path], str | None], optional
            Git ``HEAD`` reader used to detect branch transitions.
        clock : collections.abc.Callable[[], datetime.datetime], optional
            Time source used for observable status timestamps.
        status_observer : collections.abc.Callable[[DaemonStatus], None] | None, optional
            Repository-local persistence callback invoked after every status transition.

        Returns
        -------
        None
            The scheduler begins stopped with no pending reconciliation.
        """
        self._root = root.resolve()
        self._reconcile = reconcile
        self._read_head = read_head
        self._clock = clock
        self._status_observer = status_observer
        self._status = DaemonStatus(state=DaemonState.STOPPED)
        self._is_reconciling = False

    def _set_status(self, status: DaemonStatus) -> DaemonStatus:
        """Replace and publish one immutable scheduler status snapshot.

        Parameters
        ----------
        status : codira.daemon.models.DaemonStatus
            New lifecycle and reconciliation state.

        Returns
        -------
        DaemonStatus
            The published immutable status snapshot.
        """
        self._status = status
        if self._status_observer is not None:
            self._status_observer(status)
        return status

    @property
    def status(self) -> DaemonStatus:
        """Return the current immutable daemon status snapshot.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Current scheduler state without exposing mutable internals.
        """
        return self._status

    def start(self) -> DaemonStatus:
        """Start scheduling and queue one initial reconciliation.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Observable watching state with initial work pending.

        Notes
        -----
        Repeated calls are idempotent so service adapters can safely confirm
        their desired foreground state.
        """
        if self._status.state is DaemonState.STOPPED:
            self._set_status(
                replace(
                    self._status,
                    state=DaemonState.WATCHING,
                    pending_reconciliation=True,
                    last_error=None,
                )
            )
        return self._status

    def stop(self) -> DaemonStatus:
        """Stop accepting work while preserving completed reconciliation data.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Stopped state with pending work discarded.
        """
        self._set_status(
            replace(
                self._status,
                state=DaemonState.STOPPED,
                pending_reconciliation=False,
            )
        )
        return self._status

    def request_reconciliation(self) -> DaemonStatus:
        """Coalesce one filesystem notification into pending index work.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Current status with work marked pending when the scheduler runs.
        """
        if self._status.state is not DaemonState.STOPPED:
            self._set_status(replace(self._status, pending_reconciliation=True))
        return self._status

    def observe_head(self) -> DaemonStatus:
        """Queue reconciliation when Git ``HEAD`` differs from the last success.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Current status, potentially with a branch-transition pass pending.
        """
        if self._status.state is DaemonState.STOPPED:
            return self._status
        current_head = self._read_head(self._root)
        last_head = self._status.last_reconciled_commit
        if (
            current_head is not None
            and last_head is not None
            and current_head != last_head
        ):
            self.request_reconciliation()
        return self._status

    def reconcile_pending(self) -> DaemonStatus:
        """Run pending work serially and follow up on changes seen during indexing.

        Parameters
        ----------
        None

        Returns
        -------
        DaemonStatus
            Watching status after successful reconciliation or failed status
            when the index coordinator raises an expected runtime error.

        Notes
        -----
        A reentrant call returns the current status. A notification delivered
        by the active reconciliation is retained for the outer loop.
        """
        if self._status.state is DaemonState.STOPPED or self._is_reconciling:
            return self._status
        self.observe_head()
        while self._status.pending_reconciliation:
            self._is_reconciling = True
            self._set_status(
                replace(
                    self._status,
                    state=DaemonState.INDEXING,
                    pending_reconciliation=False,
                )
            )
            head_before = self._read_head(self._root)
            try:
                self._reconcile(self._root)
            except (OSError, RuntimeError, ValueError) as error:
                self._set_status(
                    replace(
                        self._status,
                        state=DaemonState.FAILED,
                        pending_reconciliation=True,
                        last_failure_at=self._clock(),
                        last_error=str(error),
                    )
                )
                self._is_reconciling = False
                return self._status
            finally:
                if self._is_reconciling:
                    self._is_reconciling = False

            head_after = self._read_head(self._root)
            self._set_status(
                replace(
                    self._status,
                    state=DaemonState.WATCHING,
                    last_reconciled_commit=head_after,
                    last_success_at=self._clock(),
                    last_error=None,
                )
            )
            if head_before != head_after:
                self.request_reconciliation()
        return self._status
