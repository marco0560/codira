"""Admit a fixed development and hold-out task panel before paid execution.

Parameters
----------
None

Returns
-------
None
    Representative panel constraints supplement the frozen legacy stages.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from codira.runtime_identity import runtime_identity


def validate_panel_tasks(
    tasks: Mapping[str, Mapping[str, object]], specification: Mapping[str, object]
) -> None:
    """Require balanced breadth, frozen splits and explicit treatment identity.

    Parameters
    ----------
    tasks : collections.abc.Mapping[str, collections.abc.Mapping[str, object]]
        Loaded public task documents.
    specification : collections.abc.Mapping[str, object]
        Proposed representative campaign specification.

    Returns
    -------
    None
        Successful return admits the 24-task panel only.

    Raises
    ------
    ValueError
        If panel coverage, split, protocol or installed serving identity differs.
    """
    families = Counter(str(task.get("family")) for task in tasks.values())
    splits = Counter(str(task.get("split")) for task in tasks.values())
    if (
        len(tasks) != 24
        or len(families) != 8
        or set(families.values()) != {3}
        or splits != {"development": 12, "holdout": 12}
    ):
        raise ValueError(
            "representative panel requires eight families and a frozen twelve/twelve split"
        )
    for family in families:
        selected = {
            task.get("split") for task in tasks.values() if task.get("family") == family
        }
        if selected != {"development", "holdout"}:
            raise ValueError("every task family must occur in both splits")
    protocol = specification.get("treatment_protocol")
    if not isinstance(protocol, Mapping) or protocol.get("version") not in {
        "mcp-optional-v3",
        "mcp-required-v3",
    }:
        raise ValueError(
            "representative campaigns require an explicit optional/forced v3 treatment"
        )
    if (
        specification.get("panel_id") != "representative-v1"
        or specification.get("runtime_source_fingerprint")
        != runtime_identity()["source_sha256"]
    ):
        raise ValueError("representative panel or serving source identity differs")


def panel_document_path(root: Path, kind: str, identifier: str) -> Path:
    """Resolve panel records separately from immutable legacy directories.

    Parameters
    ----------
    root : pathlib.Path
        Benchmark definition root.
    kind : str
        Task, fixture or oracle directory name.
    identifier : str
        Already schema-validated public identifier.

    Returns
    -------
    pathlib.Path
        Existing legacy path or the versioned representative-panel path.
    """
    legacy = root / kind / f"{identifier}.json"
    return (
        legacy
        if legacy.exists()
        else root / "panels/representative-v1" / kind / f"{identifier}.json"
    )


def prepare_panel_fixture(root: Path, task_id: str) -> None:
    """Apply frozen task seeds and remove grader material from fresh exports.

    Parameters
    ----------
    root : pathlib.Path
        Newly exported disposable agent or protected checkout.
    task_id : str
        Task selecting the versioned seed policy.

    Returns
    -------
    None
        Legacy exports remain untouched; panel seeds become the patch baseline.

    Raises
    ------
    ValueError
        If the seed anchor differs or Git is unavailable.
    """
    if not task_id.startswith("panel-"):
        return
    for relative in ("benchmarks/agent-efficiency", "docs/process"):
        candidate = root / relative
        if candidate.is_dir():
            shutil.rmtree(candidate)
    if task_id == "panel-p2":
        path = root / "lib/picomatch.js"
        source = path.read_text()
        anchor = "if (isIgnored(input)) {"
        if source.count(anchor) != 1:
            raise ValueError("frozen ignore seed anchor differs")
        path.write_text(source.replace(anchor, "if (false && isIgnored(input)) {"))
    if task_id == "panel-f1":
        parser = root / "src/codira/cli_parser.py"
        source = parser.read_text()
        option = '    context_parser.add_argument(\n        "--max-results",\n        type=_item_limit,\n        default=10,\n        help="Complete items per page, 1..100 (default 10)",\n    )\n'
        if source.count(option) != 1:
            raise ValueError("frozen max-results seed anchor differs")
        parser.write_text(source.replace(option, ""))
        query = root / "src/codira/cli_queries.py"
        source = query.read_text()
        option = '    limit = getattr(args, "max_results", 10)'
        if source.count(option) != 1:
            raise ValueError("frozen context limit seed anchor differs")
        query.write_text(source.replace(option, "    limit = 10"))
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required to prepare panel fixtures")
    subprocess.run(
        [git, "-C", str(root), "add", "--all"], check=True, capture_output=True
    )
