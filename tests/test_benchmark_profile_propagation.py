"""Exercise owned profiling journals with small child commands, never campaigns.

Parameters
----------
None

Returns
-------
None
    Real child environment/receipt checks use synthetic journal data only.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from scripts import run_test_material_benchmarks as runner

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path


CHILD = """import os
from pathlib import Path
folder = Path(os.environ['CODIRA_EMBEDDING_PROFILE_DIR'])
folder.mkdir(parents=True, exist_ok=True)
(folder / 'fixture.jsonl').write_text('{"phase":"synthetic","seconds":0.1}\\n')
print('synthetic child completed')
"""


@pytest.mark.parametrize("extended", [False, True])
def test_profile_control_reaches_each_sample_and_resume_retains_journals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extended: bool
) -> None:
    """Link unique stage/attempt/sample journals while preserving isolation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned manifest, receipts and profiling files.
    monkeypatch : pytest.MonkeyPatch
        Supplies explicit controls and hostile unrelated overrides.
    extended : bool
        Analyzer-style or stress suite.

    Returns
    -------
    None
        Child controls, hashes, ownership and checkpoint retention are real.
    """
    base = tmp_path / "profiles"
    monkeypatch.setenv("CODIRA_EMBEDDING_PROFILE_DIR", str(base))
    monkeypatch.setenv("CODIRA_MODEL_ROOT", str(tmp_path / "models"))
    monkeypatch.setenv("CODIRA_CONFIG_FILE", "/unrelated/parent.toml")
    monkeypatch.setenv("CODIRA_WORKSPACE", "unrelated-parent-workspace")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "temporary_root": str(tmp_path),
                "extended": extended,
                "profiles": [{"id": "primary", "embeddings": False}],
                "repositories": [],
            }
        )
    )
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    key = "primary/fixture/population"
    environment = campaign.environment_for_stage(key, attempt="attempt-1", sample=0)
    assert (
        "CODIRA_CONFIG_FILE" not in environment
        and "CODIRA_WORKSPACE" not in environment
    )
    assert environment["CODIRA_MODEL_ROOT"] == str(tmp_path / "models")
    assert environment["XDG_CONFIG_HOME"] == str(campaign.root / "registry/primary")
    result = campaign.command(key, [sys.executable, "-c", CHILD], repeats=2)
    assert result["status"] == "passed"
    journals = [sample["embedding_profile_journals"][0] for sample in result["samples"]]
    assert journals[0]["path"] != journals[1]["path"]
    for number, journal in enumerate(journals):
        assert f"/attempt-1/sample-{number}/" in journal["path"]
        directory = campaign.profile_directory(key, attempt="attempt-1", sample=number)
        assert directory is not None
        assert journal["sha256"] == runner.digest(directory / "fixture.jsonl")
    other = runner.Campaign(manifest, tmp_path / "other-run", False)
    assert other.profile_directory(key, attempt="attempt-1", sample=0) != (
        campaign.profile_directory(key, attempt="attempt-1", sample=0)
    )
    before = {str(path): path.read_bytes() for path in base.rglob("*.jsonl")}
    resumed = campaign.command(key, [sys.executable, "-c", CHILD], repeats=2)
    assert resumed == result
    assert before == {str(path): path.read_bytes() for path in base.rglob("*.jsonl")}
    assert campaign.progress.completed == 1


def test_interrupted_attempt_retains_journal_and_retry_gets_new_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve interrupted evidence without conflating a later attempt.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned journal and receipt roots.
    monkeypatch : pytest.MonkeyPatch
        Simulates parent interruption after the child has produced its journal.

    Returns
    -------
    None
        Interrupted and retried sample links remain distinct and durable.
    """
    monkeypatch.setenv("CODIRA_EMBEDDING_PROFILE_DIR", str(tmp_path / "profiles"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = runner.Campaign(manifest, tmp_path / "run", False)
    key = "fixture/population"
    original = runner.wait_for_resources

    def interrupted(process: subprocess.Popen[str], timeout: float) -> int | None:
        """Interrupt after real synthetic journal emission.

        Parameters
        ----------
        process : subprocess.Popen[str]
            Owned short-lived fixture child.
        timeout : float
            Unused caller budget.

        Returns
        -------
        int | None
            Does not return normally.

        Raises
        ------
        KeyboardInterrupt
            Simulates operator interruption after child output is durable.
        """
        process.wait(timeout=10)
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "wait_for_resources", interrupted)
    with pytest.raises(KeyboardInterrupt):
        campaign.command(key, [sys.executable, "-c", CHILD])
    record = campaign.root / "stages" / key / "result.json"
    failed = json.loads(record.read_text())
    assert failed["status"] == "interrupted"
    first = failed["embedding_profile_journals"][0]
    monkeypatch.setattr(runner, "wait_for_resources", original)
    recovered = campaign.command(key, [sys.executable, "-c", CHILD])
    second = recovered["embedding_profile_journals"][0]
    assert first["path"] != second["path"]
    assert len(recovered["attempt_history"]) == 2
    assert first["sha256"] == second["sha256"]


@pytest.mark.parametrize("value", ["", "relative/path"])
def test_relative_or_blank_controls_are_rejected(value: str) -> None:
    """Reject unsafe locations before launching children.

    Parameters
    ----------
    value : str
        Invalid explicitly supplied profiling directory.

    Returns
    -------
    None
        Invalid controls cannot quietly redirect operator evidence.
    """
    with pytest.raises(ValueError, match="absolute directory"):
        runner.controlled_runtime_environment({"CODIRA_EMBEDDING_PROFILE_DIR": value})
