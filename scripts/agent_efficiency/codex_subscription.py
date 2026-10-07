"""Read authenticated Codex subscription admission without exposing account data."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import json
import os
import select
import selectors
import socket
import socketserver
import subprocess
import threading
import time
from collections.abc import Mapping
from typing import IO, TYPE_CHECKING, cast
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from pathlib import Path


class SubscriptionPreflightError(ValueError):
    """Report a rejected native Codex subscription route."""


class SubscriptionQuotaError(SubscriptionPreflightError):
    """Report exhausted native quota without retrying a model request."""


_RPC_BUFFERS: WeakKeyDictionary[subprocess.Popen[str], bytearray] = WeakKeyDictionary()

ALLOWED_HOSTS = frozenset({"chatgpt.com", "auth.openai.com", "api.openai.com"})


def write_subscription_config(
    state_root: Path, model: str, effort: str, mcp_command: str | None
) -> Path:
    """Write a fresh native Codex configuration with credential read denied to tools.

    Parameters
    ----------
    state_root : pathlib.Path
        Absent per-attempt Codex state directory.
    model : str
        Authenticated native model identity.
    effort : str
        Authenticated reasoning effort.
    mcp_command : str or None
        Fixed installed MCP executable for assisted attempts.

    Returns
    -------
    pathlib.Path
        Credential-free configuration file in the new state root.

    Raises
    ------
    ValueError
        If model controls are empty or state already exists.
    """
    if not model or not effort or state_root.exists():
        raise ValueError("subscription configuration requires fresh admitted state")
    state_root.mkdir(parents=True, mode=0o700)
    configuration = (
        'approval_policy = "never"\n'
        'default_permissions = "benchmark"\n'
        'forced_login_method = "chatgpt"\n'
        'model_provider = "openai"\n'
        f"model = {json.dumps(model)}\n"
        f"model_reasoning_effort = {json.dumps(effort)}\n\n"
        "[permissions.benchmark]\n"
        'extends = ":workspace"\n\n'
        "[permissions.benchmark.filesystem]\n"
        '"/codex-state" = "deny"\n\n'
        "[permissions.benchmark.network]\n"
        "enabled = false\n\n"
        "[shell_environment_policy]\n"
        'inherit = "core"\n'
        "ignore_default_excludes = false\n\n"
        "[features]\n"
        "memories = false\n"
        "multi_agent = false\n"
        "apps = false\n"
    )
    if mcp_command is not None:
        configuration += (
            "\n[mcp_servers.codira]\n"
            f"command = {json.dumps(mcp_command)}\n"
            'args = ["--root", "/workspace"]\n'
            "required = true\n"
            'default_tools_approval_mode = "approve"\n'
        )
    destination = state_root / "config.toml"
    destination.write_text(configuration, encoding="utf-8")
    destination.chmod(0o600)
    return destination


class SubscriptionTunnel(socketserver.ThreadingUnixStreamServer):
    """Allow TLS CONNECT to the Codex account route over one Unix socket."""

    daemon_threads = True

    def __init__(self, path: str) -> None:
        """Open the isolated listener without retaining credential contents.

        Parameters
        ----------
        path : str
            Fresh Unix socket path under an operation-scoped directory.
        """
        super().__init__(path, _ConnectHandler)
        self._lock = threading.Lock()
        self.connections: dict[str, int] = {}
        self.bytes_relayed = 0

    def observe(self, host: str, count: int) -> None:
        """Record a safe tunnel destination and aggregate byte count.

        Parameters
        ----------
        host : str
            Allowlisted TLS hostname.
        count : int
            Opaque encrypted payload byte count.

        Returns
        -------
        None
            Updates aggregate counters under the tunnel lock.
        """
        with self._lock:
            self.connections[host] = self.connections.get(host, 0) + 1
            self.bytes_relayed += count


class _ConnectHandler(socketserver.BaseRequestHandler):
    """Proxy one TLS CONNECT stream while discarding request headers."""

    def handle(self) -> None:
        """Forward encrypted bytes only for an allowlisted TLS host.

        Parameters
        ----------
        None
            Uses the socket supplied by the server.

        Returns
        -------
        None
            Invalid requests are rejected without exposing their contents.
        """
        self.request.settimeout(10)
        reader = self.request.makefile("rb")
        try:
            first = reader.readline(4096)
            parts = first.decode("ascii", "replace").strip().split()
            if len(parts) != 3 or parts[0] != "CONNECT":
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            host, separator, port = parts[1].rpartition(":")
            if not separator or host not in ALLOWED_HOSTS or port != "443":
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            header_size = len(first)
            while True:
                line = reader.readline(4096)
                header_size += len(line)
                if header_size > 16384:
                    self.request.sendall(
                        b"HTTP/1.1 431 Request Header Fields Too Large\r\n\r\n"
                    )
                    return
                if not line:
                    return
                if line in {b"\r\n", b"\n"}:
                    break
            with socket.create_connection((host, 443), timeout=15) as upstream:
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                count = 0
                self.request.settimeout(None)
                upstream.settimeout(None)
                while True:
                    readable, _, _ = select.select([self.request, upstream], [], [], 60)
                    if not readable:
                        break
                    for source in readable:
                        target = upstream if source is self.request else self.request
                        data = source.recv(65536)
                        if not data:
                            cast("SubscriptionTunnel", self.server).observe(host, count)
                            return
                        target.sendall(data)
                        count += len(data)
        except (OSError, UnicodeError):
            return
        finally:
            reader.close()


def _receive(
    stream: IO[str], request_id: int, deadline: float, buffered: bytearray
) -> Mapping[str, object]:
    """Read one JSON-RPC response while ignoring unrelated notifications.

    Parameters
    ----------
    stream : IO[str]
        App-server standard output.
    request_id : int
        Exact request to await.
    deadline : float
        Monotonic absolute timeout.
    buffered : bytearray
        Process-scoped JSONL bytes carried across RPC requests.

    Returns
    -------
    Mapping[str, object]
        Successful JSON-RPC result.
    """
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    try:
        while time.monotonic() < deadline:
            while b"\n" not in buffered:
                if not selector.select(max(0, deadline - time.monotonic())):
                    raise SubscriptionPreflightError(
                        "Codex app-server response timed out"
                    )
                chunk = os.read(stream.fileno(), 65536)
                if not chunk or len(buffered) + len(chunk) > 16 * 1024 * 1024:
                    raise SubscriptionPreflightError(
                        "Codex app-server response is unavailable or oversized"
                    )
                buffered.extend(chunk)
            line, _, rest = buffered.partition(b"\n")
            buffered[:] = rest
            response = json.loads(line)
            if response.get("id") != request_id:
                continue
            if "error" in response or not isinstance(response.get("result"), dict):
                raise SubscriptionPreflightError("Codex app-server request failed")
            return cast("Mapping[str, object]", response["result"])
    finally:
        selector.close()
    raise SubscriptionPreflightError("Codex app-server response timed out")


def _request(
    process: subprocess.Popen[str],
    method: str,
    request_id: int,
    params: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Send one read-only JSON-RPC request to the native app-server.

    Parameters
    ----------
    process : subprocess.Popen[str]
        Fresh app-server child.
    method : str
        Official read-only method name.
    request_id : int
        Unique request identity.
    params : Mapping[str, object] or None
        Method parameters when required.

    Returns
    -------
    Mapping[str, object]
        Authenticated response body.
    """
    assert process.stdin is not None and process.stdout is not None
    message: dict[str, object] = {"method": method, "id": request_id}
    if params is not None:
        message["params"] = dict(params)
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    return _receive(
        process.stdout,
        request_id,
        time.monotonic() + 30,
        _RPC_BUFFERS.setdefault(process, bytearray()),
    )


