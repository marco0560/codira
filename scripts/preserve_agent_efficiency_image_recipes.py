#!/usr/bin/env python3
"""Recover recipe-only evidence for existing Codira images without deleting them.

Parameters
----------
None

Returns
-------
None
    Durable inventory, candidate contexts and explicit historical recovery gaps.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency.historical_image_recipe import recover_steps
from scripts.agent_efficiency.image_rebuild import (
    capture_inventory,
    file_sha256,
    preserve_context,
    verified_record,
    write_document,
)
from scripts.agent_efficiency.temporary import PROJECT_TEMP_ROOT

SOURCE_LABEL = "https://github.com/marco0560/codira"
PODMAN_EXECUTABLE = shutil.which("podman") or "podman"
PYTHON_BASE = "docker.io/library/python@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00"


def native_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Select native binaries, including bwrap when present in newer snapshots.

    Parameters
    ----------
    archive : tarfile.TarFile
        Snapshot of the image's shared binary directory.

    Returns
    -------
    list[tarfile.TarInfo]
        Regular native Codex binaries, excluding inherited tools and links.

    Raises
    ------
    tarfile.TarError
        If a declared native build input is missing or not a regular file.
    """
    selected = {"codex", "codex-code-mode-host", "bwrap"}
    members = [
        item
        for item in archive.getmembers()
        if item.name.removeprefix("./") in selected and item.isfile()
    ]
    if not {"codex", "codex-code-mode-host"} <= {
        item.name.removeprefix("./") for item in members
    }:
        message = "native Codex COPY inputs are incomplete"
        raise tarfile.TarError(message)
    return members


def copy_archive(step: dict[str, str], cache: Path) -> Path:
    """Retain a verified COPY payload once across related historical images.

    Parameters
    ----------
    step : dict[str, str]
        Recoverable source path, snapshot ID and original content identity.
    cache : pathlib.Path
        Audit-owned shared payload directory.

    Returns
    -------
    pathlib.Path
        Checked source archive, reusable after an interrupted audit.

    Raises
    ------
    ValueError
        If a previously retained payload has changed.
    subprocess.CalledProcessError
        If read-only source extraction fails.
    """
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (step["hash"] + ".tar.gz")
    metadata = archive.with_suffix(".json")
    if metadata.exists():
        expected = json.loads(metadata.read_text(encoding="utf-8"))["sha256"]
        if file_sha256(archive) != expected:
            message = "shared historical COPY payload checksum mismatch"
            raise ValueError(message)
        return archive
    path = step["path"].rstrip("/")
    source = Path(path)
    directory = step["kind"] in {"dir", "multi"}
    arguments = (
        ("-C", path, ".") if directory else ("-C", str(source.parent), source.name)
    )
    partial = archive.with_suffix(".partial")
    with partial.open("wb") as handle:
        subprocess.run(
            (
                PODMAN_EXECUTABLE,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=0",
                "--entrypoint=tar",
                step["snapshot"],
                "-cf",
                "-",
                "--use-compress-program=gzip -1",
                "--exclude=.venv",
                "--exclude=node_modules",
                "--exclude=__pycache__",
                "--exclude=*.pyc",
                "--exclude=uv-cache",
                "--exclude=npm-cache",
                "--exclude=pip-wheels",
                "--exclude=go-mod",
                *arguments,
            ),
            check=True,
            stdout=handle,
            stderr=subprocess.PIPE,
        )
    partial.replace(archive)
    write_document(
        metadata,
        {
            "sha256": file_sha256(archive),
            "snapshot": step["snapshot"],
            "destination": step["path"],
        },
    )
    return archive


