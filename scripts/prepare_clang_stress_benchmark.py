#!/usr/bin/env python3
"""Prepare a worktree-bound Clang variant of the local stress suite.

This command copies the frozen local stress inputs into a new preparation
artifact, selects Clang explicitly for C/C++ analyzers, and records source
coverage for selected compile contexts. It never starts the benchmark.

Parameters
----------
None

Returns
-------
None
    A preparation receipt is written to the requested fresh artifact directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, cast

import tomlkit

CONTEXT_SCHEMA = "codira.clang-stress-context-selection/1"
PREPARATION_SCHEMA = "codira.clang-stress-preparation/1"
GIT_EXECUTABLE = shutil.which("git") or "/usr/bin/git"
SOURCE_SUFFIXES = {
    "c": frozenset({".c"}),
    "cpp": frozenset({".cpp", ".cc", ".cxx"}),
}
HEADER_SUFFIXES = {
    "c": frozenset({".h"}),
    "cpp": frozenset({".h", ".hpp", ".hh", ".hxx", ".ipp"}),
}


class PreparationError(ValueError):
    """Report invalid source identities or malformed preparation inputs.

    Parameters
    ----------
    message : str
        Actionable preparation failure.

    Returns
    -------
    None
        This exception is raised instead of writing a partial preparation.
    """


@dataclass(frozen=True)
class ConfigCopyPlan:
    """Bind the inputs used while copying the source profile configurations.

    Parameters
    ----------
    output_dir : pathlib.Path
        Fresh preparation artifact root.
    source_manifest_path : pathlib.Path
        Retained source manifest used to resolve config paths.
    source_config_root : pathlib.Path
        Original benchmark directory containing config files.
    original_profiles : list[dict[str, object]]
        Original profiles used to map structural variants.
    profiles : list[dict[str, object]]
        Draft profiles to materialize.
    context_summary : dict
        Validated compiler context evidence.
    embedding_policy : str
        Chosen embedding behavior.
    attempt_root : pathlib.Path
        Unique future evidence directory.

    Returns
    -------
    None
        This record is immutable after construction.
    """

    output_dir: Path
    source_manifest_path: Path
    source_config_root: Path
    original_profiles: list[dict[str, object]]
    profiles: list[dict[str, object]]
    context_summary: dict[str, dict[str, dict[str, object]]]
    embedding_policy: str
    attempt_root: Path


def _fail(message: str, *, cause: BaseException | None = None) -> NoReturn:
    """Raise the preparation-specific input error with optional provenance.

    Parameters
    ----------
    message : str
        Actionable preparation failure.
    cause : BaseException or None, optional
        Original parsing or filesystem error.

    Returns
    -------
    NoReturn
        This function always raises.
    """
    raise PreparationError(message) from cause


def _sha256_bytes(payload: bytes) -> str:
    """Return the SHA-256 digest of exact bytes.

    Parameters
    ----------
    payload : bytes
        Input bytes.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file's current bytes.

    Parameters
    ----------
    path : pathlib.Path
        Existing file.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    return _sha256_bytes(path.read_bytes())


