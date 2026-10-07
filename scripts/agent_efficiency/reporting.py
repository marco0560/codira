"""Generate deterministic public reports from validated campaign records.

Raw JSONL and process output never enter this module.  It accepts only the
validated immutable records exposed by :mod:`campaign_state`, then emits a
canonical JSON document and a Markdown rendering generated from that document.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import mean, median
from typing import TYPE_CHECKING, cast

from scripts.agent_efficiency.campaign_state import CampaignStateError, CampaignStore

if TYPE_CHECKING:
    from pathlib import Path

REPORT_VERSION = "1.1"
_SENSITIVE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|/(?:[^\s/]+/)+|\b(?:sk|key|token)[_-][^\s]+)",
    re.IGNORECASE,
)


class ReportError(ValueError):
    """Report an invalid or incomparable reporting input.

    Parameters
    ----------
    detail : str
        Deterministic public-safe validation detail.
    """


@dataclass(frozen=True)
class ReportArtifacts:
    """Identify the two deterministic public artifacts written by one render.

    Parameters
    ----------
    json_path : pathlib.Path
        Canonical JSON report path.
    markdown_path : pathlib.Path
        Markdown rendering derived only from the JSON report.
    """

    json_path: Path
    markdown_path: Path


def _integer(value: object, field: str) -> int:
    """Require one non-negative integer reporting value.

    Parameters
    ----------
    value : object
        Candidate JSON value.
    field : str
        Public field name for a deterministic failure.

    Returns
    -------
    int
        Valid non-negative integer.

    Raises
    ------
    ReportError
        If the value is not a non-negative integer.
    """

    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ReportError(f"{field} is not a non-negative integer")
    return value


def _seconds(value: object) -> float:
    """Require one finite non-negative elapsed-time value.

    Parameters
    ----------
    value : object
        Candidate elapsed-time JSON value.

    Returns
    -------
    float
        Valid non-negative elapsed seconds.

    Raises
    ------
    ReportError
        If the value is not a finite non-negative number.
    """

    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < 0
        or not math.isfinite(value)
    ):
        raise ReportError("elapsed_seconds is not a finite non-negative number")
    return float(value)


def _redact_failure(value: object) -> tuple[str | None, bool]:
    """Return a public-safe failure description without paths or credentials.

    Parameters
    ----------
    value : object
        Private record failure classification.

    Returns
    -------
    tuple[str or None, bool]
        Sanitized value and whether content was withheld.
    """

    if value is None:
        return None, False
    if not isinstance(value, str):
        return "redacted", True
    if _SENSITIVE.search(value) or len(value) > 160:
        return "redacted", True
    return value, False


def _percentile90(values: list[float]) -> float | None:
    """Return the nearest-rank p90 for a non-empty numeric sample.

    Parameters
    ----------
    values : list[float]
        Unordered non-negative sample.

    Returns
    -------
    float or None
        The nearest-rank p90, or ``None`` for an empty sample.
    """

    if not values:
        return None
    ordered = sorted(values)
    return ordered[(9 * len(ordered) - 1) // 10]


def _outcome_axes(result: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return explicit operational and task-oracle reporting axes.

    Parameters
    ----------
    result : Mapping[str, object]
        Validated run result, possibly written before explicit axes existed.

    Returns
    -------
    dict[str, dict[str, object]]
        Public-safe axis documents with their persistence source.

    Notes
    -----
    Legacy immutable records are projected without rewriting them. Reaching an
    oracle outcome proves that the operational path completed; infrastructure
    and cancellation outcomes leave the task oracle unevaluated.
    """

    persisted_operational = result.get("operational_calibration")
    persisted_oracle = result.get("task_oracle")
    if isinstance(persisted_operational, Mapping) and isinstance(
        persisted_oracle, Mapping
    ):
        operational_failure, operational_redacted = _redact_failure(
            persisted_operational.get("failure_class")
        )
        oracle_failure, oracle_redacted = _redact_failure(
            persisted_oracle.get("failure_class")
        )
        return {
            "operational_calibration": {
                "status": persisted_operational.get("status"),
                "failure_class": operational_failure,
                "redaction_applied": operational_redacted,
                "source": "persisted",
            },
            "task_oracle": {
                "status": persisted_oracle.get("status"),
                "failure_class": oracle_failure,
                "fingerprint": persisted_oracle.get("fingerprint"),
                "checks": _safe_oracle_checks(persisted_oracle.get("checks")),
                "redaction_applied": oracle_redacted,
                "source": "persisted",
            },
        }

    outcome = result.get("outcome")
    failure, redacted = _redact_failure(result.get("failure_class"))
    operational_passed = outcome in {"success", "oracle_failure"}
    if outcome == "success":
        oracle_status = "passed"
    elif outcome == "oracle_failure":
        oracle_status = "failed"
    else:
        oracle_status = "not_evaluated"
    return {
        "operational_calibration": {
            "status": "passed" if operational_passed else "failed",
            "failure_class": None if operational_passed else failure,
            "redaction_applied": False if operational_passed else redacted,
            "source": "legacy_derived",
        },
        "task_oracle": {
            "status": oracle_status,
            "failure_class": failure if oracle_status == "failed" else None,
            "fingerprint": None,
            "checks": [],
            "redaction_applied": redacted if oracle_status == "failed" else False,
            "source": "legacy_derived",
        },
    }


