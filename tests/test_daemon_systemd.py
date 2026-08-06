"""Tests for the repository-scoped systemd user-service adapter.

Responsibilities
----------------
- Verify deterministic unit rendering and repository isolation.
- Exercise lifecycle calls through an injected systemctl boundary.
- Avoid creating or controlling host systemd units during tests.

Design principles
-----------------
Tests use temporary unit directories and completed-process fakes so systemd
behavior remains deterministic across non-systemd CI environments.

Architectural role
------------------
This module belongs to the daemon service-adapter verification layer.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from codira.daemon.systemd import SystemdUserService

if TYPE_CHECKING:
    from pathlib import Path


def test_systemd_user_service_renders_repository_scoped_unit(tmp_path: Path) -> None:
    """Render an isolated user service with absolute daemon command paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts unit identity and execution context derive from the
        canonical repository root.
    """
    root = tmp_path / "project with spaces"
    root.mkdir()
    executable = tmp_path / "bin" / "codira"
    service = SystemdUserService(
        root,
        executable=executable,
        unit_directory=tmp_path / "units",
    )
    other_service = SystemdUserService(
        tmp_path / "other-project",
        executable=executable,
        unit_directory=tmp_path / "units",
    )

    unit = service.render_unit()

    assert service.unit_name.startswith("codira-daemon-")
    assert service.unit_name.endswith(".service")
    assert service.unit_name != other_service.unit_name
    assert f'WorkingDirectory="{root}"' in unit
    assert f'ExecStart="{executable}" daemon --path "{root}" run' in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_systemd_user_service_lifecycle_uses_injected_systemctl(
    tmp_path: Path,
) -> None:
    """Install and control a user unit without invoking host systemctl.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts lifecycle operations issue deterministic systemctl
        commands and unit-file changes through injected seams.
    """
    root = tmp_path / "project"
    root.mkdir()
    commands: list[list[str]] = []

    def run_systemctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        """Record a successful systemctl command.

        Parameters
        ----------
        arguments : list[str]
            systemctl user-manager arguments supplied by the adapter.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Successful completed-process fixture.
        """
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    service = SystemdUserService(
        root,
        executable=tmp_path / "bin" / "codira",
        unit_directory=tmp_path / "units",
        run_systemctl=run_systemctl,
    )

    installed_path = service.install()
    service.start()
    service.stop()
    assert service.status().active is True
    service.uninstall()

    assert installed_path == service.unit_path
    assert not installed_path.exists()
    assert commands == [
        ["daemon-reload"],
        ["enable", service.unit_name],
        ["start", service.unit_name],
        ["stop", service.unit_name],
        ["is-active", "--quiet", service.unit_name],
        ["disable", "--now", service.unit_name],
        ["daemon-reload"],
    ]


def test_systemd_user_service_reports_inactive_status(tmp_path: Path) -> None:
    """Map the normal nonzero is-active response to inactive service status.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts inactive services do not raise lifecycle errors.
    """

    def run_systemctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        """Return systemd's inactive status code.

        Parameters
        ----------
        arguments : list[str]
            systemctl user-manager arguments supplied by the adapter.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Inactive completed-process fixture.
        """
        return subprocess.CompletedProcess(arguments, 3, "", "")

    service = SystemdUserService(
        tmp_path,
        executable=tmp_path / "bin" / "codira",
        unit_directory=tmp_path / "units",
        run_systemctl=run_systemctl,
    )

    status = service.status()

    assert status.active is False
    assert status.unit_name == service.unit_name
