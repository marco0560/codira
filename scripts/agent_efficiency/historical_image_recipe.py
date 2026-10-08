"""Recover auditable candidate recipes from retained benchmark build history.

Parameters
----------
None

Returns
-------
None
    Conservative history translation with explicit missing-input diagnostics.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence, Set

COPY_PATTERN = re.compile(
    r"COPY (?P<kind>dir|file|multi):(?P<hash>[a-f0-9]{64}) in (?P<path>/\S+)\s*$"
)
NOP_PREFIX = "/bin/sh -c #(nop) "


def copy_snapshot(
    history: Sequence[Mapping[str, object]],
    index: int,
    destination: str,
    available_images: Set[str],
) -> str | None:
    """Find a COPY snapshot without crossing a mutation or overlapping COPY.

    Parameters
    ----------
    history : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Newest-first image history bounded by the upstream base.
    index : int
        COPY instruction whose output must be recovered.
    destination : str
        Original destination path.
    available_images : collections.abc.Set[str]
        Retained image snapshots available for read-only extraction.

    Returns
    -------
    str or None
        Original or later non-mutating snapshot; None when recovery is uncertain.
    """
    snapshot = str(history[index].get("id", ""))
    if snapshot in available_images:
        return snapshot
    selected = destination.rstrip("/")
    for newer in reversed(history[:index]):
        command = str(newer.get("CreatedBy", ""))
        if not command.startswith(NOP_PREFIX):
            break
        instruction = command.removeprefix(NOP_PREFIX).strip()
        copy = COPY_PATTERN.fullmatch(instruction)
        if instruction.startswith("COPY "):
            if copy is None:
                break
            path = copy["path"].rstrip("/")
            if (
                path == selected
                or selected.startswith(path + "/")
                or path.startswith(selected + "/")
            ):
                break
        candidate = str(newer.get("id", ""))
        if candidate in available_images:
            return candidate
    return None


def recover_steps(
    history: Sequence[Mapping[str, object]], available_images: Set[str]
) -> tuple[list[dict[str, str]], list[str]]:
    """Translate Codira history while refusing unknown or unrecoverable COPYs.

    Parameters
    ----------
    history : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Podman history in newest-first order for a credential-free Codira image.
    available_images : collections.abc.Set[str]
        Existing local image IDs, including intermediate build snapshots.

    Returns
    -------
    tuple[list[dict[str, str]], list[str]]
        Chronological instructions and COPY bindings, followed by recovery gaps.
        Directory snapshots can contain inherited files and are reconstruction
        aids rather than proof of the original context bytes.
    """
    steps: list[dict[str, str]] = []
    gaps: list[str] = []
    boundary = next(
        (
            index
            for index, row in enumerate(history)
            if str(row.get("comment", "")).startswith("FROM docker.io/library/python:")
        ),
        None,
    )
    if boundary is None:
        return [], ["upstream Python base boundary is unavailable"]
    rows = history[: boundary + 1]
    for index in reversed(range(len(rows))):
        row = rows[index]
        command = str(row.get("CreatedBy", ""))
        prefix = NOP_PREFIX
        if command.startswith(prefix):
            instruction = command.removeprefix(prefix).strip()
            if instruction.startswith("COPY "):
                match = COPY_PATTERN.fullmatch(instruction)
                if match is None:
                    gaps.append("unsupported COPY history syntax")
                    continue
                path = match["path"]
                parts = PurePosixPath(path).parts
                if ".." in parts or not path.startswith(
                    ("/opt/codira", "/usr/local/bin/")
                ):
                    gaps.append("COPY destination is outside the approved source paths")
                    continue
                snapshot = copy_snapshot(rows, index, path, available_images)
                if snapshot is None:
                    gaps.append(f"COPY snapshot unavailable: {match['hash']}")
                    continue
                steps.append(
                    {
                        "kind": match["kind"],
                        "hash": match["hash"],
                        "path": path,
                        "snapshot": snapshot,
                    }
                )
            elif instruction.split(" ", 1)[0] in {
                "ARG",
                "ENV",
                "LABEL",
                "USER",
                "WORKDIR",
                "ENTRYPOINT",
                "CMD",
                "SHELL",
            }:
                if instruction.startswith("ARG "):
                    instruction = "\n".join(
                        "ARG " + name for name in instruction[4:].split()
                    )
                steps.append({"instruction": instruction})
            else:
                gaps.append("unsupported non-COPY history instruction")
        elif "/bin/sh -c " in command:
            variables, shell = command.split("/bin/sh -c ", 1)
            if variables:
                variables = "export " + re.sub(r"^\|\d+ ", "", variables).strip() + "; "
            steps.append({"instruction": "RUN " + variables + shell})
        else:
            gaps.append("unsupported build history instruction")
    return steps, gaps
