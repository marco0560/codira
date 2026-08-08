"""Platform-service rendering tests for the query daemon."""

from __future__ import annotations

import plistlib
from typing import TYPE_CHECKING

from codira.daemon.launchd import QueryDaemonLaunchdUserAgent
from codira.daemon.service_spec import ServiceSpecification
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
