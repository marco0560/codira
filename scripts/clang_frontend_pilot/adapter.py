"""Build compact, source-bound Clang frontend pilot envelopes.

The adapter reads compilation database JSON and invokes only the explicitly
provided LibTooling helper. It never evaluates a command string or runs the
original compiler driver.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import cast

from .contract import (
    CAPTURE_MODES,
    DEFAULT_CAPTURE_MODE,
    PILOT_ID,
    SCHEMA_VERSION,
    UNMODELED_FIELDS,
    JSONValue,
    raise_input_error,
)

_ACTION_FLAGS = {
    "-c",
    "-S",
    "-E",
    "-M",
    "-MM",
    "-MD",
    "-MMD",
    "-MP",
    "-MG",
    "-emit-llvm",
}
_ACTION_FLAGS_WITH_VALUE = {
    "-o",
    "-MF",
    "-MT",
    "-MQ",
    "-MJ",
    "-dependency-file",
    "-serialize-diagnostics",
    "-fmodule-output",
    "-ftime-trace-granularity",
    "-foptimization-record-file",
}
_ACTION_PREFIXES = ("-MF", "-MT", "-MQ", "-MJ", "-dependency-file=")
_DENIED_EXECUTION_FLAGS = {
    "-Xclang",
    "-cc1",
    "-cc1as",
    "-load",
    "-plugin",
    "-add-plugin",
    "-wrapper",
    "-specs",
    "-B",
    "-mllvm",
}
_DENIED_EXECUTION_PREFIXES = (
    "-fplugin",
    "-fpass-plugin",
    "-plugin-arg-",
    "--config=",
)
_VALUE_FLAGS = {
    "-D",
    "-U",
    "-I",
    "-isystem",
    "-iquote",
    "-idirafter",
    "-include",
    "-imacros",
    "-isysroot",
    "--sysroot",
    "-std",
    "-target",
    "--target",
    "-x",
    "-resource-dir",
    "-F",
    "-iframework",
    "-fmodule-map-file",
    "-fmodule-file",
    "-include-pch",
    "-stdlib",
    "-arch",
    "-gcc-toolchain",
    "--gcc-toolchain",
}


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once.

    Parameters
    ----------
    path : pathlib.Path
        File whose bytes are hashed.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.

    Raises
    ------
    OSError
        If the file cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object) -> dict[str, JSONValue]:
    """Return a JSON object after validating its runtime shape.

    Parameters
    ----------
    value : object
        Value expected to be a JSON object.

    Returns
    -------
    dict[str, JSONValue]
        Validated JSON object.

    Raises
    ------
    ValueError
        If the value is not an object.
    """
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise_input_error("expected a JSON object")
    return cast("dict[str, JSONValue]", value)


def _resolve_executable(argv0: str, directory: Path) -> Path | None:
    """Resolve a compile command executable without running it.

    Parameters
    ----------
    argv0 : str
        Original first argument from the compilation database.
    directory : pathlib.Path
        Working directory recorded by the compilation database.

    Returns
    -------
    pathlib.Path or None
        Existing executable path, or ``None`` when it cannot be resolved.
    """
    candidate = Path(argv0)
    if candidate.is_absolute() or candidate.parent != Path():
        resolved = candidate if candidate.is_absolute() else directory / candidate
        return resolved.resolve() if resolved.is_file() else None
    located = shutil.which(argv0)
    return Path(located).resolve() if located else None


def _command_arguments(command: dict[str, JSONValue]) -> tuple[list[str], str | None]:
    """Read the exact argv representation carried by one compile command.

    Parameters
    ----------
    command : dict[str, JSONValue]
        Compilation database row.

    Returns
    -------
    tuple[list[str], str or None]
        Parsed argument vector and the original command string, if supplied.

    Raises
    ------
    ValueError
        If neither supported argument representation is valid.
    """
    arguments = command.get("arguments")
    if isinstance(arguments, list) and all(isinstance(item, str) for item in arguments):
        return cast("list[str]", arguments), None
    command_text = command.get("command")
    if isinstance(command_text, str):
        return shlex.split(command_text, posix=True), command_text
    return raise_input_error("compile command requires string arguments or command")


def _source_path(command: dict[str, JSONValue], directory: Path) -> Path:
    """Resolve one compile database source path against its working directory.

    Parameters
    ----------
    command : dict[str, JSONValue]
        Compilation database row.
    directory : pathlib.Path
        Row working directory.

    Returns
    -------
    pathlib.Path
        Absolute normalized translation unit path.

    Raises
    ------
    ValueError
        If the compile row omits a source filename.
    """
    filename = command.get("file")
    if not isinstance(filename, str) or not filename:
        raise_input_error("compile command requires a nonempty file path")
    candidate = Path(filename)
    return (candidate if candidate.is_absolute() else directory / candidate).resolve()


def _execution_hazard(argument: str) -> bool:
    """Return whether an argument can load code or external driver config.

    Parameters
    ----------
    argument : str
        One original compiler argument.

    Returns
    -------
    bool
        True when forwarding could load executable code or an implicit config.
    """
    return argument in _DENIED_EXECUTION_FLAGS or argument.startswith(
        (
            *_DENIED_EXECUTION_PREFIXES,
            "@",
            "-specs=",
            "-wrapper=",
            "-B",
            "-Xclang=",
            "-cc1",
            "-load=",
        )
    )


def _removed_action(argument: str, following: str | None) -> tuple[str, int] | None:
    """Identify output, dependency, or link actions outside frontend parsing.

    Parameters
    ----------
    argument : str
        Current original argument.
    following : str or None
        Next original argument, if present.

    Returns
    -------
    tuple[str, int] or None
        Ledger explanation and number of following values to consume, or None.
    """
    if argument == "-fsyntax-only":
        return "duplicate_frontend_mode", 0
    if argument in _ACTION_FLAGS:
        return "non_frontend_action", 0
    if argument in _ACTION_FLAGS_WITH_VALUE:
        return "non_frontend_action_with_output_path", int(following is not None)
    if argument in {"-L", "-l", "-Xlinker", "-Xassembler"}:
        return "link_or_assembler_only_argument", int(following is not None)
    if argument.startswith(
        (
            *_ACTION_PREFIXES,
            "-save-temps",
            "-ftime-trace",
            "-fmodule-output=",
            "-serialize-diagnostics=",
            "-foptimization-record-file=",
        )
    ):
        return "non_frontend_output_option", 0
    if argument.startswith(("-Wl,", "-Wa,", "-L", "-l", "-fuse-ld=")):
        return "link_or_assembler_only_option", 0
    if argument in {"-shared", "-static", "-pie", "-rdynamic"}:
        return "link_only_action", 0
    return None


def _adapt_arguments(
    original: list[str], source: Path, directory: Path
) -> tuple[list[str], list[JSONValue], list[str]]:
    """Forward ordinary driver flags and ledger only explicit adaptations.

    Parameters
    ----------
    original : list[str]
        Original compilation database argv.
    source : pathlib.Path
        Resolved translation unit path.
    directory : pathlib.Path
        Compile command working directory.

    Returns
    -------
    tuple[list[str], list[JSONValue], list[str]]
        Clang argv flags, ordered transformation ledger, and denied context.

    Notes
    -----
    This is not a Clang command-line parser. Ordinary arguments are forwarded
    unchanged so Clang can diagnose unsupported options. Only known output,
    dependency, link, and executable-loading actions are transformed or held.
    """
    adapted: list[str] = ["-fsyntax-only"]
    ledger: list[JSONValue] = [
        {
            "operation": "add_frontend_mode",
            "original": None,
            "adapted": "-fsyntax-only",
            "reason": "LibTooling extracts syntax and emits no object output",
        }
    ]
    denied: list[str] = []
    index = 1
    while index < len(original):
        argument = original[index]
        if _execution_hazard(argument):
            denied.append(argument)
            ledger.append(
                {
                    "operation": "deny_executable_or_implicit_config",
                    "original": argument,
                    "adapted": None,
                    "reason": "plugin loading, direct frontend execution, response files, and implicit configs are denied",
                }
            )
            index += 1
            continue
        path_argument = Path(argument)
        if not argument.startswith("-"):
            candidate = (
                path_argument
                if path_argument.is_absolute()
                else directory / path_argument
            )
            if candidate.resolve() == source:
                ledger.append(
                    {
                        "operation": "remove_translation_unit",
                        "original": argument,
                        "adapted": None,
                        "reason": "helper receives the selected source path separately",
                    }
                )
                index += 1
                continue
            denied.append(argument)
            ledger.append(
                {
                    "operation": "hold_extra_input_file",
                    "original": argument,
                    "adapted": None,
                    "reason": "only the manifest-selected translation unit may be parsed",
                }
            )
            index += 1
            continue
        action = _removed_action(
            argument, original[index + 1] if index + 1 < len(original) else None
        )
        if action is not None:
            reason, consumed_values = action
            original_value: str | list[str] = argument
            if consumed_values:
                original_value = original[index : index + 1 + consumed_values]
            ledger.append(
                {
                    "operation": "strip_non_frontend_action",
                    "original": cast("JSONValue", original_value),
                    "adapted": None,
                    "reason": reason,
                }
            )
            index += 1 + consumed_values
            continue
        if argument == "-fdiagnostics-color":
            adapted.append("-fcolor-diagnostics")
            ledger.append(
                {
                    "operation": "translate",
                    "original": argument,
                    "adapted": "-fcolor-diagnostics",
                    "reason": "Clang diagnostic color spelling",
                }
            )
            index += 1
            continue
        adapted.append(argument)
        ledger.append(
            {
                "operation": "forward_to_clang",
                "original": argument,
                "adapted": argument,
                "reason": "generic compiler-driver option; Clang diagnoses unsupported options",
            }
        )
        if argument in _VALUE_FLAGS and index + 1 < len(original):
            value = original[index + 1]
            adapted.append(value)
            ledger.append(
                {
                    "operation": "forward_to_clang",
                    "original": value,
                    "adapted": value,
                    "reason": f"value operand for {argument}",
                }
            )
            index += 2
        else:
            index += 1
    return adapted, ledger, denied


def _manifest_identity(row: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Copy the cohort identity fields without changing their values.

    Parameters
    ----------
    row : dict[str, JSONValue]
        One cohort manifest row.

    Returns
    -------
    dict[str, JSONValue]
        Exact identity projection used by the pilot contract.
    """
    names = (
        "selection_id",
        "population_class",
        "language",
        "repository_id",
        "repository_checkout",
        "repository_revision",
        "repository_relative_path",
        "source_path",
        "source_sha256",
        "classification_disposition",
        "feature_family",
        "family_evidence",
        "profile_context_status",
        "profile_evidence",
        "context_limitations",
    )
    return {name: row.get(name) for name in names}