def _safe_oracle_checks(value: object) -> list[str]:
    """Project deterministic oracle checks without unsafe text or paths.

    Parameters
    ----------
    value : object
        Candidate persisted list of stable oracle check strings.

    Returns
    -------
    list[str]
        Public-safe checks with path-like or overlong values withheld.
    """

    if not isinstance(value, list):
        return []
    checks: list[str] = []
    for item in value:
        safe, redacted = _redact_failure(item)
        if safe is not None:
            checks.append("redacted" if redacted else safe)
    return checks


def _trajectory_public(value: object) -> dict[str, object] | None:
    """Return an allowlisted trajectory summary for public reporting.

    Parameters
    ----------
    value : object
        Private runtime trajectory evidence.

    Returns
    -------
    dict[str, object] or None
        Public-safe counters, tool names, and progress markers, or ``None`` when
        no trajectory summary was recorded.

    Raises
    ------
    ReportError
        If a present trajectory summary has invalid counter or marker fields.
    """

    if not isinstance(value, Mapping):
        return None
    status = value.get("status")
    if status == "unavailable":
        return {"status": "unavailable"}
    if status != "available":
        raise ReportError("trajectory status is invalid")
    count_fields = (
        "event_count",
        "agent_message_count",
        "reasoning_item_count",
        "command_execution_count",
        "successful_command_count",
        "failed_command_count",
        "unknown_command_exit_count",
        "repeated_command_count",
        "mcp_call_count",
        "mcp_repeated_call_count",
        "file_change_event_count",
        "changed_file_count",
    )
    summary: dict[str, object] = {
        "status": "available",
        **{key: _integer(value.get(key), f"trajectory.{key}") for key in count_fields},
    }
    for key in ("first_file_change_event_index", "last_file_change_event_index"):
        field = value.get(key)
        if field is not None:
            summary[key] = _integer(field, f"trajectory.{key}")
        else:
            summary[key] = None
    tool_counts = value.get("mcp_tool_counts")
    if not isinstance(tool_counts, list):
        raise ReportError("trajectory mcp_tool_counts is invalid")
    safe_tools: list[dict[str, object]] = []
    for item in tool_counts:
        if not isinstance(item, Mapping):
            raise ReportError("trajectory MCP tool entry is invalid")
        tool = item.get("tool")
        if not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", tool):
            raise ReportError("trajectory MCP tool name is invalid")
        safe_tools.append({"tool": tool, "calls": _integer(item.get("calls"), "calls")})
    summary["mcp_tool_counts"] = safe_tools
    markers = value.get("progress_markers")
    if not isinstance(markers, list):
        raise ReportError("trajectory progress_markers is invalid")
    safe_markers: list[dict[str, object]] = []
    allowed_kinds = {
        "command_succeeded",
        "command_failed",
        "mcp_call",
        "file_change",
    }
    for marker in markers:
        if not isinstance(marker, Mapping):
            raise ReportError("trajectory progress marker is invalid")
        kind = marker.get("kind")
        if kind not in allowed_kinds:
            raise ReportError("trajectory progress marker kind is invalid")
        safe_markers.append(
            {
                "event_index": _integer(marker.get("event_index"), "event_index"),
                "kind": kind,
            }
        )
    summary["progress_markers"] = safe_markers
    summary["progress_markers_truncated"] = (
        value.get("progress_markers_truncated") is True
    )
    summary["omitted_progress_marker_count"] = _integer(
        value.get("omitted_progress_marker_count"),
        "trajectory.omitted_progress_marker_count",
    )
    return summary


