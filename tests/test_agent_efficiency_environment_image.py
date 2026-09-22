"""Test deterministic build contexts for offline fixture environments."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts.build_agent_efficiency_environment_image import (
    HELPER_ROOT,
    EnvironmentImagePlan,
    write_build_context,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_write_build_context_embeds_profile_and_never_fixture_git_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create a disposable image context from public fixture contents only.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated pytest directory holding one synthetic public fixture.
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture replacing archive export with deterministic test data.

    Returns
    -------
    None
        The context has the profile and helper contracts needed by the build.
    """

    source = tmp_path / "source"
    source.mkdir()

    def export(source_root: Path, revision: str, destination: Path) -> None:
        """Write a minimal synthetic archived fixture for context testing.

        Parameters
        ----------
        source_root : pathlib.Path
            Ignored source path from the image-context writer.
        revision : str
            Ignored immutable revision from the build profile.
        destination : pathlib.Path
            Destination to receive the fake archive.

        Returns
        -------
        None
            The fake archive contains a package manifest and synthetic Git data.
        """

        del source_root, revision
        destination.mkdir()
        (destination / ".git").mkdir()
        (destination / "package.json").write_text(
            '{"name":"fixture"}\n', encoding="utf-8"
        )

    monkeypatch.setattr(
        "scripts.build_agent_efficiency_environment_image.export_fixture", export
    )
    plan = EnvironmentImagePlan(
        "localhost/base@sha256:" + "a" * 64,
        {"fixture-public": source},
        {
            "version": 1,
            "base_image": "localhost/base@sha256:" + "a" * 64,
            "fixtures": {"fixture-public": {"ecosystem": "npm", "revision": "a" * 40}},
        },
    )

    containerfile = write_build_context(plan, tmp_path / "context")

    profile = json.loads(
        (
            tmp_path / "context" / "fixture-environments" / "environment-profile.json"
        ).read_text(encoding="utf-8")
    )
    assert profile["fingerprint"]
    assert "build-fixture-environments" in containerfile.read_text(encoding="utf-8")
    assert "--offline" in (HELPER_ROOT / "build-fixture-environments").read_text(
        encoding="utf-8"
    )
    assert not (
        tmp_path
        / "context"
        / "fixture-environments"
        / "fixtures"
        / "fixture-public"
        / ".git"
    ).exists()
