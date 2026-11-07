"""Explicitly build the packaged LibTooling helper and write its identity receipt.

Parameters
----------
None

Returns
-------
None
    Module namespace for the explicit native build command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    """Hash one file in bounded memory.

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


def build_helper(
    compiler: Path,
    llvm_include_dir: Path,
    llvm_library_dir: Path,
    clang_cpp_library: str,
    llvm_library: str,
    output_path: Path,
    receipt_path: Path,
    *,
    compile_args: tuple[str, ...] = (),
    link_args: tuple[str, ...] = (),
) -> dict[str, object]:
    """Compile the packaged helper using only explicitly supplied native inputs.

    Parameters
    ----------
    compiler : pathlib.Path
        Explicit absolute Clang C++ compiler executable.
    llvm_include_dir, llvm_library_dir : pathlib.Path
        Explicit LLVM and Clang development directories.
    clang_cpp_library, llvm_library : str
        Exact library linker arguments, for example ``-lclang-cpp`` and a
        versioned LLVM library name supported by the selected toolchain.
    output_path, receipt_path : pathlib.Path
        New helper binary and build receipt paths.
    compile_args, link_args : tuple[str, ...], optional
        Additional exact compiler/linker argv items supplied by the operator.

    Returns
    -------
    dict[str, object]
        Reproducibility receipt containing exact argv and binary identities.

    Raises
    ------
    FileExistsError
        If the helper or receipt path already exists.
    FileNotFoundError
        If a supplied compiler, development directory, or resource header is missing.
    subprocess.CalledProcessError
        If the selected compiler rejects the exact build argv.

    Notes
    -----
    The function does not search ``PATH``, query ``llvm-config``, guess library
    names, or run during package import or source analysis.
    """
    compiler_invocation = compiler.absolute()
    compiler_path = compiler_invocation.resolve(strict=True)
    include_dir = llvm_include_dir.resolve(strict=True)
    library_dir = llvm_library_dir.resolve(strict=True)
    source = Path(__file__).resolve().parent / "native" / "clang_frontend.cpp"
    if (
        not compiler_invocation.is_file()
        or not include_dir.is_dir()
        or not library_dir.is_dir()
    ):
        raise FileNotFoundError(
            "explicit Clang compiler/include/library inputs are required"
        )
    if output_path.exists() or receipt_path.exists():
        raise FileExistsError("native helper output identities are immutable")
    attempt_dir = output_path.with_name(output_path.name + ".attempt")
    attempt_dir.mkdir(parents=True, exist_ok=False)
    probe_results: dict[str, subprocess.CompletedProcess[bytes]] = {}
    probe_commands = {
        "version": [str(compiler_invocation), "--version"],
        "resource": [str(compiler_invocation), "-print-resource-dir"],
    }
    for name, argv in probe_commands.items():
        result = subprocess.run(argv, capture_output=True, check=False, shell=False)
        probe_results[name] = result
        _write_immutable(attempt_dir / f"{name}.stdout", result.stdout)
        _write_immutable(attempt_dir / f"{name}.stderr", result.stderr)
        if result.returncode != 0:
            _write_immutable_json(
                attempt_dir / "attempt.json",
                {
                    "schema_version": "codira.clang-frontend-build-attempt/1",
                    "compiler_invocation": str(compiler_invocation),
                    "commands": probe_commands,
                    "failed_stage": name,
                    "return_code": result.returncode,
                },
            )
            raise subprocess.CalledProcessError(
                result.returncode, argv, output=result.stdout, stderr=result.stderr
            )
    version_result = probe_results["version"]
    resource_result = probe_results["resource"]
    version_text = version_result.stdout.decode("utf-8", errors="replace")
    resource_text = resource_result.stdout.decode("utf-8", errors="replace")
    resource_dir = Path(resource_text.strip()).resolve(strict=True)
    resource_probe = resource_dir / "include" / "stddef.h"
    if not resource_probe.is_file():
        raise FileNotFoundError(
            "selected Clang resource directory lacks include/stddef.h"
        )
    command = [
        str(compiler_invocation),
        "-std=c++20",
        "-O2",
        f"-I{include_dir}",
        *compile_args,
        str(source),
        f"-L{library_dir}",
        f"-Wl,-rpath,{library_dir}",
        clang_cpp_library,
        llvm_library,
        *link_args,
        "-o",
        str(output_path.resolve()),
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_result = subprocess.run(
        command, capture_output=True, check=False, shell=False
    )
    _write_immutable(attempt_dir / "build.stdout", build_result.stdout)
    _write_immutable(attempt_dir / "build.stderr", build_result.stderr)
    attempt_record: dict[str, object] = {
        "schema_version": "codira.clang-frontend-build-attempt/1",
        "compiler_invocation": str(compiler_invocation),
        "compiler_path": str(compiler_path),
        "commands": {**probe_commands, "build": command},
        "return_codes": {
            **{name: result.returncode for name, result in probe_results.items()},
            "build": build_result.returncode,
        },
        "output_files": [
            str(attempt_dir / f"{name}.{stream}")
            for name in (*probe_results, "build")
            for stream in ("stdout", "stderr")
        ],
    }
    _write_immutable_json(attempt_dir / "attempt.json", attempt_record)
    if build_result.returncode != 0:
        raise subprocess.CalledProcessError(
            build_result.returncode,
            command,
            output=build_result.stdout,
            stderr=build_result.stderr,
        )
    receipt: dict[str, object] = {
        "schema_version": "codira.clang-frontend-build-receipt/1",
        "compiler_invocation": str(compiler_invocation),
        "compiler_path": str(compiler_path),
        "compiler_sha256": _sha256(compiler_path),
        "compiler_version": version_text.splitlines()[0],
        "resource_query_argv": [str(compiler_invocation), "-print-resource-dir"],
        "resource_query_stdout": resource_text,
        "resource_query_return_code": resource_result.returncode,
        "resource_dir": str(resource_dir),
        "resource_probe": str(resource_probe.resolve()),
        "resource_probe_sha256": _sha256(resource_probe),
        "helper_source_path": str(source.resolve()),
        "source_sha256": _sha256(source),
        "helper_path": str(output_path.resolve()),
        "helper_sha256": _sha256(output_path),
        "build_argv": command,
        "build_attempt_dir": str(attempt_dir.resolve()),
        "build_stdout_path": str((attempt_dir / "build.stdout").resolve()),
        "build_stderr_path": str((attempt_dir / "build.stderr").resolve()),
        "build_stdout_sha256": _sha256(attempt_dir / "build.stdout"),
        "build_stderr_sha256": _sha256(attempt_dir / "build.stderr"),
        "runtime_shared_library_identity": "not_hashed",
    }
    _write_immutable_json(receipt_path, receipt)
    return receipt


def _write_immutable(path: Path, content: bytes) -> None:
    """Write a new immutable byte evidence file.

    Parameters
    ----------
    path : pathlib.Path
        New evidence path.
    content : bytes
        Exact subprocess output bytes.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If evidence already exists.
    OSError
        If evidence cannot be persisted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _write_immutable_json(path: Path, value: dict[str, object]) -> None:
    """Write one canonical JSON evidence record without replacement.

    Parameters
    ----------
    path : pathlib.Path
        New evidence path.
    value : dict[str, object]
        JSON-compatible record.

    Returns
    -------
    None

    Raises
    ------
    FileExistsError
        If the evidence identity already exists.
    OSError
        If evidence cannot be persisted.
    """
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _write_immutable(path, content + b"\n")


def main() -> int:
    """Build the native helper from explicit toolchain and linker inputs.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status, zero after writing the new receipt.

    Raises
    ------
    SystemExit
        If command-line arguments are invalid or the native build fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--llvm-include-dir", required=True, type=Path)
    parser.add_argument("--llvm-library-dir", required=True, type=Path)
    parser.add_argument("--clang-cpp-library", required=True)
    parser.add_argument("--llvm-library", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--compile-arg", action="append", default=[])
    parser.add_argument("--link-arg", action="append", default=[])
    args = parser.parse_args()
    receipt = build_helper(
        args.compiler,
        args.llvm_include_dir,
        args.llvm_library_dir,
        args.clang_cpp_library,
        args.llvm_library,
        args.output,
        args.receipt,
        compile_args=tuple(args.compile_arg),
        link_args=tuple(args.link_arg),
    )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
