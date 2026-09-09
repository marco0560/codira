#!/usr/bin/env python3
"""Run the non-billed Issue #53 Phase 0 escape probes in a sealed container."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0


def build_parser() -> argparse.ArgumentParser:
    """Build the escape-probe command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring a fresh fixture root and explicit output path.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime", choices=phase0.SUPPORTED_CONTAINER_RUNTIMES, required=True
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def probe_commands() -> dict[str, tuple[str, bool]]:
    """Return each mandatory escape attempt and its expected shell success.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, tuple[str, bool]]
        Probe name mapped to shell command and expected successful exit status.
    """

    return {
        "host-memory-read": ("test ! -e /host-memory-sentinel.txt", True),
        "oracle-read": ("test ! -e /hidden-oracle.txt", True),
        "outside-fixture-write": ("touch /outside-fixture-write", False),
        "direct-network": ("curl --fail --max-time 2 https://example.com", False),
        "host-docker-socket": (
            "test ! -S /var/run/docker.sock && test ! -S /run/podman/podman.sock",
            True,
        ),
    }


def blocked(returncode: int, expected_success: bool) -> bool:
    """Decide whether one escape attempt was blocked as designed.

    Parameters
    ----------
    returncode : int
        Container process exit status for the attempted escape.
    expected_success : bool
        Whether the probe command succeeds when access is correctly absent.

    Returns
    -------
    bool
        ``True`` when the observed exit status proves containment.
    """

    return (returncode == 0) is expected_success


def main(arguments: list[str] | None = None) -> int:
    """Execute each mandatory container escape probe and write its outcomes.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command arguments excluding the executable name.

    Returns
    -------
    int
        Zero only when every required escape is demonstrably blocked.
    """

    args = build_parser().parse_args(arguments)
    try:
        fixture = phase0.create_contamination_fixture(args.root)
        outcomes: dict[str, bool] = {}
        for name, (command, expected_success) in probe_commands().items():
            argv = phase0.build_container_probe_argv(
                phase0.ContainerProbeRequest(
                    args.runtime, args.image, fixture.agent_root, command
                )
            )
            completed = subprocess.run(
                argv, check=False, capture_output=True, text=True
            )
            outcomes[name] = blocked(completed.returncode, expected_success)
    except (OSError, ValueError) as error:
        print(f"escape-probe configuration error: {error}", file=sys.stderr)
        return 2
    result = phase0.escape_probe_check(outcomes)
    payload = {"passed": result.passed, "detail": result.detail, "outcomes": outcomes}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
