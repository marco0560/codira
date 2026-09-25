"""Verify Phase 3 public corpus admission and source-leak controls."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.agent_efficiency.contracts import ContractError
from scripts.agent_efficiency.corpus import (
    export_fixture,
    load_admitted_documents,
    load_task_oracles,
    verify_source_fix_excluded,
)

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks" / "agent-efficiency"


def test_public_phase3_records_are_complete_and_cross_referenced() -> None:
    """Load exactly the admitted fixtures and seven coherent task/oracle pairs.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The public records identify all required fixture/task/oracle relationships.
    """

    fixtures = load_admitted_documents(BENCHMARK_ROOT / "fixtures")
    pairs = load_task_oracles(
        BENCHMARK_ROOT / "tasks", BENCHMARK_ROOT / "oracles", fixtures
    )
    assert {item["fixture_id"] for item in fixtures} == {
        "codira-public",
        "click-public",
        "picomatch-public",
    }
    assert {task["task_id"] for task, _ in pairs} == {
        "symbols-001",
        "impact-001",
        "localize-001",
        "patch-001",
        "patch-002",
        "architecture-001",
        "documentation-001",
    }


def test_source_fix_exclusion_rejects_history_remote_and_commit_marker(
    tmp_path: Path,
) -> None:
    """Reject fixture exports exposing history, remotes, or protected identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent-visible fixture root.

    Returns
    -------
    None
        Every prohibited leak channel raises a deterministic contract error.
    """

    source_fix = "f58ca3e81424a35626c8a475eb59ab95589008ce"
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture", encoding="utf-8")
    subprocess.run(("git", "add", "README.md"), cwd=tmp_path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "synthetic history",
        ),
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(ContractError, match="Git history"):
        verify_source_fix_excluded(tmp_path, source_fix)


def test_export_fixture_creates_a_history_free_git_worktree(tmp_path: Path) -> None:
    """Provide agents normal Git status/diff commands without source history.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source and destination Git worktrees.

    Returns
    -------
    None
        The exported content is frozen while its Git worktree has no commits.
    """

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    subprocess.run(("git", "init", "--quiet"), cwd=source, check=True)
    (source / "fixture.txt").write_text("frozen", encoding="utf-8")
    subprocess.run(("git", "add", "fixture.txt"), cwd=source, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ),
        cwd=source,
        check=True,
    )
    revision = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    export_fixture(source, revision, destination)

    assert (destination / "fixture.txt").read_text(encoding="utf-8") == "frozen"
    assert (
        subprocess.run(
            ("git", "rev-parse", "--verify", "HEAD"), cwd=destination, check=False
        ).returncode
        != 0
    )
    assert (
        subprocess.run(
            ("git", "diff", "--check"), cwd=destination, check=False
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ("git", "ls-files", "--error-unmatch", "fixture.txt"),
            cwd=destination,
            check=False,
        ).returncode
        == 0
    )
    (destination / "fixture.txt").write_text("changed", encoding="utf-8")
    assert (
        "fixture.txt"
        in subprocess.run(
            ("git", "diff", "--name-only"),
            cwd=destination,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
    )
    verify_source_fix_excluded(destination, "f58ca3e81424a35626c8a475eb59ab95589008ce")
