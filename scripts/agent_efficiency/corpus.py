"""Admit and freeze public benchmark fixtures at immutable Git revisions."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Never

from scripts.agent_efficiency.contracts import ContractError, load_document

type CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
GIT_EXECUTABLE = shutil.which("git")


def _fail(detail: str) -> Never:
    """Raise one deterministic corpus-admission failure.

    Parameters
    ----------
    detail : str
        Safe diagnostic for the public admission record.

    Raises
    ------
    ContractError
        Always.
    """

    raise ContractError.message(detail)


@dataclass(frozen=True)
class FixtureReport:
    """Record verified immutable fixture metadata.

    Parameters
    ----------
    fixture_id : str
        Registered public fixture identity.
    revision : str
        Verified commit SHA.
    tree_sha : str
        Verified Git tree SHA.
    language_files : Mapping[str, int]
        Deterministic extension inventory for tracked files.
    """

    fixture_id: str
    revision: str
    tree_sha: str
    language_files: Mapping[str, int]


def _run(arguments: Sequence[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Run one text Git command in a fixture root.

    Parameters
    ----------
    arguments : Sequence[str]
        Shell-free command vector.
    root : pathlib.Path
        Checked-out fixture root.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Captured command result.
    """

    return subprocess.run(
        arguments, cwd=root, check=False, text=True, capture_output=True
    )


def _safe_path(raw: object, label: str) -> Path:
    """Return one non-escaping fixture-relative path.

    Parameters
    ----------
    raw : object
        Candidate POSIX path from a fixture document.
    label : str
        Field label for a deterministic failure.

    Returns
    -------
    pathlib.Path
        Validated relative path.

    Raises
    ------
    ContractError
        If the path is not safe beneath the fixture root.
    """

    if not isinstance(raw, str):
        _fail(f"{label} must be a safe relative path")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or "." in path.parts or ".." in path.parts:
        _fail(f"{label} must be a safe relative path")
    return Path(path)


def _sha256(path: Path) -> str:
    """Return the SHA-256 of one tracked fixture file.

    Parameters
    ----------
    path : pathlib.Path
        Existing fixture file.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """

    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_fixture(
    document: Mapping[str, object], root: Path, runner: CommandRunner = _run
) -> FixtureReport:
    """Verify one checked-out public fixture against its frozen admission record.

    Parameters
    ----------
    document : Mapping[str, object]
        Valid public fixture document with Phase 3 admission metadata.
    root : pathlib.Path
        Exact fixture checkout to verify.
    runner : CommandRunner, optional
        Injectable shell-free Git command runner.

    Returns
    -------
    FixtureReport
        Verified identity and tracked-file language inventory.

    Raises
    ------
    ContractError
        If identity, license, setup files, or transport policy differs.
    """

    required = {
        "tree_sha",
        "license_path",
        "license_sha256",
        "setup_files",
        "transport",
    }
    if not required <= document.keys() or document.get("transport") != "git-archive":
        _fail("fixture lacks immutable Phase 3 admission metadata")
    revision = runner(("git", "rev-parse", "HEAD"), root)
    tree = runner(("git", "rev-parse", "HEAD^{tree}"), root)
    files = runner(("git", "ls-files"), root)
    if any(item.returncode != 0 for item in (revision, tree, files)):
        _fail("fixture Git identity cannot be verified")
    if (
        revision.stdout.strip() != document["revision"]
        or tree.stdout.strip() != document["tree_sha"]
    ):
        _fail("fixture revision or tree does not match admission")
    license_path = root / _safe_path(document["license_path"], "license_path")
    if (
        not license_path.is_file()
        or _sha256(license_path) != document["license_sha256"]
    ):
        _fail("fixture license notice does not match admission")
    setup_files = document["setup_files"]
    if not isinstance(setup_files, list):
        _fail("fixture setup_files must be a list")
    for item in setup_files:
        if not isinstance(item, Mapping):
            _fail("fixture setup file must be an object")
        path = root / _safe_path(item.get("path"), "setup_files.path")
        if not path.is_file() or _sha256(path) != item.get("sha256"):
            _fail("fixture setup identity does not match admission")
    inventory: dict[str, int] = {}
    for raw in files.stdout.splitlines():
        suffix = Path(raw).suffix.lower().removeprefix(".") or "none"
        inventory[suffix] = inventory.get(suffix, 0) + 1
    return FixtureReport(
        fixture_id=str(document["fixture_id"]),
        revision=revision.stdout.strip(),
        tree_sha=tree.stdout.strip(),
        language_files=dict(sorted(inventory.items())),
    )


