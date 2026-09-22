"""Test deterministic environment selection for benchmark fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.agent_efficiency.environment import (
    fixture_environment,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_fixture_environment_selects_locked_uv_and_shared_directive(
    tmp_path: Path,
) -> None:
    """Select the offline uv preparation arm for a frozen Python project.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        Assertions cover the exact command and model-visible environment facts.
    """

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\n", encoding="utf-8"
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    plan = fixture_environment(tmp_path, "fixture-public")

    assert plan.ecosystem == "uv"
    assert plan.prepare_argv == (
        "/opt/codira/prepare-fixture-environment",
        "fixture-public",
        "uv",
    )
    assert ".venv" in plan.directive


def test_fixture_environment_selects_image_locked_npm_project(tmp_path: Path) -> None:
    """Select image-bound npm resolution before a benchmark agent can start.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        The pre-agent helper restores the image-bound generated lockfile.
    """

    (tmp_path / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")

    plan = fixture_environment(tmp_path, "fixture-public")

    assert plan.ecosystem == "npm"
    assert plan.prepare_argv == (
        "/opt/codira/prepare-fixture-environment",
        "fixture-public",
        "npm",
    )
