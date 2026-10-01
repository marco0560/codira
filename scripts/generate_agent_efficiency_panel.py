"""Generate frozen representative tasks and semantic rubrics from the public bank.

Parameters
----------
None

Returns
-------
None
    Reproducible public definitions; never launches a provider request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.contracts import canonical_fingerprint, validate_document
from scripts.agent_efficiency.snapshots import snapshot_files

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "benchmarks/agent-efficiency/panels/representative-v1.json"
BASE = ROOT / "benchmarks/agent-efficiency"


def generated_documents() -> dict[Path, str]:
    """Build deterministic admitted fixtures, tasks and full-quality rubrics.

    Parameters
    ----------
    None

    Returns
    -------
    dict[pathlib.Path, str]
        Paths and canonical generated JSON contents.

    Raises
    ------
    ValueError
        If panel controls or protected asset digests are invalid.
    """
    bank = json.loads(BANK.read_text())
    documents: dict[Path, str] = {}
    protected_assets: dict[str, str] = {}
    for folder in sorted((BASE / "synthetic").iterdir()):
        inventory = snapshot_files(folder)
        fixture_id = folder.name + "-synthetic"
        digest = canonical_fingerprint(inventory)
        fixture = {
            "schema_version": "1.0",
            "fixture_id": fixture_id,
            "license": "MIT",
            "license_path": "LICENSE",
            "license_sha256": inventory["LICENSE"],
            "revision": digest[:40],
            "tree_sha": digest[:40],
            "source_url": "https://github.com/marco0560/codira",
            "transport": "directory-snapshot",
            "visibility": "public",
            "setup_files": [
                {"path": path, "sha256": value} for path, value in inventory.items()
            ],
        }
        validate_document("fixture", fixture)
        documents[
            BASE / "panels/representative-v1/fixtures" / (fixture_id + ".json")
        ] = json.dumps(fixture, sort_keys=True, indent=2) + "\n"
    for row in bank["tasks"]:
        task = {
            key: value
            for key, value in row.items()
            if key not in {"candidate", "reference"}
        }
        task.update(schema_version="1.0", oracle_id=row["task_id"], visibility="public")
        validate_document("task", task)
        criteria = [
            {
                "id": "substance",
                "dimension": "correctness",
                "semantic": True,
                "requirement": row["reference"],
                "accepted_equivalents": "Any accurate wording supported by frozen source or protected behavior.",
            },
            {
                "id": "requested-coverage",
                "dimension": "completeness",
                "semantic": True,
                "requirement": row["prompt"],
            },
            {
                "id": "grounding",
                "dimension": "evidence",
                "semantic": True,
                "requirement": "Bind factual claims to actual source ranges or reproducible checks; distinguish static inference from verified behavior.",
            },
            {
                "id": "usability",
                "dimension": "usability",
                "semantic": True,
                "requirement": "Give actionable, internally consistent output at the detail the task requests.",
            },
        ]
        if row["family"] in {"diagnosis", "tracing", "patch"}:
            criteria.append(
                {
                    "id": "causal-chain",
                    "dimension": "causality",
                    "semantic": True,
                    "requirement": "Explain or implement the causal relationship, including requested negative controls.",
                }
            )
        rubric = {"version": 1, "task_id": row["task_id"], "criteria": criteria}
        definition: dict[str, object] = {"quality_rubric": rubric}
        protected = BASE / "protected" / row["task_id"] / "provenance.json"
        if row["result_format"] == "workspace-diff":
            if not protected.exists():
                detail = f"missing protected probe for {row['task_id']}"
                raise ValueError(detail)
            provenance = json.loads(protected.read_text())
            asset = protected.parent / provenance["asset_path"]
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            if digest != provenance["asset_sha256"]:
                detail = f"protected asset digest differs for {row['task_id']}"
                raise ValueError(detail)
            protected_assets[str(asset.relative_to(ROOT))] = digest
            protected_assets[str(protected.relative_to(ROOT))] = hashlib.sha256(
                protected.read_bytes()
            ).hexdigest()
            patch = {
                "patch_applies_and_tests_pass": {
                    "patch_path": row["result_path"],
                    "command": ["python", provenance["asset_path"]],
                }
            }
            definition = {"all_of": [patch, definition]}
        oracle = {
            "schema_version": "1.0",
            "oracle_id": row["task_id"],
            "task_id": row["task_id"],
            "definition": definition,
            "visibility": "public",
        }
        validate_document("oracle", oracle)
        for kind, document in (("tasks", task), ("oracles", oracle)):
            documents[
                BASE / "panels/representative-v1" / kind / (row["task_id"] + ".json")
            ] = json.dumps(document, sort_keys=True, indent=2) + "\n"
    receipt = {
        "panel_id": bank["panel_id"],
        "protected_assets": protected_assets,
        "bank_sha256": hashlib.sha256(BANK.read_bytes()).hexdigest(),
        "documents": {
            str(path.relative_to(ROOT)): hashlib.sha256(value.encode()).hexdigest()
            for path, value in documents.items()
        },
    }
    documents[BASE / "panels/representative-v1-receipt.json"] = (
        json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    )
    return documents


def main() -> int:
    """Generate or check every public panel document without changing old tasks.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero when generated files agree; one for a stale checked file.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    documents = generated_documents()
    if args.check:
        return int(
            any(
                not path.is_file() or path.read_text() != value
                for path, value in documents.items()
            )
        )
    for path, value in documents.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