def _axis_status_count(
    attempts: list[dict[str, object]], axis: str, status: str
) -> int:
    """Count attempts with one explicit outcome-axis status.

    Parameters
    ----------
    attempts : list[dict[str, object]]
        Public attempt projections containing explicit outcome axes.
    axis : str
        Outcome-axis field to inspect.
    status : str
        Status value to count.

    Returns
    -------
    int
        Number of matching attempt outcomes.

    Raises
    ------
    ReportError
        If an attempt lacks the expected outcome-axis mapping.
    """

    count = 0
    for attempt in attempts:
        outcome_axis = attempt.get(axis)
        if not isinstance(outcome_axis, Mapping):
            raise ReportError(f"attempt {axis} axis is invalid")
        count += outcome_axis.get("status") == status
    return count


def _attempt_public(record: Mapping[str, object]) -> dict[str, object]:
    """Project one validated private record into a public per-attempt entry.

    Parameters
    ----------
    record : Mapping[str, object]
        Immutable validated record from ``CampaignStore``.

    Returns
    -------
    dict[str, object]
        Transcript-free public attempt summary.

    Raises
    ------
    ReportError
        If required validated-record fields have an unexpected shape.
    """

    attempt = record.get("attempt")
    result = record.get("result")
    evidence = record.get("evidence")
    if not all(isinstance(value, Mapping) for value in (attempt, result, evidence)):
        raise ReportError("validated record lacks reporting fields")
    attempt = cast("Mapping[str, object]", attempt)
    result = cast("Mapping[str, object]", result)
    evidence = cast("Mapping[str, object]", evidence)
    usage = result.get("usage")
    if not isinstance(usage, Mapping):
        raise ReportError("result usage is invalid")
    usage = cast("Mapping[str, object]", usage)
    failure, redacted = _redact_failure(result.get("failure_class"))
    public = {
        "attempt_id": attempt.get("attempt_id"),
        "pair_id": attempt.get("pair_id"),
        "task_id": attempt.get("task_id"),
        "repetition": attempt.get("repetition"),
        "assistance_mode": result.get("assistance_mode"),
        "outcome": result.get("outcome"),
        "failure_class": failure,
        "redaction_applied": redacted,
        "usage_complete": result.get("usage_complete"),
        "usage": {
            key: _integer(usage.get(key), f"usage.{key}")
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            )
        },
        "elapsed_seconds": _seconds(evidence.get("elapsed_seconds")),
        "tool_call_count": _integer(
            evidence.get("jsonl_event_count"), "jsonl_event_count"
        ),
        "trajectory": _trajectory_public(evidence.get("trajectory")),
    }
    public.update(_outcome_axes(result))
    return public


