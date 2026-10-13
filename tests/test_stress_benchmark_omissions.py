"""Verify visible conditional skips without ordinal or checkpoint fabrication.

Parameters
----------
None

Returns
-------
None
    Shared progress tests use no corpus processes or benchmark measurements.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from scripts import run_test_material_benchmarks as runner

if TYPE_CHECKING:
    from pathlib import Path


def test_grouped_omissions_are_visible_once_with_accurate_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Emit one timestamped skip per pending child, preserving measured ordinals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Empty fixture campaign root.
    capsys : pytest.CaptureFixture[str]
        Captures progress output.

    Returns
    -------
    None
        Group pruning is deterministic and repeated exclusions are silent.
    """
    progress = runner.StageProgress(
        {"group/a", "group/b", "other/test"}, tmp_path, False
    )
    progress.omit("group", "embedding population did not complete")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[skip; 2; ")
    assert lines[1].startswith("[skip; 1; ")
    assert "] group/a excluded: embedding population did not complete" in lines[0]
    assert "] group/b excluded: embedding population did not complete" in lines[1]
    assert "remaining" not in "\n".join(lines)
    assert progress.completed == 0
    progress.omit("group", "same missing prerequisite")
    progress.report("group/a", "excluded: repeated", measured=False)
    assert capsys.readouterr().out == ""
    progress.report("other/test", "passed")
    assert capsys.readouterr().out.startswith("[1; 0; ")


@pytest.mark.parametrize("retry_failed", [False, True])
def test_resume_prunes_retained_parent_and_child_without_skip_measurements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], retry_failed: bool
) -> None:
    """Reusing MCP checkpoints never manufactures child skips or receipts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture campaign checkpoint root.
    capsys : pytest.CaptureFixture[str]
        Captures progress output.
    retry_failed : bool
        Operator control which still retains usable partial checkpoints.

    Returns
    -------
    None
        Only newly omitted tests print, even when a retained child lacks a receipt.
    """
    key = "member/mcp"
    runner.write(tmp_path / "stages" / key / "result.json", {"status": "partial"})
    progress = runner.StageProgress(
        {key, key + "/cli-evidence", "new/test"}, tmp_path, retry_failed
    )
    progress.omit(key + "/cli-evidence", retained=True)
    assert progress.pending == {"new/test"}
    assert progress.completed == 0
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "stages" / key / "cli-evidence/result.json").exists()
    progress.omit("new", "no symbol identity discovered")
    assert capsys.readouterr().out.startswith("[skip; 0; ")