def _read_object(path: Path, label: str) -> dict[str, object]:
    """Read a JSON object without accepting other top-level shapes.

    Parameters
    ----------
    path : pathlib.Path
        JSON document path.
    label : str
        Human-readable document name for errors.

    Returns
    -------
    dict[str, object]
        Parsed document.

    Raises
    ------
    PreparationError
        If the document is absent, invalid JSON, or not an object.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _fail(f"cannot read {label}: {error}", cause=error)
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return cast("dict[str, object]", value)


def _resolve_under(path: Path, root: Path, label: str) -> Path:
    """Resolve a path and require it to remain under a selected root.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path.
    root : pathlib.Path
        Required containment root.
    label : str
        Human-readable input name.

    Returns
    -------
    pathlib.Path
        Canonical contained path.

    Raises
    ------
    PreparationError
        If the path escapes the required root.
    """
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        _fail(f"{label} must be inside {root}")
    return resolved


def _scan_source_inventory(
    root: Path, language: str
) -> tuple[list[Path], list[Path], list[str], list[dict[str, object]]]:
    """Inventory analyzer-recognized source and header suffixes conservatively.

    Parameters
    ----------
    root : pathlib.Path
        Pinned third-party source checkout.
    language : str
        Analyzer language, either ``c`` or ``cpp``.

    Returns
    -------
    tuple[list[pathlib.Path], list[pathlib.Path], list[str], list[dict]]
        Sorted translation units and headers, symlink directories, and
        source/header symlink files held outside the inventory.
    """
    if language not in SOURCE_SUFFIXES:
        _fail(f"unsupported analyzer language: {language}")
    sources: list[Path] = []
    headers: list[Path] = []
    symlink_directories: list[str] = []
    symlink_files: list[dict[str, object]] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        retained_directories = []
        for name in sorted(dirnames):
            candidate = current / name
            if name in {".git", ".codira", ".artifacts"}:
                continue
            if candidate.is_symlink():
                symlink_directories.append(str(candidate.resolve()))
                continue
            retained_directories.append(name)
        dirnames[:] = retained_directories
        for name in filenames:
            path = current / name
            if (
                path.suffix in SOURCE_SUFFIXES[language] | HEADER_SUFFIXES[language]
                and path.is_symlink()
            ):
                target = path.resolve()
                symlink_files.append(
                    {
                        "path": str(path.absolute()),
                        "target": str(target),
                        "outside_repository": not target.is_relative_to(root.resolve()),
                    }
                )
                continue
            if path.suffix in SOURCE_SUFFIXES[language]:
                sources.append(path.resolve())
            elif path.suffix in HEADER_SUFFIXES[language]:
                headers.append(path.resolve())
    return (
        sorted(set(sources)),
        sorted(set(headers)),
        symlink_directories,
        symlink_files,
    )


def _source_revision_failures(repository: Path, expected_revision: object) -> list[str]:
    """Require the corpus checkout to match its pinned clean Git revision.

    Parameters
    ----------
    repository : pathlib.Path
        Pinned corpus checkout.
    expected_revision : object
        Expected commit recorded by the retained source manifest.

    Returns
    -------
    list[str]
        Empty only when HEAD matches and the checkout has no tracked or
        untracked changes.
    """
    if not isinstance(expected_revision, str) or not expected_revision:
        return ["source manifest has no pinned corpus revision"]
    try:
        head = subprocess.check_output(
            [GIT_EXECUTABLE, "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            [
                GIT_EXECUTABLE,
                "-C",
                str(repository),
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        return [f"corpus Git identity is unavailable: {error}"]
    failures: list[str] = []
    if head != expected_revision:
        failures.append(
            f"corpus HEAD {head} differs from pinned revision {expected_revision}"
        )
    if status:
        failures.append("corpus checkout has tracked or untracked changes")
    return failures


def _load_context_selection(
    contexts_path: Path | None, source_manifest_sha256: str
) -> tuple[
    dict[tuple[str, str], dict[str, object]],
    list[str],
    dict[str, object],
]:
    """Load explicit C/C++ compiler-context selections.

    Parameters
    ----------
    contexts_path : pathlib.Path or None
        Optional versioned selection file.
    source_manifest_sha256 : str
        Exact source-manifest digest expected by the selection.

    Returns
    -------
    tuple[dict[tuple[str, str], dict[str, object]], list[str], dict[str, object]]
        Per-file contexts, selection errors, and shared helper bindings.
    """
    if contexts_path is None:
        return {}, [], {}
    document = _read_object(contexts_path, "compiler-context selection")
    if (
        document.get("schema") != CONTEXT_SCHEMA
        or document.get("source_manifest_sha256") != source_manifest_sha256
    ):
        _fail("compiler-context selection schema or source manifest digest differs")
    global_contexts: dict[str, object] = {}
    for field in ("helper", "build_receipt"):
        value = document.get(field)
        if value is not None:
            if not isinstance(value, dict):
                _fail(f"context selection {field} is malformed")
            global_contexts[field] = value
    entries = document.get("contexts")
    if not isinstance(entries, list):
        _fail("context selection requires a contexts array")
    selected: dict[tuple[str, str], dict[str, object]] = {}
    for index, value in enumerate(entries):
        if not isinstance(value, dict):
            _fail(f"context selection entry {index} is malformed")
        repo = value.get("repository")
        language = value.get("language")
        if not isinstance(repo, str) or language not in {"c", "cpp"}:
            _fail(f"context selection entry {index} has invalid identity")
        key = (repo, cast("str", language))
        if key in selected:
            _fail(f"duplicate compiler context for {repo}/{language}")
        for field in ("helper", "build_receipt"):
            if (
                field in value
                and field in global_contexts
                and value[field] != global_contexts[field]
            ):
                _fail(f"context {repo}/{language} overrides the global {field}")
        selected[key] = {**global_contexts, **value}
    return selected, [], global_contexts


def _context_file(
    context: dict[str, object], field: str, label: str
) -> tuple[Path | None, str | None]:
    """Validate an explicit file path and expected digest.

    Parameters
    ----------
    context : dict[str, object]
        Selected context entry.
    field : str
        Context-file key, such as ``path`` or ``helper``.
    label : str
        Human-readable evidence label.

    Returns
    -------
    tuple[pathlib.Path or None, str or None]
        Existing path and no error when exact bytes match; otherwise a held reason.
    """
    value = context.get(field)
    if not isinstance(value, dict):
        return None, f"{label} path and digest are not supplied"
    path_value = value.get("path")
    digest_value = value.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest_value, str):
        return None, f"{label} path or digest is malformed"
    path = Path(path_value).resolve()
    if not path.is_file():
        return None, f"{label} file is absent"
    observed = _sha256_file(path)
    if observed != digest_value:
        return None, f"{label} digest differs from selection"
    return path, None


def _validate_global_helper(
    context: dict[str, object],
) -> tuple[dict[str, object] | None, list[str]]:
    """Validate the shared native helper and live compiler identity.

    Parameters
    ----------
    context : dict[str, object]
        Shared selection containing exact helper and build-receipt paths/hashes.

    Returns
    -------
    tuple[dict[str, object] or None, list[str]]
        Toolchain identity and blocking infrastructure failures.
    """
    helper, helper_error = _context_file(context, "helper", "native helper")
    receipt, receipt_error = _context_file(
        context, "build_receipt", "native build receipt"
    )
    failures = [item for item in (helper_error, receipt_error) if item]
    if helper is None or receipt is None or failures:
        return None, failures
    try:
        from codira_clang_frontend import ClangFrontend, __version__

        frontend = ClangFrontend(helper, receipt, package_version=__version__)
        identity = frontend._load_toolchain_identity()
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as error:
        return None, [f"native Clang toolchain validation failed: {error}"]
    return {
        "helper_path": str(helper),
        "helper_sha256": _sha256_file(helper),
        "build_receipt_path": str(receipt),
        "build_receipt_sha256": _sha256_file(receipt),
        "compiler_path": str(identity.compiler_path),
        "compiler_sha256": identity.compiler_sha256,
        "compiler_version": identity.compiler_version,
        "resource_dir": str(identity.resource_dir),
        "resource_probe_sha256": identity.resource_probe_sha256,
        "frontend_package_version": __version__,
    }, []


def _external_input_bindings(
    contexts: dict[str, dict[str, dict[str, object]]],
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Collect every external context artifact and its immutable digest.

    Parameters
    ----------
    contexts : dict
        Prepared per-repository and per-language context summaries.

    Returns
    -------
    dict
        Paths and SHA-256 values for the exact files used by analyzer configs.
    """
    bindings: dict[str, dict[str, list[dict[str, str]]]] = {}
    for repository, languages in contexts.items():
        bindings[repository] = {}
        for language, evidence in languages.items():
            inputs = []
            for path_key, digest_key in (
                ("compile_database_path", "compile_database_sha256"),
                ("captured_profiles_path", "captured_profiles_sha256"),
                ("helper_path", "helper_sha256"),
                ("build_receipt_path", "build_receipt_sha256"),
            ):
                path = evidence.get(path_key)
                digest = evidence.get(digest_key)
                if isinstance(path, str) and isinstance(digest, str):
                    inputs.append({"path": path, "sha256": digest})
            bindings[repository][language] = inputs
    return bindings


