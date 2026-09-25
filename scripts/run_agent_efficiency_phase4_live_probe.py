#!/usr/bin/env python3
"""Run the one authorized Phase 4 container conformance probe.

Invoke only through the dedicated SOPS OpenRouter environment.  The provider
credential stays in the runner-side Unix-socket proxy; the isolated container
receives only a fresh proxy-client token and has ``--network=none``.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
import threading
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.agent_efficiency import phase0, provider_proxy
from scripts.agent_efficiency.campaign_state import build_paired_schedule
from scripts.agent_efficiency.runner import (
    PROJECT_TEMP_ROOT,
    ContainerAttemptRequest,
    codex_model_base_instructions,
    execute_container_attempt,
    result_from_execution,
    write_proxy_relay,
)
from scripts.run_agent_efficiency_phase0_live_probe import (
    load_manifest,
    prepare_disposable_fixture,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit, bounded Phase 4 probe parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring explicit execution and disposable probe paths.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--runtime", default="podman")
    parser.add_argument("--execute", action="store_true")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Execute one conformance-only container turn after explicit approval.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero for a successful complete-usage probe, one for conformance
        failure, and two for unavailable or unsafe prerequisites.
    """

    args = build_parser().parse_args(arguments)
    if not args.execute:
        print(json.dumps({"mode": "dry-run", "image": args.image}, sort_keys=True))
        return 0
    manifest = load_manifest(Path("benchmarks/agent-efficiency/phase0-live-probe.toml"))
    provider = manifest["provider"]
    limits = manifest["limits"]
    assert isinstance(provider, dict) and isinstance(limits, dict)
    if args.events.exists() or args.state_root.exists():
        print("phase4 probe state and events must be absent", file=sys.stderr)
        return 2
    upstream = os.environ.get(provider_proxy.UPSTREAM_TOKEN_ENV, "")
    if not upstream:
        print("phase4 probe OpenRouter credential is unavailable", file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(32)
    server = None
    try:
        prepare_disposable_fixture(args.fixture_root)
        phase0.write_isolated_codex_config(
            args.state_root,
            "/workspace",
            "http://127.0.0.1:43123/v1",
            phase0.CodexProviderSettings(
                str(provider["model"]),
                str(provider["reasoning_effort"]),
                base_instructions=codex_model_base_instructions(
                    args.runtime, args.image
                ),
            ),
            "codira-mcp",
        )
        write_proxy_relay(args.state_root)
        socket_path = args.state_root / "provider.sock"
        settings = provider_proxy.ProxySettings(
            token, upstream, 0, int(limits["max_output_tokens"])
        )
        server = provider_proxy.create_unix_server(settings, str(socket_path))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        attempt = next(
            item
            for item in build_paired_schedule(("phase4-conformance",), 1, 1)
            if item.assistance_mode == "codira-mcp"
        )
        with tempfile.TemporaryDirectory(
            prefix="ae-probe-", dir=PROJECT_TEMP_ROOT
        ) as temporary_root:
            execution = execute_container_attempt(
                ContainerAttemptRequest(
                    args.runtime,
                    args.image,
                    args.fixture_root,
                    args.state_root,
                    "Use the required Codira MCP server once, then write a JSON object with status ok to .benchmark/result.json.",
                    int(limits["timeout_seconds"]),
                    proxy_socket=socket_path,
                    proxy_client_token=token,
                    temporary_root=Path(temporary_root),
                )
            )
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(execution.stdout, encoding="utf-8")
        result, evidence = result_from_execution(
            "phase4-conformance", attempt, execution
        )
        print(json.dumps({"result": result, "evidence": evidence}, sort_keys=True))
        return 0 if result["outcome"] == "success" and result["usage_complete"] else 1
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
