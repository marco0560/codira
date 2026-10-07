"""Qualify native subscription isolation and public-safe admission controls.

Parameters
----------
None

Returns
-------
None
    Module definitions for benchmark tooling and validation.
"""

from __future__ import annotations

import socket
import tempfile
import threading
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

import pytest

from scripts.agent_efficiency.codex_subscription import (
    SubscriptionTunnel,
    write_subscription_config,
)
from scripts.agent_efficiency.runner import (
    ContainerAttemptRequest,
    build_container_argv,
)
from scripts.agent_efficiency.temporary import PROJECT_TEMP_ROOT


@pytest.fixture
def socket_root() -> Iterator[Path]:
    """Provide short Unix socket paths under approved disposable storage.

    Parameters
    ----------
    None
        Uses disposable project scratch storage.

    Yields
    ------
    pathlib.Path
        Temporary socket root within the repository's scratch policy.
    """
    with tempfile.TemporaryDirectory(prefix="ae-", dir=PROJECT_TEMP_ROOT) as temporary:
        yield Path(temporary)


def test_native_config_denies_client_state_and_forces_chatgpt(tmp_path: Path) -> None:
    """Require native authentication and explicit model tool isolation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated disposable fixture root.

    Returns
    -------
    None
        Configuration has no API fallback or overriding legacy sandbox setting.
    """
    config = write_subscription_config(tmp_path / "state", "gpt-6-luna", "high", None)
    parsed = tomllib.loads(config.read_text())
    assert parsed["forced_login_method"] == "chatgpt"
    assert parsed["model_provider"] == "openai"
    assert parsed["default_permissions"] == "benchmark"
    assert parsed["permissions"]["benchmark"]["filesystem"]["/codex-state"] == "deny"
    assert parsed["permissions"]["benchmark"]["network"]["enabled"] is False
    assert "sandbox_mode" not in parsed
    with pytest.raises(ValueError, match="fresh"):
        write_subscription_config(tmp_path / "state", "gpt-6-luna", "high", None)


def test_native_container_mounts_only_readonly_managed_login(
    tmp_path: Path, socket_root: Path
) -> None:
    """Bind the client login without exposing provider keys or host home.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable workspace and public fake login paths.
    socket_root : pathlib.Path
        Short disposable socket path.

    Returns
    -------
    None
        The native client uses its qualified permissions profile.
    """
    fixture, state = tmp_path / "fixture", tmp_path / "state"
    fixture.mkdir()
    state.mkdir()
    auth = tmp_path / "managed-login.json"
    auth.write_text('{"canary":"public"}')
    with socket.socket(socket.AF_UNIX) as listener:
        socket_path = socket_root / "provider.sock"
        listener.bind(str(socket_path))
        argv = build_container_argv(
            ContainerAttemptRequest(
                "podman",
                "localhost/test@sha256:" + "a" * 64,
                fixture,
                state,
                "public task",
                30,
                proxy_socket=socket_path,
                provider_transport="codex-subscription",
                subscription_auth=auth,
            )
        )
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert any(
        f"src={auth}" in argument and "dst=/codex-state/auth.json,ro" in argument
        for argument in argv
    )
    assert not any("CODIRA_PROXY_CLIENT_TOKEN" in argument for argument in argv)
    assert "danger-full-access" not in " ".join(argv)


