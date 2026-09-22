#!/usr/bin/env python3
"""Build a candidate benchmark image with selected offline fixture material."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0
from scripts.agent_efficiency.contracts import canonical_fingerprint, load_document
from scripts.agent_efficiency.corpus import export_fixture

BENCHMARK_ROOT = Path("benchmarks/agent-efficiency")
ENVIRONMENT_ROOT = "/opt/codira/fixture-environments"
HELPER_ROOT = Path("scripts/agent_efficiency")
GIT_EXECUTABLE = shutil.which("git")


class EnvironmentImageBuildError(ValueError):
    """Report a deterministic candidate-image preparation failure.

    Parameters
    ----------
    detail : str
        Public-safe explanation of the rejected build input or result.

    Returns
    -------
    None
        Instances carry a stable preparation failure detail.
    """


@dataclass(frozen=True)
class EnvironmentImagePlan:
    """Describe the fixture inputs embedded in one candidate image.

    Parameters
    ----------
    base_image : str
        Exact digest-pinned image extended by the controlled build.
    fixtures : dict[str, Path]
        Admitted public fixture source roots by immutable identity.
    profile : dict[str, object]
        Credential-free immutable metadata embedded in the resulting image.

    Returns
    -------
    None
        The plan has no provider credentials or untracked runtime state.
    """

    base_image: str
    fixtures: dict[str, Path]
    profile: dict[str, object]


def parse_fixture_sources(values: list[str]) -> dict[str, Path]:
    """Parse distinct ``fixture_id=/absolute/source`` build bindings.

    Parameters
    ----------
    values : list[str]
        Command-line bindings for every selected fixture source.

    Returns
    -------
    dict[str, pathlib.Path]
        Absolute fixture source paths keyed by immutable fixture identity.

    Raises
    ------
    EnvironmentImageBuildError
        If an input is malformed, relative, duplicated, or unavailable.
    """

    sources: dict[str, Path] = {}
    for value in values:
        fixture_id, separator, raw_path = value.partition("=")
        path = Path(raw_path)
        if (
            not separator
            or not fixture_id
            or not path.is_absolute()
            or fixture_id in sources
            or not path.is_dir()
        ):
            raise EnvironmentImageBuildError(
                "fixture sources must be unique fixture_id=/absolute/path bindings"
            )
        sources[fixture_id] = path.resolve()
    return sources


def build_plan(base_image: str, sources: dict[str, Path]) -> EnvironmentImagePlan:
    """Verify sources and construct the immutable embedded profile.

    Parameters
    ----------
    base_image : str
        Existing exact digest-pinned benchmark image.
    sources : dict[str, pathlib.Path]
        Candidate public fixture checkout paths.

    Returns
    -------
    EnvironmentImagePlan
        Verified fixture inputs and their immutable non-secret profile.

    Raises
    ------
    EnvironmentImageBuildError
        If the base identity, fixture definition, or source admission is invalid.
    """

    if phase0.IMAGE_DIGEST_PATTERN.fullmatch(base_image) is None:
        raise EnvironmentImageBuildError("base image must use an exact sha256 digest")
    if not sources:
        raise EnvironmentImageBuildError("at least one fixture source is required")
    fixtures: dict[str, object] = {}
    for fixture_id, source in sorted(sources.items()):
        try:
            fixture = load_document(
                BENCHMARK_ROOT / "fixtures" / f"{fixture_id}.json", "fixture"
            )
            revision, tree_sha = _admit_revision(source, fixture)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise EnvironmentImageBuildError(
                f"fixture source fails immutable admission: {fixture_id}"
            ) from error
        ecosystem = _ecosystem(source)
        fixtures[fixture_id] = {
            "revision": revision,
            "tree_sha": tree_sha,
            "ecosystem": ecosystem,
            "setup_sha256": _declared_setup_fingerprints(fixture),
        }
    profile = {
        "version": 1,
        "base_image": base_image,
        "fixtures": fixtures,
        "validation": {"offline_preparation": "required-by-build"},
    }
    return EnvironmentImagePlan(base_image, dict(sources), profile)


def write_build_context(plan: EnvironmentImagePlan, destination: Path) -> Path:
    """Write the disposable, credential-free context for one image build.

    Parameters
    ----------
    plan : EnvironmentImagePlan
        Verified image and fixture inputs to embed.
    destination : pathlib.Path
        Absent temporary directory for the generated build context.

    Returns
    -------
    pathlib.Path
        Written Containerfile path.

    Raises
    ------
    EnvironmentImageBuildError
        If the temporary context is not fresh.
    """

    if destination.exists():
        raise EnvironmentImageBuildError("candidate image context must be absent")
    destination.mkdir(parents=True)
    fixture_destination = destination / "fixture-environments" / "fixtures"
    fixture_destination.mkdir(parents=True)
    profiles = plan.profile.get("fixtures")
    if not isinstance(profiles, dict):
        raise EnvironmentImageBuildError("fixture environment profile is invalid")
    for fixture_id, source in plan.fixtures.items():
        fixture = profiles.get(fixture_id)
        if not isinstance(fixture, dict):
            raise EnvironmentImageBuildError("fixture environment profile is invalid")
        revision = fixture.get("revision")
        if not isinstance(revision, str):
            raise EnvironmentImageBuildError("fixture revision is invalid")
        destination_root = fixture_destination / fixture_id
        export_fixture(source, revision, destination_root)
        shutil.rmtree(destination_root / ".git")
    profile = dict(plan.profile)
    profile["fingerprint"] = canonical_fingerprint(profile)
    (destination / "fixture-environments" / "environment-profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(HELPER_ROOT / "prepare-fixture-environment", destination)
    shutil.copy2(HELPER_ROOT / "build-fixture-environments", destination)
    containerfile = destination / "Containerfile"
    containerfile.write_text(
        "ARG BASE_IMAGE\n"
        "FROM ${BASE_IMAGE}\n"
        "COPY --chmod=755 prepare-fixture-environment /opt/codira/prepare-fixture-environment\n"
        "COPY --chmod=755 build-fixture-environments /opt/codira/build-fixture-environments\n"
        "COPY fixture-environments /opt/codira/fixture-environments\n"
        f"RUN /opt/codira/build-fixture-environments {ENVIRONMENT_ROOT}\n"
        "LABEL io.codira.agent-efficiency.environment-profile-sha256=${ENVIRONMENT_PROFILE_SHA256}\n",
        encoding="utf-8",
    )
    return containerfile


def build_image(
    plan: EnvironmentImagePlan, runtime: str, tag: str, output_profile: Path
) -> str:
    """Build with network only during dependency resolution and emit a profile.

    Parameters
    ----------
    plan : EnvironmentImagePlan
        Verified candidate build plan.
    runtime : str
        Container runtime whose build operation supports an explicit network mode.
    tag : str
        Fresh local candidate-image tag.
    output_profile : pathlib.Path
        Absent host evidence path for the exact embedded profile.

    Returns
    -------
    str
        Runtime-valid immutable repository digest reference.

    Raises
    ------
    EnvironmentImageBuildError
        If build execution or immutable evidence persistence fails.
    """

    if (
        runtime not in phase0.SUPPORTED_CONTAINER_RUNTIMES
        or not tag
        or output_profile.exists()
    ):
        raise EnvironmentImageBuildError("candidate image build arguments are invalid")
    with tempfile.TemporaryDirectory(prefix="codira-fixture-image-") as temporary:
        context = Path(temporary) / "context"
        write_build_context(plan, context)
        profile_path = context / "fixture-environments" / "environment-profile.json"
        profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        completed = subprocess.run(
            (
                runtime,
                "build",
                "--network=private",
                "--pull=never",
                "--build-arg",
                f"BASE_IMAGE={plan.base_image}",
                "--build-arg",
                f"ENVIRONMENT_PROFILE_SHA256={profile_sha}",
                "--label",
                f"io.codira.agent-efficiency.environment-profile-sha256={profile_sha}",
                "--tag",
                tag,
                "--file",
                str(context / "Containerfile"),
                str(context),
            ),
            check=False,
            text=True,
            capture_output=True,
        )
    if completed.returncode != 0:
        detail = _terminal_build_detail(completed)
        raise EnvironmentImageBuildError(f"candidate image build failed: {detail}")
    inspected = subprocess.run(
        (runtime, "image", "inspect", "--format", "{{index .RepoDigests 0}}", tag),
        check=False,
        text=True,
        capture_output=True,
    )
    runtime_image = inspected.stdout.strip()
    if (
        inspected.returncode != 0
        or phase0.IMAGE_DIGEST_PATTERN.fullmatch(runtime_image) is None
    ):
        raise EnvironmentImageBuildError("candidate image identity is unavailable")
    profile = dict(plan.profile)
    profile.update(
        {
            "profile_fingerprint": canonical_fingerprint(plan.profile),
            "image_tag": tag,
            "runtime_image": runtime_image,
            "network_policy": "build-private-only; runtime-none",
        }
    )
    output_profile.parent.mkdir(parents=True, exist_ok=True)
    output_profile.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return runtime_image


def _terminal_build_detail(completed: subprocess.CompletedProcess[str]) -> str:
    """Return one bounded public-safe diagnostic from a failed image build.

    Parameters
    ----------
    completed : subprocess.CompletedProcess[str]
        Failed local runtime build process with captured output.

    Returns
    -------
    str
        Final output excerpt, truncated to a bounded diagnostic length.
    """

    output = "\n".join(
        item for item in (completed.stdout, completed.stderr) if item.strip()
    ).strip()
    return output[-1_000:] if output else "no runtime diagnostic"


def _ecosystem(source: Path) -> str:
    """Return the supported package ecosystem selected from project files.

    Parameters
    ----------
    source : pathlib.Path
        Immutable public fixture source root.

    Returns
    -------
    str
        ``uv``, ``npm``, or ``pip``.

    Raises
    ------
    EnvironmentImageBuildError
        If no supported environment is identifiable.
    """

    if (source / "pyproject.toml").is_file() and (source / "uv.lock").is_file():
        return "uv"
    if (source / "package.json").is_file():
        return "npm"
    if (source / "requirements.txt").is_file():
        return "pip"
    raise EnvironmentImageBuildError("fixture has no supported environment")


def _admit_revision(source: Path, fixture: dict[str, object]) -> tuple[str, str]:
    """Require that a source repository retains the exact frozen revision.

    Parameters
    ----------
    source : pathlib.Path
        Repository that is permitted to supply a Git archive.
    fixture : dict[str, object]
        Validated frozen fixture document.

    Returns
    -------
    tuple[str, str]
        Exact admitted revision and tree identity.

    Raises
    ------
    EnvironmentImageBuildError
        If the source does not retain the declared commit and tree.
    """

    revision = fixture.get("revision")
    tree_sha = fixture.get("tree_sha")
    if not isinstance(revision, str) or not isinstance(tree_sha, str):
        raise EnvironmentImageBuildError("fixture revision metadata is invalid")
    if GIT_EXECUTABLE is None:
        raise EnvironmentImageBuildError("Git is unavailable for fixture admission")
    object_check = subprocess.run(
        (GIT_EXECUTABLE, "cat-file", "-e", f"{revision}^{{commit}}"),
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    tree = subprocess.run(
        (GIT_EXECUTABLE, "rev-parse", f"{revision}^{{tree}}"),
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    if (
        object_check.returncode != 0
        or tree.returncode != 0
        or tree.stdout.strip() != tree_sha
    ):
        raise EnvironmentImageBuildError(
            "fixture revision is unavailable or has drifted"
        )
    return revision, tree_sha


def _declared_setup_fingerprints(fixture: dict[str, object]) -> dict[str, str]:
    """Return immutable setup hashes from a validated fixture document.

    Parameters
    ----------
    fixture : dict[str, object]
        Validated frozen fixture document.

    Returns
    -------
    dict[str, str]
        Relative setup paths mapped to their admission SHA-256 values.
    """

    setup_files = fixture.get("setup_files")
    if not isinstance(setup_files, list):
        raise EnvironmentImageBuildError("fixture setup files are invalid")
    fingerprints: dict[str, str] = {}
    for item in setup_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise EnvironmentImageBuildError("fixture setup files are invalid")
        relative = item["path"]
        sha256 = item.get("sha256")
        if not isinstance(sha256, str):
            raise EnvironmentImageBuildError("fixture setup files are invalid")
        fingerprints[relative] = sha256
    return fingerprints


def build_parser() -> argparse.ArgumentParser:
    """Build the candidate-environment image command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for an explicit controlled candidate image build.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--fixture-source", action="append", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output-profile", type=Path, required=True)
    parser.add_argument("--runtime", default="podman")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Build one candidate image or return a safe failure code.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero after immutable profile persistence and two on safe rejection.
    """

    args = build_parser().parse_args(arguments)
    try:
        plan = build_plan(args.base_image, parse_fixture_sources(args.fixture_source))
        runtime_image = build_image(plan, args.runtime, args.tag, args.output_profile)
    except (EnvironmentImageBuildError, OSError) as error:
        print(f"environment image build error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"runtime_image": runtime_image, "profile": str(args.output_profile)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
