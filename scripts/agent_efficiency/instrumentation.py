"""Measure model-visible overhead and paired uncertainty without paid calls.

Parameters
----------
None

Returns
-------
None
    Content-free payload measurements and reproducible paired statistics.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from statistics import mean, median


def request_measurement(payload: bytes) -> dict[str, object]:
    """Measure the exact constrained wire request without retaining its text.

    Parameters
    ----------
    payload : bytes
        Actual model-visible request body after provider control mapping.

    Returns
    -------
    dict[str, object]
        Wire bytes/digest, tool-schema bytes, instructions and input sizes.
        Token attribution remains unknown until provider usage is received.
    """
    document = json.loads(payload)
    result: dict[str, object] = {
        "wire_bytes": len(payload),
        "wire_sha256": hashlib.sha256(payload).hexdigest(),
        "attributed_tokens": None,
    }
    for key in ("tools", "instructions", "input"):
        value = document.get(key, [] if key != "instructions" else "")
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        result[f"{key}_chars"] = len(encoded)
        result[f"{key}_bytes"] = len(encoded.encode())
    return result


def evidence_measurement(
    events: Sequence[Mapping[str, object]], anchors: Sequence[str]
) -> dict[str, object]:
    """Locate reference-evidence arrival and subsequent source reads.

    Parameters
    ----------
    events : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Complete recorded events in observed order.
    anchors : collections.abc.Sequence[str]
        Protected reference locators defined before the run.

    Returns
    -------
    dict[str, object]
        Exact output sizes and first locator-hit event. A locator hit is an
        instrumentation proxy, not proof of semantic usefulness.
    """
    first: int | None = None
    followup_reads = 0
    payloads: list[dict[str, object]] = []
    for index, event in enumerate(events):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if item.get("type") not in {"mcp_tool_call", "command_execution"}:
            continue
        output = (
            item.get("result")
            if item.get("type") == "mcp_tool_call"
            else item.get("aggregated_output")
        )
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        payloads.append(
            {
                "event_index": index,
                "kind": item["type"],
                "chars": len(text),
                "bytes": len(text.encode()),
                "tokens": None,
            }
        )
        if first is None and anchors and all(anchor in text for anchor in anchors):
            first = index
        elif first is not None and item.get("type") == "command_execution":
            command = str(item.get("command", ""))
            if any(
                word in command
                for word in ("cat ", "sed ", "rg ", "head ", "read_text(")
            ):
                followup_reads += 1
    return {
        "first_reference_evidence_event": first,
        "followup_source_reads": followup_reads,
        "payloads": payloads,
        "timing_scope": "event_order_only; exact provider and preparation durations recorded separately",
    }


def paired_distribution(
    differences: Sequence[float], *, seed: int = 53
) -> dict[str, object]:
    """Describe paired deltas with reproducible bootstrap mean uncertainty.

    Parameters
    ----------
    differences : collections.abc.Sequence[float]
        Assisted minus baseline differences for admitted complete pairs.
    seed : int, optional
        Frozen local bootstrap seed.

    Returns
    -------
    dict[str, object]
        Sample count, median/range and 95 percent bootstrap interval. The
        interval is unavailable for fewer than two independent task pairs.
    """
    values = list(differences)
    if not values:
        return {"count": 0, "mean": None, "median": None, "mean_ci95": None}
    rng = random.Random(seed)
    samples = (
        sorted(mean(rng.choices(values, k=len(values))) for _ in range(2000))
        if len(values) >= 2
        else []
    )
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
        "mean_ci95": [samples[49], samples[1949]] if samples else None,
        "method": "paired bootstrap; resample task means, not repeated attempts",
        "seed": seed,
    }