def _compile_database_rows(path: Path) -> tuple[dict[Path, int], list[str]]:
    """Read compile-database rows and count exact translation-unit matches.

    Parameters
    ----------
    path : pathlib.Path
        Selected compile database.

    Returns
    -------
    tuple[dict[pathlib.Path, int], list[str]]
        Canonical translation-unit row counts and malformed-row reasons.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {}, [f"compile database cannot be read: {error}"]
    if not isinstance(document, list):
        return {}, ["compile database top level must be an array"]
    rows: dict[Path, int] = {}
    failures: list[str] = []
    for index, value in enumerate(document):
        if not isinstance(value, dict):
            failures.append(f"compile database row {index} is not an object")
            continue
        directory_value = value.get("directory")
        file_value = value.get("file")
        arguments = value.get("arguments")
        command = value.get("command")
        has_argv = (
            isinstance(arguments, list)
            and bool(arguments)
            and all(isinstance(item, str) for item in arguments)
        )
        has_command = isinstance(command, str) and bool(command.strip())
        if (
            not isinstance(directory_value, str)
            or not Path(directory_value).is_absolute()
            or not isinstance(file_value, str)
            or not (has_argv or has_command)
        ):
            failures.append(f"compile database row {index} lacks an exact command")
            continue
        source = Path(file_value)
        if not source.is_absolute():
            source = Path(directory_value) / source
        resolved = source.resolve()
        rows[resolved] = rows.get(resolved, 0) + 1
    return rows, failures


def _discover_compile_databases(search_roots: object) -> list[Path]:
    """Find compile databases under explicit build-tree roots.

    Parameters
    ----------
    search_roots : object
        JSON value expected to be a list of absolute directory paths.

    Returns
    -------
    list[pathlib.Path]
        Sorted unique compile database paths. Symlink directories are skipped.

    Raises
    ------
    PreparationError
        If a root is missing, malformed, or not an absolute directory.
    """
    if not isinstance(search_roots, list) or not search_roots:
        _fail("discovery requires explicit search_roots")
    found: set[Path] = set()
    for root_value in search_roots:
        if not isinstance(root_value, str) or not Path(root_value).is_absolute():
            _fail("compile database search roots must be absolute")
        root = Path(root_value).resolve()
        if not root.is_dir():
            _fail(f"compile database search root is absent: {root}")
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(directory)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in {".git", ".codira", ".artifacts"}
                and not (current / name).is_symlink()
            )
            if "compile_commands.json" in filenames:
                candidate = (current / "compile_commands.json").resolve()
                if candidate.is_file():
                    found.add(candidate)
    return sorted(found)


def _captured_profile_sources(
    path: Path,
    sources: list[Path],
    repository_root: Path,
    helper_path: Path,
    receipt_path: Path,
) -> tuple[dict[Path, dict[str, str]], list[str]]:
    """Validate captured profiles with the frontend's dependency guards.

    Parameters
    ----------
    path : pathlib.Path
        Captured-profile collection.
    sources : list[pathlib.Path]
        Exact translation-unit inventory for this repository and language.
    repository_root : pathlib.Path
        Pinned repository checkout.
    helper_path : pathlib.Path
        Exact native helper selected for the analyzer.
    receipt_path : pathlib.Path
        Build receipt bound to the selected helper.

    Returns
    -------
    tuple[dict[pathlib.Path, dict[str, str]], list[str]]
        Sources with exactly one valid profile bound to identity and fingerprint,
        plus validation failures. Missing and ambiguous sources remain held.
    """
    expected = {source.resolve(): _sha256_file(source) for source in sources}
    try:
        from codira_clang_frontend import ClangFrontend, __version__
        from codira_clang_frontend.profile import from_captured_profiles_json

        profiles = from_captured_profiles_json(path, repository_root, expected)
        frontend = ClangFrontend(helper_path, receipt_path, package_version=__version__)
        counts: dict[Path, list[dict[str, str]]] = {}
        for profile in profiles:
            if profile.status != "complete":
                _fail("captured profile is not complete")
            source = profile.source_path.resolve()
            counts.setdefault(source, []).append(
                {
                    "profile_identity": profile.identity,
                    "toolchain_fingerprint": frontend.toolchain_fingerprint(profile),
                }
            )
    except (ImportError, OSError, ValueError, PreparationError) as error:
        return {}, [f"captured profiles failed frontend validation: {error}"]
    return {
        source: identities[0]
        for source, identities in counts.items()
        if len(identities) == 1
    }, []


def _discover_context_evidence(
    context: dict[str, object], root: Path, sources: list[Path]
) -> tuple[dict[str, object], list[str]]:
    """Select exactly one out-of-source CDB that covers each translation unit.

    Parameters
    ----------
    context : dict[str, object]
        Explicit discovery selection containing search roots.
    root : pathlib.Path
        Corpus root used to exclude in-tree databases.
    sources : list[pathlib.Path]
        Exact translation-unit inventory.

    Returns
    -------
    tuple[dict[str, object], list[str]]
        Selected CDB identity or a held reason.
    """
    summary: dict[str, object] = {
        "covered_translation_unit_count": 0,
        "missing_translation_unit_count": len(sources),
        "ambiguous_translation_unit_count": 0,
        "held_translation_units": [
            {"path": str(source), "reason": "no selected compiler context"}
            for source in sources
        ],
        "infrastructure_failures": [],
    }
    try:
        candidates = _discover_compile_databases(context.get("search_roots"))
    except PreparationError as error:
        return summary, [str(error)]
    matches: list[Path] = []
    for candidate in candidates:
        if candidate.is_relative_to(root):
            continue
        rows, failures = _compile_database_rows(candidate)
        if (
            sources
            and not failures
            and all(rows.get(source, 0) == 1 for source in sources)
        ):
            matches.append(candidate)
    if len(matches) != 1:
        return summary, [
            "out-of-source discovery found no unique compile database covering every translation unit"
        ]
    path = matches[0]
    summary.update(
        compile_database_path=str(path),
        compile_database_sha256=_sha256_file(path),
        covered_translation_unit_count=len(sources),
        missing_translation_unit_count=0,
    )
    return summary, [
        "compile database binds argv only; complete captured dependency and include guards are absent"
    ]


def _selected_context_evidence(
    context: dict[str, object] | None, root: Path, sources: list[Path]
) -> tuple[dict[str, object], list[str]]:
    """Validate a selected compile database or captured profile collection.

    Parameters
    ----------
    context : dict[str, object] or None
        Selection for one repository and language.
    root : pathlib.Path
        Corpus root used to reject in-tree context outputs.
    sources : list[pathlib.Path]
        Exact translation-unit inventory.

    Returns
    -------
    tuple[dict[str, object], list[str]]
        Context bindings and fail-closed reasons.
    """
    summary: dict[str, object] = {
        "covered_translation_unit_count": 0,
        "missing_translation_unit_count": len(sources),
        "ambiguous_translation_unit_count": 0,
        "held_translation_units": [
            {"path": str(source), "reason": "no selected compiler context"}
            for source in sources
        ],
        "infrastructure_failures": [],
    }
    if context is None:
        return summary, ["no explicit context selection for this repo/language"]
    kind = context.get("kind")
    if kind == "discover_compile_commands":
        return _discover_context_evidence(context, root, sources)
    if kind not in {"compile_commands", "captured_profiles"}:
        cast("list[str]", summary["infrastructure_failures"]).append(
            "context kind is unsupported"
        )
        return summary, [
            "context kind is unsupported; use compile_commands, captured_profiles, or discovery"
        ]
    label = (
        "compile database"
        if kind == "compile_commands"
        else "captured profile collection"
    )
    path, reason = _context_file(context, "evidence", label)
    if reason:
        cast("list[str]", summary["infrastructure_failures"]).append(reason)
        return summary, [reason]
    if path is None:
        return summary, [f"{label} path is unavailable"]
    if path.is_relative_to(root):
        cast("list[str]", summary["infrastructure_failures"]).append(
            "selected context is inside the corpus; use a separate build tree"
        )
        return summary, [
            "selected context is inside the corpus; use a separate build tree"
        ]
    if kind == "captured_profiles":
        helper_path, helper_error = _context_file(context, "helper", "native helper")
        receipt_path, receipt_error = _context_file(
            context, "build_receipt", "native build receipt"
        )
        if helper_error or receipt_error or helper_path is None or receipt_path is None:
            return summary, [
                helper_error or receipt_error or "helper build is unavailable"
            ]
        profile_bindings, failures = _captured_profile_sources(
            path, sources, root, helper_path, receipt_path
        )
        covered = len(set(profile_bindings).intersection(sources))
        summary["validated_profile_bindings"] = [
            {"path": str(source), **binding}
            for source, binding in sorted(profile_bindings.items())
        ]
        summary.update(
            captured_profiles_path=str(path),
            captured_profiles_sha256=_sha256_file(path),
            covered_translation_unit_count=covered,
            missing_translation_unit_count=len(sources) - covered,
        )
        summary["held_translation_units"] = [
            {
                "path": str(source),
                "reason": "captured profile is absent or ambiguous",
            }
            for source in sources
            if source not in profile_bindings
        ]
        if failures:
            cast("list[str]", summary["infrastructure_failures"]).extend(failures)
        if covered != len(sources):
            failures.append(
                "some source translation units lack a unique captured profile"
            )
        return summary, failures
    rows, failures = _compile_database_rows(path)
    if failures:
        cast("list[str]", summary["infrastructure_failures"]).extend(failures)
    counts = [rows.get(source, 0) for source in sources]
    covered = sum(count == 1 for count in counts)
    ambiguous = sum(count > 1 for count in counts)
    summary.update(
        compile_database_path=str(path),
        compile_database_sha256=_sha256_file(path),
        covered_translation_unit_count=covered,
        missing_translation_unit_count=sum(count == 0 for count in counts),
        ambiguous_translation_unit_count=ambiguous,
    )
    summary["held_translation_units"] = [
        {
            "path": str(source),
            "reason": (
                "compile command is ambiguous"
                if rows.get(source, 0) > 1
                else "compile command is missing"
                if rows.get(source, 0) == 0
                else "only argv is captured; guarded profile is unavailable"
            ),
        }
        for source in sources
    ]
    if covered != len(sources) or ambiguous:
        failures.append("compile database has missing or ambiguous source contexts")
    else:
        failures.append(
            "compile database has argv only; guarded Clang profiles are unavailable"
        )
    return summary, failures


def _validate_context(
    repo: dict[str, object],
    language: str,
    context: dict[str, object] | None,
    global_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Validate one repo/language context and classify uncovered files held.

    Parameters
    ----------
    repo : dict[str, object]
        Frozen corpus member from the source manifest.
    language : str
        Analyzer language, either C or C++.
    context : dict[str, object] or None
        Explicit selected context, when supplied.
    global_context : dict[str, object] or None
        Shared helper and build receipt selection.

    Returns
    -------
    dict[str, object]
        Coverage summary with source/header holds and context bindings.
    """
    label = cast("str", repo["label"])
    root = Path(cast("str", repo["path"])).resolve()
    sources, headers, symlink_directories, symlink_files = _scan_source_inventory(
        root, language
    )
    result: dict[str, object] = {
        "repository": label,
        "language": language,
        "translation_unit_count": len(sources),
        "header_count": len(headers),
        "source_inventory_sha256": _sha256_bytes(
            "\n".join(str(path) for path in sources).encode()
        ),
        "header_inventory_sha256": _sha256_bytes(
            "\n".join(str(path) for path in headers).encode()
        ),
        "covered_translation_unit_count": 0,
        "missing_translation_unit_count": len(sources),
        "ambiguous_translation_unit_count": 0,
        "held_header_count": len(headers),
        "held_headers": [
            {"path": str(header), "reason": "header owner profile is unavailable"}
            for header in headers
        ],
        "symlinked_directory_count": len(symlink_directories),
        "held_directories": [
            {"path": path, "reason": "symlink directory excluded from traversal"}
            for path in symlink_directories
        ],
        "held_symlink_files": [
            {
                **row,
                "reason": (
                    "source symlink target is outside pinned repository"
                    if row["outside_repository"]
                    else "source symlink is excluded from inventory"
                ),
            }
            for row in symlink_files
        ],
        "state": "held",
        "failures": [],
        "infrastructure_failures": [],
    }
    failures = cast("list[str]", result["failures"])
    infrastructure_failures = cast("list[str]", result["infrastructure_failures"])
    revision_failures = _source_revision_failures(root, repo.get("revision"))
    result["source_revision"] = repo.get("revision")
    result["source_revision_failures"] = revision_failures
    failures.extend(revision_failures)
    infrastructure_failures.extend(revision_failures)
    if not sources:
        failures.append(
            "source inventory is empty despite nonzero manifest analyzer LOC"
        )
    context_summary, context_failures = _selected_context_evidence(
        context, root, sources
    )
    result.update(context_summary)
    failures.extend(context_failures)
    infrastructure_failures.extend(
        cast("list[str]", context_summary.get("infrastructure_failures", []))
    )
    selected_context = context or {}
    infrastructure_context = {**(global_context or {}), **selected_context}
    helper_path, helper_error = _context_file(
        infrastructure_context, "helper", "native helper"
    )
    receipt_path, receipt_error = _context_file(
        infrastructure_context, "build_receipt", "native build receipt"
    )
    if helper_error:
        failures.append(helper_error)
    else:
        result["helper_path"] = str(helper_path)
        result["helper_sha256"] = _sha256_file(cast("Path", helper_path))
    if receipt_error:
        failures.append(receipt_error)
    else:
        result["build_receipt_path"] = str(receipt_path)
        result["build_receipt_sha256"] = _sha256_file(cast("Path", receipt_path))
    if headers:
        failures.append("header owner profiles are not supplied; headers remain held")
    if symlink_directories:
        failures.append("source inventory skipped symlinked directories")
    if symlink_files:
        failures.append("source inventory held symlinked source/header files")
    if not failures and not headers and not symlink_directories and not symlink_files:
        result["state"] = "ready"
    return result