def recover_image(
    image: dict[str, object], images: set[str], output: Path
) -> dict[str, object]:
    """Preserve recoverable COPY snapshots and an unverified historical recipe.

    Parameters
    ----------
    image : dict[str, object]
        Local image identity from the Podman inventory.
    images : set[str]
        Available intermediate and final image IDs.
    output : pathlib.Path
        Fresh evidence directory for this image.

    Returns
    -------
    dict[str, object]
        Image identity, recovered recipe location, and missing-input diagnostics.

    Raises
    ------
    subprocess.CalledProcessError
        If Podman cannot read the image history.
    OSError
        If recovered inputs or durable recipe records cannot be written.
    ValueError
        If image history or recovered recipe data is invalid.
    TypeError
        If the recovered file manifest is not an object.
    """
    identity = str(image["Id"])
    history_result = subprocess.run(
        (PODMAN_EXECUTABLE, "history", "--no-trunc", "--format", "json", identity),
        check=True,
        capture_output=True,
        text=True,
    )
    history = json.loads(history_result.stdout)
    steps, gaps = recover_steps(history, images)
    with tempfile.TemporaryDirectory(
        prefix="codira-historical-recipe-", dir=PROJECT_TEMP_ROOT
    ) as scratch:
        context = Path(scratch) / "context"
        context.mkdir()
        instructions = ["ARG BASE_IMAGE", "FROM ${BASE_IMAGE}"]
        fixture_contexts: dict[str, str] = {}
        for step in steps:
            if "instruction" in step:
                instructions.append(step["instruction"])
                continue
            recovered = context / "inputs" / step["hash"]
            path = step["path"].rstrip("/")
            source = Path(path)
            directory = step["kind"] in {"dir", "multi"}
            try:
                archive = copy_archive(step, output.parent.parent / "copy-inputs")
            except subprocess.CalledProcessError:
                gaps.append(f"COPY extraction failed: {step['hash']}")
                continue
            try:
                if not recovered.exists():
                    recovered.mkdir(parents=True)
                    with tarfile.open(archive, "r:gz") as handle:
                        members = None
                        if step["path"].rstrip("/") == "/usr/local/bin":
                            members = native_members(handle)
                        handle.extractall(recovered, members=members, filter="data")
            except tarfile.TarError:
                gaps.append(f"COPY archive rejected: {step['hash']}")
                continue
            relative = recovered.relative_to(context).as_posix()
            original = relative + "/" if directory else relative + "/" + source.name
            instructions.append("COPY " + json.dumps([original, step["path"]]))
            if step["path"].rstrip("/") == "/opt/codira/fixture-environments":
                fixtures = recovered / "fixtures"
                if fixtures.is_dir():
                    for fixture in fixtures.iterdir():
                        if fixture.is_dir():
                            fixture_contexts[fixture.name] = fixture.relative_to(
                                context
                            ).as_posix()
        (context / "Containerfile").write_text(
            "\n".join(instructions) + "\n", encoding="utf-8"
        )
        record = preserve_context(
            context,
            output,
            [
                "--network=private",
                "--pull=never",
                "--build-arg",
                f"BASE_IMAGE={PYTHON_BASE}",
            ],
        )
    write_document(output / "history.json", {"history": history})
    names = image.get("Names")
    digests = image.get("RepoDigests")
    record.update(
        {
            "status": "historical-incomplete" if gaps else "historical-unverified",
            "base_image": PYTHON_BASE,
            "image_tag": names[0] if isinstance(names, list) and names else identity,
            "runtime_image": digests[0]
            if isinstance(digests, list) and digests
            else identity,
            "recovery_gaps": gaps,
            "rebuild_validated": False,
            "fixture_contexts": fixture_contexts,
        }
    )
    files = record["files"]
    if not isinstance(files, dict):
        message = "historical file manifest must be an object"
        raise TypeError(message)
    files["history.json"] = file_sha256(output / "history.json")
    try:
        inventory_path = capture_inventory("podman", identity, output)
        files["inventory.json"] = file_sha256(inventory_path)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        gaps.append("installed dependency inventory unavailable")
        record["status"] = "historical-incomplete"
    write_document(output / "record.json", record)
    return {
        "image_id": identity,
        "names": image.get("Names"),
        "record": str(output),
        "gaps": gaps,
        "gap_count": len(gaps),
        "rebuild_validated": False,
    }


