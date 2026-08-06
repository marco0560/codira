"""Foreground watchfiles runtime for Codira's optional daemon.

Responsibilities
----------------
- Translate configured watch scope into a watchfiles filter.
- Drive the runtime-neutral scheduler from foreground filesystem events.
- Observe Git ``HEAD`` periodically when filesystem notifications are absent.

Design principles
-----------------
The foreground runtime owns notification delivery only. It delegates all
indexing, mutation coordination, and branch reconciliation policy to the
daemon scheduler.

Architectural role
------------------
This module belongs to the daemon runtime layer and adapts ``watchfiles`` to
the core scheduler without exposing watcher details to service adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import Change, watch

from codira.daemon.scheduler import DaemonScheduler
from codira.daemon.status_store import DaemonStatusStore
from codira.git import is_git_ignored
from codira.repository_scope import is_repository_scope_excluded

if TYPE_CHECKING:
    from threading import Event

    from codira.config import DaemonConfig
    from codira.daemon.models import DaemonStatus

WatchChanges = Callable[..., Iterator[set[tuple[Change, str]]]]
WatchFilter = Callable[[Change, str], bool]
IgnorePath = Callable[[Path, Path], bool]
_HEAD_POLL_TIMEOUT_MS = 1_000


def _matches_path_prefix(path: Path, prefixes: tuple[str, ...]) -> bool:
    """Return whether a repository-relative path belongs to configured scope.

    Parameters
    ----------
    path : pathlib.Path
        Repository-relative candidate path.
    prefixes : tuple[str, ...]
        Repository-relative path prefixes to test.

    Returns
    -------
    bool
        ``True`` when one prefix is the path itself or one of its parents.
    """
    return any(
        Path(prefix) == path or Path(prefix) in path.parents for prefix in prefixes
    )


def build_watch_filter(root: Path, config: DaemonConfig) -> WatchFilter:
    """Build a deterministic watchfiles filter from daemon configuration.

    Parameters
    ----------
    root : pathlib.Path
        Repository root watched by the foreground runtime.
    config : codira.config.DaemonConfig
        Effective daemon watch scope controls.

    Returns
    -------
    collections.abc.Callable[[watchfiles.Change, str], bool]
        Predicate accepting source changes inside the configured scope.

    Notes
    -----
    Codira's own state and Git metadata are always excluded. Git-ignore rules
    are evaluated once per yielded change batch before scheduling work. Git
    ``HEAD`` is observed separately on timeout yields so a checkout still
    reconciles even when the filesystem watcher emits no usable source event.
    """
    resolved_root = root.resolve()

    def accept_change(change: Change, path: str) -> bool:
        """Accept one watchfiles event when it belongs to daemon scope.

        Parameters
        ----------
        change : watchfiles.Change
            Filesystem change kind supplied by watchfiles.
        path : str
            Changed absolute or repository-relative filesystem path.

        Returns
        -------
        bool
            ``True`` when the scheduler should reconcile the repository.
        """
        del change
        candidate = Path(path).resolve()
        try:
            relative_path = candidate.relative_to(resolved_root)
        except ValueError:
            return False
        if is_repository_scope_excluded(candidate, resolved_root):
            return False
        if config.include_paths and not _matches_path_prefix(
            relative_path,
            config.include_paths,
        ):
            return False
        return not _matches_path_prefix(relative_path, config.exclude_paths)

    return accept_change


def run_foreground_daemon(  # noqa: PLR0913
    root: Path,
    config: DaemonConfig,
    *,
    scheduler: DaemonScheduler | None = None,
    watch_changes: WatchChanges = watch,
    is_ignored: IgnorePath = is_git_ignored,
    stop_event: Event | None = None,
    status_store: DaemonStatusStore | None = None,
) -> DaemonStatus:
    """Run foreground automatic indexing until watchfiles stops or interrupts.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose working-tree index should be reconciled.
    config : codira.config.DaemonConfig
        Effective daemon settings including debounce and watch scope.
    scheduler : codira.daemon.scheduler.DaemonScheduler | None, optional
        Scheduler override used by deterministic tests. ``None`` creates the
        standard scheduler backed by ``index_repo()``.
    watch_changes : collections.abc.Callable, optional
        watchfiles-compatible iterator factory used to receive change batches.
    is_ignored : collections.abc.Callable[[pathlib.Path, pathlib.Path], bool], optional
        Git-ignore predicate used to discard batches that affect only ignored
        paths. The default checks active repository Git ignore rules.
    stop_event : threading.Event | None, optional
        Event that stops watchfiles after the active reconciliation completes.
        ``None`` leaves foreground mode under terminal interrupt control.
    status_store : codira.daemon.status_store.DaemonStatusStore | None, optional
        Durable repository-local status sink. ``None`` creates the standard
        ``.codira`` status and activity store when this runtime creates its scheduler.

    Returns
    -------
    DaemonStatus
        Final stopped scheduler status after the foreground loop exits.

    Notes
    -----
    Every timeout yield observes Git ``HEAD``. This covers branch checkouts
    whose source changes are hash-identical or otherwise absent from watcher
    notifications.
    """
    active_store = status_store or DaemonStatusStore(root)
    active_scheduler = scheduler or DaemonScheduler(
        root,
        status_observer=active_store.record,
    )
    active_scheduler.start()
    try:
        active_scheduler.reconcile_pending()
        for changes in watch_changes(
            root.resolve(),
            watch_filter=build_watch_filter(root, config),
            debounce=config.debounce_ms,
            rust_timeout=_HEAD_POLL_TIMEOUT_MS,
            yield_on_timeout=True,
            stop_event=stop_event,
        ):
            if changes and any(
                not is_ignored(root, Path(path)) for _change, path in changes
            ):
                active_scheduler.request_reconciliation()
            active_scheduler.observe_head()
            active_scheduler.reconcile_pending()
    finally:
        active_scheduler.stop()
    return active_scheduler.status
