#!/usr/bin/env python3
"""Run the approved Issue #53 live conformance probe.

The process is invoked only under the dedicated SOPS OpenRouter environment.
It keeps that credential in the loopback proxy process and removes it from the
Codex child environment before the child starts.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0, provider_proxy

PROMPT = (
    "Use the required Codira MCP server once to inspect this fixture. Then write "
    "a JSON object with key 'status' and value 'ok' to .benchmark/result.json."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the bounded live-probe command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring explicit state, fixture, and evidence locations.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("benchmarks/agent-efficiency/phase0-live-probe.toml"),
    )
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--codira-mcp", default="codira-mcp")
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument(
        "--cancel-after-seconds",
        type=float,
        help="Send SIGINT after this delay instead of waiting for turn completion.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Start the paid Codex turn; omitted means credential-free dry run.",
    )
    return parser


def load_manifest(path: Path) -> dict[str, object]:
    """Load and validate the approved conformance-only probe manifest.

    Parameters
    ----------
    path : pathlib.Path
        TOML manifest path.

    Returns
    -------
    dict[str, object]
        Validated manifest mapping.

    Raises
    ------
    ValueError
        If required bounded-probe fields are missing or invalid.
    """

    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = manifest.get("provider")
    limits = manifest.get("limits")
    admission = manifest.get("admission")
    if (
        manifest.get("purpose") != "runner-and-isolation-conformance"
        or manifest.get("attempts") != 1
        or not isinstance(provider, dict)
        or not isinstance(limits, dict)
        or not isinstance(admission, dict)
        or provider.get("name") != "openrouter"
        or not isinstance(provider.get("model"), str)
        or not isinstance(provider.get("reasoning_effort"), str)
        or limits.get("max_attempts") != 1
        or limits.get("timeout_seconds") != 600
        or limits.get("max_output_tokens") != 12000
        or limits.get("observed_total_tokens_ceiling") != 80000
        or admission.get("exclude_from_paired_savings_analysis") is not True
    ):
        message = "live-probe manifest is not the approved bounded conformance manifest"
        raise ValueError(message)
    return manifest


def build_codex_argv(codex: str, fixture_root: Path) -> tuple[str, ...]:
    """Build the fixed Codex command for one conformance-only turn.

    Parameters
    ----------
    codex : str
        Codex executable name or absolute path.
    fixture_root : pathlib.Path
        Agent-visible fixture directory.

    Returns
    -------
    tuple[str, ...]
        Shell-free command vector for JSONL, ephemeral Codex execution.
    """

    return (
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--cd",
        str(fixture_root),
        PROMPT,
    )


def prepare_disposable_fixture(root: Path) -> None:
    """Create the small agent-visible fixture for one conformance execution.

    Parameters
    ----------
    root : pathlib.Path
        Empty or absent fixture directory outside the implementation checkout.

    Returns
    -------
    None
        A deterministic Python fixture and writable result directory are made.

    Raises
    ------
    ValueError
        If the requested fixture directory contains prior-run state.
    """

    if root.exists() and any(root.iterdir()):
        message = "fixture root must be absent or empty for a fresh probe"
        raise ValueError(message)
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "# Phase 0 fixture\n\nA disposable Codira MCP conformance fixture.\n",
        encoding="utf-8",
    )
    (root / "sample.py").write_text(
        '"""Minimal symbol for Codira MCP conformance."""\n\n\ndef greeting() -> str:\n'
        '    """Return the deterministic fixture greeting.\n\n'
        "    Returns\n"
        "    -------\n"
        "    str\n"
        "        Stable greeting value.\n"
        '    """\n\n'
        '    return "hello"\n',
        encoding="utf-8",
    )
    (root / ".benchmark").mkdir()


def resolve_executable(executable: str) -> str | None:
    """Resolve one executable without accepting a missing relative path.

    Parameters
    ----------
    executable : str
        Executable name or absolute path.

    Returns
    -------
    str or None
        Absolute executable path, or ``None`` when unavailable.
    """

    if Path(executable).name != executable:
        path = Path(executable)
        return (
            str(path.resolve()) if path.is_file() and os.access(path, os.X_OK) else None
        )
    return shutil.which(executable)


