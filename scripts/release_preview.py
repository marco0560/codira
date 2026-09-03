#!/usr/bin/env python3
"""Preview the semantic-release result for a guarded Codira release."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import PERSONAL_SECRETS_DIR, run, sops_exec_env_argv

RELEASE_CONFIG = Path(".releaserc.json")


def semantic_release_preview_argv(config: Path) -> tuple[str, ...]:
    """
    Build the local semantic-release dry-run command.

    Parameters
    ----------
    config : pathlib.Path
        Semantic-release configuration file.

    Returns
    -------
    tuple[str, ...]
        Command that previews release effects without publishing them.
    """
    return (
        "npx",
        "semantic-release",
        "--dry-run",
        "--config",
        str(config),
    )


def main() -> int:
    """
    Run the semantic-release preview with scoped GitHub credentials.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status from semantic-release, or ``1`` when the release
        configuration is absent.
    """
    if not RELEASE_CONFIG.is_file():
        print(f"ERROR: semantic-release config not found: {RELEASE_CONFIG}")
        return 1

    print("▶ Running semantic-release preview")
    command = sops_exec_env_argv(
        PERSONAL_SECRETS_DIR / "github.env",
        semantic_release_preview_argv(RELEASE_CONFIG),
    )
    return run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