def _held_envelope(
    row: dict[str, JSONValue],
    manifest_source: dict[str, JSONValue],
    context_status: str,
    reason: str,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
    **extra: object,
) -> dict[str, JSONValue]:
    """Create a complete terminal envelope for a held selection row.

    Parameters
    ----------
    row : dict[str, JSONValue]
        Cohort selection row.
    manifest_source : dict[str, JSONValue]
        Bound manifest path and digest metadata.
    context_status : str
        Context status assigned by the manifest or adapter.
    reason : str
        Concrete reason the frontend was not run to completion.
    **extra : object
        Additional bound compile-command or helper metadata.

    Returns
    -------
    dict[str, JSONValue]
        Versioned held result envelope.
    """
    envelope: dict[str, JSONValue] = {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": PILOT_ID,
        "manifest_source": manifest_source,
        "selection_row": row,
        **_manifest_identity(row),
        "context_status": context_status,
        "capture_mode": capture_mode,
        "status": "held",
        "hold_reasons": [reason],
        "observed_context_status": "unavailable",
        "native_execution": {"status": "not_run", "engine": "clang-libtooling"},
        "independent_qualification": {"status": "not_run"},
        "original_compile_command": row.get("original_compile_command"),
        "clang_adaptation": {
            "status": "not_run",
            "argv": [],
            "transformations": [],
            "unsupported_context": [],
            "toolchain": None,
        },
        "dependency_closure": {"status": "unavailable", "files": [], "sha256": None},
        "frontend": {
            "status": "not_run",
            "declarations": [],
            "calls": [],
            "preprocessing": [],
            "includes": [],
            "diagnostics": [],
        },
        "unmodeled_fields": list(UNMODELED_FIELDS),
    }
    envelope.update(cast("dict[str, JSONValue]", extra))
    return envelope