def _set_clang_config(
    config: object,
    language: str,
    evidence: dict[str, object],
    attempt_root: Path,
) -> str:
    """Set explicit Clang frontend options and serialize a copied TOML config.

    Parameters
    ----------
    config : object
        Parsed TOML document.
    language : str
        Analyzer language, either C or C++.
    evidence : dict[str, object]
        Validated context summary.
    attempt_root : pathlib.Path
        Future durable attempt directory unique to this config.

    Returns
    -------
    str
        TOML configuration text.
    """
    if not isinstance(config, MutableMapping):
        _fail("copied analyzer config is not a table")
    plugins = config.setdefault("plugins", tomlkit.table())
    if not isinstance(plugins, MutableMapping):
        _fail("plugins config is not a table")
    key = f"analyzer-{language}"
    existing = plugins.get(key)
    plugin = existing if isinstance(existing, MutableMapping) else tomlkit.table()
    plugin["frontend"] = "clang"
    if isinstance(evidence.get("compile_database_path"), str):
        plugin["clang_compile_commands"] = evidence["compile_database_path"]
        plugin.pop("clang_captured_profiles", None)
    if isinstance(evidence.get("captured_profiles_path"), str):
        plugin["clang_captured_profiles"] = evidence["captured_profiles_path"]
        plugin.pop("clang_compile_commands", None)
    if isinstance(evidence.get("helper_path"), str):
        plugin["clang_helper_path"] = evidence["helper_path"]
    if isinstance(evidence.get("build_receipt_path"), str):
        plugin["clang_build_receipt_path"] = evidence["build_receipt_path"]
    plugin["clang_attempt_root"] = str(attempt_root.resolve())
    plugins[key] = plugin
    return tomlkit.dumps(config)


