"""Exercise fresh-clone history repair and complete quality failure collection.

Parameters
----------
None

Returns
-------
None
    Regression checks run without providers or external network access.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from scripts import check_workflow_quality, prepare_benchmark_history

if TYPE_CHECKING:
    from pathlib import Path

GIT = shutil.which("git") or "git"


def _git(root: Path, *arguments: str) -> str:
    """Run Git in the isolated regression fixture.

    Parameters
    ----------
    root : pathlib.Path
        Disposable repository directory.
    *arguments : str
        Git command arguments.

    Returns
    -------
    str
        Stripped stdout.

    Raises
    ------
    subprocess.CalledProcessError
        If fixture construction fails.
    """
    return subprocess.run(
        (GIT, "-C", str(root), *arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_history_repair_recovers_a_commit_omitted_by_single_branch_clone(
    tmp_path: Path,
) -> None:
    """Keep frozen source revisions available after ordinary branch checkout.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary workspace.

    Returns
    -------
    None
        Offline verification fails before exact-SHA fetching and passes after.
    """
    source = tmp_path / "origin"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "Fixture")
    _git(source, "config", "user.email", "fixture@example.invalid")
    _git(source, "config", "commit.gpgsign", "false")
    (source / "file.txt").write_text("base\n")
    _git(source, "add", "file.txt")
    _git(source, "commit", "-m", "base")
    base = _git(source, "rev-parse", "HEAD")
    _git(source, "checkout", "-b", "frozen")
    (source / "file.txt").write_text("frozen\n")
    _git(source, "commit", "-am", "frozen")
    frozen = _git(source, "rev-parse", "HEAD")
    checkout = tmp_path / "checkout"
    _git(
        tmp_path,
        "clone",
        "--no-local",
        "--single-branch",
        "--branch",
        "main",
        str(source),
        str(checkout),
    )
    corpus = checkout / "benchmarks/agent-efficiency"
    (corpus / "fixtures").mkdir(parents=True)
    (corpus / "reviewer-evaluation").mkdir()
    (corpus / "fixtures/codira-public.json").write_text(
        json.dumps({"revision": frozen})
    )
    (corpus / "reviewer-evaluation/phase6-deepseek-v4-1-flash.json").write_text(
        json.dumps({"cases": [{"base": base, "head": frozen}]})
    )
    assert prepare_benchmark_history.prepare_history(checkout) == (frozen,)
    assert prepare_benchmark_history.prepare_history(checkout, fetch=True) == ()
    assert _git(checkout, "rev-parse", "HEAD") == base
    assert (checkout / "file.txt").read_text() == "base\n"
    (corpus / "fixtures/codira-public.json").write_text(
        json.dumps({"revision": "--upload-pack=unexpected"})
    )
    with pytest.raises(ValueError, match="full lowercase commit IDs"):
        prepare_benchmark_history.prepare_history(checkout, fetch=True)


def test_quality_preflight_collects_later_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Keep independent quality diagnostics after the first failed check.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces child commands with controlled check results.
    capsys : pytest.CaptureFixture[str]
        Captures the failure summary.

    Returns
    -------
    None
        Both early and late failures survive in a nonzero summary.
    """
    outcomes = iter((0, 1, 0, 0, 0, 0, 1))
    monkeypatch.setattr(
        check_workflow_quality, "run_validation", lambda _commands: next(outcomes)
    )
    assert check_workflow_quality.main([]) == 1
    summary = json.loads(capsys.readouterr().out)["quality_checks"]
    assert summary["ruff"] == 1
    assert summary["docstring-audit"] == 1
    assert len(summary) == 7


def test_quality_preflight_does_not_query_a_stale_index(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mark documentation audit unavailable after index refresh fails.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces child commands with an index failure and passing lint.
    capsys : pytest.CaptureFixture[str]
        Captures the unavailable audit marker.

    Returns
    -------
    None
        Stale-index results cannot be reported as a passing audit.
    """
    outcomes = iter((1, 0, 0, 0, 0, 0))
    monkeypatch.setattr(
        check_workflow_quality, "run_validation", lambda _commands: next(outcomes)
    )
    assert check_workflow_quality.main([]) == 1
    summary = json.loads(capsys.readouterr().out)["quality_checks"]
    assert summary["docstring-audit"] is None
