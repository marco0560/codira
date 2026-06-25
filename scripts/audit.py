#!/usr/bin/env python3
"""Run security and dependency audit helpers."""

from __future__ import annotations

import argparse

from scripts.scriptlib import run


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
        if run(["uvx", "semgrep", "scan"]).returncode:
            print("[!] Semgrep (deep) found issues")
    else:
        print("[i] Running light scan (p/security-audit)")
        if run(["uvx", "semgrep", "--config", "p/security-audit"]).returncode:
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