@pytest.mark.parametrize(
    "wire_request",
    [
        b"GET / HTTP/1.1\r\n\r\n",
        b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",
        b"CONNECT chatgpt.com:80 HTTP/1.1\r\n\r\n",
    ],
)
def test_tunnel_rejects_nonallowlisted_routes(
    socket_root: Path, wire_request: bytes
) -> None:
    """Reject generic network routes before opening an upstream connection.

    Parameters
    ----------
    socket_root : pathlib.Path
        Short disposable Unix socket root.
    wire_request : bytes
        Public malformed or nonallowlisted CONNECT request.

    Returns
    -------
    None
        Only exact approved TLS endpoints may be reached.
    """
    server = SubscriptionTunnel(str(socket_root / "tunnel.sock"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(socket_root / "tunnel.sock"))
            client.sendall(wire_request)
            assert b"403 Forbidden" in client.recv(1024)
        assert server.connections == {}
    finally:
        server.shutdown()
        server.server_close()


def test_rpc_preserves_buffered_responses() -> None:
    """Handle several JSON-RPC frames received in one pipe read.

    Parameters
    ----------
    None
        Uses local pipes without a provider request.

    Returns
    -------
    None
        A buffered second response does not wait for another kernel event.
    """
    import json
    import os
    import time

    from scripts.agent_efficiency.codex_subscription import _receive

    reader, writer = os.pipe()
    frames = b"".join(
        json.dumps({"id": identifier, "result": {"value": identifier}}).encode() + b"\n"
        for identifier in (1, 2)
    )
    try:
        os.write(writer, frames)
        with os.fdopen(reader, "r") as stream:
            buffered = bytearray()
            assert _receive(stream, 1, time.monotonic() + 1, buffered)["value"] == 1
            assert _receive(stream, 2, time.monotonic() + 1, buffered)["value"] == 2
    finally:
        os.close(writer)


@pytest.mark.parametrize(
    "usage,exhausted", [((100, 0), False), ((0, 100), False), ((100, 100), True)]
)
def test_quota_does_not_guess_model_bucket(
    usage: tuple[int, int], exhausted: bool
) -> None:
    """Leave eligibility to the provider while any distinct quota is available.

    Parameters
    ----------
    usage : tuple[int, int]
        Public fixture percentages for two separate native quota buckets.
    exhausted : bool
        Whether all reported buckets are exhausted.

    Returns
    -------
    None
        An unrelated full bucket does not prematurely block a model.
    """
    from scripts.agent_efficiency.codex_subscription import subscription_quota_exhausted

    receipt = {
        "rate_limits": {
            str(index): {"primary": {"usedPercent": used}, "reached": False}
            for index, used in enumerate(usage)
        }
    }
    assert subscription_quota_exhausted(receipt) is exhausted


def test_native_scheduler_checkpoints_without_a_start(tmp_path: Path) -> None:
    """Exhausted quota does not consume or start a pending scheduled slot.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable campaign-state root.

    Returns
    -------
    None
        Both paired slots remain available for explicit continuation.
    """
    from scripts.agent_efficiency.campaign_state import (
        CampaignStore,
        build_paired_schedule,
    )
    from scripts.agent_efficiency.subscription_campaign import run_subscription_campaign

    store = CampaignStore(
        tmp_path / "state",
        "quota-test-001",
        {"frozen": True},
        build_paired_schedule(["panel-n1"], 1, 7),
    )
    store.initialize()
    report = run_subscription_campaign(
        store,
        lambda _: pytest.fail("no model request is allowed"),
        check_quota=lambda: {"rate_limits": {"codex": {"reached": True}}},
    )
    assert report["status"] == "checkpoint"
    assert report["pending_attempt_count"] == 2
    assert list((store.root / "subscription-starts").glob("*.json")) == []


def test_native_scheduler_rejects_an_unsettled_start(tmp_path: Path) -> None:
    """Preserve interrupted attempts until their evidence is investigated.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable campaign-state root.

    Returns
    -------
    None
        No automatic model retry or quota request occurs.
    """
    from scripts.agent_efficiency.campaign_state import (
        CampaignStore,
        build_paired_schedule,
    )
    from scripts.agent_efficiency.subscription_campaign import run_subscription_campaign

    schedule = build_paired_schedule(["panel-n1"], 1, 7)
    store = CampaignStore(
        tmp_path / "state", "quota-test-002", {"frozen": True}, schedule
    )
    store.initialize()
    start_root = store.root / "subscription-starts"
    start_root.mkdir()
    (start_root / f"{schedule[0].attempt_id}.json").write_text(
        '{"public":"unfinished"}'
    )
    with pytest.raises(ValueError, match="unfinished"):
        run_subscription_campaign(
            store,
            lambda _: pytest.fail("no retry"),
            check_quota=lambda: pytest.fail("no quota check before investigation"),
        )