def _window(raw: object) -> dict[str, object] | None:
    """Retain only public-safe quota window measurements.

    Parameters
    ----------
    raw : object
        Untrusted account rate-limit window.

    Returns
    -------
    dict[str, object] or None
        Sanitized measurements, when present.
    """
    if not isinstance(raw, Mapping):
        return None
    return {
        key: raw[key]
        for key in ("usedPercent", "windowDurationMins", "resetsAt")
        if isinstance(raw.get(key), (int, float)) and not isinstance(raw[key], bool)
    }


def subscription_quota_exhausted(receipt: Mapping[str, object]) -> bool:
    """Recognize exhaustion without guessing which bucket covers a model.

    Parameters
    ----------
    receipt : collections.abc.Mapping[str, object]
        Sanitized native route quota snapshot.

    Returns
    -------
    bool
        True only if every reported bucket is exhausted. An available distinct
        bucket remains admissible; the native provider decides model eligibility.
    """
    buckets = receipt.get("rate_limits")
    if not isinstance(buckets, Mapping) or not buckets:
        return False
    return all(
        isinstance(bucket, Mapping)
        and (
            bucket.get("reached") is True
            or any(
                isinstance(window, Mapping)
                and isinstance(window.get("usedPercent"), (int, float))
                and window["usedPercent"] >= 100
                for window in (bucket.get("primary"), bucket.get("secondary"))
            )
        )
        for bucket in buckets.values()
    )


