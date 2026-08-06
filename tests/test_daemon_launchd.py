"""Tests for the repository-scoped launchd user-agent adapter.

Responsibilities
----------------
- Verify deterministic LaunchAgent plist rendering and repository isolation.
- Exercise lifecycle calls through an injected launchctl boundary.
- Avoid creating or controlling host launchd agents during tests.

Design principles
-----------------
Tests use temporary agent directories and completed-process fakes so launchd
behavior remains deterministic on non-macOS development and CI systems.

Architectural role
------------------
This module belongs to the daemon service-adapter verification layer.
"""

from __future__ import annotations

import plistlib
import subprocess
from typing import TYPE_CHECKING

from codira.daemon.launchd import LaunchdUserAgent

if TYPE_CHECKING:
    from pathlib import Path


def test_launchd_user_agent_renders_repository_scoped_plist(tmp_path: Path) -> None:
    """Render an isolated LaunchAgent with absolute daemon arguments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts agent identity and plist command arguments derive from
        the canonical repository root.
    """
    root = tmp_path / "project with spaces"
    root.mkdir()
    executable = tmp_path / "bin" / "codira"
    agent = LaunchdUserAgent(
        root,
        executable=executable,
        agent_directory=tmp_path / "agents",
        uid=501,
    )
    other_agent = LaunchdUserAgent(
        tmp_path / "other-project",
        executable=executable,
        agent_directory=tmp_path / "agents",
        uid=501,
    )

    payload = plistlib.loads(agent.render_plist())

    assert agent.label.startswith("io.codira.daemon.")
    assert agent.label != other_agent.label
    assert agent.domain == "gui/501"
    assert agent.target == f"gui/501/{agent.label}"
    assert payload == {
        "KeepAlive": True,
        "Label": agent.label,
        "ProgramArguments": [
            str(executable),
            "daemon",
            "--path",
            str(root),
            "run",
        ],
        "RunAtLoad": True,
        "WorkingDirectory": str(root),
    }


def test_launchd_user_agent_lifecycle_uses_injected_launchctl(
    tmp_path: Path,
) -> None:
    """Install and control an agent without invoking host launchctl.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts lifecycle operations issue deterministic launchctl
        commands and agent-file changes through injected seams.
    """
    root = tmp_path / "project"
    root.mkdir()
    commands: list[list[str]] = []

    def run_launchctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        """Record successful launchctl commands and active print status.

        Parameters
        ----------
        arguments : list[str]
            launchctl arguments supplied by the adapter.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Successful completed-process fixture.
        """
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    agent = LaunchdUserAgent(
        root,
        executable=tmp_path / "bin" / "codira",
        agent_directory=tmp_path / "agents",
        uid=501,
        run_launchctl=run_launchctl,
    )

    installed_path = agent.install()
    agent.start()
    agent.stop()
    assert agent.status().active is True
    agent.uninstall()

    assert installed_path == agent.plist_path
    assert not installed_path.exists()
    assert commands == [
        ["bootout", agent.target],
        ["bootstrap", agent.domain, str(agent.plist_path)],
        ["print", agent.target],
        ["kickstart", "-k", agent.target],
        ["bootout", agent.target],
        ["print", agent.target],
        ["bootout", agent.target],
    ]


def test_launchd_user_agent_starts_unloaded_agent_with_bootstrap(
    tmp_path: Path,
) -> None:
    """Bootstrap an installed agent when launchctl reports it unloaded.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts start uses bootstrap rather than kickstart for an
        unloaded login-session agent.
    """
    commands: list[list[str]] = []

    def run_launchctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        """Return inactive for print and successful bootstrap otherwise.

        Parameters
        ----------
        arguments : list[str]
            launchctl arguments supplied by the adapter.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Deterministic inactive or successful completed-process fixture.
        """
        commands.append(arguments)
        returncode = 3 if arguments[0] == "print" else 0
        return subprocess.CompletedProcess(arguments, returncode, "", "")

    agent = LaunchdUserAgent(
        tmp_path,
        executable=tmp_path / "bin" / "codira",
        agent_directory=tmp_path / "agents",
        uid=501,
        run_launchctl=run_launchctl,
    )

    agent.start()

    assert commands == [
        ["print", agent.target],
        ["bootstrap", agent.domain, str(agent.plist_path)],
    ]
