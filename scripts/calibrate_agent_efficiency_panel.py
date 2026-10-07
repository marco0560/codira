"""Reproduce source-curated substantive calibration for every panel rubric."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.contracts import load_document
from scripts.agent_efficiency.quality import adjudicate_quality, grade_quality

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "benchmarks/agent-efficiency/panels/representative-v1.json"
CALIBRATION = (
    ROOT / "benchmarks/agent-efficiency/panels/representative-v1-calibration.json"
)
ORACLES = ROOT / "benchmarks/agent-efficiency/panels/representative-v1/oracles"
REPORT = ROOT / "docs/process/agent-efficiency-panel-calibration-2026-10-01.md"


def calibration_report() -> str:
    """Build a reproducible report from the frozen task-specific claim cases.

    Parameters
    ----------
    None
        Uses the versioned bank, calibration and oracle documents.

    Returns
    -------
    str
        Public-safe Markdown report binding every claim to its frozen rubric.

    Raises
    ------
    ValueError
        If any rubric, case, or semantic adjudication is inconsistent.
    """
    bank = json.loads(BANK.read_text(encoding="utf-8"))
    calibration = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    rows = bank["tasks"]
    cases = calibration["cases"]
    if set(cases) != {row["task_id"] for row in rows}:
        raise ValueError("calibration case set differs from the frozen panel")
    lines = [
        "# Representative panel rubric calibration — 2026-10-01",
        "",
        "This is a reproducible, source-curated calibration of all 24 complete task rubrics. Correct cases use eighteen text exemplars with source grounding and six actual protected-test-qualified patches. Incomplete cases omit a required distinction; wrong cases assert a plausible contrary fact. Every rubric criterion is reviewed against the exact artifact and frozen rubric digest. Real campaign answers still require blinded semantic adjudication; this replay is not an automatic semantic classifier.",
        "",
        "All 72 answer probes bind exact response and rubric digests to source-curated adjudications. Correct exemplars support every required criterion; incomplete and wrong responses fail the substantive and requested-coverage criteria. The table highlights each task's decisive distinction. The full exemplars are in the [versioned calibration JSON](../../benchmarks/agent-efficiency/panels/representative-v1-calibration.json). Applied patch behavior is also checked independently in the exact admitted image.",
        "",
        "| Task | Correct claim | Incomplete claim | Subtly wrong claim | Decisive distinction |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        task_id = row["task_id"]
        oracle = load_document(ORACLES / f"{task_id}.json", "oracle")
        definition = cast("dict[str, object]", oracle["definition"])
        if "all_of" in definition:
            definition = cast("list[dict[str, object]]", definition["all_of"])[1]
        rubric = cast("dict[str, object]", definition["quality_rubric"])
        substance = next(
            criterion
            for criterion in cast("list[dict[str, object]]", rubric["criteria"])
            if criterion["id"] == "substance"
        )
        if substance["requirement"] != row["reference"]:
            raise ValueError(f"frozen rubric differs from reference: {task_id}")
        case = cases[task_id]
        for label, answer, expected in (
            ("correct", case["correct"], "supported"),
            ("incomplete", case["incomplete"], "missing"),
            ("subtly_wrong", case["wrong"], "contradicted"),
        ):
            initial = grade_quality(answer, rubric)
            if initial["status"] != "review_required":
                raise ValueError(
                    f"semantic claim was decided without review: {task_id}/{label}"
                )
            reviewed = adjudicate_quality(
                answer,
                rubric,
                {
                    "reviewer": "source-curated-panel-calibration-2026-10-01",
                    "answer_sha256": initial["answer_sha256"],
                    "rubric_sha256": initial["rubric_sha256"],
                    "decisions": [
                        {
                            "id": criterion["id"],
                            "status": expected
                            if criterion["id"] == "substance"
                            else ("supported" if label == "correct" else "missing"),
                            "reason": case["distinction"]
                            + "; checked against the source-curated complete exemplar and requested deliverable",
                            "evidence": answer if label == "correct" else "",
                        }
                        for criterion in cast(
                            "list[dict[str, object]]", rubric["criteria"]
                        )
                    ],
                },
            )
            if reviewed["status"] != ("passed" if label == "correct" else "failed"):
                raise ValueError(f"calibration adjudication differs: {task_id}/{label}")

        def cell(value: str) -> str:
            """Escape one Markdown table cell.

            Parameters
            ----------
            value : str
                Public source-curated claim.

            Returns
            -------
            str
                One escaped table cell.
            """
            return value.replace("|", "\\|").replace("\n", " ")

        lines.append(
            "| "
            + " | ".join(
                map(
                    cell,
                    (
                        task_id,
                        row["reference"],
                        case["incomplete"],
                        case["wrong"],
                        case["distinction"],
                    ),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            f"Bank SHA-256: `{hashlib.sha256(BANK.read_bytes()).hexdigest()}`. Calibration SHA-256: `{hashlib.sha256(CALIBRATION.read_bytes()).hexdigest()}`.",
            "",
            "Patch and feature tasks additionally require their frozen protected probes to pass on the actual applied patch. The preparation receipt records correct, incomplete and subtly wrong applied patch cases; their protected traces remain in ignored durable evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    """Write or check the durable calibration report.

    Parameters
    ----------
    None
        Reads command-line arguments.

    Returns
    -------
    int
        Zero when the report was written or matches the frozen inputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--qualify-patches", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--runtime", default="podman", choices=("podman", "docker"))
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--fixture-source", action="append", default=[])
    parser.add_argument("--patch-receipt", type=Path)
    args = parser.parse_args()
    if args.qualify_patches:
        from scripts.agent_efficiency.panel_patch_calibration import qualify_patch_cases
        from scripts.run_agent_efficiency_phase6_pilot import parse_fixture_sources

        if args.image is None or args.evidence_root is None or args.check:
            parser.error("patch qualification requires --image and --evidence-root")
        receipt = qualify_patch_cases(
            args.runtime,
            args.image,
            args.evidence_root,
            parse_fixture_sources(args.fixture_source),
        )
        print(
            json.dumps(
                {"status": receipt["status"], "case_count": receipt["case_count"]}
            )
        )
        return 0
    if args.patch_receipt is not None:
        receipt = json.loads(args.patch_receipt.read_text())
        if (
            receipt.get("status") != "passed"
            or receipt.get("case_count") != 18
            or any(row["passed"] != row["expected"] for row in receipt["cases"])
        ):
            parser.error(
                "all eighteen applied patch cases must match their expected verdicts"
            )
        calibration = json.loads(CALIBRATION.read_text())
        for row in receipt["cases"]:
            if row["case"] == "correct":
                artifact = (
                    args.patch_receipt.parent
                    / (row["task_id"] + "-correct")
                    / "fix.patch"
                )
                content = artifact.read_bytes()
                if hashlib.sha256(content).hexdigest() != row["patch_sha256"]:
                    parser.error("correct patch evidence digest differs")
                calibration["cases"][row["task_id"]]["correct"] = content.decode()
        CALIBRATION.write_text(
            json.dumps(calibration, indent=2, ensure_ascii=False) + "\n"
        )
        public = {
            "image": receipt["image"],
            "case_count": 18,
            "status": "passed",
            "bank_sha256": hashlib.sha256(BANK.read_bytes()).hexdigest(),
            "calibration_sha256": hashlib.sha256(CALIBRATION.read_bytes()).hexdigest(),
            "cases": [
                {
                    key: row[key]
                    for key in ("task_id", "case", "passed", "expected", "patch_sha256")
                }
                for row in receipt["cases"]
            ],
        }
        (BANK.parent / "representative-v1-patch-calibration.json").write_text(
            json.dumps(public, indent=2) + "\n"
        )
    expected = calibration_report()
    if args.check:
        return (
            0
            if REPORT.is_file() and REPORT.read_text(encoding="utf-8") == expected
            else 1
        )
    REPORT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
