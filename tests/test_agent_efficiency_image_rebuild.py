"""Exercise durable recipes, failed builds, and reconstruction boundaries.

Parameters
----------
None

Returns
-------
None
    Regression tests using synthetic contexts and a simulated container runtime.
"""

from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts import (
    build_agent_efficiency_environment_image as builder,
    preserve_agent_efficiency_image_recipes as historical,
    rebuild_agent_efficiency_environment_image as replay,
)
from scripts.agent_efficiency import image_rebuild
from scripts.agent_efficiency.historical_image_recipe import (
    copy_snapshot,
    recover_steps,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def synthetic_context(destination: Path) -> None:
    """Write a small recipe whose fixture has no original npm lockfile.

    Parameters
    ----------
    destination : pathlib.Path
        Fresh context directory.

    Returns
    -------
    None
        Creates source material, a Containerfile, and an embedded profile.
    """
    fixture = destination / "fixture-environments" / "fixtures" / "example"
    fixture.mkdir(parents=True)
    (fixture / "package.json").write_text('{"name":"example"}\n', encoding="utf-8")
    (destination / "Containerfile").write_text(
        "ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n", encoding="utf-8"
    )
    (destination / "fixture-environments" / "environment-profile.json").write_text(
        "{}\n", encoding="utf-8"
    )


@pytest.mark.parametrize("failed", [False, True])
def test_builder_retains_context_before_build_and_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    """Retain inputs even when the runtime fails after temporary context creation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated build and evidence paths.
    monkeypatch : pytest.MonkeyPatch
        Replaces the container runtime with deterministic responses.
    failed : bool
        Whether the simulated build fails.

    Returns
    -------
    None
        Asserts the context survives and the original scratch disappears.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(builder, "PROJECT_TEMP_ROOT", tmp_path)
    tag = "localhost/recipe:new"
    record = image_rebuild.record_path(tag)
    contexts: list[Path] = []
    image = "localhost/recipe@sha256:" + "b" * 64

    def write_context(plan: builder.EnvironmentImagePlan, destination: Path) -> Path:
        """Supply synthetic inputs to the production builder.

        Parameters
        ----------
        plan : EnvironmentImagePlan
            Unused verified test plan.
        destination : pathlib.Path
            Disposable build context.

        Returns
        -------
        pathlib.Path
            Synthetic Containerfile.
        """
        del plan
        contexts.append(destination)
        synthetic_context(destination)
        return destination / "Containerfile"

    def run(
        arguments: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Check preservation ordering and emulate build and inspection.

        Parameters
        ----------
        arguments : collections.abc.Sequence[str]
            Runtime argument vector.
        kwargs : object
            Ignored subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Deterministic build result, image identity, or dependency inventory.
        """
        del kwargs
        if arguments[1] == "build":
            assert image_rebuild.verified_record(record)["status"] == "prepared"
            return subprocess.CompletedProcess(
                arguments, 1 if failed else 0, "build log", ""
            )
        if arguments[1] == "image":
            return subprocess.CompletedProcess(arguments, 0, image + "\n", "")
        if arguments[1] == "run":
            assert "--network=none" in arguments and "--read-only" in arguments
            return subprocess.CompletedProcess(
                arguments, 0, '{"generated_npm_locks":{}}', ""
            )
        return subprocess.CompletedProcess(arguments, 0, "podman test\n", "")

    monkeypatch.setattr(builder, "write_build_context", write_context)
    monkeypatch.setattr(subprocess, "run", run)
    plan = builder.EnvironmentImagePlan("localhost/base@sha256:" + "a" * 64, {}, {})
    profile = tmp_path / "profile.json"
    if failed:
        with pytest.raises(builder.EnvironmentImageBuildError, match="build failed"):
            builder.build_image(plan, "podman", tag, profile)
    else:
        assert builder.build_image(plan, "podman", tag, profile) == image
        assert json.loads(profile.read_text())["rebuild_policy"] == "recipe-only"
    document = image_rebuild.verified_record(record)
    assert document["status"] == ("build-failed" if failed else "built")
    assert document["exact_image_recovery"] is False
    assert not contexts[0].exists()
    restored = image_rebuild.restore_context(record, tmp_path / "restored")
    assert (restored / "fixture-environments/fixtures/example/package.json").is_file()


def test_records_refuse_overwrite_tampering_and_external_links(tmp_path: Path) -> None:
    """Reject lost payload integrity, record reuse, and escaped source links.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated curated context and record paths.

    Returns
    -------
    None
        Checks each rejection before reconstruction can run.
    """
    context = tmp_path / "context"
    synthetic_context(context)
    record = tmp_path / "record"
    image_rebuild.preserve_context(context, record, ["--pull=never"])
    with pytest.raises(FileExistsError):
        image_rebuild.preserve_context(context, record, [])
    (record / "context.tar.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        image_rebuild.restore_context(record, tmp_path / "restored")
    (context / "external").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="external symlink"):
        image_rebuild.preserve_context(context, tmp_path / "rejected", [])
    assert not (tmp_path / "rejected").exists()


def test_rebuild_reuses_generated_lock_and_requires_new_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore the effective npm lock while preserving the historical recipe.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated original record and reconstructed output.
    monkeypatch : pytest.MonkeyPatch
        Replaces the runtime and scratch directory.

    Returns
    -------
    None
        Confirms fresh identity, lock restoration, and unchanged original bytes.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(replay, "PROJECT_TEMP_ROOT", tmp_path)
    context = tmp_path / "context"
    synthetic_context(context)
    source = tmp_path / "source"
    document = image_rebuild.preserve_context(context, source, ["--pull=never"])
    document["image_tag"] = "localhost/test:old"
    inventory = {
        "generated_npm_locks": {"example/package-lock.json": {"lockfileVersion": 3}}
    }
    image_rebuild.write_document(source / "inventory.json", inventory)
    files = document["files"]
    assert isinstance(files, dict)
    files["inventory.json"] = image_rebuild.file_sha256(source / "inventory.json")
    image_rebuild.write_document(source / "record.json", document)
    before = (source / "record.json").read_bytes()
    image = "localhost/rebuilt@sha256:" + "c" * 64

    def run(
        arguments: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Validate the replay context before returning a successful new image.

        Parameters
        ----------
        arguments : collections.abc.Sequence[str]
            Runtime argument vector.
        kwargs : object
            Ignored subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Deterministic absence, build, inspection, or inventory response.
        """
        del kwargs
        if arguments[1] == "build":
            lock = (
                Path(arguments[-1])
                / "fixture-environments/fixtures/example/package-lock.json"
            )
            assert json.loads(lock.read_text())["lockfileVersion"] == 3
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if "--format" in arguments:
            return subprocess.CompletedProcess(arguments, 0, image, "")
        if arguments[1] == "run":
            return subprocess.CompletedProcess(arguments, 0, json.dumps(inventory), "")
        return subprocess.CompletedProcess(arguments, 1, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="fresh tag"):
        replay.rebuild(source, "podman", "localhost/test:old", None)
    destination = replay.rebuild(source, "podman", "localhost/test:new", None)
    assert image_rebuild.verified_record(destination)["runtime_image"] == image
    assert (source / "record.json").read_bytes() == before


def test_archive_extraction_refuses_parent_traversal(tmp_path: Path) -> None:
    """Reject unsafe archive members even when the archive checksum is recorded.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated context, record, and reconstruction destination.

    Returns
    -------
    None
        Verifies no file can be extracted outside the disposable directory.
    """
    context = tmp_path / "context"
    synthetic_context(context)
    record = tmp_path / "record"
    document = image_rebuild.preserve_context(context, record, [])
    with tarfile.open(record / "context.tar.gz", "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("../../escaped"))
    files = document["files"]
    assert isinstance(files, dict)
    files["context.tar.gz"] = image_rebuild.file_sha256(record / "context.tar.gz")
    image_rebuild.write_document(record / "record.json", document)
    with pytest.raises(tarfile.FilterError):
        image_rebuild.restore_context(record, tmp_path / "restored")
    assert not (tmp_path / "escaped").exists()


def test_historical_recipe_requires_recoverable_source_snapshots() -> None:
    """Distinguish recoverable COPY inputs from missing historical evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks upstream boundary, runtime arguments, and missing-input diagnostics.
    """
    copy = "COPY dir:" + "a" * 64 + " in /opt/codira/fixture-environments"
    history: list[dict[str, object]] = [
        {"CreatedBy": "|1 CODEX_VERSION=1.0 /bin/sh -c npm install --global codex"},
        {"CreatedBy": "/bin/sh -c #(nop) " + copy, "id": "snapshot"},
        {
            "CreatedBy": "/bin/sh -c #(nop) LABEL example=value",
            "comment": "FROM docker.io/library/python:3.13-slim",
        },
    ]
    steps, gaps = recover_steps(history, {"snapshot"})
    assert not gaps
    assert steps[1]["snapshot"] == "snapshot"
    assert (
        steps[-1]["instruction"]
        == "RUN export CODEX_VERSION=1.0; npm install --global codex"
    )
    _, gaps = recover_steps(history, set())
    assert "COPY snapshot unavailable" in gaps[0]
    assert recover_steps([], set())[1] == [
        "upstream Python base boundary is unavailable"
    ]


@pytest.mark.parametrize("mutation", ["RUN", "COPY"])
def test_snapshot_fallback_stops_before_source_mutation(mutation: str) -> None:
    """Allow later COPY snapshots only when the requested source is unchanged.

    Parameters
    ----------
    mutation : str
        Later build action that could alter the requested source directory.

    Returns
    -------
    None
        Confirms recovery from a disjoint COPY and refusal after mutation.
    """
    source = {
        "id": "missing",
        "CreatedBy": "/bin/sh -c #(nop) COPY dir:" + "a" * 64 + " in /opt/codira",
    }
    safe = {
        "id": "available",
        "CreatedBy": "/bin/sh -c #(nop) COPY file:"
        + "b" * 64
        + " in /opt/codira-helper",
    }
    assert copy_snapshot([safe, source], 1, "/opt/codira", {"available"}) == "available"
    command = (
        "/bin/sh -c mutate-source"
        if mutation == "RUN"
        else "/bin/sh -c #(nop) COPY file:" + "c" * 64 + " in /opt/codira/source.py"
    )
    changed = {"id": "available", "CreatedBy": command}
    assert copy_snapshot([changed, source], 1, "/opt/codira", {"available"}) is None


@pytest.mark.parametrize("with_bwrap", [False, True])
def test_native_recovery_excludes_inherited_external_links(
    tmp_path: Path, with_bwrap: bool
) -> None:
    """Retain supplied Codex binaries without unrelated inherited npm symlinks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated synthetic binary snapshot.
    with_bwrap : bool
        Whether the historical native context supplied bwrap in addition to Codex.

    Returns
    -------
    None
        Confirms extraction selects complete regular inputs and refuses gaps.
    """
    snapshot = tmp_path / "binaries.tar"
    with tarfile.open(snapshot, "w") as archive:
        expected = {"codex", "codex-code-mode-host"}
        if with_bwrap:
            expected.add("bwrap")
        for name in sorted(expected):
            archive.addfile(tarfile.TarInfo("./" + name))
        inherited = tarfile.TarInfo("./npm")
        inherited.type = tarfile.SYMTYPE
        inherited.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        archive.addfile(inherited)
    with tarfile.open(snapshot) as archive:
        members = historical.native_members(archive)
        archive.extractall(tmp_path / "restored", members=members, filter="data")
    assert {path.name for path in (tmp_path / "restored").iterdir()} == expected
    with tarfile.open(snapshot, "w") as archive:
        archive.addfile(tarfile.TarInfo("./codex"))
    with (
        tarfile.open(snapshot) as archive,
        pytest.raises(tarfile.TarError, match="incomplete"),
    ):
        historical.native_members(archive)
