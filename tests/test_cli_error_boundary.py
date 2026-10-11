"""Real-process regressions for CLI workspace resolution errors.

Parameters
----------
None

Returns
-------
None
    Workspace failures preserve controlled text and structured JSON diagnoses.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("json_output", [False, True])
def test_missing_workspace_has_controlled_error(
    tmp_path: Path, json_output: bool
) -> None:
    """Resolve an unknown workspace through the real public CLI process.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated registry and current directory.
    json_output : bool
        Whether a structured error envelope is requested.

    Returns
    -------
    None
        Exit status two retains the workspace cause without a traceback.
    """
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("CODIRA_")
    }
    environment["XDG_CONFIG_HOME"] = str(tmp_path / "registry")
    command = [
        sys.executable,
        "-m",
        "codira",
        "config",
        "--workspace",
        "missing-workspace",
        "validate",
    ]
    if json_output:
        command.append("--json")
    result = subprocess.run(
        command,
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Workspace is not registered" in result.stderr
    assert "Traceback" not in result.stderr
    assert "[codira] WorkspaceError:" in result.stderr
    if json_output:
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["error"]["type"] == "WorkspaceError"
        assert "missing-workspace" in payload["error"]["message"]
    else:
        assert not result.stdout
