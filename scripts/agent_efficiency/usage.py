"""Normalize provider usage from one completed Codex JSONL turn.

The benchmark treats cached input as a subset of input, not an additional
chargeable category.  Missing or ambiguous provider accounting is represented
explicitly and makes a run ineligible for paired token comparisons.
"""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class UsageError(ValueError):
    """Report malformed or ambiguous provider usage evidence.

    Parameters
    ----------
    detail : str
        Deterministic explanation of the rejected evidence.

    Returns
    -------
    None
        The exception carries the evidence failure detail.
    """


@dataclass(frozen=True)
class NormalizedUsage:
    """Hold normalized usage and comparison eligibility for one turn.

    Parameters
    ----------
    values : Mapping[str, int]
        Canonical provider-reported token counters.
    complete : bool
        Whether all counters were present and semantically valid.
    observed_total_tokens : int or None
        Input plus output plus reasoning-output tokens, excluding cached input.

    Returns
    -------
    None
        Instances preserve the provider accounting decision.
    """

    values: Mapping[str, int]
    complete: bool
    observed_total_tokens: int | None

    def as_document(self) -> dict[str, int]:
        """Return schema-compatible usage counters.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, int]
            A detached mapping of the four canonical counters.
        """

        return {field: self.values[field] for field in USAGE_FIELDS}


def incomplete_usage() -> NormalizedUsage:
    """Return the explicit non-comparable representation for absent usage.

    Parameters
    ----------
    None

    Returns
    -------
    NormalizedUsage
        Zero-valued schema-compatible counters with incomplete accounting.
    """

    return NormalizedUsage({field: 0 for field in USAGE_FIELDS}, False, None)


def normalize_completed_turn(events: Sequence[Mapping[str, object]]) -> NormalizedUsage:
    """Normalize exactly one completed-turn usage payload.

    Parameters
    ----------
    events : Sequence[Mapping[str, object]]
        Parsed JSONL events captured for a single benchmark attempt.

    Returns
    -------
    NormalizedUsage
        Complete normalized usage, or an explicit incomplete representation
        when the unique completion event has no usage payload.

    Raises
    ------
    UsageError
        If terminal events are duplicated or usage counters are invalid.
    """

    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(completed) != 1:
        raise UsageError("JSONL must contain exactly one turn.completed event")
    usage = completed[0].get("usage")
    if usage is None:
        return incomplete_usage()
    if not isinstance(usage, Mapping):
        raise UsageError("turn completion usage must be an object")
    values: dict[str, int] = {}
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise UsageError(f"usage field {field} must be a non-negative integer")
        values[field] = value
    if values["cached_input_tokens"] > values["input_tokens"]:
        raise UsageError("cached_input_tokens cannot exceed input_tokens")
    total = (
        values["input_tokens"]
        + values["output_tokens"]
        + values["reasoning_output_tokens"]
    )
    return NormalizedUsage(values, True, total)
