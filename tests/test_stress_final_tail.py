"""Regression evidence for the stress campaign's final daemon probes.

Parameters
----------
None

Returns
-------
None
    Bounded harness checks preserve failed outcomes and restoration evidence.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from scripts import run_test_material_benchmarks as runner
from scripts.benchmark_query_daemon import _parser

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.mark.parametrize("budget", ["nan", "inf", "-1", "0"])
def test_query_benchmark_rejects_invalid_request_budget(budget: str) -> None:
    """Reject budgets that could conceal or indefinitely wait on a failure.

    Parameters
    ----------
    budget : str
        Invalid duration supplied by the operator.

    Returns
    -------
    None
        Argument parsing fails before starting a daemon.
    """
    with pytest.raises(SystemExit):
        _parser().parse_args(["--request-timeout-seconds", budget])


@pytest.mark.parametrize("exited", [False, True])
def test_foreground_failure_retains_reason_and_restores_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exited: bool
) -> None:
    """Retain terminal diagnostics when a newer generation is never observed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable clone and checkpoint directory.
    monkeypatch : pytest.MonkeyPatch
        Replaces process execution and elapsed time with deterministic seams.
    exited : bool
        Whether the foreground process exits after initial reconciliation.

    Returns
    -------
    None
        Both failure modes retain their reason and restore the witness bytes.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "temporary_root": str(tmp_path),
                "codira_root": str(tmp_path),
                "daemon_reconciliation_timeout_seconds": 2,
            }
        )
    )
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    clone = campaign.root / "daemon-clone" / "fixture"
    state_dir = clone / ".codira"
    state_dir.mkdir(parents=True)
    source = clone / "sample.py"
    source.write_text("value = 1\n")
    (state_dir / "index-generation.json").write_text(
        json.dumps({"state": "ready", "generation": 1})
    )
    (state_dir / "daemon-status.json").write_text(
        json.dumps({"last_success_at": "ready"})
    )
    polls = 0

    def poll() -> int | None:
        """Exit only after the initial reconciliation readiness check.

        Parameters
        ----------
        None

        Returns
        -------
        int or None
            Terminal code or live process marker.
        """
        nonlocal polls
        polls += 1
        return 7 if exited and polls > 1 else None

    process = SimpleNamespace(
        poll=poll, send_signal=lambda signal: None, wait=lambda timeout: 0
    )
    ticks: Iterator[float] = iter(i / 2 for i in range(100))
    monkeypatch.setattr(
        "scripts.run_test_material_benchmarks.time.monotonic", lambda: next(ticks)
    )
    monkeypatch.setattr(
        "scripts.run_test_material_benchmarks.time.sleep", lambda seconds: None
    )
    monkeypatch.setattr(
        "scripts.run_test_material_benchmarks.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        campaign,
        "command",
        lambda key, *args, **kwargs: {"key": key, "status": "passed"},
    )
    monkeypatch.setattr(campaign, "cli", lambda *args, **kwargs: {"status": "passed"})
    monkeypatch.setattr(campaign, "finish_daemon", lambda *args: None)
    campaign.daemons(
        {
            "repo": {
                "label": "fixture",
                "configs": {"primary": "config.toml"},
                "repetitions": 1,
                "daemon_witness": "sample.py",
            },
            "profile": {"id": "primary"},
            "query": "value",
        }
    )
    result = json.loads(
        (campaign.root / "stages/daemons/fixture/foreground/result.json").read_text()
    )
    assert result["status"] == "failed"
    assert result["reason"] == (
        "process exited" if exited else "reconciliation timeout"
    )
    assert result["before"] == result["observed_generation"] == 1
    assert result["seconds"] >= 0
    assert source.read_text() == "value = 1\n"