def _copy_config(
    destination: Path,
    source_bytes: bytes,
    repo: dict[str, object],
    language_evidence: dict[str, dict[str, object]],
    attempt_root: Path,
) -> str:
    """Copy one profile config and set only explicit C/C++ frontend options.

    Parameters
    ----------
    destination : pathlib.Path
        New preparation config path.
    repo : dict[str, object]
        Corpus member record.
    language_evidence : dict[str, dict[str, object]]
        Per-language context coverage summaries for this repository.
    attempt_root : pathlib.Path
        Future run artifact root.

    Returns
    -------
    str
        SHA-256 digest of the copied-and-updated config.
    """
    document = tomlkit.parse(source_bytes.decode("utf-8"))
    plugin_loc = repo.get("analyzer_loc", {})
    if not isinstance(plugin_loc, dict):
        plugin_loc = {}
    for language in ("c", "cpp"):
        if int(plugin_loc.get(language, 0)) <= 0:
            continue
        config_text = _set_clang_config(
            document,
            language,
            language_evidence.get(language, {}),
            attempt_root / cast("str", repo["label"]) / language,
        )
        document = tomlkit.parse(config_text)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = tomlkit.dumps(document).encode()
    destination.write_bytes(payload)
    return _sha256_bytes(payload)


def _validated_source_config_hashes(
    source_identity: dict[str, object],
    source_config_root: Path,
    allow_mismatch: bool,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Verify the selected config root against the retained config digests.

    Parameters
    ----------
    source_identity : dict[str, object]
        Adjacent historical run identity.
    source_config_root : pathlib.Path
        Original suite directory containing the config files.
    allow_mismatch : bool
        Permit current config bytes as a separately bound new input.

    Returns
    -------
    tuple[dict[str, str], list[dict[str, str]]]
        Current digest map and explicit historical/current mismatches.
    """
    historical = source_identity.get("configs")
    if not isinstance(historical, dict):
        _fail("source identity does not bind config hashes")
    current: dict[str, str] = {}
    mismatches: list[dict[str, str]] = []
    for relative, expected in historical.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            _fail("source identity contains malformed config hashes")
        path = _resolve_under(
            source_config_root / relative, source_config_root, "source config"
        )
        if not path.is_file():
            _fail(f"source config is absent: {relative}")
        observed = _sha256_file(path)
        current[relative] = observed
        if observed != expected:
            mismatches.append(
                {
                    "path": relative,
                    "historical_sha256": expected,
                    "current_sha256": observed,
                }
            )
    if mismatches and not allow_mismatch:
        _fail("one or more source configs differ from the adjacent historical identity")
    return current, mismatches


def _load_source_bundle(
    source_manifest_path: Path,
    worktree: Path,
    contexts_path: Path | None,
    allow_manifest_mismatch: bool,
) -> tuple[
    dict[str, object],
    str,
    str,
    Path,
    Path,
    dict[str, str],
    list[dict[str, str]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Verify the retained campaign manifest, identity and configurations.

    Parameters
    ----------
    source_manifest_path : pathlib.Path
        Original immutable campaign manifest.
    worktree : pathlib.Path
        Git worktree that will own the new campaign.
    contexts_path : pathlib.Path or None
        Optional selection supplying an explicit original config directory.
    allow_manifest_mismatch : bool
        Treat current manifest bytes as a new baseline when explicitly allowed.

    Returns
    -------
    tuple
        Source manifest, current and historical digests, identity path, current
        config digests, their historical mismatches, profiles, and repositories.
    """
    source_manifest_path = source_manifest_path.resolve()
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = _read_object(source_manifest_path, "source stress manifest")
    source_manifest_sha = _sha256_bytes(source_manifest_bytes)
    source_identity_path = source_manifest_path.with_name("identity.json")
    source_identity = _read_object(source_identity_path, "source campaign identity")
    source_config_root = source_manifest_path.parent
    if contexts_path is not None:
        config_root_value = _read_object(
            contexts_path, "compiler-context selection"
        ).get("source_config_root")
        if isinstance(config_root_value, str):
            source_config_root = Path(config_root_value).resolve()
            original_root = source_manifest.get("codira_root")
            if not isinstance(
                original_root, str
            ) or not source_config_root.is_relative_to(Path(original_root).resolve()):
                _fail("source config root must be inside the original Codira checkout")
            if not source_config_root.is_dir():
                _fail("selected source config root is absent")
    historical_manifest_sha = source_identity.get("manifest_sha256")
    if not isinstance(historical_manifest_sha, str):
        _fail("source campaign identity lacks its manifest digest")
    if historical_manifest_sha != source_manifest_sha and not allow_manifest_mismatch:
        _fail("source manifest does not match its immutable identity")
    if source_manifest.get("schema_version") != 1:
        _fail("source stress manifest schema is unsupported")
    profiles_value = source_manifest.get("profiles")
    repositories_value = source_manifest.get("repositories")
    if not isinstance(profiles_value, list) or not isinstance(repositories_value, list):
        _fail("source stress manifest lacks profiles or repositories")
    profiles = [
        cast("dict[str, object]", item)
        for item in profiles_value
        if isinstance(item, dict)
    ]
    repositories = [
        cast("dict[str, object]", item)
        for item in repositories_value
        if isinstance(item, dict)
    ]
    if len(profiles) != len(profiles_value) or len(repositories) != len(
        repositories_value
    ):
        _fail("source stress manifest contains malformed rows")
    current_config_hashes, config_mismatches = _validated_source_config_hashes(
        source_identity, source_config_root, allow_manifest_mismatch
    )
    for repository in repositories:
        config_map = repository.get("configs")
        if not isinstance(config_map, dict):
            _fail("source manifest repository lacks config paths")
        for relative in config_map.values():
            if not isinstance(relative, str) or relative not in current_config_hashes:
                _fail("manifest-selected config is not bound by source identity")
            _resolve_under(
                source_config_root / relative, source_config_root, "source config"
            )
    actual_worktree = Path(
        subprocess.check_output(
            [GIT_EXECUTABLE, "-C", str(worktree), "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    ).resolve()
    if actual_worktree != worktree:
        _fail("worktree path is not the Git checkout root")
    return (
        source_manifest,
        source_manifest_sha,
        historical_manifest_sha,
        source_identity_path,
        source_config_root,
        current_config_hashes,
        config_mismatches,
        profiles,
        repositories,
    )


def _manifest_mismatch_ack(contexts_path: Path | None) -> bool:
    """Read the exact acknowledgement for treating changed manifest bytes as new.

    Parameters
    ----------
    contexts_path : pathlib.Path or None
        Bound compiler-context selection document.

    Returns
    -------
    bool
        Whether the new-input acknowledgement is present.
    """
    if contexts_path is None:
        return False
    try:
        document = _read_object(contexts_path, "compiler-context selection")
    except PreparationError:
        return False
    return (
        document.get("source_manifest_mismatch_ack")
        == "accept_current_bytes_as_new_input"
    )


def _prepare_context_summaries(
    repositories: list[dict[str, object]],
    selected: dict[tuple[str, str], dict[str, object]],
    global_context: dict[str, object] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    """Validate selected contexts for every declared C/C++ workload.

    Parameters
    ----------
    repositories : list[dict[str, object]]
        Frozen corpus member rows.
    selected : dict
        Context selections indexed by repository label and language.
    global_context : dict[str, object] or None
        Shared helper and build receipt selection.

    Returns
    -------
    dict
        Per-repository/language held or ready context records.
    """
    summary: dict[str, dict[str, dict[str, object]]] = {}
    for repo in repositories:
        label = repo.get("label")
        path_value = repo.get("path")
        analyzer_loc = repo.get("analyzer_loc", {})
        if not isinstance(label, str) or not isinstance(path_value, str):
            _fail("repository record lacks label or path")
        if not isinstance(analyzer_loc, dict):
            analyzer_loc = {}
        summary[label] = {}
        for language in ("c", "cpp"):
            if int(analyzer_loc.get(language, 0)) <= 0:
                continue
            context = selected.get((label, language))
            evidence = _validate_context(repo, language, context, global_context)
            if context is not None or global_context:
                effective_context = {**(global_context or {}), **(context or {})}
                for field, result_key, description in (
                    ("helper", "helper", "native helper"),
                    ("build_receipt", "build_receipt", "native build receipt"),
                ):
                    path, reason = _context_file(effective_context, field, description)
                    failures = cast("list[str]", evidence["failures"])
                    if reason:
                        if reason not in failures:
                            failures.append(reason)
                    elif path is not None:
                        evidence[f"{result_key}_path"] = str(path)
                        evidence[f"{result_key}_sha256"] = _sha256_file(path)
            if not evidence["failures"]:
                evidence["state"] = "ready"
            summary[label][language] = evidence
    return summary


def _copy_profile_configs(
    repositories: list[dict[str, object]],
    plan: ConfigCopyPlan,
) -> dict[str, str]:
    """Copy and route configs without modifying their source files.

    Parameters
    ----------
    repositories : list[dict[str, object]]
        Draft repository rows whose config maps are replaced in memory.
    plan : ConfigCopyPlan
        Immutable profile, context, output and policy bindings.

    Returns
    -------
    dict[str, str]
        Hashes of every new config file.
    """
    hashes: dict[str, str] = {}
    for repo in repositories:
        label = cast("str", repo["label"])
        source_configs = repo.get("configs")
        if not isinstance(source_configs, dict):
            _fail(f"{label} has no config map")
        new_configs: dict[str, str] = {}
        for profile in plan.profiles:
            profile_id = cast("str", profile["id"])
            source_profile_id = profile_id
            if plan.embedding_policy == "structural-only":
                candidates = [
                    str(item["id"])
                    for item in plan.original_profiles
                    if item.get("backend") == profile.get("backend")
                ]
                if not candidates:
                    _fail(f"no source profile for backend {profile['backend']}")
                source_profile_id = candidates[0]
            source_config_value = source_configs.get(source_profile_id)
            if not isinstance(source_config_value, str):
                _fail(f"{label}/{source_profile_id} config is absent")
            source_config = plan.source_config_root / source_config_value
            raw_config = tomlkit.parse(source_config.read_text(encoding="utf-8"))
            if plan.embedding_policy == "structural-only":
                embeddings = raw_config.get("embeddings")
                if not isinstance(embeddings, MutableMapping):
                    _fail(f"{label}/{source_profile_id} embeddings table is absent")
                embeddings["enabled"] = False
                for key in (
                    "engine",
                    "model",
                    "dimension",
                    "batch_size",
                    "vector_store",
                ):
                    embeddings.pop(key, None)
                raw_config["plugins"].pop("embedding-onnx", None)
            relative = Path("configs") / profile_id / f"{label}.toml"
            language_evidence = plan.context_summary.get(label, {})
            payload = _copy_config(
                plan.output_dir / relative,
                tomlkit.dumps(raw_config).encode("utf-8"),
                repo,
                language_evidence,
                plan.attempt_root / profile_id,
            )
            hashes[str(relative)] = payload
            new_configs[profile_id] = str(relative)
        repo["configs"] = new_configs
    return hashes


def prepare(
    source_manifest_path: Path,
    worktree: Path,
    output_dir: Path,
    contexts_path: Path | None,
    embedding_policy: str = "preserve",
) -> dict[str, object]:
    """Create a fresh, non-runnable Clang stress preparation artifact.

    Parameters
    ----------
    source_manifest_path : pathlib.Path
        Frozen local stress manifest from the original campaign.
    worktree : pathlib.Path
        Remediation checkout that will own a future campaign.
    output_dir : pathlib.Path
        New destination under ``worktree/.artifacts/analysis``.
    contexts_path : pathlib.Path or None
        Optional exact context-selection document.
    embedding_policy : str
        ``undecided``, ``preserve``, or ``structural-only``.

    Returns
    -------
    dict[str, object]
        Preparation summary with held contexts and immutable input hashes.
    """
    worktree = worktree.resolve()
    output_dir = _resolve_under(
        output_dir, worktree / ".artifacts" / "analysis", "output"
    )
    if output_dir.exists():
        _fail(f"output directory already exists: {output_dir}")
    (
        source_manifest,
        source_sha,
        historical_source_sha,
        identity_path,
        source_config_root,
        current_source_config_hashes,
        historical_config_mismatches,
        profiles,
        original_repos,
    ) = _load_source_bundle(
        source_manifest_path,
        worktree,
        contexts_path,
        _manifest_mismatch_ack(contexts_path),
    )
    selected, selection_failures, global_context = _load_context_selection(
        contexts_path, source_sha
    )
    helper_identity, helper_failures = _validate_global_helper(global_context)
    context_summary = _prepare_context_summaries(
        original_repos, selected, global_context
    )
    draft = json.loads(json.dumps(source_manifest))
    draft_repositories = cast("list[dict[str, object]]", draft["repositories"])
    draft["codira_root"] = str(worktree)
    future_artifact_root = (
        worktree / ".artifacts" / "benchmarks" / "test-material" / "clang-full-stress"
    )
    draft["artifact_root"] = str(future_artifact_root / output_dir.name)
    draft["require_clang_frontend_status"] = True
    draft_profiles = _selected_profiles(profiles, embedding_policy)
    draft["profiles"] = draft_profiles
    draft["clang_toolchain"] = helper_identity
    draft["clang_external_inputs"] = _external_input_bindings(context_summary)
    draft["clang_context_profiles"] = {
        label: {
            language: evidence.get("validated_profile_bindings", [])
            for language, evidence in language_rows.items()
        }
        for label, language_rows in context_summary.items()
    }
    draft["clang_context_profiles"] = {
        label: {
            language: evidence.get("validated_profile_bindings", [])
            for language, evidence in language_rows.items()
        }
        for label, language_rows in context_summary.items()
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    config_hashes = _copy_profile_configs(
        draft_repositories,
        ConfigCopyPlan(
            output_dir=output_dir,
            source_manifest_path=source_manifest_path.resolve(),
            source_config_root=source_config_root,
            original_profiles=profiles,
            profiles=draft_profiles,
            context_summary=context_summary,
            embedding_policy=embedding_policy,
            attempt_root=future_artifact_root / "clang-attempts",
        ),
    )
    draft["source_campaign_name"] = str(draft.get("name", "stress"))
    draft["name"] = f"clang-full-stress-{output_dir.name}"
    context_infrastructure_failures = [
        f"{label}/{language}: {failure}"
        for label, language_rows in context_summary.items()
        for language, evidence in language_rows.items()
        for failure in cast("list[str]", evidence.get("infrastructure_failures", []))
    ]
    blockers = _preparation_blockers(
        context_summary,
        [*selection_failures, *helper_failures, *context_infrastructure_failures],
        embedding_policy,
    )
    plan: dict[str, object] = {
        "schema": PREPARATION_SCHEMA,
        "preparation_only": True,
        "launch_eligible": not blockers,
        "blocking_reasons": sorted(set(blockers)),
        "source_manifest_path": str(source_manifest_path.resolve()),
        "source_manifest_sha256": source_sha,
        "historical_identity_manifest_sha256": historical_source_sha,
        "source_manifest_identity_matches": source_sha == historical_source_sha,
        "source_manifest_treated_as_new_input": source_sha != historical_source_sha,
        "source_inputs_treated_as_new_input": (
            source_sha != historical_source_sha or bool(historical_config_mismatches)
        ),
        "historical_config_mismatches": historical_config_mismatches,
        "current_source_config_sha256": current_source_config_hashes,
        "source_identity_path": str(identity_path),
        "source_identity_sha256": _sha256_file(identity_path),
        "source_config_root": str(source_config_root),
        "worktree": str(worktree),
        "worktree_commit": subprocess.check_output(
            [GIT_EXECUTABLE, "-C", str(worktree), "rev-parse", "HEAD"], text=True
        ).strip(),
        "runner_sha256": _sha256_file(
            worktree / "scripts/run_test_material_benchmarks.py"
        ),
        "context_selection_path": str(contexts_path.resolve())
        if contexts_path
        else None,
        "context_selection_sha256": _sha256_file(contexts_path)
        if contexts_path
        else None,
        "embedding_policy": embedding_policy,
        "contexts": context_summary,
        "clang_toolchain": helper_identity,
        "clang_external_inputs": _external_input_bindings(context_summary),
        "clang_context_profiles": draft["clang_context_profiles"],
        "config_sha256": config_hashes,
        "third_party_source_mutations": False,
        "benchmark_launched": False,
        "tree_sitter_fallback_counted_as_clang": False,
    }
    _write_preparation(output_dir, draft, plan)
    return plan


def _selected_profiles(
    profiles: list[dict[str, object]], embedding_policy: str
) -> list[dict[str, object]]:
    """Return the selected profile set without changing the retained source.

    Parameters
    ----------
    profiles : list[dict[str, object]]
        Frozen original profile rows.
    embedding_policy : str
        ``undecided``, ``preserve``, or ``structural-only``.

    Returns
    -------
    list[dict[str, object]]
        Preserved or backend-deduplicated structural profiles.
    """
    if embedding_policy in {"undecided", "preserve"}:
        return profiles
    if embedding_policy != "structural-only":
        _fail(f"unsupported embedding policy: {embedding_policy}")
    selected: dict[str, dict[str, object]] = {}
    for profile in profiles:
        backend = profile.get("backend")
        if isinstance(backend, str):
            selected.setdefault(
                backend,
                {
                    "id": f"{backend}-structural-clang",
                    "backend": backend,
                    "embeddings": False,
                },
            )
    if not selected:
        _fail("structural profile selection found no backend profiles")
    return list(selected.values())


def _preparation_blockers(
    context_summary: dict[str, dict[str, dict[str, object]]],
    selection_failures: list[str],
    embedding_policy: str,
) -> list[str]:
    """List every reason the draft cannot be treated as launch-ready.

    Parameters
    ----------
    context_summary : dict
        Per-repository compiler coverage evidence.
    selection_failures : list[str]
        Missing or invalid global selection evidence.
    embedding_policy : str
        Selected embedding behavior.

    Returns
    -------
    list[str]
        Deterministically sorted launch blockers.
    """
    blockers = list(selection_failures)
    if embedding_policy == "undecided":
        blockers.append("embedding policy awaits user selection")
    return sorted(set(blockers))


def _write_preparation(
    output_dir: Path, draft: dict[str, object], plan: dict[str, object]
) -> None:
    """Persist the immutable draft, plan and content identity.

    Parameters
    ----------
    output_dir : pathlib.Path
        Fresh preparation artifact directory.
    draft : dict[str, object]
        Copied manifest that is intentionally not named ``manifest.json``.
    plan : dict[str, object]
        Preparation-only readiness and held-coverage report.

    Returns
    -------
    None
        Three hash-linked preparation documents are written.
    """
    draft_path = output_dir / "manifest.draft.json"
    plan_path = output_dir / "plan.json"
    draft_path.write_text(
        json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    plan_path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    identity = {
        "schema": PREPARATION_SCHEMA,
        "preparation_id": output_dir.name,
        "plan_sha256": _sha256_file(plan_path),
        "draft_manifest_sha256": _sha256_file(draft_path),
        "created_by_script_sha256": _sha256_file(Path(__file__).resolve()),
        "launch_eligible": plan["launch_eligible"],
    }
    (output_dir / "identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    """Parse preparation arguments and report the held or launch-ready plan.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero when a preparation artifact is written, one for invalid input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--contexts", type=Path)
    parser.add_argument(
        "--embedding-policy",
        choices=("undecided", "preserve", "structural-only"),
        default="preserve",
    )
    args = parser.parse_args()
    try:
        summary = prepare(
            args.source_manifest,
            args.worktree,
            args.output_dir,
            args.contexts,
            args.embedding_policy,
        )
    except (OSError, PreparationError, tomlkit.exceptions.ParseError) as error:
        print(f"preparation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