def build_report(store: CampaignStore) -> dict[str, object]:
    """Build a deterministic public report from one frozen campaign store.

    Parameters
    ----------
    store : CampaignStore
        Campaign state whose records are validated before reporting.

    Returns
    -------
    dict[str, object]
        Canonical public report with per-attempt summaries, pair deltas, and
        explicit incomparable or incomplete exclusions.

    Raises
    ------
    ReportError
        If stored records cannot form a public report.
    """

    try:
        records = store.validated_records()
    except CampaignStateError as error:
        raise ReportError(str(error)) from error
    attempts = [_attempt_public(records[key]) for key in sorted(records)]
    by_pair: dict[str, dict[str, dict[str, object]]] = {}
    for attempt in attempts:
        pair_id = attempt.get("pair_id")
        mode = attempt.get("assistance_mode")
        if not isinstance(pair_id, str) or not isinstance(mode, str):
            raise ReportError("public attempt identity is invalid")
        by_pair.setdefault(pair_id, {})[mode] = attempt
    pairs: list[dict[str, object]] = []
    exclusions: list[dict[str, str]] = []
    deltas: list[float] = []
    elapsed: list[float] = []
    for attempt in attempts:
        value = attempt.get("elapsed_seconds")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        ):
            elapsed.append(float(value))
    for pair_id, members in sorted(by_pair.items()):
        baseline = members.get("baseline")
        assisted = members.get("codira-mcp")
        if baseline is None or assisted is None:
            exclusions.append({"pair_id": pair_id, "reason": "incomplete_pair"})
            continue
        if not baseline["usage_complete"] or not assisted["usage_complete"]:
            exclusions.append({"pair_id": pair_id, "reason": "incomplete_usage"})
            continue
        if baseline["outcome"] != "success" or assisted["outcome"] != "success":
            exclusions.append({"pair_id": pair_id, "reason": "unsuccessful_outcome"})
            continue
        baseline_usage = baseline["usage"]
        assisted_usage = assisted["usage"]
        assert isinstance(baseline_usage, Mapping) and isinstance(
            assisted_usage, Mapping
        )
        baseline_total = sum(
            _integer(baseline_usage.get(key), key)
            for key in ("input_tokens", "output_tokens")
        )
        assisted_total = sum(
            _integer(assisted_usage.get(key), key)
            for key in ("input_tokens", "output_tokens")
        )
        delta = assisted_total - baseline_total
        deltas.append(float(delta))
        pairs.append(
            {
                "pair_id": pair_id,
                "baseline_tokens": baseline_total,
                "codira_mcp_tokens": assisted_total,
                "token_difference": delta,
            }
        )
    return {
        "schema_version": REPORT_VERSION,
        "campaign_id": store.campaign_id,
        "configuration_fingerprint": store.configuration_fingerprint,
        "attempts": attempts,
        "paired_token_differences": pairs,
        "exclusions": exclusions,
        "instrumented_comparison": _instrumented_comparison(attempts, records),
        "summary": {
            "attempt_count": len(attempts),
            "pair_count": len(pairs),
            "excluded_pair_count": len(exclusions),
            "median_token_difference": median(deltas) if deltas else None,
            "p90_token_difference": _percentile90(deltas),
            "median_elapsed_seconds": median(elapsed) if elapsed else None,
            "p90_elapsed_seconds": _percentile90(elapsed),
            "operational_pass_count": _axis_status_count(
                attempts, "operational_calibration", "passed"
            ),
            "task_oracle_pass_count": _axis_status_count(
                attempts, "task_oracle", "passed"
            ),
            "task_oracle_fail_count": _axis_status_count(
                attempts, "task_oracle", "failed"
            ),
            "task_oracle_not_evaluated_count": _axis_status_count(
                attempts, "task_oracle", "not_evaluated"
            ),
        },
    }


def _oracle_check_lines(attempts: list[object]) -> list[str]:
    """Render validated oracle diagnostics as table rows.

    Parameters
    ----------
    attempts : list[object]
        Canonical public attempt projections.

    Returns
    -------
    list[str]
        Markdown heading, table header, and rows.

    Raises
    ------
    ReportError
        If an attempt or its task-oracle check list is malformed.
    """

    lines = ["", "## Oracle checks", "", "| Attempt | Checks |", "| --- | --- |"]
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ReportError("report attempt is invalid")
        oracle = attempt.get("task_oracle")
        if not isinstance(oracle, Mapping):
            raise ReportError("report task-oracle axis is invalid")
        checks = oracle.get("checks")
        if not isinstance(checks, list) or not all(
            isinstance(item, str) for item in checks
        ):
            raise ReportError("report oracle checks are invalid")
        lines.append(
            f"| {attempt['attempt_id']} | {'; '.join(checks) if checks else 'none recorded'} |"
        )
    return lines


