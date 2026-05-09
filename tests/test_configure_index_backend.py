"""Tests for the repository-local backend-switch helper script.

Responsibilities
----------------
- Verify backend selection remains env-based and shell-evaluable.
- Ensure backend switches trigger reindexing only when the backend name changes.
- Keep the helper aligned with the repository-local ``codira`` executable path.

Design principles
-----------------
The tests patch subprocess execution and backend detection so behavior stays
deterministic without mutating the real repository index.

Architectural role
------------------
This module belongs to the **tooling verification layer** guarding
repository-local backend activation workflows.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

import pytest


class _ConfigureIndexBackendModule(Protocol):
    """Protocol for the standalone backend-switch helper module."""

    REPO_ROOT: Path

    def uv_executable(self) -> str:
        """
        Return the preferred ``uv`` executable for repository-local commands.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Resolved ``uv`` executable path.
        """
        ...

    def shell_activate_command(self, backend_name: str) -> str:
        """
        Render shell code that activates one backend.

        Parameters
        ----------
        backend_name : str
            Backend name to activate.

        Returns
        -------
        str
            Shell code that configures the backend selection environment
            variable.
        """
        ...

    def run_backend_reindex(self, repo_root: Path, backend_name: str) -> None:
        """
        Refresh the local index under one selected backend environment.

        Parameters
        ----------
        repo_root : pathlib.Path
            Repository root whose index should be refreshed.
        backend_name : str
            Backend name to activate during the refresh.

        Returns
        -------
        None
            The repository index is refreshed in place.
        """
        ...

    def main(self, argv: list[str] | None = None) -> int:
        """
        Configure one backend or print help text.

        Parameters
        ----------
        argv : list[str] | None, optional
            Explicit command arguments. ``None`` uses ``sys.argv[1:]``.

        Returns
        -------
        int
            Process exit status for the backend-switch helper.
        """
        ...


def _load_configure_index_backend_helper() -> _ConfigureIndexBackendModule:
    """
    Load the standalone backend-switch helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the backend-switch helper.
    """

    helper_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "configure_index_backend.py"
    )
    spec = importlib.util.spec_from_file_location(
        "configure_index_backend", helper_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast("_ConfigureIndexBackendModule", module)


def test_help_reports_the_current_backend(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Print usage text plus the currently configured backend name.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control the backend reported by the helper.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture helper output.

    Returns
    -------
    None
        The test asserts the help action includes the current backend.
    """

    helper = _load_configure_index_backend_helper()
    monkeypatch.setattr(helper, "configured_index_backend_name", lambda: "duckdb")

    assert helper.main(["help"]) == 0

    captured = capsys.readouterr()
    assert "usage:" in captured.out
    assert "Current backend: duckdb" in captured.out
    assert captured.err == ""


def test_main_reindexes_only_when_backend_name_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Reindex only when the requested backend differs from the current backend.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend detection and reindex side effects.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture helper output.

    Returns
    -------
    None
        The test asserts backend changes trigger one reindex and emit the
        shell activation snippet.
    """

    helper = _load_configure_index_backend_helper()
    reindexed: list[tuple[Path, str]] = []
    monkeypatch.setattr(helper, "configured_index_backend_name", lambda: "sqlite")
    monkeypatch.setattr(
        helper,
        "run_backend_reindex",
        lambda repo_root, backend_name: reindexed.append((repo_root, backend_name)),
    )

    assert helper.main(["duckdb"]) == 0

    captured = capsys.readouterr()
    assert reindexed == [(helper.REPO_ROOT, "duckdb")]
    assert captured.out == "export CODIRA_INDEX_BACKEND=duckdb\n"
    assert captured.err == ""


def test_main_skips_reindex_when_backend_name_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Avoid reindexing when the requested backend already matches the current one.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch backend detection and reindex side effects.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture helper output.

    Returns
    -------
    None
        The test asserts the helper emits the SQLite activation snippet
        without calling the reindex helper.
    """

    helper = _load_configure_index_backend_helper()
    monkeypatch.setattr(helper, "configured_index_backend_name", lambda: "sqlite")

    def _unexpected_reindex(repo_root: Path, backend_name: str) -> None:
        del repo_root, backend_name
        msg = "reindex should not run when the backend is unchanged"
        raise AssertionError(msg)

    monkeypatch.setattr(helper, "run_backend_reindex", _unexpected_reindex)

    assert helper.main(["sqlite"]) == 0

    captured = capsys.readouterr()
    assert captured.out == "unset CODIRA_INDEX_BACKEND\n"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("backend_name", "expected_env_value"),
    [
        ("sqlite", None),
        ("duckdb", "duckdb"),
    ],
)
def test_run_backend_reindex_uses_the_requested_backend_environment(
    backend_name: str,
    expected_env_value: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Invoke the repository-local ``codira`` executable with the requested backend.

    Parameters
    ----------
    backend_name : str
        Backend name passed to the helper.
    expected_env_value : str | None
        Expected environment-variable value after helper normalization.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch subprocess execution.
    tmp_path : pathlib.Path
        Temporary repository root used to avoid the real checkout path.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture helper status output.

    Returns
    -------
    None
        The test asserts the helper runs ``codira index`` with the correct
        repository-local executable and backend environment.
    """

    helper = _load_configure_index_backend_helper()
    recorded: dict[str, object] = {}
    monkeypatch.setattr(helper, "uv_executable", lambda: "uv")

    def _record_run(
        argv: list[str],
        *,
        check: bool,
        cwd: Path,
        env: dict[str, str],
        stdout: object,
        stderr: object,
    ) -> subprocess.CompletedProcess[str]:
        recorded["argv"] = argv
        recorded["check"] = check
        recorded["cwd"] = cwd
        recorded["env"] = env
        recorded["stdout"] = stdout
        recorded["stderr"] = stderr
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", _record_run)

    helper.run_backend_reindex(tmp_path, backend_name)

    captured = capsys.readouterr()
    assert recorded["argv"] == ["uv", "run", "codira", "index"]
    assert recorded["check"] is True
    assert recorded["cwd"] == tmp_path
    assert recorded["stdout"] is sys.stderr
    assert recorded["stderr"] is sys.stderr
    env = cast("dict[str, str]", recorded["env"])
    if expected_env_value is None:
        assert "CODIRA_INDEX_BACKEND" not in env
    else:
        assert env["CODIRA_INDEX_BACKEND"] == expected_env_value
    assert (
        f"[codira] Switching backend to {backend_name} and refreshing the index..."
        in captured.err
    )


def test_shell_activate_command_uses_unset_for_the_default_backend() -> None:
    """
    Represent the default SQLite backend by unsetting the environment variable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the helper keeps the default-backend contract stable.
    """

    helper = _load_configure_index_backend_helper()

    assert helper.shell_activate_command("sqlite") == "unset CODIRA_INDEX_BACKEND"
    assert (
        helper.shell_activate_command("duckdb") == "export CODIRA_INDEX_BACKEND=duckdb"
    )
