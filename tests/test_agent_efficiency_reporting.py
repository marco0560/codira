"""Test deterministic public reporting for agent-efficiency campaigns."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING, cast

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
    assert report["summary"]["operational_pass_count"] == 4
    assert report["summary"]["task_oracle_pass_count"] == 4
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    assert {
        attempt["operational_calibration"]["source"]
        for attempt in attempts
        if isinstance(attempt, dict)
    } == {"legacy_derived"}
    assert "Outcome axes" in first_markdown
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


def test_report_exposes_safe_oracle_and_trajectory_diagnostics(
    tmp_path: Path,
) -> None:
    """Publish useful stage and progress evidence without private content.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated campaign record directory.

    Returns
    -------
    None
        Public output retains safe checks and counters only.
    """

    store = _store(tmp_path)
    record_path = next(store.records_root.glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["result"]["operational_calibration"] = {
        "status": "passed",
        "failure_class": None,
    }
    record["result"]["task_oracle"] = {
        "status": "passed",
        "failure_class": None,
        "fingerprint": "a" * 64,
    }
    record["result"]["task_oracle"]["checks"] = [
        "text_contains[0]:passed",
        "patch.protected_command:failed:exit=1:stdout_sha256=" + "a" * 64,
        "unsafe /home/private/source.py: redacted",
    ]
    record["evidence"]["oracle_trace"] = {
        "path": "oracle-trace/manifest.json",
        "manifest_sha256": "private-trace-digest",
        "raw_stderr": "private protected test failure details",
    }
    record["evidence"]["trajectory"] = {
        "status": "available",
        "event_count": 8,
        "agent_message_count": 2,
        "reasoning_item_count": 1,
        "command_execution_count": 3,
        "successful_command_count": 2,
        "failed_command_count": 1,
        "unknown_command_exit_count": 0,
        "repeated_command_count": 1,
        "mcp_call_count": 2,
        "mcp_repeated_call_count": 0,
        "file_change_event_count": 1,
        "changed_file_count": 2,
        "first_file_change_event_index": 7,
        "last_file_change_event_index": 7,
        "mcp_tool_counts": [{"tool": "codira_search", "calls": 2}],
        "progress_markers": [{"event_index": 7, "kind": "file_change"}],
        "progress_markers_truncated": False,
        "omitted_progress_marker_count": 0,
        "raw_query": "do not publish this private query",
    }
    evidence = record["evidence"]
    record["evidence_fingerprint"] = sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record_path.write_text(json.dumps(record), encoding="utf-8")

    report = build_report(store)
    attempts = cast("list[object]", report["attempts"])
    attempt = next(
        item
        for item in attempts
        if isinstance(item, dict)
        and item["attempt_id"] == record["attempt"]["attempt_id"]
    )
    public = json.dumps(report, sort_keys=True)
    markdown = render_markdown(report)

    assert "text_contains[0]:passed" in public
    assert "codira_search" in public
    assert "do not publish" not in public
    assert "private-trace-digest" not in public
    assert "private protected test failure details" not in public
    assert "oracle-trace/manifest.json" not in public
    assert "/home/private" not in public
    assert isinstance(attempt, dict)
    assert attempt["trajectory"]["successful_command_count"] == 2
    assert "## Oracle checks" in markdown
    assert "## Trajectory progress" in markdown


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


def test_report_excludes_unsuccessful_pairs_with_complete_usage(tmp_path: Path) -> None:
    """Exclude task failures even when both provider usage records are complete.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state root.

    Returns
    -------
    None
        Task failures never enter token-saving statistics.
    """

    store = _store(tmp_path)
    for record_path in store.records_root.glob("symbols-001-*.json"):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["result"]["outcome"] = "oracle_failure"
        record["result"]["failure_class"] = "deterministic_oracle"
        evidence = record["evidence"]
        record["evidence_fingerprint"] = sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        record_path.write_text(json.dumps(record), encoding="utf-8")

    report = build_report(store)
    assert report["paired_token_differences"] == [
        {
            "pair_id": "patch-001-r01",
            "baseline_tokens": 33,
            "codira_mcp_tokens": 44,
            "token_difference": 11,
        }
    ]
    assert report["exclusions"] == [
        {"pair_id": "symbols-001-r01", "reason": "unsuccessful_outcome"}
    ]
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    symbols_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt, dict) and attempt["task_id"] == "symbols-001"
    ]
    assert {
        attempt["operational_calibration"]["status"] for attempt in symbols_attempts
    } == {"passed"}
    assert {attempt["task_oracle"]["status"] for attempt in symbols_attempts} == {
        "failed"
    }


def test_report_preserves_explicit_persisted_outcome_axes(tmp_path: Path) -> None:
    """Report new two-axis records without collapsing oracle and operation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary campaign state root.

    Returns
    -------
    None
        Assertions distinguish persisted operational and oracle outcomes.
    """

    store = _store(tmp_path)
    record_path = next(store.records_root.glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["result"]["outcome"] = "oracle_failure"
    record["result"]["failure_class"] = "deterministic_oracle"
    record["result"]["operational_calibration"] = {
        "status": "passed",
        "failure_class": None,
    }
    record["result"]["task_oracle"] = {
        "status": "failed",
        "failure_class": "deterministic_oracle",
        "fingerprint": "a" * 64,
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")

    report = build_report(store)
    attempts = report["attempts"]
    assert isinstance(attempts, list)
    attempt = next(
        item
        for item in attempts
        if isinstance(item, dict)
        and item["attempt_id"] == record["attempt"]["attempt_id"]
    )
    assert attempt["operational_calibration"] == {
        "status": "passed",
        "failure_class": None,
        "redaction_applied": False,
        "source": "persisted",
    }
    assert attempt["task_oracle"] == {
        "status": "failed",
        "failure_class": "deterministic_oracle",
        "fingerprint": "a" * 64,
        "checks": [],
        "redaction_applied": False,
        "source": "persisted",
    }


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