def main(arguments: list[str] | None = None) -> int:
    """Execute or render the bounded live conformance probe.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command arguments excluding the executable name.

    Returns
    -------
    int
        Zero for a successful dry run or admissible execution; nonzero for
        invalid input, unavailable credentials, or failed evidence.
    """

    args = build_parser().parse_args(arguments)
    try:
        manifest = load_manifest(args.manifest)
        fixture_root = args.fixture_root.resolve()
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"live-probe configuration error: {error}", file=sys.stderr)
        return 2
    if fixture_root.exists() and not fixture_root.is_dir():
        print(
            "live-probe configuration error: fixture root must be a directory",
            file=sys.stderr,
        )
        return 2
    if args.events.exists() or args.state_root.exists():
        print(
            "live-probe configuration error: events and state paths must not exist "
            "before a fresh probe",
            file=sys.stderr,
        )
        return 2
    if args.cancel_after_seconds is not None and args.cancel_after_seconds <= 0:
        print(
            "live-probe configuration error: cancellation delay must be positive",
            file=sys.stderr,
        )
        return 2
    provider = manifest["provider"]
    limits = manifest["limits"]
    assert isinstance(provider, dict)
    assert isinstance(limits, dict)
    model = provider["model"]
    effort = provider["reasoning_effort"]
    max_output_tokens = limits["max_output_tokens"]
    observed_total_tokens_ceiling = limits["observed_total_tokens_ceiling"]
    assert isinstance(model, str)
    assert isinstance(effort, str)
    assert isinstance(max_output_tokens, int)
    assert isinstance(observed_total_tokens_ceiling, int)

    argv = build_codex_argv(args.codex, fixture_root)
    if not args.execute:
        print(json.dumps({"mode": "dry-run", "argv": argv, "model": model}))
        return 0
    upstream_token = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
    if not upstream_token:
        print(
            "live-probe configuration error: missing OpenRouter credential",
            file=sys.stderr,
        )
        return 2
    mcp_command = resolve_executable(args.codira_mcp)
    if mcp_command is None:
        print(
            "live-probe configuration error: codira-mcp executable is unavailable",
            file=sys.stderr,
        )
        return 2
    client_token = secrets.token_urlsafe(32)
    server = provider_proxy.create_server(
        provider_proxy.ProxySettings(client_token, upstream_token, 0, max_output_tokens)
    )
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    result = 1
    try:
        prepare_disposable_fixture(fixture_root)
        phase0.write_isolated_codex_config(
            args.state_root,
            str(fixture_root),
            f"http://127.0.0.1:{port}/v1",
            phase0.CodexProviderSettings(model, effort),
            mcp_command,
        )
        environment = phase0.isolated_environment(os.environ, args.state_root)
        environment[provider_proxy.PROXY_CLIENT_TOKEN_ENV] = client_token
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        if args.cancel_after_seconds is None:
            stdout, _ = process.communicate(timeout=600)
            cancellation = None
            cancellation_elapsed_seconds = None
        else:
            time.sleep(args.cancel_after_seconds)
            cancellation_started = time.monotonic()
            process.send_signal(signal.SIGINT)
            stdout, _ = process.communicate(timeout=15)
            cancellation_elapsed_seconds = time.monotonic() - cancellation_started
            cancellation = phase0.cancellation_check(
                process.returncode,
                cancellation_elapsed_seconds,
                15,
                signal_sent=True,
            )
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(stdout, encoding="utf-8")
        diagnostic_path = args.events.with_suffix(
            args.events.suffix + ".diagnostic.json"
        )
        diagnostic = {
            "returncode": process.returncode,
            "cancellation_elapsed_seconds": cancellation_elapsed_seconds,
            "cancellation_check": (
                {"passed": cancellation.passed, "detail": cancellation.detail}
                if cancellation is not None
                else None
            ),
        }
        diagnostic_path.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if cancellation is not None:
            events = phase0.parse_jsonl_events(stdout)
            event_check = phase0.cancellation_event_check(events)
            result = 0 if cancellation.passed and event_check.passed else 1
        else:
            events = phase0.parse_jsonl_events(stdout)
            check = phase0.jsonl_conformance_check(events, "codira-mcp")
            token_check = phase0.observed_total_token_check(
                events, observed_total_tokens_ceiling
            )
            result = (
                0
                if process.returncode == 0 and check.passed and token_check.passed
                else 1
            )
    except (OSError, subprocess.TimeoutExpired, phase0.JsonlEvidenceError) as error:
        print(f"live-probe execution error: {error}", file=sys.stderr)
        return 1
    finally:
        server.shutdown()
        server.server_close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
