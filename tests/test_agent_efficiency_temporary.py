"""Exercise benchmark scratch storage on machines without workstation paths.

Parameters
----------
None

Returns
-------
None
    Regression checks for portable temporary directory creation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from scripts.agent_efficiency import temporary


def test_non_workstation_can_create_disposable_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create scratch work when the workstation-only directory is absent.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing platform scratch directory supplied by pytest.
    monkeypatch : pytest.MonkeyPatch
        Isolates workstation detection and the platform temporary directory.

    Returns
    -------
    None
        A disposable directory can be created without workstation paths.
    """
    monkeypatch.delenv("CODIRA_BENCHMARK_TEMP_ROOT", raising=False)
    monkeypatch.setattr(temporary, "WORKSTATION_TEMP_ROOT", tmp_path / "absent")
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    with tempfile.TemporaryDirectory(dir=temporary.project_temp_root()) as scratch:
        assert Path(scratch).parent == tmp_path
        assert Path(scratch).is_dir()


def test_explicit_scratch_root_is_created_and_overrides_workstation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Honor a configured missing scratch root even on a workstation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Existing isolated root containing the simulated workstation directory.
    monkeypatch : pytest.MonkeyPatch
        Supplies the explicit benchmark scratch configuration.

    Returns
    -------
    None
        Nested configured storage exists and supports disposable work.
    """
    configured = tmp_path / "configured" / "scratch"
    monkeypatch.setenv("CODIRA_BENCHMARK_TEMP_ROOT", str(configured))
    monkeypatch.setattr(temporary, "WORKSTATION_TEMP_ROOT", tmp_path)
    with tempfile.TemporaryDirectory(dir=temporary.project_temp_root()) as scratch:
        assert Path(scratch).parent == configured
        assert configured.is_dir()
