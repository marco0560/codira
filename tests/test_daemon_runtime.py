"""Tests for the foreground watchfiles daemon runtime.

Responsibilities
----------------
- Verify configured watcher filters include and exclude repository paths.
- Exercise finite watcher batches without starting OS notification backends.
- Confirm timeout yields preserve Git-HEAD reconciliation behavior.

Design principles
-----------------
Tests inject scheduler and watch iterator seams so foreground runtime behavior
remains deterministic and does not depend on host filesystem notifications.

Architectural role
------------------
This module belongs to the daemon runtime verification layer.
"""

from __future__ import annotations

import subprocess
from threading import Event
from typing import TYPE_CHECKING

from watchfiles import Change

from codira.config import DaemonConfig
from codira.daemon import (
    DaemonScheduler,
    DaemonState,
    build_watch_filter,
    run_foreground_daemon,
)
from codira.git import is_git_ignored

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import pytest


def test_build_watch_filter_applies_configured_scope_and_internal_exclusions(
    tmp_path: Path,
) -> None:
    """Accept configured source changes while excluding runtime-owned paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts include, exclude, Git, and Codira paths are filtered
        deterministically.
    """
    watch_filter = build_watch_filter(
        tmp_path,
        DaemonConfig(
            enabled=True,
            include_paths=("src",),
            exclude_paths=("src/generated",),
        ),
    )

    assert watch_filter(Change.modified, str(tmp_path / "src" / "main.py"))
    assert not watch_filter(
        Change.modified,
        str(tmp_path / "src" / "generated" / "schema.py"),
    )
    assert not watch_filter(Change.modified, str(tmp_path / "tests" / "test_main.py"))
    assert not watch_filter(Change.modified, str(tmp_path / ".codira" / "index.db"))
    assert not watch_filter(Change.modified, str(tmp_path / ".git" / "HEAD"))


def test_run_foreground_daemon_drives_debounced_batches_and_head_checks(
    tmp_path: Path,
) -> None:
    """Run initial and event-driven reconciliation through a finite watcher.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts runtime arguments, serial indexing, and final stopped
        status without invoking a real OS watcher.
    """
    calls: list[Path] = []
    watch_arguments: dict[str, object] = {}

    def reconcile(root: Path) -> None:
        """Record one reconciliation request.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The call is recorded for runtime assertions.
        """
        calls.append(root)

    def read_head(root: Path) -> str | None:
        """Return stable Git state for the finite watcher.

        Parameters
        ----------
        root : pathlib.Path
            Repository root ignored by this deterministic fixture.

        Returns
        -------
        str | None
            Stable Git commit identity.
        """
        del root
        return "head"

    def watch_changes(
        *paths: Path,
        **kwargs: object,
    ) -> Iterator[set[tuple[Change, str]]]:
        """Yield one event batch and one timeout batch.

        Parameters
        ----------
        *paths : pathlib.Path
            Repository roots supplied by the foreground runtime.
        **kwargs : object
            watchfiles-compatible controls supplied by the foreground runtime.

        Returns
        -------
        collections.abc.Iterator[set[tuple[watchfiles.Change, str]]]
            Finite event and timeout batches.
        """
        watch_arguments["paths"] = paths
        watch_arguments.update(kwargs)
        yield {(Change.modified, str(tmp_path / "src" / "main.py"))}
        yield set()

    config = DaemonConfig(enabled=True, debounce_ms=375, include_paths=("src",))
    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=read_head,
    )
    stop_event = Event()

    status = run_foreground_daemon(
        tmp_path,
        config,
        scheduler=scheduler,
        watch_changes=watch_changes,
        stop_event=stop_event,
    )

    assert calls == [tmp_path.resolve(), tmp_path.resolve()]
    assert watch_arguments["paths"] == (tmp_path.resolve(),)
    assert watch_arguments["debounce"] == 375
    assert watch_arguments["rust_timeout"] == 1_000
    assert watch_arguments["yield_on_timeout"] is True
    assert watch_arguments["stop_event"] is stop_event
    assert status.state is DaemonState.STOPPED
    assert status.last_reconciled_commit == "head"


def test_run_foreground_daemon_discards_git_ignored_change_batches(
    tmp_path: Path,
) -> None:
    """Avoid an index run when each watch event is ignored by Git.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts Git-ignore filtering runs after watcher batching and
        preserves the initial reconciliation only.
    """
    calls: list[Path] = []

    def reconcile(root: Path) -> None:
        """Record each scheduler reconciliation.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the scheduler.

        Returns
        -------
        None
            The call is recorded for assertions.
        """
        calls.append(root)

    def watch_changes(
        *paths: Path,
        **kwargs: object,
    ) -> Iterator[set[tuple[Change, str]]]:
        """Yield one Git-ignored filesystem event batch.

        Parameters
        ----------
        *paths : pathlib.Path
            Repository roots ignored by this deterministic fixture.
        **kwargs : object
            watchfiles controls ignored by this deterministic fixture.

        Returns
        -------
        collections.abc.Iterator[set[tuple[watchfiles.Change, str]]]
            One ignored change batch.
        """
        del paths, kwargs
        yield {(Change.modified, str(tmp_path / "generated" / "result.py"))}

    def is_ignored(root: Path, path: Path) -> bool:
        """Classify the deterministic generated path as Git-ignored.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the foreground runtime.
        path : pathlib.Path
            Changed path supplied by the watcher batch.

        Returns
        -------
        bool
            ``True`` only for the configured generated result path.
        """
        return path == root / "generated" / "result.py"

    scheduler = DaemonScheduler(
        tmp_path,
        reconcile=reconcile,
        read_head=lambda root: "head",
    )

    run_foreground_daemon(
        tmp_path,
        DaemonConfig(enabled=True),
        scheduler=scheduler,
        watch_changes=watch_changes,
        is_ignored=is_ignored,
    )

    assert calls == [tmp_path.resolve()]


def test_is_git_ignored_checks_repository_ignore_rules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evaluate one path through Git's ignore matcher without shell execution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to record the Git subprocess request.

    Returns
    -------
    None
        The test asserts the daemon uses no-index Git ignore evaluation for a
        repository-relative candidate path.
    """
    commands: list[list[str]] = []

    def run_git(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Record the expected Git check-ignore invocation.

        Parameters
        ----------
        arguments : list[str]
            Git command arguments supplied by the ignore helper.
        **kwargs : object
            subprocess controls supplied by the ignore helper.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Successful ignored-path completed-process fixture.
        """
        del kwargs
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("codira.git.subprocess.run", run_git)

    assert is_git_ignored(tmp_path, tmp_path / "generated" / "result.py")
    assert commands[0][1:5] == ["check-ignore", "--quiet", "--no-index", "--"]
    assert commands[0][-1] == "generated/result.py"
