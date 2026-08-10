"""Tests for no-network installer release-rehearsal command construction."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _load_helper() -> ModuleType:
    """Load the standalone installer rehearsal helper from its script path.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Imported installer-rehearsal helper module.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "rehearse_installer_installs.py"
    )
    spec = importlib.util.spec_from_file_location("rehearse_installer_installs", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_offline_install_command_disables_index_and_dependencies() -> None:
    """Keep artifact rehearsal unable to contact an index or resolve packages.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    helper = _load_helper()
    command = helper.build_offline_install_argv(
        python=Path("/tmp/venv/bin/python"),
        wheel_path=Path("/tmp/wheels/codira_installer.whl"),
    )

    assert command[:5] == ("uv", "pip", "install", "--python", "/tmp/venv/bin/python")
    assert "--no-index" in command
    assert "--no-deps" in command


def test_rehearsal_covers_the_four_supported_installer_paths() -> None:
    """Cover standalone, selected, core-only, and local-checkout exports.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    helper = _load_helper()
    scenarios = helper.scenarios(checkout=Path("/clone/codira"), target=Path("/env"))

    assert tuple(scenario.name for scenario in scenarios) == (
        "standalone",
        "selected-feature",
        "core-only",
        "local-checkout",
    )
    assert "--package" in scenarios[1].arguments
    assert "core-only" in scenarios[2].arguments
    assert "/clone/codira" in scenarios[3].arguments


def test_windows_venv_interpreter_path_is_explicit() -> None:
    """Keep Windows smoke coverage on the standard Scripts interpreter path.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    helper = _load_helper()

    assert helper.venv_python(Path("C:/env"), platform="win32") == Path(
        "C:/env/Scripts/python.exe"
    )


def test_cleanup_preserves_preexisting_build_byproducts(tmp_path: Path) -> None:
    """Remove only rehearsal-created build directories from package sources.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary package source directory.

    Returns
    -------
    None
    """
    helper = _load_helper()
    package = tmp_path / "package"
    existing = package / "existing.egg-info"
    created = package / "build"
    existing.mkdir(parents=True)
    before = helper._build_byproducts(package)
    created.mkdir()

    helper._cleanup_new_byproducts(package, before=before)

    assert existing.exists()
    assert not created.exists()


def test_ci_exercises_installer_rehearsal_on_every_supported_platform() -> None:
    """Require Linux, macOS, and Windows installer smoke coverage in CI.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    ci_workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    )
    workflow = ci_workflow.read_text(encoding="utf-8")

    assert "installer-smoke:" in workflow
    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    assert "scripts/rehearse_installer_installs.py" in workflow
