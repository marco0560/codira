"""Verify immutable identities, interrupted-run reuse and honest readiness counts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from scripts import analyzer_backlog_inventory as inventory


def original(path: Path, repository: str = "sample") -> dict[str, Any]:
    """Build one synthetic original ledger identity.

    Parameters
    ----------
    path : pathlib.Path
        Existing C source.
    repository : str, optional
        Repository label for selection controls.

    Returns
    -------
    dict
        Source-hashed ledger row.
    """
    return {
        "path": str(path),
        "relative_path": path.name,
        "repository": repository,
        "repository_revision": "1" * 40,
        "analyzer": "c",
        "source_sha256": inventory.digest(path),
        "version": "not specified by source harness",
        "disposition": "investigate_and_fix",
    }


def prepare(tmp_path: Path) -> tuple[Path, Path]:
    """Create a valid C source and its immutable-ledger fixture.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated test directory.

    Returns
    -------
    tuple of pathlib.Path
        Source and ledger paths.
    """
    source = tmp_path / "sample.c"
    source.write_text("int function(int value) { return value; }\n")
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(original(source)) + "\n")
    return source, ledger


def test_selection_keeps_originals_and_explicit_profiles_separate(
    tmp_path: Path,
) -> None:
    """Exclude a repository only from measurement and deduplicate empty profiles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source fixtures.

    Returns
    -------
    None
        Original rows stay unchanged and no case is a verified fix.
    """
    source, _ = prepare(tmp_path)
    rows = [
        original(source),
        {**original(source, "excluded"), "path": str(tmp_path / "other.c")},
    ]
    before = json.dumps(rows, sort_keys=True)
    cases = inventory.make_cases(
        rows,
        {"sample": {"c": {"include_search_paths": ["include"]}}},
        {"excluded"},
        tmp_path / "run",
    )
    assert [case.profile for case in cases] == ["default", "configured"]
    assert cases[0].configuration == {}
    assert cases[1].configuration == {"include_search_paths": ["include"]}
    assert json.dumps(rows, sort_keys=True) == before
    assert len(inventory.make_cases(rows, {}, {"excluded"}, tmp_path / "run")) == 1
    with pytest.raises(ValueError, match="duplicate original"):
        inventory.make_cases([rows[0], rows[0]], {}, set(), tmp_path / "run")


def test_complete_inventory_does_not_admit_ready_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture real public-analyzer DTOs while keeping qualification at zero.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated measurement identity.
    monkeypatch : pytest.MonkeyPatch
        Runs the same capture function without child startup in this unit test.

    Returns
    -------
    None
        Readiness, raw DTO digest and immutable completed-run reuse are checked.
    """
    _, ledger = prepare(tmp_path)
    monkeypatch.setattr(inventory, "ProcessPoolExecutor", ThreadPoolExecutor)
    output = tmp_path / "run"
    summary = inventory.run_inventory(ledger, None, output, set(), 1)
    assert summary["profiles"] == {"default": {"ready": 1, "partial": 0, "error": 0}}
    assert summary["qualified_files"] == 0
    record = inventory.json_rows(output / "results.jsonl")[0]
    assert (
        inventory.digest(Path(record["analysis_artifact"])) == record["analysis_sha256"]
    )
    snapshot = inventory.digest(output / "results.jsonl")
    assert inventory.run_inventory(ledger, None, output, set(), 1) == summary
    assert inventory.digest(output / "results.jsonl") == snapshot


def test_resume_skips_completed_cases_and_preserves_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume a simulated interruption without repeating the completed profile.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable test evidence, not a campaign identity.
    monkeypatch : pytest.MonkeyPatch
        Uses threads and records newly executed profiles.

    Returns
    -------
    None
        Only the missing case executes; previous full DTO evidence is unchanged.
    """
    _, ledger = prepare(tmp_path)
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({"sample": {"c": {"include_search_paths": ["include"]}}})
    )
    monkeypatch.setattr(inventory, "ProcessPoolExecutor", ThreadPoolExecutor)
    output = tmp_path / "run"
    inventory.run_inventory(ledger, profiles, output, set(), 1)
    results = inventory.json_rows(output / "results.jsonl")
    saved = results[0]
    output.joinpath("results.jsonl").write_text(json.dumps(saved) + "\n")
    output.joinpath("summary.json").unlink()
    executed: list[str] = []
    capture = inventory.capture

    def observed(case: inventory.InventoryCase) -> dict[str, Any]:
        """Record the executed profile and use the real capture path.

        Parameters
        ----------
        case : InventoryCase
            Remaining test case.

        Returns
        -------
        dict
            Original capture result.
        """
        executed.append(case.profile)
        return capture(case)

    monkeypatch.setattr(inventory, "capture", observed)
    result = inventory.run_inventory(ledger, profiles, output, set(), 1)
    assert result["processed"] == 2
    assert executed == [results[1]["profile"]]
    assert (
        inventory.digest(Path(saved["analysis_artifact"])) == saved["analysis_sha256"]
    )


def test_resume_rejects_changed_header_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject dependency drift even when the original source bytes are unchanged.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Source and literal include fixtures.
    monkeypatch : pytest.MonkeyPatch
        Uses the same capture code without child startup.

    Returns
    -------
    None
        The completed evidence is preserved and a fresh identity is required.
    """
    source, ledger = prepare(tmp_path)
    source.write_text('#include "header.h"\nint function(void) { return VALUE; }\n')
    header = tmp_path / "header.h"
    header.write_text("#define VALUE 1\n")
    ledger.write_text(json.dumps(original(source)) + "\n")
    monkeypatch.setattr(inventory, "ProcessPoolExecutor", ThreadPoolExecutor)
    output = tmp_path / "run"
    inventory.run_inventory(ledger, None, output, set(), 1)
    before = inventory.digest(output / "results.jsonl")
    header.write_text("#define VALUE 2\n")
    with pytest.raises(ValueError, match="source context drifted"):
        inventory.run_inventory(ledger, None, output, set(), 1)
    assert inventory.digest(output / "results.jsonl") == before


def test_changed_identity_cannot_reuse_completed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require a new run identity after changing the declared profile.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated completed run.
    monkeypatch : pytest.MonkeyPatch
        Uses threads for focused validation.

    Returns
    -------
    None
        Existing inputs and results remain byte-for-byte intact.
    """
    _, ledger = prepare(tmp_path)
    monkeypatch.setattr(inventory, "ProcessPoolExecutor", ThreadPoolExecutor)
    output = tmp_path / "run"
    inventory.run_inventory(ledger, None, output, set(), 1)
    before = inventory.digest(output / "inputs.json")
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps({"sample": {"c": {"include_search_paths": ["include"]}}})
    )
    with pytest.raises(ValueError, match="fresh immutable identity"):
        inventory.run_inventory(ledger, profiles, output, set(), 1)
    assert inventory.digest(output / "inputs.json") == before


def test_failed_original_is_retained_and_not_counted_ready(tmp_path: Path) -> None:
    """Preserve an original-byte mismatch as a failed case with raw traceback.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Original source that drifts after selection.

    Returns
    -------
    None
        Failure evidence survives and qualification stays zero.
    """
    source, _ = prepare(tmp_path)
    case = inventory.make_cases([original(source)], {}, set(), tmp_path / "run")[0]
    source.write_text("int changed;\n")
    result = inventory.capture(case)
    assert result["state"] == "error"
    assert "original source drift" in result["error"]
    assert result["qualified_files"] == 0
    assert len(list((tmp_path / "run").rglob("failure.stderr"))) == 1
