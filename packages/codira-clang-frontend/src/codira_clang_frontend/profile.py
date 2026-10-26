"""Load exact compilation profiles without executing their compiler command.

Parameters
----------
None

Returns
-------
None
    Module namespace for captured and prepared compiler profiles.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import shlex
from pathlib import Path
from typing import Literal, cast

from .contracts import (
    CompilationContext,
    CompileProfile,
    DependencyInput,
    IncludeDirectoryInput,
)

PROFILE_SCHEMA = "codira.clang-frontend-profile/2"
_PREVIOUS_PROFILE_SCHEMA = "codira.clang-frontend-profile/1"


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file.

    Parameters
    ----------
    path : pathlib.Path
        File whose current bytes are hashed.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: object) -> str:
    """Hash a JSON-compatible value using canonical serialization.

    Parameters
    ----------
    value : object
        JSON-compatible value to serialize deterministically.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    TypeError
        If the value cannot be serialized as JSON.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _mapping(value: object) -> dict[str, object] | None:
    """Return a JSON object with string keys when the runtime shape matches.

    Parameters
    ----------
    value : object
        Decoded JSON value to inspect.

    Returns
    -------
    dict[str, object] or None
        Mapping when the value is a JSON object with string keys.
    """
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return cast("dict[str, object]", value)
    return None


def directory_membership_sha256(directory: Path) -> str:
    """Hash recursive entry names and symlink targets beneath a search directory.

    Parameters
    ----------
    directory : pathlib.Path
        Effective include search directory reported by Clang.

    Returns
    -------
    str
        Digest of sorted relative entry paths, entry kinds, and symlink targets.

    Raises
    ------
    OSError
        If a search directory or header-map file cannot be read.

    Notes
    -----
    File contents are bound separately by dependency hashes. This digest exists
    to detect new or removed candidate headers that could shadow prior includes.
    Symlink directories are recorded and traversed by target inode, so new
    files beneath standard symlinked system roots remain visible without
    repeated traversal of cycles or duplicate target directories.
    """
    root = directory.resolve(strict=True)
    if root.is_file():
        return _sha256(root)
    if not root.is_dir():
        raise OSError(f"include search root is not a file or directory: {root}")
    entries: list[dict[str, str]] = []
    pending = [(root, "")]
    visited: set[tuple[int, int]] = set()
    while pending:
        current, prefix = pending.pop()
        metadata = current.stat()
        identity = (metadata.st_dev, metadata.st_ino)
        if identity in visited:
            continue
        visited.add(identity)
        with os.scandir(current) as iterator:
            children = sorted(iterator, key=lambda item: item.name)
        for child in children:
            path = Path(child.path)
            relative = str(Path(prefix) / child.name) if prefix else child.name
            if child.is_symlink():
                target_text = os.readlink(path)
                entries.append(
                    {"path": relative, "kind": "symlink", "target": target_text}
                )
                try:
                    target_info = path.stat()
                except FileNotFoundError:
                    entries.append(
                        {
                            "path": relative,
                            "kind": "broken_symlink",
                            "target": target_text,
                        }
                    )
                    continue
                if stat.S_ISDIR(target_info.st_mode):
                    pending.append((path.resolve(strict=True), relative))
                elif stat.S_ISREG(target_info.st_mode):
                    entries.append(
                        {
                            "path": str(path.resolve(strict=True)),
                            "kind": "symlink_file_target",
                            "target": target_text,
                        }
                    )
            elif child.is_dir(follow_symlinks=False):
                entries.append({"path": relative, "kind": "directory", "target": ""})
                pending.append((path, relative))
            else:
                entries.append({"path": relative, "kind": "file", "target": ""})
    entries.sort(key=lambda item: (item["path"], item["kind"], item["target"]))
    return _canonical_hash(entries)


