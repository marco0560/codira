"""Persist managed-runtime receipts and deterministic user launchers."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeReceipt:
    """Record the immutable installation choices for one managed runtime.

    Parameters
    ----------
    source : str
        Coordinated distribution source selected at installation.
    profile : str
        Package profile selected at installation.
    version : str
        Coordinated Codira version.
    packages : tuple[str, ...]
        Explicit extension package set.
    """

    source: str
    profile: str
    version: str
    packages: tuple[str, ...]


def receipt_path(runtime_root: Path) -> Path:
    """Return the managed-runtime receipt location.

    Parameters
    ----------
    runtime_root : pathlib.Path
        Managed runtime root.

    Returns
    -------
    pathlib.Path
        Receipt file under the managed runtime root.
    """
    return runtime_root / "receipt.json"


def write_receipt(runtime_root: Path, receipt: RuntimeReceipt) -> Path:
    """Atomically write one runtime receipt.

    Parameters
    ----------
    runtime_root : pathlib.Path
        Managed runtime root.
    receipt : RuntimeReceipt
        Immutable installation choices to persist.

    Returns
    -------
    pathlib.Path
        Written receipt path.
    """
    path = receipt_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(receipt), sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def write_launchers(runtime_root: Path) -> tuple[Path, ...]:
    """Write shell-free launcher scripts for the managed runtime.

    Parameters
    ----------
    runtime_root : pathlib.Path
        Managed runtime root containing its Python executable.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Launcher paths for Codira, MCP, and installer commands.
    """
    executable = runtime_root / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    launchers = runtime_root / "launchers"
    launchers.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, module in (
        ("codira", "codira"),
        ("codira-mcp", "codira.mcp.server"),
        ("codira-installer", "codira_installer.cli"),
    ):
        path = launchers / name
        path.write_text(
            f"#!{executable}\nimport runpy\nrunpy.run_module({module!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        written.append(path)
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    """Write one receipt or deterministic launcher set.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command arguments, or process arguments when omitted.

    Returns
    -------
    int
        Zero after the requested runtime artifact is written.
    """
    parser = argparse.ArgumentParser(prog="codira-installer-runtime")
    subcommands = parser.add_subparsers(dest="action", required=True)
    receipt = subcommands.add_parser("write-receipt")
    receipt.add_argument("--root", type=Path, required=True)
    receipt.add_argument("--source", required=True)
    receipt.add_argument("--profile", required=True)
    receipt.add_argument("--version", required=True)
    receipt.add_argument("--package", action="append", default=[])
    launchers = subcommands.add_parser("write-launchers")
    launchers.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "write-receipt":
        write_receipt(
            args.root,
            RuntimeReceipt(
                args.source, args.profile, args.version, tuple(sorted(args.package))
            ),
        )
    else:
        write_launchers(args.root)
    return 0
