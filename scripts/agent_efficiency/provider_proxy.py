#!/usr/bin/env python3
"""Run a loopback-only, credential-separating OpenRouter Responses proxy.

Responsibilities
----------------
- Accept Codex requests only with a runner-generated proxy token.
- Replace that token with the OpenRouter credential outside the agent.
- Forward only the Responses API endpoints needed by the benchmark runner.

Design principles
-----------------
The proxy never logs credentials or request bodies. It binds only to loopback,
and it rejects every endpoint except the explicit Responses API allowlist.

Architectural role
------------------
This module is the runner-side authentication boundary for issue #53 Phase 0.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

UPSTREAM_HOST = "openrouter.ai"
UPSTREAM_PATH_PREFIX = "/api/v1"
ALLOWED_PATHS = frozenset({"/v1/responses", "/v1/models"})
PROXY_CLIENT_TOKEN_ENV = "CODIRA_PROXY_CLIENT_TOKEN"
UPSTREAM_TOKEN_ENV = "OPENROUTER_API_KEY"


@dataclass(frozen=True)
class ResponseConstraints:
    """Define the immutable provider controls for one benchmark response.

    Parameters
    ----------
    expected_model : str or None, optional
        Exact model identity admitted for a bounded benchmark execution.
    expected_reasoning_effort : str or None, optional
        Exact reasoning effort admitted for a bounded benchmark execution.
    max_prompt_usd_per_million : float or None, optional
        Maximum admitted OpenRouter prompt price in USD per million tokens.
    max_completion_usd_per_million : float or None, optional
        Maximum admitted OpenRouter completion price in USD per million tokens.
    """

    expected_model: str | None = None
    expected_reasoning_effort: str | None = None
    max_prompt_usd_per_million: float | None = None
    max_completion_usd_per_million: float | None = None


@dataclass
class ResponseRequestLimiter:
    """Admit at most a fixed number of Responses requests for one attempt.

    Parameters
    ----------
    maximum : int
        Positive request count permitted by the frozen campaign manifest.

    Returns
    -------
    None
        Instances retain only an in-memory counter for one proxy server.
    """

    maximum: int
    count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def admit(self) -> bool:
        """Consume one request slot if the immutable ceiling permits it.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``True`` for an admitted request and ``False`` after exhaustion.
        """

        with self._lock:
            if self.maximum < 1 or self.count >= self.maximum:
                return False
            self.count += 1
            return True


@dataclass(frozen=True)
class ProxySettings:
    """Contain the non-logged runtime settings for one proxy process.

    Parameters
    ----------
    client_token : str
        Token required from the locally running Codex client.
    upstream_token : str
        OpenRouter credential used only by the proxy's outbound connection.
    port : int
        Loopback TCP port on which the proxy listens.
    max_output_tokens : int
        Maximum output-token allowance applied to every Responses request.
    constraints : ResponseConstraints, optional
        Immutable model, reasoning, and price constraints for one request.

    Returns
    -------
    None
        Instances carry validated settings without rendering secret values.
    """

    client_token: str
    upstream_token: str
    port: int
    max_output_tokens: int = 12000
    constraints: ResponseConstraints = ResponseConstraints()
    max_response_requests: int = 1
    max_transport_attempts_per_response: int = 1
    max_total_tokens: int | None = None
    max_context_tokens: int | None = None
    max_prompt_usd_per_million: float | None = None
    max_completion_usd_per_million: float | None = None
    max_attempt_spend_usd: float | None = None
    response_artifact_root: Path | None = None
    limiter: ResponseRequestLimiter = field(init=False, repr=False)
    response_observations: list[dict[str, object]] = field(
        default_factory=list, repr=False
    )
    observation_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    response_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    provider_total_tokens: int = 0
    provider_estimated_cost_usd: float = 0.0
    token_accounting_failed: bool = False

    def __post_init__(self) -> None:
        """Create the private per-server request counter.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Invalid zero request ceilings fail immediately.
        """

        if (
            self.max_response_requests < 1
            or self.max_transport_attempts_per_response < 1
            or (self.max_total_tokens is not None and self.max_total_tokens < 1)
            or (self.max_context_tokens is not None and self.max_context_tokens < 1)
            or (
                self.max_prompt_usd_per_million is not None
                and self.max_prompt_usd_per_million <= 0
            )
            or (
                self.max_completion_usd_per_million is not None
                and self.max_completion_usd_per_million <= 0
            )
            or (
                self.max_attempt_spend_usd is not None
                and self.max_attempt_spend_usd <= 0
            )
        ):
            message = "proxy max response requests must be positive"
            raise ValueError(message)
        object.__setattr__(
            self, "limiter", ResponseRequestLimiter(self.max_response_requests)
        )
        if self.response_artifact_root is not None:
            if not self.response_artifact_root.is_absolute():
                message = "proxy response artifact root must be absolute"
                raise ValueError(message)
            try:
                self.response_artifact_root.mkdir(mode=0o700)
            except OSError as error:
                message = "proxy response artifact root must be fresh"
                raise ValueError(message) from error

    def record_response(
        self,
        status: int,
        headers: list[tuple[str, str]],
        source: str = "upstream",
        body: bytes | None = None,
        reason: str | None = None,
    ) -> None:
        """Persist an exact upstream body and append public-safe metadata.

        Parameters
        ----------
        status : int
            Upstream HTTP status code.
        headers : list[tuple[str, str]]
            Upstream headers from which only ``Retry-After`` is retained.
        source : str, optional
            ``"upstream"`` for provider traffic or ``"local"`` for a proxy cap.
        body : bytes or None, optional
            Exact received upstream response body. Paid runners supply it so
            evidence is durable before the body reaches semantic consumers.
        reason : str or None, optional
            Stable reason for a local admission rejection; never provider data.

        Returns
        -------
        None
            The in-memory evidence ledger receives one sanitized observation.

        Raises
        ------
        ValueError
            If an upstream body has no configured private artifact root.
        OSError
            If exact response evidence cannot be persisted durably.
        """

        retry_after = next(
            (value for key, value in headers if key.lower() == "retry-after"), None
        )
        observed_at = datetime.now(UTC).isoformat()
        with self.observation_lock:
            observation: dict[str, object] = {
                "observed_at": observed_at,
                "status": status,
                "source": source,
            }
            if retry_after is not None:
                observation["retry_after"] = retry_after
            if source == "local" and reason is not None:
                observation["reason"] = reason
            if body is not None and source == "upstream":
                if self.response_artifact_root is None:
                    message = "upstream response artifact root is unavailable"
                    raise ValueError(message)
                index = len(self.response_observations) + 1
                stem = f"response-{index:03d}"
                body_path = self.response_artifact_root / f"{stem}.body"
                metadata_path = self.response_artifact_root / f"{stem}.json"
                digest = hashlib.sha256(body).hexdigest()
                self._atomic_bytes(body_path, body)
                usage = _provider_usage(body)
                self._atomic_bytes(
                    metadata_path,
                    (
                        json.dumps(
                            {
                                "body_sha256": digest,
                                "body_size_bytes": len(body),
                                "headers": headers,
                                "observed_at": observed_at,
                                "source": source,
                                "status": status,
                            },
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n"
                    ).encode("utf-8"),
                )
                observation.update(
                    {
                        "response_artifact": body_path.name,
                        "response_sha256": digest,
                        "response_size_bytes": len(body),
                    }
                )
                if usage is not None:
                    observation["provider_usage"] = usage
                    object.__setattr__(
                        self,
                        "provider_total_tokens",
                        self.provider_total_tokens + int(usage["total_tokens"]),
                    )
                    if (
                        self.max_prompt_usd_per_million is not None
                        and self.max_completion_usd_per_million is not None
                    ):
                        estimated_cost = (
                            usage["input_tokens"] * self.max_prompt_usd_per_million
                            + usage["output_tokens"]
                            * self.max_completion_usd_per_million
                        ) / 1_000_000
                        object.__setattr__(
                            self,
                            "provider_estimated_cost_usd",
                            self.provider_estimated_cost_usd + estimated_cost,
                        )
                        observation["estimated_cost_usd_at_ceiling"] = round(
                            estimated_cost, 8
                        )
                    if (
                        self.max_context_tokens is not None
                        and int(usage["total_tokens"]) > self.max_context_tokens
                    ) or int(usage["output_tokens"]) > self.max_output_tokens:
                        object.__setattr__(self, "token_accounting_failed", True)
                        observation["usage_exceeded_frozen_response_limits"] = True
                elif 200 <= status < 300 or status in {
                    HTTPStatus.BAD_GATEWAY,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    HTTPStatus.GATEWAY_TIMEOUT,
                }:
                    # Preserve exact bytes when available, then fail closed:
                    # successful or transport-uncertain responses without
                    # usage cannot be admitted against the session ceiling.
                    object.__setattr__(self, "token_accounting_failed", True)
            self.response_observations.append(observation)
            if (
                body is None
                and source == "upstream"
                and status
                in {
                    HTTPStatus.BAD_GATEWAY,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    HTTPStatus.GATEWAY_TIMEOUT,
                }
            ):
                object.__setattr__(self, "token_accounting_failed", True)

    def local_token_cap_reason(self) -> str | None:
        """Return why another completion cannot be admitted, if applicable.

        Parameters
        ----------
        None

        Returns
        -------
        str or None
            Stable public-safe reason for stopping further upstream requests.
        """

        if self.token_accounting_failed:
            return "provider_usage_unavailable"
        if (
            self.max_total_tokens is not None
            and self.provider_total_tokens >= self.max_total_tokens
        ):
            return "session_token_budget_exhausted"
        if (
            self.max_attempt_spend_usd is not None
            and self.provider_estimated_cost_usd >= self.max_attempt_spend_usd
        ):
            return "attempt_spend_budget_exhausted"
        if (
            self.max_total_tokens is not None
            and self.max_context_tokens is not None
            and self.max_prompt_usd_per_million is not None
            and self.max_completion_usd_per_million is not None
            and self.max_attempt_spend_usd is not None
        ):
            remaining_token_spend = (
                max(0, self.max_total_tokens - self.provider_total_tokens)
                * max(
                    self.max_prompt_usd_per_million,
                    self.max_completion_usd_per_million,
                )
                / 1_000_000
            )
            one_response_spend = (
                self.max_context_tokens * self.max_prompt_usd_per_million
                + self.max_output_tokens * self.max_completion_usd_per_million
            ) / 1_000_000
            if (
                self.provider_estimated_cost_usd
                + remaining_token_spend
                + one_response_spend
                > self.max_attempt_spend_usd
            ):
                return "attempt_spend_cap_reservation_exceeded"
        return None

    @staticmethod
    def _atomic_bytes(path: Path, content: bytes) -> None:
        """Write one absent response artifact atomically and durably.

        Parameters
        ----------
        path : pathlib.Path
            Absent ignored artifact path beneath the per-attempt directory.
        content : bytes
            Exact bytes to persist without interpretation.

        Raises
        ------
        OSError
            If the response evidence cannot be persisted without overwrite.
        """

        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()


def parse_settings(
    environment: dict[str, str], port: int, max_output_tokens: int = 12000
) -> ProxySettings:
    """Validate secret-bearing proxy settings without exposing their values.

    Parameters
    ----------
    environment : dict[str, str]
        Environment supplied only to the runner-side proxy process.
    port : int
        Requested loopback TCP port.
    max_output_tokens : int, optional
        Approved ceiling for each proxied Responses request.

    Returns
    -------
    ProxySettings
        Validated proxy process settings.

    Raises
    ------
    ValueError
        If either required token is absent or the port is out of range.
    """

    client_token = environment.get(PROXY_CLIENT_TOKEN_ENV, "")
    upstream_token = environment.get(UPSTREAM_TOKEN_ENV, "")
    if not client_token or not upstream_token:
        message = "proxy client and upstream credentials are both required"
        raise ValueError(message)
    if not 1 <= port <= 65535:
        message = "proxy port must be between 1 and 65535"
        raise ValueError(message)
    if max_output_tokens < 1:
        message = "proxy max output tokens must be positive"
        raise ValueError(message)
    return ProxySettings(client_token, upstream_token, port, max_output_tokens)


def _provider_usage(body: bytes) -> dict[str, int] | None:
    """Extract one terminal OpenAI Responses usage record from JSON or SSE.

    Parameters
    ----------
    body : bytes
        Exact provider response already persisted by the caller.

    Returns
    -------
    dict[str, int] or None
        Input, output, and total token counts from a terminal usage object.
    """

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    documents: list[object] = []
    try:
        documents.append(json.loads(text))
    except json.JSONDecodeError:
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                documents.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
    for document in reversed(documents):
        if not isinstance(document, Mapping):
            continue
        if document.get("type") == "response.completed":
            response = document.get("response")
            document = response if isinstance(response, Mapping) else document
        usage = document.get("usage")
        if not isinstance(usage, Mapping):
            continue
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if (
            isinstance(input_tokens, int)
            and not isinstance(input_tokens, bool)
            and input_tokens >= 0
            and isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and output_tokens >= 0
            and isinstance(total_tokens, int)
            and not isinstance(total_tokens, bool)
            and total_tokens == input_tokens + output_tokens
        ):
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
    return None


def is_authorized(authorization: str | None, client_token: str) -> bool:
    """Compare one bearer credential without timing-sensitive string equality.

    Parameters
    ----------
    authorization : str or None
        Authorization header received from the local Codex client.
    client_token : str
        Expected runner-generated proxy token.

    Returns
    -------
    bool
        ``True`` only for the exact expected bearer token.
    """

    prefix = "Bearer "
    if authorization is None or not authorization.startswith(prefix):
        return False
    return hmac.compare_digest(authorization.removeprefix(prefix), client_token)


def upstream_path(request_path: str) -> str:
    """Build the OpenRouter target for one allowlisted local request.

    Parameters
    ----------
    request_path : str
        Request target received by the loopback proxy, including an optional
        query string.

    Returns
    -------
    str
        Equivalent OpenRouter target beneath ``/api/v1``.

    Raises
    ------
    ValueError
        If the request path is not in the constrained local allowlist.
    """

    path = request_path.split("?", maxsplit=1)[0]
    if path not in ALLOWED_PATHS:
        message = "request path is not allowlisted"
        raise ValueError(message)
    return f"{UPSTREAM_PATH_PREFIX}{request_path.removeprefix('/v1')}"


def constrain_response_request(
    payload: bytes,
    max_output_tokens: int,
    constraints: ResponseConstraints = ResponseConstraints(),
) -> bytes:
    """Cap one Responses request without exposing or persisting its content.

    Parameters
    ----------
    payload : bytes
        JSON request body received from the local Codex client.
    max_output_tokens : int
        Approved ceiling to apply to the request's output allowance.
    constraints : ResponseConstraints, optional
        Immutable model, reasoning, and price limits for a bounded pilot.

    Returns
    -------
    bytes
        Compact JSON body with a bounded ``max_output_tokens`` field.

    Raises
    ------
    ValueError
        If the request body is malformed or the ceiling is invalid.
    TypeError
        If the request body or output allowance has the wrong JSON type.
    """

    if max_output_tokens < 1:
        message = "proxy max output tokens must be positive"
        raise ValueError(message)
    try:
        request = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        message = "Responses request must be valid JSON"
        raise ValueError(message) from error
    if not isinstance(request, dict):
        message = "Responses request must be a JSON object"
        raise TypeError(message)
    requested = request.get("max_output_tokens", max_output_tokens)
    if not isinstance(requested, int) or isinstance(requested, bool):
        message = "Responses max_output_tokens must be an integer"
        raise TypeError(message)
    if (
        constraints.expected_model is not None
        and request.get("model") != constraints.expected_model
    ):
        message = "Responses request model does not match the approved model"
        raise ValueError(message)
    if constraints.expected_reasoning_effort is not None:
        reasoning = request.get("reasoning")
        if (
            not isinstance(reasoning, Mapping)
            or reasoning.get("effort") != constraints.expected_reasoning_effort
        ):
            message = "Responses reasoning effort does not match the approved effort"
            raise ValueError(message)
    if (constraints.max_prompt_usd_per_million is None) != (
        constraints.max_completion_usd_per_million is None
    ):
        message = "Responses provider price ceilings must be supplied together"
        raise ValueError(message)
    if constraints.max_prompt_usd_per_million is not None:
        if (
            constraints.max_prompt_usd_per_million <= 0
            or constraints.max_completion_usd_per_million is None
            or constraints.max_completion_usd_per_million <= 0
        ):
            message = "Responses provider price ceilings must be positive"
            raise ValueError(message)
        request["provider"] = {
            "allow_fallbacks": False,
            "max_price": {
                "prompt": constraints.max_prompt_usd_per_million,
                "completion": constraints.max_completion_usd_per_million,
            },
        }
    request["max_output_tokens"] = min(requested, max_output_tokens)
    return json.dumps(request, separators=(",", ":")).encode("utf-8")


def create_server(settings: ProxySettings) -> ThreadingHTTPServer:
    """Create a loopback server configured with one validated proxy identity.

    Parameters
    ----------
    settings : ProxySettings
        Validated client credential, provider credential, and requested port.

    Returns
    -------
    http.server.ThreadingHTTPServer
        Unstarted loopback server using the constrained proxy handler.
    """

    return ThreadingHTTPServer(("127.0.0.1", settings.port), _handler_type(settings))


class ThreadingUnixHTTPServer(ThreadingHTTPServer):
    """Serve the constrained HTTP proxy over one runner-owned Unix socket."""

    address_family = socket.AF_UNIX
    allow_reuse_address = False


def create_unix_server(
    settings: ProxySettings, socket_path: str
) -> ThreadingHTTPServer:
    """Create a credential-separating proxy without a host TCP listener.

    Parameters
    ----------
    settings : ProxySettings
        Validated runner-only credentials and request ceiling.
    socket_path : str
        Absent Unix-domain socket owned by the disposable runner state.

    Returns
    -------
    http.server.ThreadingHTTPServer
        Unstarted proxy reachable only through the mounted socket capability.

    Raises
    ------
    ValueError
        If the requested socket path already exists.
    """

    if Path(socket_path).exists():
        message = "provider proxy socket path must be absent"
        raise ValueError(message)
    server = ThreadingUnixHTTPServer(
        socket_path,  # type: ignore[arg-type]
        _handler_type(settings),
    )
    Path(socket_path).chmod(0o600)
    return server


class ProviderProxyHandler(BaseHTTPRequestHandler):
    """Forward an allowlisted local request with server-side provider auth.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Handler instances are constructed by ``ThreadingHTTPServer``.
    """

    protocol_version = "HTTP/1.1"
    settings: ClassVar[ProxySettings]

    def do_GET(self) -> None:
        """Forward an allowlisted GET request.

        Parameters
        ----------
        None

        Returns
        -------
        None
            A response is written to the local client.
        """

        self._forward()

    def do_POST(self) -> None:
        """Forward an allowlisted POST request.

        Parameters
        ----------
        None

        Returns
        -------
        None
            A response is written to the local client.
        """

        self._forward()

    def do_PUT(self) -> None:
        """Reject unsupported request methods.

        Parameters
        ----------
        None

        Returns
        -------
        None
            A method-not-allowed response is written to the local client.
        """

        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_DELETE(self) -> None:
        """Reject unsupported request methods.

        Parameters
        ----------
        None

        Returns
        -------
        None
            A method-not-allowed response is written to the local client.
        """

        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress request logging that could include sensitive metadata.

        Parameters
        ----------
        format : str
            Unused base-handler format string.
        *args : object
            Unused base-handler formatting arguments.

        Returns
        -------
        None
            No request data is emitted.
        """

        del format, args

    def _forward(self) -> None:
        """Authorize, persist, and relay one supported provider response.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Exact upstream bytes are persisted before reaching the client.
        """

        path = self.path.split("?", maxsplit=1)[0]
        try:
            provider_path = upstream_path(self.path)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not is_authorized(
            self.headers.get("Authorization"), self.settings.client_token
        ):
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        payload = self.rfile.read(content_length)
        response_request = path == "/v1/responses" and self.command == "POST"
        if response_request:
            try:
                payload = constrain_response_request(
                    payload,
                    self.settings.max_output_tokens,
                    self.settings.constraints,
                )
            except (TypeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            self.settings.response_lock.acquire()
            if not self.settings.limiter.admit():
                self.settings.record_response(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    [],
                    source="local",
                    reason="response_request_limit_exceeded",
                )
                self.settings.response_lock.release()
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS)
                return
            token_cap_reason = self.settings.local_token_cap_reason()
            if token_cap_reason is not None:
                self.settings.record_response(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    [],
                    source="local",
                    reason=token_cap_reason,
                )
                self.settings.response_lock.release()
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS)
                return
        request_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {"authorization", "connection", "content-length", "host"}
        }
        request_headers["Authorization"] = f"Bearer {self.settings.upstream_token}"
        request_headers["Content-Length"] = str(len(payload))
        try:
            response = None
            response_body = b""
            response_headers: list[tuple[str, str]] = []
            for transport_attempt in range(
                self.settings.max_transport_attempts_per_response
            ):
                connection = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=300)
                connection.request(
                    self.command, provider_path, payload, request_headers
                )
                response = connection.getresponse()
                response_headers = response.getheaders()
                response_body = response.read()
                self.settings.record_response(
                    response.status, response_headers, body=response_body
                )
                if (
                    response.status
                    not in {
                        HTTPStatus.TOO_MANY_REQUESTS,
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    }
                    or transport_attempt + 1
                    == self.settings.max_transport_attempts_per_response
                ):
                    break
                retry_after = next(
                    (
                        value
                        for key, value in response_headers
                        if key.lower() == "retry-after"
                    ),
                    None,
                )
                connection.close()
                time.sleep(
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else 1.0 * (2**transport_attempt)
                )
            assert response is not None
            self.send_response(response.status, response.reason)
            for key, value in response_headers:
                if key.lower() not in {
                    "connection",
                    "content-length",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response_body)
            self.wfile.flush()
        except OSError:
            self.settings.record_response(HTTPStatus.BAD_GATEWAY, [])
            self.send_error(HTTPStatus.BAD_GATEWAY)
        finally:
            connection.close()
            if response_request:
                self.settings.response_lock.release()
            self.close_connection = True


def _handler_type(settings: ProxySettings) -> type[ProviderProxyHandler]:
    """Bind one immutable settings object to an isolated handler class.

    Parameters
    ----------
    settings : ProxySettings
        Credentials and request limits for exactly one listening server.

    Returns
    -------
    type[ProviderProxyHandler]
        A fresh subclass, preventing concurrent proxy servers from sharing
        mutable class-level configuration.
    """

    return type(
        "ConfiguredProviderProxyHandler",
        (ProviderProxyHandler,),
        {"settings": settings},
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the loopback provider-proxy command-line parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for the proxy's non-secret listening settings.
    """

    parser = argparse.ArgumentParser(
        description="Run a loopback-only Responses API credential boundary."
    )
    parser.add_argument("--port", type=int, required=True, help="Loopback port.")
    return parser


def main(arguments: list[str] | None = None) -> int:
    """Run the loopback-only provider proxy until terminated by its runner.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command arguments excluding the program name.

    Returns
    -------
    int
        Zero after normal server shutdown.
    """

    args = build_parser().parse_args(arguments)
    try:
        settings = parse_settings(dict(os.environ), args.port)
    except ValueError as error:
        print(f"provider proxy configuration error: {error}", file=sys.stderr)
        return 2
    server = create_server(settings)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
