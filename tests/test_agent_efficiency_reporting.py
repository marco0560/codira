"""Test deterministic public reporting for agent-efficiency campaigns."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

from scripts.agent_efficiency.campaign_state import CampaignStore, build_paired_schedule
from scripts.agent_efficiency.contracts import OfflineRunnerAdapter, OfflineRunRequest
from scripts.agent_efficiency.reporting import (
    build_report,
    render_markdown,
    write_report,
)
from scripts.report_agent_efficiency_benchmark import main as report_main

if TYPE_CHECKING:
    from pathlib import Path


def _store(tmp_path: Path, failure_class: str | None = None) -> CampaignStore:
    """Create one two-pair campaign with complete public-safe records.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary ignored state root.
    failure_class : str or None, optional
        Synthetic failure content assigned to the first public result.

    Returns
    -------
    CampaignStore
        Initialized campaign with one result per scheduled attempt.
    """

    store = CampaignStore(
        tmp_path / "state",
        "report-001",
        {"image": "digest", "model": "fixed", "seed": 1},
        build_paired_schedule(("symbols-001", "patch-001"), 1, 1),
    )
    store.initialize()
    adapter = OfflineRunnerAdapter(outcome="success")
    for index, attempt in enumerate(store.schedule, start=1):
        result = dict(
            adapter.run(
                OfflineRunRequest(
                    store.campaign_id,
                    attempt.task_id,
                    attempt.attempt_id,
                    attempt.assistance_mode,
                )
            )
        )
        result["usage"] = {
            "input_tokens": index * 10,
            "cached_input_tokens": 0,
            "output_tokens": index,
            "reasoning_output_tokens": 0,
        }
        if index == 1:
            result["failure_class"] = failure_class
        store.store_result(
            attempt.attempt_id,
            result,
            {"elapsed_seconds": index / 10, "jsonl_event_count": index},
        )
    return store


def test_report_is_deterministic_and_markdown_is_derived(tmp_path: Path) -> None:
    """Render reproducible JSON and Markdown from immutable campaign records.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign and public-output directories.

    Returns
    -------
    None
        Assertions cover canonical rendering and paired metrics.
    """

    store = _store(tmp_path)
    first = write_report(store, tmp_path / "public")
    first_json = first.json_path.read_text(encoding="utf-8")
    first_markdown = first.markdown_path.read_text(encoding="utf-8")
    second = write_report(store, tmp_path / "public")
    report = json.loads(second.json_path.read_text(encoding="utf-8"))
    assert first_json == second.json_path.read_text(encoding="utf-8")
    assert first_markdown == render_markdown(report)
    assert report["summary"]["pair_count"] == 2
    assert "Paired token differences" in first_markdown


def test_report_redacts_synthetic_private_failure_data(tmp_path: Path) -> None:
    """Withhold path-like and token-like text from public per-attempt output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state root.

    Returns
    -------
    None
        Assertions cover deterministic synthetic-redaction proof.
    """

    store = _store(tmp_path, "token_secret /private/fixture/path")
    public = json.dumps(build_report(store), sort_keys=True)
    assert "private/fixture" not in public
    assert "token_secret" not in public
    assert '"failure_class": "redacted"' in public


def test_report_excludes_incomplete_usage_pairs(tmp_path: Path) -> None:
    """Exclude, rather than compare, pairs with incomplete usage evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state root.

    Returns
    -------
    None
        Assertions cover explicit incomparable-pair exclusion.
    """

    store = _store(tmp_path)
    record_path = next(store.records_root.glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["result"]["usage_complete"] = False
    evidence = record["evidence"]
    record["evidence_fingerprint"] = sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record_path.write_text(json.dumps(record), encoding="utf-8")
    report = build_report(store)
    summary = report["summary"]
    exclusions = report["exclusions"]
    assert isinstance(summary, dict)
    assert isinstance(exclusions, list)
    assert summary["excluded_pair_count"] == 1
    assert {entry["reason"] for entry in exclusions if isinstance(entry, dict)} == {
        "incomplete_usage"
    }
    assert "| Pair | Reason |" in render_markdown(report)
    assert "incomplete_usage" in render_markdown(report)


def test_report_excludes_incomplete_pair(tmp_path: Path) -> None:
    """Exclude a pair when only one scheduled variant has a terminal record.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state root.

    Returns
    -------
    None
        Assertions cover incomplete-pair classification.
    """

    store = _store(tmp_path)
    first = next(store.records_root.glob("*.json"))
    first.unlink()
    report = build_report(store)
    exclusions = report["exclusions"]
    assert isinstance(exclusions, list)
    assert {entry["reason"] for entry in exclusions if isinstance(entry, dict)} == {
        "incomplete_pair"
    }


def test_report_command_reconstructs_and_renders_frozen_campaign(
    tmp_path: Path,
) -> None:
    """Render reports only when supplied identity matches persisted state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary state, configuration, and public output directories.

    Returns
    -------
    None
        Assertions cover command-level reconstruction and output creation.
    """

    store = _store(tmp_path)
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(dict(store.configuration)), encoding="utf-8"
    )
    output_dir = tmp_path / "public"
    assert (
        report_main(
            [
                "--state-root",
                str(store.root),
                "--output-dir",
                str(output_dir),
                "--campaign-id",
                store.campaign_id,
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--repetitions",
                "1",
                "--seed",
                "1",
                "--configuration-json",
                str(configuration_path),
            ]
        )
        == 0
    )
    assert (output_dir / "report.json").is_file()
    assert (output_dir / "report.md").is_file()


def test_report_command_rejects_incomparable_configuration(tmp_path: Path) -> None:
    """Reject reporting inputs whose configuration differs from stored state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state and incompatible configuration file.

    Returns
    -------
    None
        The command returns its deterministic invalid-input status.
    """

    store = _store(tmp_path)
    configuration_path = tmp_path / "wrong-configuration.json"
    configuration_path.write_text(
        json.dumps({"image": "other", "model": "fixed", "seed": 1}),
        encoding="utf-8",
    )
    assert (
        report_main(
            [
                "--state-root",
                str(store.root),
                "--output-dir",
                str(tmp_path / "public"),
                "--campaign-id",
                store.campaign_id,
                "--task-id",
                "symbols-001",
                "--task-id",
                "patch-001",
                "--repetitions",
                "1",
                "--seed",
                "1",
                "--configuration-json",
                str(configuration_path),
            ]
        )
        == 2
    )
