#!/usr/bin/env python3
"""Rebuild a retained recipe under a fresh identity, allowing dependency drift.

Parameters
----------
None

Returns
-------
None
    Command-line reconstruction without modifying historical campaign records.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0
from scripts.agent_efficiency.image_rebuild import (
    capture_inventory,
    file_sha256,
    preserve_context,
    record_path,
    restore_context,
    verified_record,
    write_document,
)
from scripts.agent_efficiency.temporary import PROJECT_TEMP_ROOT


def rebuild(source: Path, runtime: str, tag: str, base_image: str | None) -> Path:
    """Execute a verified recipe and retain a separate reconstruction record.

    Parameters
    ----------
    source : pathlib.Path
        Previous recipe with its original context and metadata.
    runtime : str
        Supported container runtime.
    tag : str
        New, unused image tag.
    base_image : str or None
        Replacement digest-pinned parent for a recipe-only rebuilt parent chain.

    Returns
    -------
    pathlib.Path
        New record containing the build result and dependency inventory.

    Raises
    ------
    ValueError
        If inputs are unsupported, incomplete, or would overwrite an image.
    subprocess.CalledProcessError
        If rebuilding or dependency inventory fails.
    """
    previous = verified_record(source)
    arguments = previous.get("build_arguments")
    if (
        runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES
        or not tag
        or tag == previous.get("image_tag")
        or not isinstance(arguments, list)
        or not all(isinstance(item, str) for item in arguments)
        or previous.get("status") == "historical-incomplete"
        or (
            base_image is not None
            and phase0.IMAGE_DIGEST_PATTERN.fullmatch(base_image) is None
        )
    ):
        message = (
            "rebuilding requires a valid recipe, runtime, fresh tag and pinned parent"
        )
        raise ValueError(message)
    existing = subprocess.run(
        (runtime, "image", "inspect", tag), check=False, capture_output=True
    )
    if existing.returncode == 0:
        message = "reconstruction tag already exists"
        raise ValueError(message)
    destination = record_path(tag)
    with tempfile.TemporaryDirectory(
        prefix="codira-image-rebuild-", dir=PROJECT_TEMP_ROOT
    ) as scratch:
        context = restore_context(source, Path(scratch) / "restored")
        inventory_path = source / "inventory.json"
        if inventory_path.exists():
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            for relative, lock in inventory.get("generated_npm_locks", {}).items():
                parts = Path(relative).parts
                if (
                    len(parts) != 2
                    or parts[1] != "package-lock.json"
                    or parts[0] in {".", ".."}
                ):
                    message = "invalid retained npm lock path"
                    raise ValueError(message)
                fixture = context / "fixture-environments" / "fixtures" / parts[0]
                bindings = previous.get("fixture_contexts", {})
                if isinstance(bindings, dict) and parts[0] in bindings:
                    relative_fixture = bindings[parts[0]]
                    if not isinstance(relative_fixture, str):
                        message = "invalid historical fixture context binding"
                        raise TypeError(message)
                    fixture = context / relative_fixture
                    if not fixture.resolve().is_relative_to(context.resolve()):
                        message = "historical fixture binding escapes the context"
                        raise ValueError(message)
                if not fixture.is_dir():
                    message = "retained npm lock has no archived fixture"
                    raise ValueError(message)
                write_document(fixture / "package-lock.json", lock)
        if base_image is not None:
            arguments = [*arguments, "--build-arg", f"BASE_IMAGE={base_image}"]
        record = preserve_context(context, destination, arguments)
        record.update(
            {
                "image_tag": tag,
                "reconstructed_from": str(source),
                "base_image": base_image or previous.get("base_image"),
            }
        )
        write_document(destination / "record.json", record)
        result = subprocess.run(
            (
                runtime,
                "build",
                *arguments,
                "--tag",
                tag,
                "--file",
                str(context / "Containerfile"),
                str(context),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        for stream, value in (("stdout", result.stdout), ("stderr", result.stderr)):
            (destination / f"build.{stream}.txt").write_text(value, encoding="utf-8")
        if result.returncode != 0:
            record.update(
                {"status": "build-failed", "build_exit_code": result.returncode}
            )
            write_document(destination / "record.json", record)
            result.check_returncode()
        image = subprocess.run(
            (runtime, "image", "inspect", "--format", "{{index .RepoDigests 0}}", tag),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if phase0.IMAGE_DIGEST_PATTERN.fullmatch(image) is None:
            message = "rebuilt image identity is unavailable"
            raise ValueError(message)
        retained_inventory = capture_inventory(runtime, image, destination)
        files = record["files"]
        if not isinstance(files, dict):
            message = "reconstruction file manifest is invalid"
            raise TypeError(message)
        files["inventory.json"] = file_sha256(retained_inventory)
        record.update({"status": "built", "runtime_image": image})
        write_document(destination / "record.json", record)
    return destination


def main(arguments: list[str] | None = None) -> int:
    """Run an explicitly requested reconstruction and report its new record.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero after reconstruction, two on rejection or build failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--runtime", choices=phase0.SUPPORTED_CONTAINER_RUNTIMES, default="podman"
    )
    parser.add_argument("--base-image")
    args = parser.parse_args(arguments)
    try:
        destination = rebuild(args.record, args.runtime, args.tag, args.base_image)
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"image reconstruction failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps({"rebuild_record": str(destination), "exact_image_recovery": False})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