def _persist_raw(path: Path | None, content: bytes) -> dict[str, JSONValue] | None:
    """Persist raw helper output without replacing evidence from an earlier run.

    Parameters
    ----------
    path : pathlib.Path or None
        New durable artifact path, or ``None`` when the caller did not request
        raw sidecars.
    content : bytes
        Exact helper stdout or stderr bytes captured by ``subprocess.run``.

    Returns
    -------
    dict[str, JSONValue] or None
        Artifact path and digest metadata, or ``None`` if no path was supplied.

    Raises
    ------
    FileExistsError
        If the target path already exists.
    OSError
        If the artifact cannot be written.
    """
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(content).hexdigest()}


def adapt_selection(  # noqa: C901, PLR0913, PLR0912
    row: dict[str, JSONValue],
    manifest_source: dict[str, JSONValue],
    compile_database: list[JSONValue],
    repository_root: Path,
    helper_path: Path,
    *,
    stderr_path: Path | None = None,
    stdout_path: Path | None = None,
    force_hold_reason: str | None = None,
    capture_mode: str = DEFAULT_CAPTURE_MODE,
) -> dict[str, JSONValue]:
    """Run the supplied LibTooling helper for one cohort row.

    Parameters
    ----------
    row : dict[str, JSONValue]
        One source-bound cohort row.
    manifest_source : dict[str, JSONValue]
        Manifest file path, digest, and schema version.
    compile_database : list[JSONValue]
        Decoded ``compile_commands.json`` entries.
    repository_root : pathlib.Path
        Checkout root for this manifest row.
    helper_path : pathlib.Path
        Explicitly built Clang LibTooling helper executable.
    stderr_path : pathlib.Path or None, optional
        Durable path for raw helper stderr. Existing paths are never replaced.
    stdout_path : pathlib.Path or None, optional
        Durable path for raw helper stdout. Existing paths are never replaced.
    force_hold_reason : str or None, optional
        External repository-context hold, such as a pinned revision mismatch.
    capture_mode : str, optional
        `source_relevant` projects main-file facts; `full` retains the legacy
        header declaration and preprocessing projection.

    Returns
    -------
    dict[str, JSONValue]
        One terminal versioned frontend envelope, including held outcomes.

    Raises
    ------
    OSError
        If source or toolchain evidence cannot be read.
    ValueError
        If the manifest identity or compile database row is malformed.

    Notes
    -----
    The original compiler is never executed. Only the explicitly supplied
    LibTooling helper runs, with a JSON request on stdin and ``shell=False``.
    """
    if capture_mode not in CAPTURE_MODES:
        raise_input_error(f"unsupported capture mode: {capture_mode}")

    def held(
        row_value: dict[str, JSONValue],
        manifest_value: dict[str, JSONValue],
        status_value: str,
        reason_value: str,
        **extra: object,
    ) -> dict[str, JSONValue]:
        return _held_envelope(
            row_value,
            manifest_value,
            status_value,
            reason_value,
            capture_mode=capture_mode,
            **extra,
        )

    context_value = row.get("profile_context_status")
    context_status = context_value if isinstance(context_value, str) else "no_profile"
    source_value = row.get("source_path")
    if not isinstance(source_value, str) or not source_value:
        return held(
            row, manifest_source, context_status, "missing_absolute_source_path"
        )
    repository = repository_root.resolve()
    source = Path(source_value).resolve()
    try:
        source.relative_to(repository)
    except ValueError:
        return held(
            row, manifest_source, context_status, "source_path_outside_repository_root"
        )
    if not source.is_file():
        return held(row, manifest_source, context_status, "source_file_missing")
    source_digest = sha256_file(source)
    expected_digest = row.get("source_sha256")
    if not isinstance(expected_digest, str) or source_digest != expected_digest:
        return held(
            row,
            manifest_source,
            context_status,
            "source_sha256_mismatch",
            observed_source_sha256=source_digest,
        )
    if force_hold_reason is not None:
        return held(
            row,
            manifest_source,
            context_status,
            force_hold_reason,
            observed_source_sha256=source_digest,
        )

    matching: list[tuple[dict[str, JSONValue], list[str], str | None, Path, Path]] = []
    for value in compile_database:
        try:
            command = _mapping(value)
            directory_value = command.get("directory")
            if not isinstance(directory_value, str):
                continue
            directory = Path(directory_value)
            if not directory.is_absolute():
                directory = repository / directory
            directory = directory.resolve()
            if _source_path(command, directory) != source:
                continue
            arguments, command_text = _command_arguments(command)
            if not arguments:
                continue
            matching.append(
                (
                    command,
                    arguments,
                    command_text,
                    directory,
                    _source_path(command, directory),
                )
            )
        except (ValueError, OSError):
            continue
    manifest_command = row.get("original_compile_command")
    requested_index: int | None = None
    if isinstance(manifest_command, dict):
        candidate_index = manifest_command.get("command_index")
        if isinstance(candidate_index, int):
            requested_index = candidate_index
    if requested_index is not None:
        if isinstance(manifest_command, dict):
            expected_database_sha = manifest_command.get("database_sha256")
            if isinstance(expected_database_sha, str) and expected_database_sha != next(
                (
                    command.get("database_sha256")
                    for command in compile_database
                    if isinstance(command, dict)
                ),
                expected_database_sha,
            ):
                return held(
                    row,
                    manifest_source,
                    context_status,
                    "compile_database_sha256_mismatch",
                )
        if requested_index < 0 or requested_index >= len(compile_database):
            return held(
                row,
                manifest_source,
                context_status,
                "compile_command_index_out_of_range",
            )
        try:
            command = _mapping(compile_database[requested_index])
            directory_value = command.get("directory")
            if not isinstance(directory_value, str):
                raise_input_error("compile directory missing")
            directory = Path(directory_value)
            if not directory.is_absolute():
                directory = repository / directory
            directory = directory.resolve()
            arguments, command_text = _command_arguments(command)
            if _source_path(command, directory) != source:
                raise_input_error(
                    "manifest-selected compile command points at another source"
                )
            if isinstance(manifest_command, dict):
                expected_arguments = manifest_command.get("arguments")
                expected_command = manifest_command.get("command")
                expected_directory = manifest_command.get("directory")
                if (
                    isinstance(expected_arguments, list)
                    and arguments != expected_arguments
                ):
                    raise_input_error(
                        "manifest-selected compiler argv differs from the database"
                    )
                if (
                    isinstance(expected_command, str)
                    and command_text != expected_command
                ):
                    raise_input_error(
                        "manifest-selected command text differs from the database"
                    )
                if (
                    isinstance(expected_command, list)
                    and command.get("command") != expected_command
                ):
                    raise_input_error(
                        "manifest-selected command argv differs from the database"
                    )
                if isinstance(expected_directory, str):
                    expected_path = Path(expected_directory)
                    if not expected_path.is_absolute():
                        expected_path = repository / expected_path
                    if expected_path.resolve() != directory:
                        raise_input_error(
                            "manifest-selected working directory differs from the database"
                        )
                expected_database_path = manifest_command.get("database_path")
                actual_database_path = command.get("database_path")
                if (
                    isinstance(expected_database_path, str)
                    and isinstance(actual_database_path, str)
                    and Path(expected_database_path).resolve()
                    != Path(actual_database_path).resolve()
                ):
                    raise_input_error(
                        "manifest-selected compilation database path differs"
                    )
            matching = [(command, arguments, command_text, directory, source)]
        except (ValueError, OSError):
            return held(
                row,
                manifest_source,
                context_status,
                "manifest_compile_command_mismatch",
            )
    if not matching:
        database_digest = manifest_source.get("compile_commands_sha256")
        reason = (
            "compile_database_missing"
            if database_digest is None
            else "held_no_reproducible_profile"
        )
        return held(row, manifest_source, context_status, reason)
    if len(matching) != 1:
        return held(
            row,
            manifest_source,
            context_status,
            "ambiguous_compile_commands",
            matching_command_count=len(matching),
        )

    command, original, command_text, directory, _ = matching[0]
    driver_path = _resolve_executable(original[0], directory)
    driver_digest = sha256_file(driver_path) if driver_path else None
    original_record: dict[str, JSONValue] = {
        "directory": str(directory),
        "directory_original": command.get("directory"),
        "command": command.get("command", command_text),
        "arguments": cast("list[JSONValue]", original),
        "source_file": command.get("file"),
        "output": command.get("output"),
        "database_path": command.get("database_path"),
        "database_sha256": command.get("database_sha256"),
        "command_index": command.get("command_index"),
        "driver": {
            "argv0": original[0],
            "resolved_path": str(driver_path) if driver_path else None,
            "binary_sha256": driver_digest,
            "version": None,
            "version_status": "not_queried_no_extra_compiler_command",
        },
    }
    adapted, ledger, unsupported = _adapt_arguments(original, source, directory)
    if context_status not in {"reproducible_profile", "partial_profile"}:
        return held(
            row,
            manifest_source,
            context_status,
            "held_no_reproducible_profile",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "not_run_context_incomplete",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": unsupported,
                "toolchain": None,
            },
        )
    if unsupported:
        return held(
            row,
            manifest_source,
            context_status,
            "unsupported_compile_arguments",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "held_unsupported_arguments",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": unsupported,
                "toolchain": None,
            },
        )
    if not helper_path.is_file() or not os.access(helper_path, os.X_OK):
        return held(
            row,
            manifest_source,
            context_status,
            "libtooling_helper_missing_or_not_executable",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_unavailable",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": None,
            },
        )
    helper = helper_path.resolve()
    helper_digest = sha256_file(helper)
    receipt_path = helper.with_name(helper.name + ".build.json")
    if not receipt_path.is_file():
        return held(
            row,
            manifest_source,
            context_status,
            "helper_build_receipt_missing",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_receipt_missing",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": None,
            },
        )
    try:
        build_receipt = _mapping(json.loads(receipt_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return held(
            row,
            manifest_source,
            context_status,
            "helper_build_receipt_invalid",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_receipt_invalid",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": None,
            },
            helper_receipt_error=str(error),
        )
    if build_receipt.get("helper_sha256") != helper_digest:
        return held(
            row,
            manifest_source,
            context_status,
            "helper_build_receipt_binary_mismatch",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_receipt_mismatch",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": None,
            },
            helper_sha256=helper_digest,
        )
    receipt_helper_path = build_receipt.get("helper_path")
    compiler_invocation = build_receipt.get("compiler_invocation")
    compiler_path = build_receipt.get("compiler_path")
    compiler_digest = build_receipt.get("compiler_sha256")
    helper_source_digest = build_receipt.get("source_sha256")
    resource_dir_value = build_receipt.get("resource_dir")
    resource_query_argv = build_receipt.get("resource_query_argv")
    resource_query_stdout = build_receipt.get("resource_query_stdout")
    resource_query_return_code = build_receipt.get("resource_query_return_code")
    resource_probe_value = build_receipt.get("resource_probe")
    resource_probe_digest = build_receipt.get("resource_probe_sha256")
    expected_resource_probe = (
        Path(resource_dir_value) / "include" / "stddef.h"
        if isinstance(resource_dir_value, str)
        else None
    )
    helper_source = Path(__file__).with_name("clang_frontend.cpp")
    receipt_identity_valid = (
        isinstance(receipt_helper_path, str)
        and Path(receipt_helper_path).resolve() == helper
        and isinstance(compiler_invocation, str)
        and isinstance(compiler_path, str)
        and Path(compiler_invocation).is_file()
        and Path(compiler_invocation).resolve() == Path(compiler_path).resolve()
        and isinstance(compiler_digest, str)
        and Path(compiler_path).is_file()
        and sha256_file(Path(compiler_path)) == compiler_digest
        and isinstance(helper_source_digest, str)
        and helper_source.is_file()
        and sha256_file(helper_source) == helper_source_digest
        and expected_resource_probe is not None
        and isinstance(resource_probe_value, str)
        and Path(resource_probe_value).resolve() == expected_resource_probe.resolve()
        and expected_resource_probe.is_file()
        and isinstance(resource_probe_digest, str)
        and sha256_file(expected_resource_probe) == resource_probe_digest
        and isinstance(resource_query_argv, list)
        and resource_query_argv == [compiler_invocation, "-print-resource-dir"]
        and isinstance(resource_query_stdout, str)
        and isinstance(resource_dir_value, str)
        and Path(resource_query_stdout.strip()).resolve()
        == Path(resource_dir_value).resolve()
        and resource_query_return_code == 0
    )
    if not receipt_identity_valid:
        return held(
            row,
            manifest_source,
            context_status,
            "helper_build_receipt_toolchain_mismatch",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_receipt_toolchain_mismatch",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": None,
            },
        )
    explicit_resource_dir: str | None = None
    for argument_index, argument in enumerate(original):
        if argument == "-resource-dir" and argument_index + 1 < len(original):
            explicit_resource_dir = original[argument_index + 1]
            break
        if argument.startswith("-resource-dir="):
            explicit_resource_dir = argument.partition("=")[2]
            break
    if (
        explicit_resource_dir is not None
        and isinstance(resource_dir_value, str)
        and Path(explicit_resource_dir).resolve() != Path(resource_dir_value).resolve()
    ):
        return held(
            row,
            manifest_source,
            context_status,
            "original_resource_directory_differs_from_clang_toolchain",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "held_resource_directory_mismatch",
                "argv": adapted,
                "transformations": ledger,
                "unsupported_context": [explicit_resource_dir],
                "toolchain": None,
            },
        )
    if explicit_resource_dir is None and isinstance(resource_dir_value, str):
        adapted.extend(["-resource-dir", resource_dir_value])
        ledger.append(
            {
                "operation": "add_toolchain_resource_directory",
                "original": None,
                "adapted": ["-resource-dir", resource_dir_value],
                "reason": "use the compiler receipt-bound Clang builtin headers",
            }
        )
    request: dict[str, JSONValue] = {
        "file": str(source),
        "directory": str(directory),
        "repository_root": str(repository),
        "language": row.get("language"),
        "capture_mode": capture_mode,
        "argv": cast("list[JSONValue]", adapted),
    }
    argv = [str(helper)]
    result = subprocess.run(
        argv,
        input=json.dumps(request, separators=(",", ":")),
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    stderr = result.stderr.encode("utf-8", errors="replace")
    stdout = result.stdout.encode("utf-8", errors="replace")
    stderr_artifact = _persist_raw(stderr_path, stderr)
    stdout_artifact = _persist_raw(stdout_path, stdout)
    source_digest_after = sha256_file(source)
    toolchain: dict[str, JSONValue] = {
        "compiler_invocation": build_receipt.get("compiler_invocation"),
        "compiler_path": build_receipt.get("compiler_path"),
        "compiler_sha256": build_receipt.get("compiler_sha256"),
        "compiler_version": build_receipt.get("compiler_version"),
        "llvm_prefix": build_receipt.get("llvm_prefix"),
        "helper_path": str(helper),
        "helper_sha256": helper_digest,
        "build_receipt_path": str(receipt_path),
        "build_receipt_sha256": sha256_file(receipt_path),
        "runtime_shared_library_identity": "not_hashed",
        "resource_dir": resource_dir_value,
        "resource_probe": resource_probe_value,
        "resource_probe_sha256": resource_probe_digest,
        "resource_query_argv": cast("list[JSONValue]", resource_query_argv),
        "resource_query_stdout": resource_query_stdout,
        "resource_query_return_code": resource_query_return_code,
    }
    if result.returncode != 0:
        return held(
            row,
            manifest_source,
            context_status,
            "libtooling_helper_failed",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_failed",
                "argv": [
                    build_receipt.get("compiler_invocation"),
                    *adapted,
                    str(source),
                ],
                "helper_argv": argv,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": toolchain,
                "return_code": result.returncode,
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            },
            native_execution={
                "status": "failed",
                "engine": "clang-libtooling",
                "helper_return_code": result.returncode,
            },
            helper_stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            raw_stderr=stderr_artifact,
            raw_stdout=stdout_artifact,
            observed_source_sha256_after=source_digest_after,
        )
    try:
        frontend = _mapping(json.loads(result.stdout))
    except (json.JSONDecodeError, ValueError) as error:
        return held(
            row,
            manifest_source,
            context_status,
            "invalid_libtooling_json",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "helper_invalid_output",
                "argv": [
                    build_receipt.get("compiler_invocation"),
                    *adapted,
                    str(source),
                ],
                "helper_argv": argv,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": toolchain,
            },
            native_execution={
                "status": "completed",
                "engine": "clang-libtooling",
                "helper_return_code": result.returncode,
            },
            helper_stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            raw_stderr=stderr_artifact,
            raw_stdout=stdout_artifact,
            helper_parse_error=str(error),
        )
    if source_digest_after != source_digest:
        return held(
            row,
            manifest_source,
            context_status,
            "source_changed_during_frontend",
            original_compile_command=original_record,
            clang_adaptation={
                "status": "source_race",
                "argv": [
                    build_receipt.get("compiler_invocation"),
                    *adapted,
                    str(source),
                ],
                "helper_argv": argv,
                "transformations": ledger,
                "unsupported_context": [],
                "toolchain": toolchain,
            },
            frontend=frontend,
            native_execution={
                "status": "completed",
                "engine": "clang-libtooling",
                "helper_return_code": result.returncode,
                "clang_tool_return_code": frontend.get("tool_return_code"),
            },
            observed_context_status="invalidated",
            independent_qualification={"status": "not_run"},
            raw_stderr=stderr_artifact,
            raw_stdout=stdout_artifact,
            observed_source_sha256_after=source_digest_after,
        )
    diagnostics_value = frontend.get("diagnostics")
    diagnostics = diagnostics_value if isinstance(diagnostics_value, list) else []
    clang_errors = any(
        isinstance(item, dict) and item.get("severity") == "error"
        for item in diagnostics
    )
    tool_return_code = frontend.get("tool_return_code")
    clang_errors = clang_errors or (
        isinstance(tool_return_code, int) and tool_return_code != 0
    )
    dependencies_value = frontend.get("dependency_paths")
    dependency_paths = (
        dependencies_value if isinstance(dependencies_value, list) else []
    )
    dependency_files: list[JSONValue] = []
    dependency_status = "complete"
    includes_value = frontend.get("includes")
    if isinstance(includes_value, list):
        for include in includes_value:
            if isinstance(include, dict) and include.get("resolved_path") is None:
                dependency_status = "incomplete"
    for value in dependency_paths:
        if not isinstance(value, str):
            dependency_status = "incomplete"
            continue
        dependency_path = Path(value)
        if not dependency_path.is_file():
            dependency_status = "incomplete"
            dependency_files.append({"path": value, "sha256": None})
            continue
        dependency_files.append(
            {
                "path": str(dependency_path.resolve()),
                "sha256": sha256_file(dependency_path),
            }
        )
    dependency_json = json.dumps(
        dependency_files, sort_keys=True, separators=(",", ":")
    ).encode()
    if source_digest_after != sha256_file(source):
        dependency_status = "incomplete"
    envelope: dict[str, JSONValue] = {
        "schema_version": SCHEMA_VERSION,
        "pilot_id": PILOT_ID,
        "manifest_source": manifest_source,
        "selection_row": row,
        **_manifest_identity(row),
        "context_status": context_status,
        "capture_mode": capture_mode,
        "status": "partial" if clang_errors else "complete",
        "hold_reasons": ["clang_frontend_reported_errors"] if clang_errors else [],
        "observed_context_status": dependency_status,
        "native_execution": {
            "status": "completed",
            "engine": "clang-libtooling",
            "helper_return_code": result.returncode,
            "clang_tool_return_code": tool_return_code,
        },
        "independent_qualification": {"status": "not_run"},
        "original_compile_command": original_record,
        "clang_adaptation": {
            "status": "applied",
            "argv": cast(
                "list[JSONValue]",
                [build_receipt.get("compiler_invocation"), *adapted, str(source)],
            ),
            "helper_argv": cast("list[JSONValue]", argv),
            "transformations": ledger,
            "unsupported_context": [],
            "toolchain": toolchain,
            "clang_frontend_version": frontend.get("clang_version"),
            "return_code": result.returncode,
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        },
        "dependency_closure": {
            "status": dependency_status,
            "files": dependency_files,
            "sha256": hashlib.sha256(dependency_json).hexdigest(),
        },
        "frontend": {
            "status": "diagnostics" if clang_errors else "parsed",
            **{
                key: value
                for key, value in frontend.items()
                if key != "dependency_paths"
            },
        },
        "unmodeled_fields": list(UNMODELED_FIELDS),
        "raw_stderr": stderr_artifact,
        "raw_stdout": stdout_artifact,
    }
    if dependency_status != "complete":
        envelope["status"] = "partial"
        reasons = envelope["hold_reasons"]
        if isinstance(reasons, list):
            reasons.append("dependency_closure_incomplete")
    return envelope
