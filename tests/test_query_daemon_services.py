"""Platform-service rendering tests for the query daemon."""

from __future__ import annotations

import plistlib
import subprocess
from typing import TYPE_CHECKING

import pytest

from codira.daemon.launchd import QueryDaemonLaunchdUserAgent
from codira.daemon.service_spec import (
    ServiceDefinitionDriftError,
    ServiceSpecification,
)
from codira.daemon.systemd import QueryDaemonSystemdUserService

if TYPE_CHECKING:
    from pathlib import Path


def test_query_service_specification_isolates_root_output_and_kind(
    tmp_path: Path,
) -> None:
    """Derive distinct stable service identities for each service boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary service paths.

    Returns
    -------
    None
        The test asserts no root/output/service-kind collision is possible.
    """
    root = tmp_path / "repo"
    assert (
        ServiceSpecification.query(root, tmp_path / "one").identity
        != ServiceSpecification.query(root, tmp_path / "two").identity
    )
    assert (
        ServiceSpecification.query(root, tmp_path / "one").identity
        != ServiceSpecification.indexing(root).identity
    )


def test_query_systemd_and_launchd_render_fixed_output_paths(tmp_path: Path) -> None:
    """Render exact absolute query-daemon arguments without host installation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output paths.

    Returns
    -------
    None
        The test asserts both platform renderers select query-daemon run.
    """
    root = tmp_path / "repo with spaces"
    output = tmp_path / "output with spaces"
    executable = tmp_path / "bin" / "codira"
    systemd = QueryDaemonSystemdUserService(
        root, output, executable=executable, unit_directory=tmp_path / "units"
    )
    launchd = QueryDaemonLaunchdUserAgent(
        root,
        output,
        executable=executable,
        agent_directory=tmp_path / "agents",
        uid=501,
    )

    assert systemd.unit_name.startswith("codira-query-daemon-")
    assert f'--output-dir "{output}" run' in systemd.render_unit()
    payload = plistlib.loads(launchd.render_plist())
    assert launchd.label.startswith("io.codira.query-daemon.")
    assert payload["ProgramArguments"] == [
        str(executable),
        "query-daemon",
        "--path",
        str(root),
        "--output-dir",
        str(output),
        "run",
    ]


def test_workspace_service_rendering_and_drift_require_regeneration(
    tmp_path: Path,
) -> None:
    """Bind service commands to one workspace and reject descriptor drift.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository, state, and user-unit roots.

    Returns
    -------
    None
        The test asserts workspace launch arguments and stale-definition guard.
    """
    root = tmp_path / "repository"
    root.mkdir()
    specification = ServiceSpecification.workspace(
        kind="query-daemon",
        root=root,
        output_root=tmp_path / "state",
        workspace_name="sample",
        descriptor_fingerprint="a" * 64,
        effective_config={"query_daemon": {"enabled": True}},
    )

    def successful(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        """Return a successful systemctl operation for one isolated service.

        Parameters
        ----------
        arguments : list[str]
            Service-manager arguments supplied by the adapter.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Successful completed-process fixture.
        """
        return subprocess.CompletedProcess(arguments, 0, "", "")

    service = QueryDaemonSystemdUserService(
        root,
        specification.output_root,
        specification=specification,
        executable=tmp_path / "bin" / "codira",
        unit_directory=tmp_path / "units",
        run_systemctl=successful,
    )
    service.install()
    rendered = service.render_unit()
    drifted = ServiceSpecification.workspace(
        kind="query-daemon",
        root=root,
        output_root=specification.output_root,
        workspace_name="sample",
        descriptor_fingerprint="b" * 64,
        effective_config={"query_daemon": {"enabled": True}},
    )

    assert (
        '--workspace "sample" --workspace-fingerprint '
        '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" run'
    ) in rendered
    assert "--path" not in rendered
    assert specification.definition_path.exists()
    with pytest.raises(ServiceDefinitionDriftError, match="drift"):
        drifted.require_current_definition()
