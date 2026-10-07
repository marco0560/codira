"""Grade answer quality with calibrated facts and immutable adjudication.

Parameters
----------
None

Returns
-------
None
    Traceable quality evidence separate from operational and frozen grades.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

from scripts.agent_efficiency.contracts import canonical_fingerprint

DIMENSIONS = frozenset(
    {"correctness", "causality", "completeness", "evidence", "usability"}
)


def grade_quality(answer: str, rubric: Mapping[str, object]) -> dict[str, object]:
    """Assess explicit task criteria while leaving semantic judgment pending.

    Parameters
    ----------
    answer : str
        Complete response artifact.
    rubric : collections.abc.Mapping[str, object]
        Versioned task-specific criteria, equivalents and critical counterclaims.

    Returns
    -------
    dict[str, object]
        Per-dimension findings, exact evidence and immutable input digests.

    Raises
    ------
    ValueError
        If criterion identities, dimensions or match rules are malformed.
    """
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("quality rubric requires explicit task criteria")
    normalized = unicodedata.normalize("NFKC", answer).casefold()
    findings: list[dict[str, object]] = []
    ids: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, Mapping):
            raise TypeError("quality criterion must be an object")
        identifier = criterion.get("id")
        if (
            not isinstance(identifier, str)
            or identifier in ids
            or criterion.get("dimension") not in DIMENSIONS
        ):
            raise ValueError("invalid or repeated quality criterion")
        ids.add(identifier)
        semantic = criterion.get("semantic", False)
        accepted = criterion.get("accepted", [])
        counterclaims = criterion.get("counterclaims", [])
        if (
            not isinstance(accepted, list)
            or not isinstance(counterclaims, list)
            or not all(
                isinstance(item, str) and item for item in [*accepted, *counterclaims]
            )
        ):
            raise ValueError("quality match rules must be nonempty regular expressions")
        if not accepted and not semantic:
            raise ValueError("deterministic criterion needs accepted equivalents")
        support = [
            match.group()
            for pattern in accepted
            if (match := re.search(pattern, normalized))
        ]
        contrary = [
            match.group()
            for pattern in counterclaims
            if (match := re.search(pattern, normalized))
        ]
        status = (
            "contradicted"
            if contrary
            else "review_required"
            if semantic
            else "supported"
            if support
            else "missing"
        )
        findings.append(
            {
                "id": identifier,
                "dimension": criterion["dimension"],
                "required": criterion.get("required", True),
                "status": status,
                "support": support,
                "counterclaims": contrary,
                "requirement": criterion.get("requirement"),
            }
        )
    required = [item["status"] for item in findings if item["required"]]
    status = (
        "failed"
        if any(item in {"missing", "contradicted"} for item in required)
        else "review_required"
        if "review_required" in required
        else "passed"
    )
    return {
        "version": 1,
        "status": status,
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "rubric_sha256": canonical_fingerprint(rubric),
        "criteria": findings,
    }


def adjudicate_quality(
    answer: str, rubric: Mapping[str, object], review: Mapping[str, object]
) -> dict[str, object]:
    """Bind a blinded review to exact answer, rubric and quoted evidence.

    Parameters
    ----------
    answer : str
        Complete reviewed artifact.
    rubric : collections.abc.Mapping[str, object]
        Frozen task requirements.
    review : collections.abc.Mapping[str, object]
        Reviewer identity, input digests and a decision for every criterion.

    Returns
    -------
    dict[str, object]
        Adjudicated quality report containing the unchanged automatic report.

    Raises
    ------
    ValueError
        If review binding, evidence, decisions or reasons are incomplete.
    """
    original = grade_quality(answer, rubric)
    if any(
        review.get(key) != original[key] for key in ("answer_sha256", "rubric_sha256")
    ) or not review.get("reviewer"):
        raise ValueError("review does not bind the exact answer and rubric")
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise TypeError("review requires per-criterion decisions")
    criteria = cast("list[dict[str, object]]", original["criteria"])
    if {item.get("id") for item in decisions} != {
        item["id"] for item in criteria
    } or len(decisions) != len(criteria):
        raise ValueError("review decisions must cover every criterion exactly once")
    for item in decisions:
        if item.get("status") not in {
            "supported",
            "missing",
            "contradicted",
        } or not item.get("reason"):
            raise ValueError("review decisions require status and reason")
        quote = item.get("evidence")
        if (
            not isinstance(quote, str)
            or (quote and quote not in answer)
            or (item["status"] == "supported" and not quote)
        ):
            raise ValueError("review evidence must quote the exact answer")
    required_ids = {item["id"] for item in criteria if item["required"]}
    passed = all(
        item["status"] == "supported"
        for item in decisions
        if item["id"] in required_ids
    )
    return {
        "version": 1,
        "status": "passed" if passed else "failed",
        "original": original,
        "review": dict(review),
        "review_sha256": canonical_fingerprint(review),
    }


def write_blinded_packet(
    answer: str, rubric: Mapping[str, object], destination: Path
) -> str:
    """Persist a review packet without arm, model or earlier grade information.

    Parameters
    ----------
    answer : str
        Full response to review.
    rubric : collections.abc.Mapping[str, object]
        Explicit task requirements.
    destination : pathlib.Path
        New ignored durable artifact path.

    Returns
    -------
    str
        Packet digest usable as an opaque review identity.
    """
    packet = {"answer": answer, "rubric": dict(rubric)}
    digest = canonical_fingerprint(packet)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(packet, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    destination.chmod(0o600)
    return digest


def persist_adjudication(
    answer: str,
    rubric: Mapping[str, object],
    review: Mapping[str, object],
    destination: Path,
) -> dict[str, object]:
    """Write a new adjudication receipt without replacing any original grade.

    Parameters
    ----------
    answer : str
        Complete answer under review.
    rubric : collections.abc.Mapping[str, object]
        Frozen requirements.
    review : collections.abc.Mapping[str, object]
        Quote-bound reviewer decisions.
    destination : pathlib.Path
        Fresh private durable receipt path.

    Returns
    -------
    dict[str, object]
        Original findings, reviewed decision and all input digests.
    """
    report = adjudicate_quality(answer, rubric, review)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    destination.chmod(0o600)
    return report
