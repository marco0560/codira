"""Verify independent architecture budgets and optional-render evidence.

Parameters
----------
None

Returns
-------
None
    Uses fake commands and manifests; never launches a corpus campaign.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import TextIO
from unittest.mock import Mock

import pytest

from scripts import run_test_material_benchmarks as runner


@pytest.mark.parametrize("extended", [False, True])
def test_svg_budget_is_forwarded_and_explicit_override_is_preserved(
    tmp_path: Path, extended: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Propagate the inner limit identically for analyzer and stress manifests.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned manifest and stage directory.
    extended : bool
        Analyzer-style or stress suite selector.
    monkeypatch : pytest.MonkeyPatch
        Captures commands without starting a process.

    Returns
    -------
    None
        Inner and outer controls remain separate; explicit arguments win.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"temporary_root": str(tmp_path), "extended": extended})
    )
    campaign = runner.Campaign(manifest, tmp_path / "run", False, 300, 17)
    capture = Mock(return_value={"status": "passed"})
    monkeypatch.setattr(campaign, "command", capture)
    campaign.cli("arch", "fixture", ["arch", "--output", str(tmp_path / "out")])
    assert capture.call_args.args[1][-2:] == ["--svg-timeout-seconds", "17"]
    campaign.cli("arch", "fixture", ["arch", "--svg-timeout-seconds", "9"])
    assert capture.call_args.args[1].count("--svg-timeout-seconds") == 1
    assert capture.call_args.args[1][-1] == "9"
    assert campaign.architecture_timeout_seconds == 300


@pytest.mark.parametrize("budget", [-1, float("inf"), float("nan")])
def test_invalid_inner_budget_is_rejected(tmp_path: Path, budget: float) -> None:
    """Reject invalid renderer deadlines before any child can start.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned manifest directory.
    budget : float
        Invalid inner deadline.

    Returns
    -------
    None
        Invalid controls cannot create a measured attempt.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    with pytest.raises(ValueError, match="SVG timeout"):
        runner.Campaign(manifest, tmp_path / "run", False, 300, budget)


def test_optional_svg_timeout_preserves_reports_and_each_sample_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Retain an optional inner timeout without claiming outer command failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned simulated report directory.
    monkeypatch : pytest.MonkeyPatch
        Simulates a successful mandatory-report command.
    capsys : pytest.CaptureFixture[str]
        Captures the prominent optional-render warning.

    Returns
    -------
    None
        Each repeated sample retains the renderer's evidence and a valid command.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    output = tmp_path / "reports"
    output.mkdir()
    payload = {
        "artifacts": ["architecture.dot", "architecture.md"],
        "render_options": {"svg_timeout_seconds": 17},
        "svg": {
            "available": False,
            "warning": "Graphviz SVG not rendered: exceeded 17 seconds.",
        },
        "timings": {"svg_seconds": 17.01},
    }

    def simulate(
        argv: list[str], *, stdout: TextIO, **options: object
    ) -> SimpleNamespace:
        """Write completed mandatory-report evidence without rendering.

        Parameters
        ----------
        argv : list of str
            Unused command descriptor.
        stdout : typing.TextIO
            Captured command output.
        **options : object
            Unused process parameters.

        Returns
        -------
        types.SimpleNamespace
            Successful simulated process.
        """
        (output / "manifest.json").write_text(json.dumps(payload))
        stdout.write("Wrote architecture report\n")
        return SimpleNamespace(returncode=0, wait=Mock(return_value=0))

    monkeypatch.setattr(subprocess, "Popen", simulate)
    campaign = runner.Campaign(manifest, tmp_path / "run", False, 300, 17)
    result = campaign.cli(
        "profile/member/arch", "fixture", ["arch", "--output", str(output)], repeats=2
    )
    assert result["status"] == "passed"
    assert result["optional_artifacts"]["svg"]["available"] is False
    assert "exceeded 17 seconds" in capsys.readouterr().out
    for number, sample in enumerate(result["samples"]):
        assert sample["status"] == "passed"
        assert sample["architecture_artifacts"] == payload
        retained = Path(sample["stdout"]).with_name(
            f"{number}.architecture-manifest.json"
        )
        assert json.loads(retained.read_text()) == payload