def _trajectory_lines(attempts: list[object]) -> list[str]:
    """Render validated safe trajectory summaries as table rows.

    Parameters
    ----------
    attempts : list[object]
        Canonical public attempt projections.

    Returns
    -------
    list[str]
        Markdown heading, table header, and rows.

    Raises
    ------
    ReportError
        If an attempt projection is malformed.
    """

    lines = [
        "",
        "## Trajectory progress",
        "",
        "| Attempt | Commands ok/failed | Repeated commands | MCP calls/repeats | File changes |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ReportError("report attempt is invalid")
        trajectory = attempt.get("trajectory")
        if (
            not isinstance(trajectory, Mapping)
            or trajectory.get("status") != "available"
        ):
            lines.append(f"| {attempt['attempt_id']} | unavailable | — | — | — |")
            continue
        lines.append(
            f"| {attempt['attempt_id']} | {trajectory['successful_command_count']}/{trajectory['failed_command_count']} | "
            f"{trajectory['repeated_command_count']} | "
            f"{trajectory['mcp_call_count']}/{trajectory['mcp_repeated_call_count']} | "
            f"{trajectory['file_change_event_count']}/{trajectory['changed_file_count']} |"
        )
    return lines


def render_markdown(report: Mapping[str, object]) -> str:
    """Render deterministic Markdown only from a canonical public report.

    Parameters
    ----------
    report : Mapping[str, object]
        Canonical report returned by :func:`build_report`.

    Returns
    -------
    str
        Public Markdown rendering with no raw evidence content.

    Raises
    ------
    ReportError
        If the supplied report lacks the canonical public sections.
    """

    campaign_id = report.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise ReportError("report campaign_id is invalid")
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        raise ReportError("report summary is invalid")
    lines = [
        "# Agent-efficiency benchmark report",
        "",
        f"Campaign: `{campaign_id}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in (
        "attempt_count",
        "pair_count",
        "excluded_pair_count",
        "median_token_difference",
        "p90_token_difference",
        "median_elapsed_seconds",
        "p90_elapsed_seconds",
        "operational_pass_count",
        "task_oracle_pass_count",
        "task_oracle_fail_count",
        "task_oracle_not_evaluated_count",
    ):
        lines.append(f"| {key} | {summary[key]} |")
    lines.extend(
        [
            "",
            "## Outcome axes",
            "",
            "| Attempt | Operational calibration | Task oracle | Source |",
            "| --- | --- | --- | --- |",
        ]
    )
    attempts = report.get("attempts")
    if not isinstance(attempts, list):
        raise ReportError("report attempts are invalid")
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ReportError("report attempt is invalid")
        operational = attempt.get("operational_calibration")
        oracle = attempt.get("task_oracle")
        if not isinstance(operational, Mapping) or not isinstance(oracle, Mapping):
            raise ReportError("report outcome axes are invalid")
        source = operational.get("source")
        if source != oracle.get("source"):
            raise ReportError("report outcome-axis sources differ")
        lines.append(
            f"| {attempt['attempt_id']} | {operational['status']} | {oracle['status']} | {source} |"
        )
    lines.extend(_oracle_check_lines(attempts))
    lines.extend(_trajectory_lines(attempts))
    lines.extend(
        [
            "",
            "## Paired token differences",
            "",
            "| Pair | Baseline | Codira MCP | Difference |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    pairs = report.get("paired_token_differences")
    if not isinstance(pairs, list):
        raise ReportError("paired_token_differences is invalid")
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise ReportError("paired token difference is invalid")
        lines.append(
            f"| {pair['pair_id']} | {pair['baseline_tokens']} | {pair['codira_mcp_tokens']} | {pair['token_difference']} |"
        )
    exclusions = report.get("exclusions")
    if not isinstance(exclusions, list):
        raise ReportError("report exclusions are invalid")
    lines.extend(["", "## Exclusions", "", "| Pair | Reason |", "| --- | --- |"])
    for exclusion in exclusions:
        if not isinstance(exclusion, Mapping):
            raise ReportError("report exclusion is invalid")
        lines.append(f"| {exclusion['pair_id']} | {exclusion['reason']} |")
    return "\n".join(lines) + "\n"


def write_report(store: CampaignStore, output_dir: Path) -> ReportArtifacts:
    """Write canonical JSON and its deterministic Markdown rendering.

    Parameters
    ----------
    store : CampaignStore
        Validated campaign state to report.
    output_dir : pathlib.Path
        Public-safe destination directory.

    Returns
    -------
    ReportArtifacts
        Paths of the generated JSON and Markdown files.
    """

    report = build_report(store)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    markdown_path = output_dir / "report.md"
    json_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return ReportArtifacts(json_path, markdown_path)


def _instrumented_comparison(
    attempts: list[dict[str, object]], records: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    """Report all measured trajectories and task-level paired uncertainty.

    Parameters
    ----------
    attempts : list[dict[str, object]]
        Validated public attempt projections, including failures.
    records : collections.abc.Mapping[str, collections.abc.Mapping[str, object]]
        Immutable private records; only numeric observations are projected.

    Returns
    -------
    dict[str, object]
        All-attempt costs/cache/payload counters and independent task means.
        Missing observations remain unknown rather than assumed zero.
    """
    from scripts.agent_efficiency.instrumentation import paired_distribution

    measured: list[dict[str, object]] = []
    pairs: dict[str, dict[str, dict[str, object]]] = {}
    costs: list[float] = []
    failed_costs: list[float] = []
    for attempt in attempts:
        identifier = str(attempt["attempt_id"])
        evidence = cast("Mapping[str, object]", records[identifier]["evidence"])
        responses = evidence.get("provider_responses", [])
        upstream = (
            [
                item
                for item in responses
                if isinstance(item, Mapping) and item.get("source") == "upstream"
            ]
            if isinstance(responses, list)
            else []
        )
        known = bool(upstream) and all(
            isinstance(item.get("estimated_cost_usd_at_ceiling"), (int, float))
            for item in upstream
        )
        cost = (
            sum(float(item["estimated_cost_usd_at_ceiling"]) for item in upstream)
            if known
            else None
        )
        if cost is not None:
            costs.append(cost)
            if (
                cast("Mapping[str, object]", attempt["task_oracle"])["status"]
                != "passed"
            ):
                failed_costs.append(cost)
        usage = cast("Mapping[str, object]", attempt["usage"])
        stage = evidence.get("stage_measurement", {})
        stage = stage if isinstance(stage, Mapping) else {}
        payloads = stage.get("payloads", [])
        payload_bytes = (
            sum(
                int(item["bytes"])
                for item in payloads
                if isinstance(item, Mapping) and isinstance(item.get("bytes"), int)
            )
            if isinstance(payloads, list)
            else None
        )
        preparation = evidence.get("environment_preparation", {})
        prep_seconds = (
            preparation.get("elapsed_seconds")
            if isinstance(preparation, Mapping)
            else None
        )
        phases = evidence.get("phase_timings", {})
        phases = phases if isinstance(phases, Mapping) else {}
        measured.append(
            {
                "attempt_id": identifier,
                "cost_usd_at_ceiling": cost,
                "cost_scope": "all received upstream responses; invoice cost unknown",
                "cached_input_tokens": usage["cached_input_tokens"],
                "uncached_input_tokens": int(str(usage["input_tokens"]))
                - int(str(usage["cached_input_tokens"])),
                "tool_payload_bytes": payload_bytes,
                "first_reference_evidence_event": stage.get(
                    "first_reference_evidence_event"
                ),
                "followup_source_reads": stage.get("followup_source_reads"),
                "phase_seconds": {
                    key: value
                    for key, value in phases.items()
                    if key
                    in {
                        "fixture_export_seconds",
                        "environment_preparation_seconds",
                        "index_preparation_seconds",
                        "container_execution_seconds",
                        "grading_seconds",
                    }
                    and isinstance(value, (int, float))
                    and math.isfinite(value)
                    and value >= 0
                },
                "preparation_seconds": prep_seconds
                if isinstance(prep_seconds, (int, float))
                else None,
            }
        )
        if attempt["usage_complete"]:
            pairs.setdefault(str(attempt["pair_id"]), {})[
                str(attempt["assistance_mode"])
            ] = attempt
    task_deltas: dict[str, list[float]] = {}
    for pair in pairs.values():
        if "baseline" not in pair or "codira-mcp" not in pair:
            continue
        baseline, assisted = pair["baseline"], pair["codira-mcp"]
        bu, au = (
            cast("Mapping[str, object]", baseline["usage"]),
            cast("Mapping[str, object]", assisted["usage"]),
        )
        difference = sum(
            int(str(au[key])) - int(str(bu[key]))
            for key in ("input_tokens", "output_tokens")
        )
        task_deltas.setdefault(str(baseline["task_id"]), []).append(float(difference))
    return {
        "attempts": measured,
        "known_cost_usd_at_ceiling": sum(costs),
        "unknown_cost_attempt_count": len(attempts) - len(costs),
        "nonpassing_known_cost_usd_at_ceiling": sum(failed_costs),
        "all_usage_complete_pairs": paired_distribution(
            [mean(values) for values in task_deltas.values()]
        ),
        "uncertainty_scope": "bootstrap over independent task means; includes unsuccessful trajectories; quality reported separately",
    }
