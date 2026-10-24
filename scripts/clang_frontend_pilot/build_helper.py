"""Build the standalone Clang22 LibTooling comparison helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def _sha256(path: Path) -> str:
    """Hash one executable or source file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_helper(
    source: Path,
    output: Path,
    compiler: str,
    llvm_prefix: Path,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    """Compile the fixed helper source against the selected LLVM installation.

    Parameters
    ----------
    source : pathlib.Path
        Tracked C++ LibTooling helper source.
    output : pathlib.Path
        New executable output path.
    compiler : str
        Explicit Clang C++ compiler executable name or path.
    llvm_prefix : pathlib.Path
        LLVM installation root containing ``include`` and ``lib64``.
    receipt_path : pathlib.Path or None, optional
        New path for the compiler and helper identity receipt.

    Returns
    -------
    dict[str, object]
        Compiler, helper, and build-argv identity record.

    Raises
    ------
    FileNotFoundError
        If the compiler or requested LLVM installation is missing.
    FileExistsError
        If the output path already exists.
    subprocess.CalledProcessError
        If the selected compiler rejects the fixed build command.
    """
    executable = shutil.which(compiler)
    if executable is None:
        message = f"Clang compiler not found: {compiler}"
        raise FileNotFoundError(message)
    compiler_invocation = Path(executable).absolute()
    compiler_path = compiler_invocation.resolve()
    include_dir = llvm_prefix / "include"
    library_dir = llvm_prefix / "lib64"
    if not include_dir.is_dir() or not library_dir.is_dir():
        message = f"LLVM headers/libraries are missing under {llvm_prefix}"
        raise FileNotFoundError(message)
    if output.exists():
        raise FileExistsError(output)
    receipt = receipt_path or output.with_name(output.name + ".build.json")
    if receipt.exists():
        raise FileExistsError(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    version_result = subprocess.run(
        [str(compiler_invocation), "--version"],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    resource_result = subprocess.run(
        [str(compiler_invocation), "-print-resource-dir"],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    resource_dir = Path(resource_result.stdout.strip()).resolve()
    resource_probe = resource_dir / "include" / "stddef.h"
    if not resource_probe.is_file():
        message = f"Clang builtin stddef.h is missing under {resource_dir}"
        raise FileNotFoundError(message)
    command = [
        str(compiler_invocation),
        "-std=c++20",
        "-O2",
        f"-I{include_dir}",
        str(source.resolve()),
        f"-L{library_dir}",
        f"-Wl,-rpath,{library_dir}",
        "-lclang-cpp",
        "-lLLVM-22",
        "-o",
        str(output.resolve()),
    ]
    subprocess.run(command, check=True, shell=False)
    result: dict[str, object] = {
        "compiler_path": str(compiler_path),
        "compiler_invocation": str(compiler_invocation),
        "compiler_sha256": _sha256(compiler_path),
        "compiler_version": version_result.stdout.splitlines()[0],
        "resource_query_argv": [str(compiler_invocation), "-print-resource-dir"],
        "resource_query_stdout": resource_result.stdout,
        "resource_query_return_code": resource_result.returncode,
        "resource_dir": str(resource_dir),
        "resource_probe": str(resource_probe),
        "resource_probe_sha256": _sha256(resource_probe),
        "llvm_prefix": str(llvm_prefix.resolve()),
        "build_argv": command,
        "source_sha256": _sha256(source),
        "helper_path": str(output.resolve()),
        "helper_sha256": _sha256(output),
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
    result["build_receipt_path"] = str(receipt.resolve())
    return result


def main() -> int:
    """Parse build arguments and emit a machine-readable receipt.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compiler", default="clang++-22")
    parser.add_argument("--llvm-prefix", type=Path, default=Path("/usr/lib/llvm/22"))
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).with_name("clang_frontend.cpp"),
    )
    arguments = parser.parse_args()
    build_receipt = build_helper(
        arguments.source,
        arguments.output,
        arguments.compiler,
        arguments.llvm_prefix,
        arguments.receipt,
    )
    print(json.dumps(build_receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
