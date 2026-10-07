"""Measure frozen source-reference retrieval without paid model calls."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.registry import active_index_backend
from scripts.agent_efficiency.contracts import canonical_fingerprint, load_document
from scripts.agent_efficiency.corpus import export_fixture, verify_fixture


def evaluate(source: Path, panel: Path) -> dict[str, object]:
    """Index a disposable admitted source and measure reference precision/recall.

    Parameters
    ----------
    source : pathlib.Path
        Local frozen public fixture checkout.
    panel : pathlib.Path
        Versioned reference queries with development and holdout labels.

    Returns
    -------
    dict[str, object]
        Content-safe item identities, recall, precision, ranks and payload bytes.
        Reference lists bound these metrics; they are not general relevance truth.
    """
    bank = json.loads(panel.read_text())
    root = Path("benchmarks/agent-efficiency")
    fixture = load_document(root / "fixtures" / f"{bank['fixture_id']}.json", "fixture")
    verify_fixture(fixture, source)
    observations: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix="ae-retrieval-", dir="/home/marco/Personalia/Progetti/.Temp"
    ) as temporary:
        workspace = Path(temporary) / "fixture"
        export_fixture(source, str(fixture["revision"]), workspace)
        active_index_backend().initialize(workspace)
        index_repo(workspace)
        adapter = MCPAdapter(workspace)
        for row in bank["queries"]:
            response = adapter.context_for_task(row["query"], limit=10)
            items = cast(
                "list[dict[str, object]]",
                cast("dict[str, object]", response["result"])["items"],
            )
            names = [str(item["name"]) for item in items]
            expected = row["relevant_names"]
            hits = sum(
                any(anchor == name or name.endswith("." + anchor) for name in names)
                for anchor in expected
            )
            relevant_items = sum(
                any(
                    anchor == name or name.endswith("." + anchor) for anchor in expected
                )
                for name in names
            )
            observations.append(
                {
                    "id": row["id"],
                    "split": row["split"],
                    "names": names,
                    "reference_recall": hits / len(expected) if expected else None,
                    "reference_precision": relevant_items / len(names)
                    if names and expected
                    else None,
                    "first_reference_rank": next(
                        (
                            i + 1
                            for i, name in enumerate(names)
                            if any(
                                anchor == name or name.endswith("." + anchor)
                                for anchor in expected
                            )
                        ),
                        None,
                    ),
                    "forbidden_hits": [
                        name for name in names if name in row.get("forbidden_names", [])
                    ],
                    "serialized_payload_bytes": len(json.dumps(response).encode()),
                }
            )
    return {
        "version": 1,
        "fixture_revision": fixture["revision"],
        "panel_sha256": canonical_fingerprint(bank),
        "queries": observations,
        "scope": "Reference retrieval metrics, including negative controls; precision uses a deliberately narrow reference set, not all potentially useful context.",
    }


def main() -> int:
    """Write one fresh durable offline retrieval receipt.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero after evaluation; metrics are evidence, not a paid-launch gate.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--panel",
        type=Path,
        default=Path("benchmarks/agent-efficiency/panels/sentinel-retrieval-v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = evaluate(args.source, args.panel)
    with args.output.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