def preflight_subscription(
    codex: Path,
    model: str,
    effort: str,
    *,
    command: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Verify ChatGPT login, exact model effort, and quota via native Codex.

    Parameters
    ----------
    codex : pathlib.Path
        Exact installed Codex CLI binary.
    model : str
        Native Codex model identity, such as ``gpt-6-luna``.
    effort : str
        Requested reasoning effort.
    command : tuple[str, ...] or None, optional
        Qualified container app-server command for route admission; otherwise
        use the supplied native host binary.

    Returns
    -------
    dict[str, object]
        Public-safe model, plan type and quota windows; no email or tokens.

    Raises
    ------
    SubscriptionPreflightError
        If native authentication, model availability, or quota is unavailable.
    """
    if not codex.is_file() or not model or not effort:
        raise SubscriptionPreflightError("native Codex preflight arguments are invalid")
    with subprocess.Popen(
        command or (str(codex), "--no-daemon", "app-server"),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    ) as process:
        try:
            _request(
                process,
                "initialize",
                0,
                {
                    "clientInfo": {
                        "name": "codira_benchmark",
                        "title": "Codira benchmark",
                        "version": "1.0",
                    }
                },
            )
            assert process.stdin is not None
            process.stdin.write(
                json.dumps({"method": "initialized", "params": {}}) + "\n"
            )
            process.stdin.flush()
            account_result = _request(
                process, "account/read", 1, {"refreshToken": False}
            )
            account = account_result.get("account")
            if not isinstance(account, Mapping) or account.get("type") != "chatgpt":
                raise SubscriptionPreflightError("Codex is not signed in with ChatGPT")
            plan_type = account.get("planType")
            if plan_type not in {
                "plus",
                "pro",
                "team",
                "business",
                "enterprise",
                "edu",
            }:
                raise SubscriptionPreflightError("ChatGPT plan type is not admitted")
            model_result = _request(
                process, "model/list", 2, {"limit": 100, "includeHidden": True}
            )
            models = model_result.get("data")
            if not isinstance(models, list):
                raise SubscriptionPreflightError("Codex model catalog is unavailable")
            selected = next(
                (
                    item
                    for item in models
                    if isinstance(item, Mapping) and item.get("id") == model
                ),
                None,
            )
            if selected is None:
                raise SubscriptionPreflightError(
                    "selected model is unavailable to this ChatGPT account"
                )
            efforts = selected.get("supportedReasoningEfforts")
            if not isinstance(efforts, list) or effort not in {
                item.get("reasoningEffort")
                for item in efforts
                if isinstance(item, Mapping)
            }:
                raise SubscriptionPreflightError(
                    "selected reasoning effort is unavailable"
                )
            limits = _request(process, "account/rateLimits/read", 3)
            buckets = limits.get("rateLimitsByLimitId")
            if not isinstance(buckets, Mapping):
                default = limits.get("rateLimits")
                buckets = {"codex": default} if isinstance(default, Mapping) else {}
            safe_limits = {
                str(bucket_id): {
                    "primary": _window(item.get("primary")),
                    "secondary": _window(item.get("secondary")),
                    "reached": item.get("rateLimitReachedType") is not None,
                }
                for bucket_id, item in buckets.items()
                if isinstance(bucket_id, str) and isinstance(item, Mapping)
            }
            if not safe_limits:
                raise SubscriptionPreflightError("ChatGPT Codex quota is unavailable")
            if subscription_quota_exhausted({"rate_limits": safe_limits}):
                raise SubscriptionQuotaError("ChatGPT Codex quota is exhausted")
            return {
                "route": "codex-subscription",
                "model": model,
                "reasoning_effort": effort,
                "plan_type": plan_type,
                "rate_limits": safe_limits,
                "provider_response_evidence": "native Codex events only; raw provider HTTP responses are unavailable",
                "pricing": "subscription quota; no per-token USD price or campaign dollar cap",
            }
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
