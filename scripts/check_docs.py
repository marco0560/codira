#!/usr/bin/env python3
"""Build the published documentation strictly without leaving site artifacts.

Parameters
----------
None

Returns
-------
None
    Local release and validation entry points share the CI documentation rules.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def build_documentation(root: Path) -> int:
    """Check documentation links and rendering using the repository MkDocs config.

    Parameters
    ----------
    root : pathlib.Path
        Checkout root containing mkdocs.yml and its documentation tree.

    Returns
    -------
    int
        MkDocs exit status. Warnings remain fatal, and child diagnostics are
        preserved in the caller's terminal. Generated HTML is temporary.
    """
    env = {**os.environ, "NO_MKDOCS_2_WARNING": "1"}
    with tempfile.TemporaryDirectory(prefix="codira-docs-check-") as site:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "mkdocs",
                "build",
                "--strict",
                "--config-file",
                str(root.resolve() / "mkdocs.yml"),
                "--site-dir",
                site,
            ],
            cwd=root,
            env=env,
            check=False,
        ).returncode


def main() -> int:
    """Run the local strict documentation gate.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero only when the documentation build succeeds without warnings.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    options = parser.parse_args()
    return build_documentation(options.root)


if __name__ == "__main__":
    raise SystemExit(main())
