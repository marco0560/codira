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
import hmac
import http.client
import json
import os
import socket
import sys
from dataclasses import dataclass
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

    Returns
    -------
    None
        Instances carry validated settings without rendering secret values.
    """

    client_token: str
    upstream_token: str
    port: int
    max_output_tokens: int = 12000


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


def constrain_response_request(payload: bytes, max_output_tokens: int) -> bytes:
    """Cap one Responses request without exposing or persisting its content.

    Parameters
    ----------
    payload : bytes
        JSON request body received from the local Codex client.
    max_output_tokens : int
        Approved ceiling to apply to the request's output allowance.

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
        """Authorize and relay one supported request without persisting data.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The upstream status, headers, and body are streamed to the client.
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
        if path == "/v1/responses" and self.command == "POST":
            try:
                payload = constrain_response_request(
                    payload, self.settings.max_output_tokens
                )
            except (TypeError, ValueError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
        request_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {"authorization", "connection", "content-length", "host"}
        }
        request_headers["Authorization"] = f"Bearer {self.settings.upstream_token}"
        request_headers["Content-Length"] = str(len(payload))
        connection = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=300)
        try:
            connection.request(self.command, provider_path, payload, request_headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {
                    "connection",
                    "content-length",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while chunk := response.read(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:
            self.send_error(HTTPStatus.BAD_GATEWAY)
        finally:
            connection.close()
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