def _read_json_object(path: Path) -> dict[str, object]:
    """Read a JSON object from a UTF-8 file.

    Parameters
    ----------
    path : pathlib.Path
        Evidence file to read.

    Returns
    -------
    dict[str, object]
        Parsed JSON mapping with string keys.

    Raises
    ------
    ValueError
        If the file does not contain a JSON object.
    OSError
        If the evidence file cannot be read.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"expected a JSON object in {path}")
    return cast("dict[str, object]", value)


def from_compile_commands(
    database_path: Path,
    source_path: Path,
    repository_root: Path,
    language: str,
    *,
    dependencies: tuple[DependencyInput, ...] = (),
    include_directories: tuple[IncludeDirectoryInput, ...] = (),
    include_search_complete: bool = False,
    environment: tuple[tuple[str, str], ...] = (),
    environment_mode: str | None = None,
) -> CompileProfile:
    """Select the unique compile database row for one translation unit.

    Parameters
    ----------
    database_path : pathlib.Path
        Exact ``compile_commands.json`` evidence file.
    source_path : pathlib.Path
        Translation unit to select.
    repository_root : pathlib.Path
        Repository checkout used to resolve relative command directories.
    language : str
        Owning analyzer language, either ``c`` or ``cpp``.
    dependencies : tuple[DependencyInput, ...], optional
        Previously retained complete dependency closure. Without it the profile
        remains partial until the explicit preparation stage completes.
    include_directories : tuple[IncludeDirectoryInput, ...], optional
        Search directory membership captured by the profile provider.
    include_search_complete : bool, optional
        Whether the profile binds implicit and explicit Clang search roots.
    environment : tuple[tuple[str, str], ...], optional
        Explicit compiler environment inputs captured with the original command.
    environment_mode : str or None, optional
        Captured allowlisted values or controlled no-ambient mode.
    Returns
    -------
    codira_clang_frontend.contracts.CompileProfile
        Exact original argv and source-bound database identity.

    Raises
    ------
    ValueError
        If the database, language, or matching row is missing or ambiguous.
    OSError
        If the database or translation unit cannot be read.

    Notes
    -----
    The compiler command is parsed as data only. This function never executes
    the compiler, build system, wrappers, or shell command.
    """
    if language not in {"c", "cpp"}:
        raise ValueError("language must be c or cpp")
    selected_environment_mode = environment_mode or (
        "captured_allowlisted" if environment else "controlled_no_ambient"
    )
    if selected_environment_mode not in {
        "captured_allowlisted",
        "controlled_no_ambient",
    }:
        raise ValueError("compile profile environment mode is invalid")
    database = database_path.resolve()
    source = source_path.resolve()
    repository = repository_root.resolve()
    database_bytes = database.read_bytes()
    database_digest = hashlib.sha256(database_bytes).hexdigest()
    rows = json.loads(database_bytes)
    if not isinstance(rows, list):
        raise ValueError("compile database must contain a JSON array")
    matches: list[tuple[dict[str, object], Path, tuple[str, ...]]] = []
    for value in rows:
        if not isinstance(value, dict):
            continue
        row = cast("dict[str, object]", value)
        directory_value = row.get("directory")
        filename_value = row.get("file")
        if not isinstance(directory_value, str) or not isinstance(filename_value, str):
            continue
        directory = Path(directory_value)
        if not directory.is_absolute():
            directory = repository / directory
        directory = directory.resolve()
        filename = Path(filename_value)
        candidate = filename if filename.is_absolute() else directory / filename
        if candidate.resolve() != source:
            continue
        arguments = row.get("arguments")
        if isinstance(arguments, list) and all(
            isinstance(item, str) for item in arguments
        ):
            argv = tuple(cast("list[str]", arguments))
        else:
            command = row.get("command")
            if not isinstance(command, str):
                continue
            try:
                argv = tuple(shlex.split(command, posix=True))
            except ValueError:
                continue
        if argv:
            matches.append((row, directory, argv))
    if len(matches) != 1:
        raise ValueError(
            "compile database must contain exactly one matching row; "
            f"found {len(matches)}"
        )
    row, directory, argv = matches[0]
    source_digest = _sha256(source)
    identity = _canonical_hash(
        {
            "schema": PROFILE_SCHEMA,
            "origin": "compile_commands",
            "database_sha256": database_digest,
            "row": row,
            "source_sha256": source_digest,
            "language": language,
            "dependencies": [
                {"path": str(item.path.resolve()), "sha256": item.sha256}
                for item in dependencies
            ],
            "include_directories": [
                {
                    "path": str(item.path.resolve()),
                    "membership_sha256": item.membership_sha256,
                    "order": item.order,
                    "kind": item.kind,
                }
                for item in include_directories
            ],
            "include_search_complete": include_search_complete,
            "environment": environment,
            "environment_mode": selected_environment_mode,
        }
    )
    return CompileProfile(
        source_path=source,
        source_sha256=source_digest,
        working_directory=directory,
        repository_root=repository,
        argv=argv,
        language=cast("Literal['c', 'cpp']", language),
        origin="compile_commands",
        status="complete" if dependencies and include_search_complete else "partial",
        identity=identity,
        evidence_path=database,
        evidence_sha256=database_digest,
        dependencies=dependencies,
        include_directories=include_directories,
        include_search_complete=include_search_complete,
        environment=environment,
        environment_mode=cast(
            "Literal['controlled_no_ambient', 'captured_allowlisted']",
            selected_environment_mode,
        ),
    )


def from_captured_argv(
    source_path: Path,
    working_directory: Path,
    repository_root: Path,
    argv: tuple[str, ...],
    language: str,
    *,
    profile_id: str = "",
    status: str,
    evidence_path: Path,
    dependencies: tuple[DependencyInput, ...] = (),
    include_directories: tuple[IncludeDirectoryInput, ...] = (),
    include_search_complete: bool = False,
    environment: tuple[tuple[str, str], ...] = (),
    environment_mode: str | None = None,
    compilation_context: CompilationContext | None = None,
) -> CompileProfile:
    """Create a profile from retained compiler-capture evidence.

    Parameters
    ----------
    source_path : pathlib.Path
        Captured translation unit path.
    working_directory : pathlib.Path
        Exact working directory recorded with the compiler invocation.
    repository_root : pathlib.Path
        Repository checkout containing the translation unit.
    argv : tuple[str, ...]
        Complete original compiler argv including argv zero.
    language : str
        Owning analyzer language, either ``c`` or ``cpp``.
    profile_id : str
        Stable identifier of the selected capture record.
    status : str
        Capture completeness, either ``complete`` or ``partial``.
    evidence_path : pathlib.Path
        Immutable evidence file containing or identifying the capture record.
    dependencies : tuple[codira_clang_frontend.contracts.DependencyInput, ...], optional
        Independently captured dependency paths and content hashes.
    include_directories : tuple[codira_clang_frontend.contracts.IncludeDirectoryInput, ...], optional
        Captured effective Clang search directories and membership hashes.
    include_search_complete : bool, optional
        Whether all effective search directories were captured.
    environment : tuple[tuple[str, str], ...], optional
        Explicitly captured compiler environment variables.
    environment_mode : str or None, optional
        Captured allowlisted values or controlled no-ambient mode.
    compilation_context : CompilationContext or None, optional
        Actual target and sysroot reported by Clang.

    Returns
    -------
    codira_clang_frontend.contracts.CompileProfile
        Source- and evidence-bound captured profile.

    Raises
    ------
    ValueError
        If required identity fields are missing or inconsistent.
    OSError
        If the source, evidence, or a declared dependency cannot be read.
    """
    source = source_path.resolve()
    working = working_directory.resolve()
    repository = repository_root.resolve()
    evidence = evidence_path.resolve()
    if language not in {"c", "cpp"} or status not in {"complete", "partial"}:
        raise ValueError("captured profile language or status is invalid")
    if not argv or not argv[0]:
        raise ValueError("captured profile requires a complete argv")
    if status == "complete" and (
        not dependencies or not include_directories or not include_search_complete
    ):
        raise ValueError(
            "complete profile requires dependency hashes and every effective include root"
        )
    allowed_environment = {
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "OBJC_INCLUDE_PATH",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "GCC_EXEC_PREFIX",
        "COMPILER_PATH",
        "LIBRARY_PATH",
    }
    if {key for key, _ in environment} - allowed_environment:
        raise ValueError(
            "captured profile contains unsupported compiler environment keys"
        )
    selected_environment_mode = environment_mode or (
        "captured_allowlisted" if environment else "controlled_no_ambient"
    )
    if selected_environment_mode not in {
        "captured_allowlisted",
        "controlled_no_ambient",
    }:
        raise ValueError("captured profile environment mode is invalid")
    if selected_environment_mode == "controlled_no_ambient" and environment:
        raise ValueError("controlled environment cannot contain ambient variables")
    source.relative_to(repository)
    source_digest = _sha256(source)
    evidence_digest = _sha256(evidence)
    dependency_payload: list[dict[str, str]] = []
    for dependency in sorted(dependencies, key=lambda item: str(item.path)):
        path = dependency.path.resolve()
        observed = _sha256(path)
        if observed != dependency.sha256:
            raise ValueError(f"captured dependency digest mismatch: {path}")
        dependency_payload.append({"path": str(path), "sha256": observed})
    for directory in include_directories:
        observed = directory_membership_sha256(directory.path)
        if observed != directory.membership_sha256:
            raise ValueError(f"include directory membership changed: {directory.path}")
    identity = _canonical_hash(
        {
            "schema": PROFILE_SCHEMA,
            "origin": "captured_argv",
            "profile_id": profile_id or None,
            "source_path": str(source),
            "source_sha256": source_digest,
            "working_directory": str(working),
            "argv": argv,
            "language": language,
            "status": status,
            "evidence_sha256": evidence_digest,
            "dependencies": dependency_payload,
            "include_directories": [
                {
                    "path": str(item.path.resolve()),
                    "membership_sha256": item.membership_sha256,
                    "order": item.order,
                    "kind": item.kind,
                }
                for item in include_directories
            ],
            "include_search_complete": include_search_complete,
            "environment": environment,
            "environment_mode": selected_environment_mode,
            "compilation_context": (
                {
                    "target_triple": compilation_context.target_triple,
                    "sysroot": compilation_context.sysroot,
                    "sysroot_path": (
                        str(compilation_context.sysroot_path)
                        if compilation_context.sysroot_path is not None
                        else None
                    ),
                }
                if compilation_context is not None
                else None
            ),
        }
    )
    return CompileProfile(
        source_path=source,
        source_sha256=source_digest,
        working_directory=working,
        repository_root=repository,
        argv=argv,
        language=cast("Literal['c', 'cpp']", language),
        origin="captured_argv",
        status=cast("Literal['complete', 'partial']", status),
        identity=identity,
        evidence_path=evidence,
        evidence_sha256=evidence_digest,
        dependencies=dependencies,
        include_directories=include_directories,
        include_search_complete=include_search_complete,
        environment=environment,
        environment_mode=cast(
            "Literal['controlled_no_ambient', 'captured_allowlisted']",
            selected_environment_mode,
        ),
        compilation_context=compilation_context,
    )


def from_captured_profile_json(
    evidence_path: Path,
    source_path: Path,
    repository_root: Path,
    source_sha256: str,
) -> CompileProfile:
    """Load the exact selected record from a versioned captured-profile file.

    Parameters
    ----------
    evidence_path : pathlib.Path
        Immutable JSON evidence containing captured profile records.
    source_path : pathlib.Path
        Expected translation unit path.
    repository_root : pathlib.Path
        Repository checkout containing the translation unit.
    source_sha256 : str
        Expected source digest used with the canonical source path to select
        exactly one profile record.

    Returns
    -------
    codira_clang_frontend.contracts.CompileProfile
        Validated profile with original argv and dependency evidence.

    Raises
    ------
    ValueError
        If the schema, record, or selected source identity is invalid.
    OSError
        If evidence or source files cannot be read.
    """
    document = _read_json_object(evidence_path)
    schema = document.get("schema", document.get("schema_version"))
    if schema not in {PROFILE_SCHEMA, _PREVIOUS_PROFILE_SCHEMA}:
        raise ValueError("captured profile evidence has an unsupported schema")
    records_value = document.get("profiles")
    if not isinstance(records_value, list):
        raise ValueError("captured profile evidence requires a profiles array")
    source = source_path.resolve()
    matches = []
    for value in records_value:
        row = _mapping(value)
        if row is None:
            continue
        row_source = row.get("source_path")
        row_digest = row.get("source_sha256")
        if (
            isinstance(row_source, str)
            and Path(row_source).resolve() == source
            and row_digest == source_sha256
        ):
            matches.append(row)
    if len(matches) != 1:
        raise ValueError(
            "captured profile file must contain exactly one record matching "
            f"{source} at {source_sha256}; found {len(matches)}"
        )
    row = matches[0]
    expected_source_digest = row.get("source_sha256")
    if (
        not isinstance(expected_source_digest, str)
        or _sha256(source) != expected_source_digest
    ):
        raise ValueError("captured profile source digest does not match selection")
    directory = row.get("working_directory")
    argv_value = row.get("argv")
    language = row.get("language")
    status = row.get("status")
    evidence_value = row.get("evidence")
    evidence_record = _mapping(evidence_value)
    if evidence_record is None:
        raise ValueError("captured profile requires retained evidence identity")
    evidence_path_value = evidence_record.get("path")
    evidence_digest_value = evidence_record.get("sha256")
    if not isinstance(evidence_path_value, str) or not isinstance(
        evidence_digest_value, str
    ):
        raise ValueError("captured profile evidence requires absolute path and sha256")
    retained_evidence_path = Path(evidence_path_value)
    if not retained_evidence_path.is_absolute():
        raise ValueError("captured profile evidence path must be absolute")
    if _sha256(retained_evidence_path) != evidence_digest_value:
        raise ValueError("captured profile evidence digest does not match")
    if (
        not isinstance(directory, str)
        or not isinstance(argv_value, list)
        or not all(isinstance(item, str) for item in argv_value)
        or not isinstance(language, str)
        or not isinstance(status, str)
    ):
        raise ValueError("captured profile row lacks cwd, argv, language, or status")
    dependencies_value = row.get("dependencies", [])
    if not isinstance(dependencies_value, list):
        raise ValueError("captured profile dependencies must be an array")
    dependencies: list[DependencyInput] = []
    for value in dependencies_value:
        if not isinstance(value, dict):
            raise ValueError("captured dependency record must be an object")
        path_value = value.get("path")
        digest_value = value.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest_value, str):
            raise ValueError("captured dependency needs path and sha256")
        dependency_path = Path(path_value)
        if not dependency_path.is_absolute():
            raise ValueError("captured dependency paths must be absolute")
        dependencies.append(DependencyInput(dependency_path, digest_value))
    include_directories_value = row.get("include_directories", [])
    if not isinstance(include_directories_value, list):
        raise ValueError("captured profile include_directories must be an array")
    include_directories: list[IncludeDirectoryInput] = []
    for value in include_directories_value:
        if not isinstance(value, dict):
            raise ValueError("captured include directory record must be an object")
        path_value = value.get("path")
        membership_value = value.get("membership_sha256")
        order_value = value.get("order", 0)
        kind_value = value.get("kind", "directory")
        if (
            not isinstance(path_value, str)
            or not Path(path_value).is_absolute()
            or not isinstance(membership_value, str)
            or not isinstance(order_value, int)
            or kind_value
            not in {
                "directory",
                "framework",
                "header_map",
                "quoted_include_parent",
            }
        ):
            raise ValueError("captured include directory record is incomplete")
        directory_input = IncludeDirectoryInput(
            Path(path_value),
            membership_value,
            order_value,
            cast(
                "Literal['directory', 'framework', 'header_map', 'quoted_include_parent']",
                kind_value,
            ),
        )
        if directory_membership_sha256(directory_input.path) != membership_value:
            raise ValueError(f"captured include directory changed: {path_value}")
        include_directories.append(directory_input)
    include_search_complete = row.get("include_search_complete") is True
    environment_value = row.get("environment", {})
    environment_mode = row.get("environment_mode")
    context_value = row.get("compilation_context")
    compilation_context: CompilationContext | None = None
    if context_value is not None:
        context_row = _mapping(context_value)
        if context_row is None:
            raise ValueError("captured profile compilation_context must be an object")
        triple = context_row.get("target_triple")
        sysroot = context_row.get("sysroot")
        sysroot_value = context_row.get("sysroot_path")
        if (
            not isinstance(triple, str)
            or not triple
            or not isinstance(sysroot, str)
            or (sysroot_value is not None and not isinstance(sysroot_value, str))
        ):
            raise ValueError("captured profile compilation_context is incomplete")
        sysroot_path = Path(sysroot_value) if isinstance(sysroot_value, str) else None
        if sysroot_path is not None and not sysroot_path.is_absolute():
            raise ValueError("captured sysroot_path must be absolute")
        expected_sysroot_path: Path | None = None
        if sysroot:
            candidate = Path(sysroot)
            if not candidate.is_absolute():
                candidate = Path(directory) / candidate
            expected_sysroot_path = candidate.resolve()
        if sysroot_path != expected_sysroot_path:
            raise ValueError("captured sysroot_path does not match Clang sysroot value")
        compilation_context = CompilationContext(triple, sysroot, sysroot_path)
    if environment_mode not in {"controlled_no_ambient", "captured_allowlisted"}:
        raise ValueError("captured profile must declare an environment_mode")
    if not isinstance(environment_value, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in environment_value.items()
    ):
        raise ValueError("captured compiler environment must be a string mapping")
    environment_keys = {
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "OBJC_INCLUDE_PATH",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "GCC_EXEC_PREFIX",
        "COMPILER_PATH",
        "LIBRARY_PATH",
    }
    if set(environment_value) - environment_keys:
        raise ValueError(
            "captured profile contains unsupported compiler environment keys"
        )
    if status == "complete" and (
        not dependencies or not include_directories or not include_search_complete
    ):
        raise ValueError(
            "complete profile must include dependencies and effective include roots"
        )
    if (
        schema == PROFILE_SCHEMA
        and status == "complete"
        and compilation_context is None
    ):
        raise ValueError("complete profile must bind native Clang compilation context")
    if (
        schema == _PREVIOUS_PROFILE_SCHEMA
        and status == "complete"
        and compilation_context is None
    ):
        status = "partial"
    profile_id_value = row.get("profile_id")
    return from_captured_argv(
        source,
        Path(directory),
        repository_root,
        tuple(cast("list[str]", argv_value)),
        language,
        profile_id=profile_id_value if isinstance(profile_id_value, str) else "",
        status=status,
        evidence_path=retained_evidence_path,
        dependencies=tuple(dependencies),
        include_directories=tuple(include_directories),
        include_search_complete=include_search_complete,
        environment=tuple(sorted(cast("dict[str, str]", environment_value).items())),
        environment_mode=cast(
            "Literal['controlled_no_ambient', 'captured_allowlisted']",
            environment_mode,
        ),
        compilation_context=compilation_context,
    )


def write_prepared_profile(
    profile: CompileProfile,
    dependencies: tuple[DependencyInput, ...],
    include_directories: tuple[IncludeDirectoryInput, ...],
    environment: tuple[tuple[str, str], ...],
    environment_mode: str,
    compilation_context: CompilationContext,
    output_path: Path,
) -> CompileProfile:
    """Persist a new immutable generic profile with a verified closure.

    Parameters
    ----------
    profile : codira_clang_frontend.contracts.CompileProfile
        Exact compile profile that was analyzed during preparation.
    dependencies : tuple[codira_clang_frontend.contracts.DependencyInput, ...]
        Complete compiler-observed dependency closure.
    include_directories : tuple[codira_clang_frontend.contracts.IncludeDirectoryInput, ...]
        Ordered effective search directories and membership hashes.
    environment : tuple[tuple[str, str], ...]
        Exact effective compiler environment values from the controlled run.
    environment_mode : str
        Explicit process environment policy used to produce the closure.
    compilation_context : CompilationContext
        Actual target and sysroot reported by the preparation invocation.
    output_path : pathlib.Path
        New durable profile manifest path; existing files are never replaced.

    Returns
    -------
    codira_clang_frontend.contracts.CompileProfile
        Re-loaded complete profile with exact argv and verified dependency hashes.

    Raises
    ------
    ValueError
        If a dependency changed or the exact profile evidence is unavailable.
    FileExistsError
        If ``output_path`` already exists.
    OSError
        If the profile evidence cannot be read or persisted.
    """
    if profile.evidence_path is None or profile.evidence_sha256 is None:
        raise ValueError("prepared profile requires retained original profile evidence")
    if _sha256(profile.evidence_path) != profile.evidence_sha256:
        raise ValueError("original profile evidence changed before preparation")
    source_digest = _sha256(profile.source_path)
    normalized_dependencies: list[dict[str, str]] = []
    for dependency in sorted(dependencies, key=lambda item: str(item.path)):
        path = dependency.path.resolve()
        observed = _sha256(path)
        if observed != dependency.sha256:
            raise ValueError(f"dependency changed before profile persistence: {path}")
        normalized_dependencies.append({"path": str(path), "sha256": observed})
    normalized_directories: list[dict[str, object]] = []
    for directory in include_directories:
        path = directory.path.resolve()
        observed = directory_membership_sha256(path)
        if observed != directory.membership_sha256:
            raise ValueError(
                f"include directory changed before profile persistence: {path}"
            )
        normalized_directories.append(
            {
                "path": str(path),
                "membership_sha256": observed,
                "order": directory.order,
                "kind": directory.kind,
            }
        )
    if not any(
        item["path"] == str(profile.source_path.resolve())
        and item["sha256"] == source_digest
        for item in normalized_dependencies
    ):
        normalized_dependencies.append(
            {"path": str(profile.source_path.resolve()), "sha256": source_digest}
        )
        normalized_dependencies.sort(key=lambda item: item["path"])
    record = {
        "source_path": str(profile.source_path.resolve()),
        "source_sha256": source_digest,
        "working_directory": str(profile.working_directory.resolve()),
        "argv": list(profile.argv),
        "language": profile.language,
        "status": "complete",
        "evidence": {
            "path": str(profile.evidence_path.resolve()),
            "sha256": profile.evidence_sha256,
        },
        "dependencies": normalized_dependencies,
        "include_directories": normalized_directories,
        "include_search_complete": True,
        "environment": dict(environment),
        "environment_mode": environment_mode,
        "compilation_context": {
            "target_triple": compilation_context.target_triple,
            "sysroot": compilation_context.sysroot,
            "sysroot_path": (
                str(compilation_context.sysroot_path)
                if compilation_context.sysroot_path is not None
                else None
            ),
        },
    }
    document = {
        "schema_version": PROFILE_SCHEMA,
        "profiles": [record],
    }
    data = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return from_captured_profile_json(
        output_path,
        profile.source_path,
        profile.repository_root,
        source_digest,
    )
