"""Persist a quote-bound adjudication of a blinded quality packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.quality import persist_adjudication


def main() -> int:
    """Bind reviewer decisions to an exact packet and write a fresh receipt.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero after recording the review; no frozen attempt record is altered.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = json.loads(args.packet.read_text())
    review = json.loads(args.review.read_text())
    report = persist_adjudication(
        packet["answer"], packet["rubric"], review, args.output
    )
    print(
        json.dumps(
            {"status": report["status"], "review_sha256": report["review_sha256"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
