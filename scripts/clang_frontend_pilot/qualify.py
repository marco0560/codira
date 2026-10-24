"""Grade a retained Clang pilot batch and write an immutable report.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from .cohort import grade_cohort
from .measure import _key_path


def main(argv: Sequence[str] | None = None) -> int:
    """Grade one complete cohort attempt with the shared deterministic rules.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        CLI arguments, defaulting to the process argument vector.

    Returns
    -------
    int
        Zero when every manifest row has an envelope and no identity or
        coordinate issues; one otherwise. Semantic completeness remains a
        separate report axis.

    Raises
    ------
    SystemExit
        When required arguments are missing or malformed.
    OSError, ValueError
        If inputs or raw evidence violate the pinned contract.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument(
        "--repository-root", action="append", type=_key_path, default=[]
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = grade_cohort(
        args.manifest,
        args.attempt_root,
        dict(args.repository_root),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    summary_value = report.get("summary")
    summary = summary_value if isinstance(summary_value, dict) else {}
    issues = summary.get("issue_counts")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