def load_admitted_documents(root: Path) -> tuple[dict[str, object], ...]:
    """Load every public fixture document from one admission directory.

    Parameters
    ----------
    root : pathlib.Path
        Directory containing public fixture JSON documents.

    Returns
    -------
    tuple[dict[str, object], ...]
        Fixture documents in deterministic filename order.
    """

    return tuple(load_document(path, "fixture") for path in sorted(root.glob("*.json")))


def load_task_oracles(
    task_root: Path, oracle_root: Path, fixtures: Sequence[Mapping[str, object]]
) -> tuple[tuple[dict[str, object], dict[str, object]], ...]:
    """Load public task/oracle pairs with complete frozen references.

    Parameters
    ----------
    task_root : pathlib.Path
        Directory of public task records.
    oracle_root : pathlib.Path
        Directory of public oracle records.
    fixtures : Sequence[Mapping[str, object]]
        Admitted fixture records.

    Returns
    -------
    tuple[tuple[dict[str, object], dict[str, object]], ...]
        Deterministically paired task and oracle documents.

    Raises
    ------
    ContractError
        If records are incomplete, duplicate, or cross-reference unknown IDs.
    """

    fixture_ids = {str(item["fixture_id"]) for item in fixtures}
    tasks = tuple(
        load_document(path, "task") for path in sorted(task_root.glob("*.json"))
    )
    oracles = tuple(
        load_document(path, "oracle") for path in sorted(oracle_root.glob("*.json"))
    )
    if len(tasks) != 7 or len(oracles) != 7:
        _fail("Phase 3 requires exactly seven task and oracle records")
    oracle_by_id = {str(item["oracle_id"]): item for item in oracles}
    if len(oracle_by_id) != len(oracles):
        _fail("oracle identifiers must be unique")
    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    for task in tasks:
        if task["fixture_id"] not in fixture_ids:
            _fail("task references an unadmitted fixture")
        oracle = oracle_by_id.get(str(task["oracle_id"]))
        if oracle is None or oracle["task_id"] != task["task_id"]:
            _fail("task and oracle identities do not match")
        pairs.append((task, oracle))
    return tuple(pairs)


def export_fixture(source: Path, revision: str, destination: Path) -> None:
    """Export one immutable Git revision with synthetic empty Git metadata.

    Parameters
    ----------
    source : pathlib.Path
        Verified Git checkout holding the admitted revision object.
    revision : str
        Immutable commit SHA to export.
    destination : pathlib.Path
        Absent or empty agent-visible fixture destination.

    Returns
    -------
    None
        A clean archive extraction and history-free Git working tree are written
        at ``destination``.

    Raises
    ------
    ContractError
        If Git export fails or the destination is unsafe for a fresh fixture.
    """

    if destination.exists() and any(destination.iterdir()):
        _fail("fixture export destination must be empty")
    if GIT_EXECUTABLE is None:
        _fail("fixture Git executable is unavailable")
    result = subprocess.run(
        (GIT_EXECUTABLE, "archive", "--format=tar", revision),
        cwd=source,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        _fail("fixture Git archive export failed")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=BytesIO(result.stdout), mode="r:") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                _fail("fixture archive contains an unsafe path")
        archive.extractall(destination, filter="data")
    initialized = subprocess.run(
        (GIT_EXECUTABLE, "init", "--quiet"),
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if initialized.returncode != 0:
        _fail("fixture synthetic Git initialization failed")
    staged = subprocess.run(
        (GIT_EXECUTABLE, "add", "--all"),
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if staged.returncode != 0:
        _fail("fixture synthetic Git index initialization failed")


def verify_source_fix_excluded(root: Path, source_fix: str) -> None:
    """Verify an agent fixture has no Git history, remote, or source-fix marker.

    Parameters
    ----------
    root : pathlib.Path
        Exported agent-visible fixture root.
    source_fix : str
        Protected source-fix commit SHA forbidden to the agent fixture.

    Returns
    -------
    None
        The fixture has only synthetic empty metadata and no protected marker.

    Raises
    ------
    ContractError
        If Git history, a remote, or the protected commit identity is present.
    """

    metadata = root / ".git"
    if not metadata.is_dir() or any(
        path.name == ".git" and path != metadata for path in root.rglob(".git")
    ):
        _fail("agent fixture has invalid synthetic Git metadata")
    if GIT_EXECUTABLE is None:
        _fail("fixture Git executable is unavailable")
    history = _run((GIT_EXECUTABLE, "rev-parse", "--verify", "HEAD"), root)
    if history.returncode == 0:
        _fail("agent fixture exposes Git history")
    remotes = _run((GIT_EXECUTABLE, "remote"), root)
    if remotes.returncode != 0 or remotes.stdout.strip():
        _fail("agent fixture exposes a Git remote")
    for path in root.rglob("*"):
        if path.is_file() and source_fix in path.read_text(
            encoding="utf-8", errors="ignore"
        ):
            _fail("agent fixture leaks protected source-fix identity")
