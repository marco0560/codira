"""Tests for the repository-local warm query-daemon contract declarations."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from codira.cli import main
from codira.query_daemon import (
    QueryDaemonAlreadyRunningError,
    QueryDaemonIdentity,
    QueryDaemonInstanceRegistry,
    QueryDaemonState,
    QueryDaemonStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_query_daemon_identity_isolates_repository_and_output_roots(
    tmp_path: Path,
) -> None:
    """Keep service identities isolated by both canonical runtime paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to create distinct repository and output paths.

    Returns
    -------
    None
        The test asserts no two repository/output combinations share identity.
    """
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_output = tmp_path / "first-output"
    second_output = tmp_path / "second-output"

    first = QueryDaemonIdentity.from_paths(first_root, first_output)

    assert (
        first.value != QueryDaemonIdentity.from_paths(second_root, first_output).value
    )
    assert (
        first.value != QueryDaemonIdentity.from_paths(first_root, second_output).value
    )
    assert first.repository_root == first_root.resolve()
    assert first.output_root == first_output.resolve()


def test_query_daemon_registry_rejects_duplicate_foreground_identity(
    tmp_path: Path,
) -> None:
    """Reject a duplicate foreground claim for one service identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to create the claimed identity.

    Returns
    -------
    None
        The test asserts release permits a later replacement claim.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state")
    registry = QueryDaemonInstanceRegistry()

    registry.claim(identity)
    with pytest.raises(QueryDaemonAlreadyRunningError, match=identity.value):
        registry.claim(identity)
    registry.release(identity)
    registry.claim(identity)


def test_query_daemon_status_defaults_to_no_warmed_generation(tmp_path: Path) -> None:
    """Declare a starting query daemon without runtime-owned state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary root used to construct the service identity.

    Returns
    -------
    None
        The test asserts deterministic lifecycle defaults.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "state")

    status = QueryDaemonStatus(identity=identity, state=QueryDaemonState.STARTING)

    assert status.generation is None
    assert status.last_error is None


def test_query_daemon_help_and_disabled_run_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expose all reserved commands while retaining disabled-by-default safety.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to select the temporary repository and CLI arguments.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts help is complete and ``run`` cannot start by default.
    """
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["codira", "query-daemon", "--help"])

    with pytest.raises(SystemExit, match="0"):
        main()

    output = capsys.readouterr().out
    for action in ("run", "install", "uninstall", "start", "stop", "status"):
        assert f"codira query-daemon {action}" in output

    monkeypatch.setattr(sys, "argv", ["codira", "query-daemon", "run"])

    assert main() == 2
    assert "query_daemon.enabled = true" in capsys.readouterr().err