def preserve(output: Path, repair_incomplete: bool = False) -> None:
    """Inventory all images and recover Codira leaf recipes with checkpoints.

    Parameters
    ----------
    output : pathlib.Path
        Durable root on the repository filesystem. Completed records are
        checksum-verified and reused when resuming an interrupted audit.
    repair_incomplete : bool, optional
        Recover incomplete records into separate replacement directories after
        updating recovery tooling. Original diagnostic records are retained.

    Returns
    -------
    None
        Saves all image identities and one result per named or leaf Codira image.

    Raises
    ------
    subprocess.CalledProcessError
        If Podman cannot inventory images or read their history.
    OSError
        If inventory, checkpoint, or recipe files cannot be read or written.
    ValueError
        If the inventory changes, a checkpoint escapes the audit root, or a
        retained record is invalid.
    TypeError
        If a recovered file manifest is not an object.
    """
    current_images = json.loads(
        subprocess.run(
            (PODMAN_EXECUTABLE, "images", "--all", "--format", "json"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    if output.exists():
        images = json.loads((output / "images.json").read_text(encoding="utf-8"))[
            "images"
        ]
        if not {image["Id"] for image in images} <= {
            image["Id"] for image in current_images
        }:
            message = "historical image inventory changed before audit completion"
            raise ValueError(message)
    else:
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        images = current_images
        write_document(output / "images.json", {"images": images})
    identities = {str(image["Id"]) for image in images}
    parents = {str(image.get("ParentId")) for image in images}
    candidates = [
        image
        for image in images
        if (image.get("Labels") or {}).get("org.opencontainers.image.source")
        == SOURCE_LABEL
        and (image.get("Names") or image["Id"] not in parents)
    ]
    results = []
    previous_results = {}
    summary = output / "summary.json"
    if summary.exists():
        previous_results = {
            item["image_id"]: item["record"]
            for item in json.loads(summary.read_text(encoding="utf-8"))["results"]
        }
    for number, image in enumerate(candidates, 1):
        identity = str(image["Id"])
        destination = Path(
            previous_results.get(identity, output / "recipes" / identity)
        )
        if not destination.resolve().is_relative_to(output.resolve()):
            message = "historical checkpoint escapes its audit root"
            raise ValueError(message)
        if destination.exists() and repair_incomplete:
            previous_record = verified_record(destination)
            if previous_record.get("recovery_gaps"):
                revision = 1
                destination = output / "repairs" / f"{identity}-r{revision}"
                while destination.exists():
                    revision += 1
                    destination = output / "repairs" / f"{identity}-r{revision}"
        if destination.exists():
            record = verified_record(destination)
            gaps = record.get("recovery_gaps")
            if not isinstance(gaps, list):
                message = "existing historical record lacks recovery diagnostics"
                raise ValueError(message)
            result = {
                "image_id": str(image["Id"]),
                "names": image.get("Names"),
                "record": str(destination),
                "gaps": gaps,
                "gap_count": len(gaps),
                "rebuild_validated": False,
            }
        else:
            result = recover_image(image, identities, destination)
        results.append(result)
        write_document(
            output / "summary.json",
            {
                "policy": "recipe-only",
                "image_count": len(images),
                "selected_count": len(candidates),
                "completed_count": len(results),
                "results": results,
                "deletion_performed": False,
            },
        )
        print(
            json.dumps(
                {
                    "completed": number,
                    "total": len(candidates),
                    "gaps": result["gap_count"],
                }
            ),
            flush=True,
        )


def main(arguments: list[str] | None = None) -> int:
    """Run an explicitly requested historical recipe preservation audit.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero after the audit; two on runtime or input failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair-incomplete", action="store_true")
    args = parser.parse_args(arguments)
    try:
        preserve(args.output, args.repair_incomplete)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"historical image preservation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
