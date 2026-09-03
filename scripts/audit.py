#!/usr/bin/env python3
"""Run security and dependency audit helpers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import PERSONAL_SECRETS_DIR, run, sops_exec_env_argv


def main() -> int:
    """
    Run repository audit checks.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    parser = argparse.ArgumentParser(description="Audit the Codira project.")
    parser.add_argument("--deep", action="store_true", help="Run Semgrep auto rules.")
    args = parser.parse_args()

    print("[*] Code security (Semgrep)")
    if args.deep:
        print("[i] Running deep scan (Semgrep auto rules)")
        command = sops_exec_env_argv(
            PERSONAL_SECRETS_DIR / "semgrep.env",
            ("uvx", "semgrep", "scan"),
        )
        if run(command).returncode:
            print("[!] Semgrep (deep) found issues")
    else:
        print("[i] Running light scan (p/security-audit)")
        command = sops_exec_env_argv(
            PERSONAL_SECRETS_DIR / "semgrep.env",
            ("uvx", "semgrep", "--config", "p/security-audit"),
        )
        if run(command).returncode:
            print("[!] Semgrep (light) found issues")

    print()
    print("[*] Dependency audit (uv audit)")
    if run(["uv", "audit", "--frozen"]).returncode:
        print("[!] Vulnerable dependencies found")

    print()
    print(f"[OK] Audit completed ({'deep' if args.deep else 'light'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
