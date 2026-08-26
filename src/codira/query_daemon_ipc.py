"""Authenticated repository-local transport for warm query execution.

Responsibilities
----------------
- Define versioned UTF-8 JSON frames for fixed-root query-daemon clients.
- Authenticate local clients with a repository-local capability secret.
- Dispatch bounded read operations only when a ready index generation is warm.
- Provide Unix-socket and Windows named-pipe transport adapters without pickle.

Design principles
-----------------
The transport never accepts a repository path, indexes files, or stores query
results. Its public endpoint descriptor deliberately excludes the credential.

Architectural role
------------------
This module is the local IPC boundary between a repository-fixed warm runtime
and later MCP or CLI proxies.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import stat
import struct
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock, Thread
from typing import TYPE_CHECKING, Literal, Protocol, cast

from codira.contracts import BackendQueryConnection
from codira.index_generation import IndexGenerationStore

if TYPE_CHECKING:
    from codira.query_daemon import QueryDaemonIdentity


PROTOCOL_VERSION = 2
DEFAULT_REQUEST_LIMIT = 64 * 1024
DEFAULT_RESPONSE_LIMIT = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_QUEUE_LIMIT = 32
DEFAULT_WORKER_COUNT = 4
CAPABILITY_SECRET_BYTES = 32
_FRAME_HEADER = struct.Struct("!I")
_FORBIDDEN_ARGUMENT_KEYS = frozenset({"root", "repository_root", "output_root", "path"})
_PORTABLE_UNIX_SOCKET_PATH_BYTES = 100

TransportKind = Literal["unix", "named_pipe"]
QueryOperation = Callable[
    [dict[str, object], BackendQueryConnection], dict[str, object]
]


class QueryDaemonIpcError(RuntimeError):
    """Base error for rejected local query-daemon IPC operations.

    Parameters
    ----------
    message : str
        Stable operator-facing diagnostic.
    """


class QueryDaemonProtocolError(QueryDaemonIpcError):
    """Report malformed, oversized, or incompatible protocol data.

    Parameters
    ----------
    message : str
        Stable protocol diagnostic.
    """


class QueryDaemonAuthenticationError(QueryDaemonIpcError):
    """Report a missing or invalid repository-local capability secret.

    Parameters
    ----------
    message : str
        Stable authentication diagnostic.
    """


class QueryDaemonUnavailableError(QueryDaemonIpcError):
    """Report a transient runtime or generation state that cannot serve reads.

    Parameters
    ----------
    message : str
        Stable availability diagnostic.
    """


@dataclass(frozen=True)
class QueryDaemonEndpoint:
    """Public endpoint descriptor that deliberately excludes the secret.

    Parameters
    ----------
    protocol_version : int
        IPC contract version supported by the server.
    transport : {"unix", "named_pipe"}
        Local transport selected for this platform.
    address : str
        Socket path or named-pipe address.
    identity : str
        Opaque repository/output identity fixed at startup.
    """

    protocol_version: int
    transport: TransportKind
    address: str
    identity: str


class QueryDaemonIpcPaths:
    """Resolve repository-local IPC endpoint and capability-secret paths.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Fixed repository/output identity that owns the IPC files.
    """

    def __init__(self, identity: QueryDaemonIdentity) -> None:
        """Initialize paths below the fixed effective output directory.

        Parameters
        ----------
        identity : codira.query_daemon.QueryDaemonIdentity
            Fixed repository/output identity that owns the IPC files.

        Returns
        -------
        None
        """
        self.identity = identity
        self.state_dir = identity.output_root / ".codira"

    @property
    def endpoint_path(self) -> Path:
        """Return the public endpoint descriptor path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Repository-local JSON descriptor path.
        """
        return self.state_dir / "query-daemon-endpoint.json"

    @property
    def secret_path(self) -> Path:
        """Return the private repository-local capability secret path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Private binary key path kept separate from the descriptor.
        """
        return self.state_dir / "query-daemon.key"

    @property
    def unix_socket_path(self) -> Path:
        """Return a fixed, portable Unix-domain socket path for this identity.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Repository-local path when its encoded length is portable; otherwise
            a short identity-derived path below ``/tmp``.

        Notes
        -----
        Unix socket path limits are materially shorter than normal filesystem
        limits.  The endpoint descriptor and credential always remain below
        the effective output directory; only the transport address moves when
        a deeply nested repository would otherwise exceed the platform limit.
        """
        repository_local = self.state_dir / "query-daemon.sock"
        if len(os.fsencode(repository_local)) <= _PORTABLE_UNIX_SOCKET_PATH_BYTES:
            return repository_local
        return Path("/tmp") / f"codira-query-{self.identity.value[:32]}.sock"

    @property
    def named_pipe_address(self) -> str:
        """Return the stable Windows named-pipe address for this identity.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Windows-only named-pipe address with no repository path.
        """
        return rf"\\.\pipe\codira-query-{self.identity.value[:24]}"

    def endpoint_for_platform(
        self, *, windows: bool | None = None
    ) -> QueryDaemonEndpoint:
        """Build the expected public endpoint for the current platform.

        Parameters
        ----------
        windows : bool | None, optional
            Explicit platform selector used by adapter contract tests.

        Returns
        -------
        QueryDaemonEndpoint
            Expected endpoint descriptor for the selected transport.
        """
        use_windows = os.name == "nt" if windows is None else windows
        if use_windows:
            return QueryDaemonEndpoint(
                protocol_version=PROTOCOL_VERSION,
                transport="named_pipe",
                address=self.named_pipe_address,
                identity=self.identity.value,
            )
        return QueryDaemonEndpoint(
            protocol_version=PROTOCOL_VERSION,
            transport="unix",
            address=str(self.unix_socket_path),
            identity=self.identity.value,
        )


class _QueryRuntime(Protocol):
    """Warm runtime subset consumed by the transport server.

    Parameters
    ----------
    None
    """

    @property
    def generation(self) -> int | None:
        """Return the active warm generation.

        Parameters
        ----------
        None

        Returns
        -------
        int | None
            Current warm generation when one is installed.
        """
        ...

    def refresh_from_generation_store(self) -> bool:
        """Observe and refresh the durable generation handoff.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            Whether a replacement session was installed.
        """
        ...

    def execute(self, operation: Callable[[BackendQueryConnection], object]) -> object:
        """Execute one read operation against the warm connection.

        Parameters
        ----------
        operation : collections.abc.Callable
            Operation that receives the worker-owned read connection.

        Returns
        -------
        object
            Operation result.
        """
        ...


class _FrameChannel(Protocol):
    """Raw UTF-8 JSON frame channel with no object serialization.

    Parameters
    ----------
    None
    """

    def receive(self) -> dict[str, object]:
        """Receive one decoded JSON object frame.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Decoded JSON object.
        """
        ...

    def send(self, payload: dict[str, object]) -> None:
        """Send one JSON object frame.

        Parameters
        ----------
        payload : dict[str, object]
            JSON-compatible object to send.

        Returns
        -------
        None
        """
        ...

    def close(self) -> None:
        """Close the underlying local transport.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        ...


class _PipeListener(Protocol):
    """Bytes-only Windows pipe-listener subset used by the transport server.

    Parameters
    ----------
    None
    """

    def accept(self) -> object:
        """Accept one named-pipe connection.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Bytes-capable connection object.
        """
        ...


def _json_bytes(payload: dict[str, object], *, limit: int) -> bytes:
    """Encode one bounded JSON object as UTF-8 bytes.

    Parameters
    ----------
    payload : dict[str, object]
        JSON-compatible object to encode.
    limit : int
        Maximum permitted encoded byte count.

    Returns
    -------
    bytes
        Bounded UTF-8 JSON payload.

    Raises
    ------
    QueryDaemonProtocolError
        If serialization fails or the payload exceeds ``limit``.
    """
    try:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as error:
        msg = "IPC payload is not JSON serializable."
        raise QueryDaemonProtocolError(msg) from error
    if len(encoded) > limit:
        msg = f"IPC frame exceeds the {limit}-byte limit."
        raise QueryDaemonProtocolError(msg)
    return encoded


def _json_object(encoded: bytes, *, limit: int) -> dict[str, object]:
    """Decode and validate one bounded UTF-8 JSON object frame.

    Parameters
    ----------
    encoded : bytes
        Raw frame payload.
    limit : int
        Maximum permitted frame size.

    Returns
    -------
    dict[str, object]
        Decoded JSON object.

    Raises
    ------
    QueryDaemonProtocolError
        If the frame is oversized, malformed, or not an object.
    """
    if len(encoded) > limit:
        msg = f"IPC frame exceeds the {limit}-byte limit."
        raise QueryDaemonProtocolError(msg)
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        msg = "IPC frame is not valid UTF-8 JSON."
        raise QueryDaemonProtocolError(msg) from error
    if not isinstance(payload, dict):
        msg = "IPC frame must contain a JSON object."
        raise QueryDaemonProtocolError(msg)
    return cast("dict[str, object]", payload)


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    """Receive exactly one bounded byte sequence from a stream socket.

    Parameters
    ----------
    sock : socket.socket
        Connected Unix-domain socket.
    size : int
        Required byte count.

    Returns
    -------
    bytes
        Exactly ``size`` bytes.

    Raises
    ------
    QueryDaemonProtocolError
        If the peer disconnects before the frame is complete.
    """
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            msg = "IPC peer disconnected during a frame."
            raise QueryDaemonProtocolError(msg)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class UnixFrameChannel:
    """Length-prefixed raw JSON frame channel over one Unix-domain socket.

    Parameters
    ----------
    sock : socket.socket
        Connected Unix-domain stream socket.
    request_limit : int, optional
        Maximum incoming JSON payload size.
    response_limit : int, optional
        Maximum outgoing JSON payload size.
    """

    def __init__(
        self,
        sock: socket.socket,
        *,
        request_limit: int = DEFAULT_REQUEST_LIMIT,
        response_limit: int = DEFAULT_RESPONSE_LIMIT,
    ) -> None:
        """Initialize one bounded Unix socket frame channel.

        Parameters
        ----------
        sock : socket.socket
            Connected Unix-domain stream socket.
        request_limit : int, optional
            Maximum incoming JSON payload size.
        response_limit : int, optional
            Maximum outgoing JSON payload size.

        Returns
        -------
        None
        """
        self._socket = sock
        self._request_limit = request_limit
        self._response_limit = response_limit

    def receive(self) -> dict[str, object]:
        """Receive one length-prefixed UTF-8 JSON object.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Decoded JSON object frame.

        Raises
        ------
        QueryDaemonProtocolError
            If the peer disconnects, the frame is oversized, or JSON is invalid.
        """
        size = _FRAME_HEADER.unpack(_receive_exact(self._socket, _FRAME_HEADER.size))[0]
        if size > self._request_limit:
            msg = f"IPC frame exceeds the {self._request_limit}-byte limit."
            raise QueryDaemonProtocolError(msg)
        return _json_object(
            _receive_exact(self._socket, size), limit=self._request_limit
        )

    def send(self, payload: dict[str, object]) -> None:
        """Send one length-prefixed UTF-8 JSON object.

        Parameters
        ----------
        payload : dict[str, object]
            JSON-compatible response object.

        Returns
        -------
        None
        """
        encoded = _json_bytes(payload, limit=self._response_limit)
        self._socket.sendall(_FRAME_HEADER.pack(len(encoded)) + encoded)

    def close(self) -> None:
        """Close the owned Unix-domain socket.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self._socket.close()


class NamedPipeFrameChannel:
    """Raw JSON bytes channel over ``multiprocessing.connection`` pipes.

    Parameters
    ----------
    connection : object
        Pipe connection exposing only ``send_bytes``, ``recv_bytes``, and
        ``close``. Object-level ``send`` and ``recv`` are intentionally unused.
    request_limit : int, optional
        Maximum incoming JSON payload size.
    response_limit : int, optional
        Maximum outgoing JSON payload size.
    """

    def __init__(
        self,
        connection: object,
        *,
        request_limit: int = DEFAULT_REQUEST_LIMIT,
        response_limit: int = DEFAULT_RESPONSE_LIMIT,
    ) -> None:
        """Initialize a bytes-only named-pipe channel.

        Parameters
        ----------
        connection : object
            Pipe connection exposing bytes-only operations.
        request_limit : int, optional
            Maximum incoming JSON payload size.
        response_limit : int, optional
            Maximum outgoing JSON payload size.

        Returns
        -------
        None
        """
        self._connection = connection
        self._request_limit = request_limit
        self._response_limit = response_limit

    def receive(self) -> dict[str, object]:
        """Receive one bytes-only JSON frame without pickle deserialization.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Decoded JSON object frame.

        Raises
        ------
        QueryDaemonProtocolError
            If bytes-only receive support is absent or the frame is invalid.
        """
        receiver = getattr(self._connection, "recv_bytes", None)
        if not callable(receiver):
            msg = "Named-pipe transport does not provide recv_bytes()."
            raise QueryDaemonProtocolError(msg)
        received = receiver()
        if not isinstance(received, bytes):
            msg = "Named-pipe transport returned a non-bytes frame."
            raise QueryDaemonProtocolError(msg)
        return _json_object(received, limit=self._request_limit)

    def send(self, payload: dict[str, object]) -> None:
        """Send one bytes-only JSON frame without pickle serialization.

        Parameters
        ----------
        payload : dict[str, object]
            JSON-compatible response object.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonProtocolError
            If bytes-only send support is absent or the payload is oversized.
        """
        sender = getattr(self._connection, "send_bytes", None)
        if not callable(sender):
            msg = "Named-pipe transport does not provide send_bytes()."
            raise QueryDaemonProtocolError(msg)
        sender(_json_bytes(payload, limit=self._response_limit))

    def close(self) -> None:
        """Close the owned named-pipe connection.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        closer = getattr(self._connection, "close", None)
        if callable(closer):
            closer()


def ensure_capability_secret(paths: QueryDaemonIpcPaths) -> bytes:
    """Load or create the private capability secret with owner-only mode.

    Parameters
    ----------
    paths : QueryDaemonIpcPaths
        Repository-local endpoint and secret paths.

    Returns
    -------
    bytes
        Fixed-length capability secret.

    Raises
    ------
    QueryDaemonAuthenticationError
        If the existing secret is unreadable or has an invalid length.
    """
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    try:
        secret = paths.secret_path.read_bytes()
    except FileNotFoundError:
        generated = secrets.token_bytes(CAPABILITY_SECRET_BYTES)
        try:
            descriptor = os.open(
                paths.secret_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            secret = paths.secret_path.read_bytes()
        else:
            with os.fdopen(descriptor, "wb") as secret_file:
                secret_file.write(generated)
            secret = generated
    except OSError as error:
        msg = "Unable to read IPC capability secret."
        raise QueryDaemonAuthenticationError(msg) from error
    if len(secret) != CAPABILITY_SECRET_BYTES:
        msg = "IPC capability secret has an invalid length."
        raise QueryDaemonAuthenticationError(msg)
    return secret


def read_capability_secret(paths: QueryDaemonIpcPaths) -> bytes:
    """Read the existing private capability secret without creating one.

    Parameters
    ----------
    paths : QueryDaemonIpcPaths
        Repository-local endpoint and secret paths.

    Returns
    -------
    bytes
        Fixed-length existing capability secret.

    Raises
    ------
    QueryDaemonAuthenticationError
        If the secret is absent, unreadable, or invalid.
    """
    try:
        secret = paths.secret_path.read_bytes()
    except OSError as error:
        msg = "Unable to read IPC capability secret."
        raise QueryDaemonAuthenticationError(msg) from error
    if len(secret) != CAPABILITY_SECRET_BYTES:
        msg = "IPC capability secret has an invalid length."
        raise QueryDaemonAuthenticationError(msg)
    return secret


def read_endpoint(paths: QueryDaemonIpcPaths) -> QueryDaemonEndpoint:
    """Read and validate a public endpoint descriptor for one fixed identity.

    Parameters
    ----------
    paths : QueryDaemonIpcPaths
        Expected repository-local IPC paths.

    Returns
    -------
    QueryDaemonEndpoint
        Valid endpoint descriptor matching the fixed identity.

    Raises
    ------
    QueryDaemonProtocolError
        If the descriptor is absent, malformed, incompatible, or cross-root.
    """
    try:
        payload = json.loads(paths.endpoint_path.read_text(encoding="utf-8"))
        endpoint = QueryDaemonEndpoint(**payload)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        msg = "Unable to read IPC endpoint descriptor."
        raise QueryDaemonProtocolError(msg) from error
    expected = paths.endpoint_for_platform()
    if (
        endpoint.protocol_version != PROTOCOL_VERSION
        or endpoint.identity != paths.identity.value
        or endpoint.transport != expected.transport
        or endpoint.address != expected.address
    ):
        msg = "IPC endpoint descriptor is incompatible with this repository identity."
        raise QueryDaemonProtocolError(msg)
    return endpoint


def _write_endpoint(paths: QueryDaemonIpcPaths, endpoint: QueryDaemonEndpoint) -> None:
    """Atomically write one public endpoint descriptor without credentials.

    Parameters
    ----------
    paths : QueryDaemonIpcPaths
        Repository-local IPC paths.
    endpoint : QueryDaemonEndpoint
        Public descriptor to persist.

    Returns
    -------
    None
    """
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=paths.state_dir,
        prefix=".query-daemon-endpoint.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(asdict(endpoint), temporary, sort_keys=True)
        temporary.write("\n")
    Path(temporary.name).replace(paths.endpoint_path)


def _remove_socket(path: Path) -> None:
    """Remove only a stale Unix-domain socket, never an arbitrary file.

    Parameters
    ----------
    path : pathlib.Path
        Expected Unix-domain socket path.

    Returns
    -------
    None

    Raises
    ------
    QueryDaemonProtocolError
        If an existing path is not a socket.
    """
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(mode):
        msg = f"Refusing to replace non-socket IPC path: {path}"
        raise QueryDaemonProtocolError(msg)
    path.unlink()


def _has_forbidden_argument_key(value: object) -> bool:
    """Return whether a request contains a repository or filesystem path key.

    Parameters
    ----------
    value : object
        Decoded JSON value to inspect recursively.

    Returns
    -------
    bool
        ``True`` when a forbidden arbitrary-path field is present.
    """
    if isinstance(value, dict):
        return any(
            str(key) in _FORBIDDEN_ARGUMENT_KEYS or _has_forbidden_argument_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_forbidden_argument_key(item) for item in value)
    return False


class QueryDaemonIpcServer:
    """Serve authenticated named read operations for one fixed repository identity.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Repository/output identity fixed for the lifetime of the server.
    runtime : _QueryRuntime
        Warm runtime that owns the repository read connection.
    operations : collections.abc.Mapping[str, QueryOperation]
        Explicitly approved read operations keyed by stable protocol name.
    capabilities : collections.abc.Mapping[str, object] | None, optional
        Additional public capability metadata for handshake responses.
    request_limit : int, optional
        Maximum request JSON size.
    response_limit : int, optional
        Maximum response JSON size.
    timeout_seconds : float, optional
        Socket read and write timeout.
    queue_limit : int, optional
        Maximum accepted work waiting behind active handlers.
    worker_count : int, optional
        Maximum simultaneous client handler threads.
    """

    def __init__(  # noqa: PLR0913
        self,
        identity: QueryDaemonIdentity,
        runtime: _QueryRuntime,
        operations: Mapping[str, QueryOperation],
        *,
        capabilities: Mapping[str, object] | None = None,
        request_limit: int = DEFAULT_REQUEST_LIMIT,
        response_limit: int = DEFAULT_RESPONSE_LIMIT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        queue_limit: int = DEFAULT_QUEUE_LIMIT,
        worker_count: int = DEFAULT_WORKER_COUNT,
    ) -> None:
        """Initialize a stopped bounded IPC server.

        Parameters
        ----------
        identity : codira.query_daemon.QueryDaemonIdentity
            Repository/output identity fixed for the lifetime of the server.
        runtime : _QueryRuntime
            Warm runtime that owns the repository read connection.
        operations : collections.abc.Mapping[str, QueryOperation]
            Explicitly approved read operations keyed by protocol name.
        capabilities : collections.abc.Mapping[str, object] | None, optional
            Additional public capability metadata for handshake responses.
        request_limit : int, optional
            Maximum request JSON size.
        response_limit : int, optional
            Maximum response JSON size.
        timeout_seconds : float, optional
            Socket read and write timeout.
        queue_limit : int, optional
            Maximum accepted work waiting behind active handlers.
        worker_count : int, optional
            Maximum simultaneous client handler threads.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If a limit or worker count is not positive.
        """
        if min(request_limit, response_limit, queue_limit, worker_count) <= 0:
            msg = "IPC limits and worker count must be positive."
            raise ValueError(msg)
        if timeout_seconds <= 0:
            msg = "IPC timeout must be positive."
            raise ValueError(msg)
        self.identity = identity
        self.paths = QueryDaemonIpcPaths(identity)
        self._runtime = runtime
        self._operations = dict(operations)
        self._capabilities = dict(capabilities or {})
        self._request_limit = request_limit
        self._response_limit = response_limit
        self._timeout_seconds = timeout_seconds
        self._worker_count = worker_count
        self._capacity = BoundedSemaphore(worker_count + queue_limit)
        self._executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="codira-query-ipc",
        )
        self._stopped = Event()
        self._stopped.set()
        self._listener: socket.socket | object | None = None
        self._accept_thread: Thread | None = None
        self._secret: bytes | None = None
        self._lifecycle_lock = Lock()

    @property
    def endpoint(self) -> QueryDaemonEndpoint:
        """Return the expected public endpoint descriptor.

        Parameters
        ----------
        None

        Returns
        -------
        QueryDaemonEndpoint
            Fixed endpoint descriptor for the current platform.
        """
        return self.paths.endpoint_for_platform()

    def start(self) -> None:
        """Bind the local transport, persist its descriptor, and accept clients.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonIpcError
            If the endpoint cannot be bound safely.
        """
        with self._lifecycle_lock:
            if not self._stopped.is_set():
                msg = "Query daemon IPC server is already running."
                raise QueryDaemonIpcError(msg)
            self._secret = ensure_capability_secret(self.paths)
            self._listener = self._bind_listener()
            _write_endpoint(self.paths, self.endpoint)
            self._stopped.clear()
            self._accept_thread = Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()

    def close(self) -> None:
        """Stop accepting clients and remove only this server's public endpoint.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        with self._lifecycle_lock:
            if self._stopped.is_set():
                return
            self._stopped.set()
            listener, self._listener = self._listener, None
        if listener is not None:
            closer = getattr(listener, "close", None)
            if callable(closer):
                closer()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=self._timeout_seconds + 1)
        self._executor.shutdown(wait=True, cancel_futures=True)
        if self.endpoint.transport == "unix":
            _remove_socket(self.paths.unix_socket_path)
        with suppress(FileNotFoundError):
            self.paths.endpoint_path.unlink()

    def _bind_listener(self) -> socket.socket | object:
        """Bind the current platform's local listener without network exposure.

        Parameters
        ----------
        None

        Returns
        -------
        socket.socket | object
            Unix stream socket or bytes-only Windows pipe listener.
        """
        if self.endpoint.transport == "named_pipe":
            from multiprocessing.connection import Listener

            return Listener(self.endpoint.address, family="AF_PIPE")
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        _remove_socket(self.paths.unix_socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.paths.unix_socket_path))
            self.paths.unix_socket_path.chmod(0o600)
            listener.listen()
            listener.settimeout(0.2)
        except OSError as error:
            listener.close()
            msg = "Unable to bind local IPC socket."
            raise QueryDaemonIpcError(msg) from error
        return listener

    def _accept_loop(self) -> None:
        """Accept bounded client connections until shutdown.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        while not self._stopped.is_set():
            try:
                channel = self._accept_channel()
            except (OSError, EOFError):
                if self._stopped.is_set():
                    return
                continue
            if not self._capacity.acquire(blocking=False):
                self._send_busy_and_close(channel)
                continue
            self._executor.submit(self._serve_channel, channel)

    def _accept_channel(self) -> _FrameChannel:
        """Accept one client and wrap it in the selected raw-frame adapter.

        Parameters
        ----------
        None

        Returns
        -------
        _FrameChannel
            Accepted bounded JSON frame channel.
        """
        listener = self._listener
        if listener is None:
            msg = "IPC listener is closed."
            raise OSError(msg)
        if self.endpoint.transport == "named_pipe":
            connection = cast("_PipeListener", listener).accept()
            return NamedPipeFrameChannel(
                connection,
                request_limit=self._request_limit,
                response_limit=self._response_limit,
            )
        client, _address = cast("socket.socket", listener).accept()
        client.settimeout(self._timeout_seconds)
        return UnixFrameChannel(
            client,
            request_limit=self._request_limit,
            response_limit=self._response_limit,
        )

    def _send_busy_and_close(self, channel: _FrameChannel) -> None:
        """Return a bounded queue-exhaustion response before disconnecting.

        Parameters
        ----------
        channel : _FrameChannel
            Accepted client channel that cannot be scheduled.

        Returns
        -------
        None
        """
        try:
            channel.send(_error_payload("busy", "IPC request queue is full."))
        except (OSError, QueryDaemonProtocolError):
            pass
        finally:
            channel.close()

    def _serve_channel(self, channel: _FrameChannel) -> None:
        """Authenticate and service sequential requests for one client connection.

        Parameters
        ----------
        channel : _FrameChannel
            Accepted raw JSON frame channel.

        Returns
        -------
        None
        """
        try:
            self._handshake(channel)
            while not self._stopped.is_set():
                request = channel.receive()
                response = self._dispatch(request)
                channel.send(response)
        except QueryDaemonAuthenticationError as error:
            self._send_error_and_close(channel, "authentication_failed", str(error))
            return
        except QueryDaemonUnavailableError as error:
            self._send_error_and_close(channel, "unavailable", str(error))
            return
        except QueryDaemonProtocolError as error:
            self._send_error_and_close(channel, "invalid_request", str(error))
            return
        except (EOFError, OSError, TimeoutError):
            return
        finally:
            channel.close()
            self._capacity.release()

    def _send_error_and_close(
        self,
        channel: _FrameChannel,
        code: str,
        message: str,
    ) -> None:
        """Best-effort send one credential-free error before connection closure.

        Parameters
        ----------
        channel : _FrameChannel
            Connected client frame channel.
        code : str
            Stable machine-readable error classifier.
        message : str
            Credential-free diagnostic.

        Returns
        -------
        None
        """
        with suppress(OSError, QueryDaemonProtocolError):
            channel.send(_error_payload(code, message))

    def _handshake(self, channel: _FrameChannel) -> None:
        """Authenticate a client and return identity-bound protocol capabilities.

        Parameters
        ----------
        channel : _FrameChannel
            Connected client frame channel.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonProtocolError
            If the client handshake is malformed or incompatible.
        QueryDaemonAuthenticationError
            If the client secret is invalid.
        """
        request = channel.receive()
        if request.get("type") != "handshake":
            msg = "IPC client must begin with a handshake."
            raise QueryDaemonProtocolError(msg)
        _require_protocol_version(request)
        if request.get("identity") != self.identity.value:
            msg = "IPC client identity does not match this repository."
            raise QueryDaemonProtocolError(msg)
        candidate = request.get("secret")
        if not isinstance(candidate, str) or self._secret is None:
            msg = "IPC client capability secret is invalid."
            raise QueryDaemonAuthenticationError(msg)
        try:
            supplied = bytes.fromhex(candidate)
        except ValueError as error:
            msg = "IPC client capability secret is invalid."
            raise QueryDaemonAuthenticationError(msg) from error
        if not hmac.compare_digest(supplied, self._secret):
            msg = "IPC client capability secret is invalid."
            raise QueryDaemonAuthenticationError(msg)
        generation = self._ready_generation()
        channel.send(
            {
                "type": "handshake_ok",
                "protocol_version": PROTOCOL_VERSION,
                "identity": self.identity.value,
                "generation": generation,
                "capabilities": {
                    "operations": sorted(self._operations),
                    **self._capabilities,
                },
            }
        )

    def _dispatch(self, request: dict[str, object]) -> dict[str, object]:
        """Validate and execute one approved request against the warm runtime.

        Parameters
        ----------
        request : dict[str, object]
            Authenticated JSON request frame.

        Returns
        -------
        dict[str, object]
            Versioned success or stable error response.
        """
        try:
            return self._execute_request(request)
        except QueryDaemonUnavailableError as error:
            return _error_payload("unavailable", str(error), request)
        except QueryDaemonAuthenticationError as error:
            return _error_payload("authentication_failed", str(error), request)
        except QueryDaemonProtocolError as error:
            return _error_payload("invalid_request", str(error), request)
        except Exception:  # noqa: BLE001
            return _error_payload("execution_failed", "IPC operation failed.", request)

    def _execute_request(self, request: dict[str, object]) -> dict[str, object]:
        """Validate and execute one request, raising typed protocol errors.

        Parameters
        ----------
        request : dict[str, object]
            Authenticated JSON request frame.

        Returns
        -------
        dict[str, object]
            Versioned successful response.

        Raises
        ------
        QueryDaemonProtocolError
            If request fields are invalid or the operation is unsupported.
        QueryDaemonUnavailableError
            If no matching ready warm session can serve the request.
        """
        if request.get("type") != "request":
            msg = "IPC frame is not a request."
            raise QueryDaemonProtocolError(msg)
        _require_protocol_version(request)
        request_id = request.get("request_id")
        operation_name = request.get("operation")
        arguments = request.get("arguments", {})
        if not isinstance(request_id, str) or not request_id:
            msg = "IPC request_id must be a non-empty string."
            raise QueryDaemonProtocolError(msg)
        if not isinstance(operation_name, str) or not operation_name:
            msg = "IPC operation must be a non-empty string."
            raise QueryDaemonProtocolError(msg)
        if not isinstance(arguments, dict) or _has_forbidden_argument_key(arguments):
            msg = "IPC request may not contain repository or filesystem paths."
            raise QueryDaemonProtocolError(msg)
        handler = self._operations.get(operation_name)
        if handler is None:
            msg = f"Unsupported IPC operation: {operation_name}."
            raise QueryDaemonProtocolError(msg)
        generation = self._ready_generation()
        result = self._runtime.execute(
            lambda connection: handler(cast("dict[str, object]", arguments), connection)
        )
        if not isinstance(result, dict):
            msg = "IPC operation returned a non-object response."
            raise QueryDaemonProtocolError(msg)
        return {
            "type": "response",
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "generation": generation,
            "result": result,
        }

    def _ready_generation(self) -> int:
        """Require a current ready generation before serving a cached session.

        Parameters
        ----------
        None

        Returns
        -------
        int
            Ready generation represented by the warm runtime.

        Raises
        ------
        QueryDaemonUnavailableError
            If indexing is incomplete, the record is missing, or warmup failed.
        """
        record = IndexGenerationStore(
            self.identity.repository_root,
            output_root=self.identity.output_root,
        ).read()
        if record is None:
            msg = "No durable index generation is available."
            raise QueryDaemonUnavailableError(msg)
        if record.state != "ready":
            msg = (
                "Index generation is updating; warm reads are temporarily unavailable."
            )
            raise QueryDaemonUnavailableError(msg)
        try:
            self._runtime.refresh_from_generation_store()
        except Exception as error:  # noqa: BLE001
            msg = "Warm runtime refresh failed."
            raise QueryDaemonUnavailableError(msg) from error
        if self._runtime.generation != record.generation:
            msg = "Warm runtime does not match the ready index generation."
            raise QueryDaemonUnavailableError(msg)
        return record.generation


class QueryDaemonIpcClient:
    """Connect to one authenticated repository-local query-daemon endpoint.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Expected fixed repository/output identity.
    timeout_seconds : float, optional
        Connection and request timeout.
    request_limit : int, optional
        Maximum outgoing request JSON size.
    response_limit : int, optional
        Maximum incoming response JSON size.
    """

    def __init__(
        self,
        identity: QueryDaemonIdentity,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        request_limit: int = DEFAULT_REQUEST_LIMIT,
        response_limit: int = DEFAULT_RESPONSE_LIMIT,
    ) -> None:
        """Initialize a client bound to one repository/output identity.

        Parameters
        ----------
        identity : codira.query_daemon.QueryDaemonIdentity
            Expected fixed repository/output identity.
        timeout_seconds : float, optional
            Connection and request timeout.
        request_limit : int, optional
            Maximum outgoing request JSON size.
        response_limit : int, optional
            Maximum incoming response JSON size.

        Returns
        -------
        None
        """
        self.identity = identity
        self.paths = QueryDaemonIpcPaths(identity)
        self._timeout_seconds = timeout_seconds
        self._request_limit = request_limit
        self._response_limit = response_limit

    def handshake(self) -> dict[str, object]:
        """Authenticate and return server generation and capabilities.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Validated handshake response.

        Raises
        ------
        QueryDaemonIpcError
            If discovery, authentication, or compatibility validation fails.
        """
        channel = self._connect()
        try:
            self._send_handshake(channel)
            response = channel.receive()
            self._validate_handshake_response(response)
            return response
        finally:
            channel.close()

    def request(
        self,
        operation: str,
        arguments: Mapping[str, object] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, object]:
        """Authenticate then invoke one named read operation.

        Parameters
        ----------
        operation : str
            Explicit approved operation name.
        arguments : collections.abc.Mapping[str, object] | None, optional
            JSON-compatible operation arguments with no path fields.
        request_id : str | None, optional
            Caller-selected opaque request identifier.

        Returns
        -------
        dict[str, object]
            Validated response object from the server.

        Raises
        ------
        QueryDaemonIpcError
            If endpoint discovery, authentication, or request validation fails.
        """
        if not operation:
            msg = "IPC operation must be non-empty."
            raise QueryDaemonProtocolError(msg)
        request_arguments = dict(arguments or {})
        if _has_forbidden_argument_key(request_arguments):
            msg = "IPC request may not contain repository or filesystem paths."
            raise QueryDaemonProtocolError(msg)
        resolved_request_id = request_id or secrets.token_hex(16)
        channel = self._connect()
        try:
            self._send_handshake(channel)
            self._validate_handshake_response(channel.receive())
            channel.send(
                {
                    "type": "request",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": resolved_request_id,
                    "operation": operation,
                    "arguments": request_arguments,
                }
            )
            response = channel.receive()
            if response.get("type") == "error":
                self._raise_server_error(response)
            if (
                response.get("type") != "response"
                or response.get("protocol_version") != PROTOCOL_VERSION
                or response.get("request_id") != resolved_request_id
                or response.get("generation") is None
                or not isinstance(response.get("result"), dict)
            ):
                msg = "IPC server returned an invalid response."
                raise QueryDaemonProtocolError(msg)
            return response
        finally:
            channel.close()

    def _connect(self) -> _FrameChannel:
        """Discover and connect to the fixed local endpoint.

        Parameters
        ----------
        None

        Returns
        -------
        _FrameChannel
            Connected bounded frame channel.

        Raises
        ------
        QueryDaemonIpcError
            If the endpoint cannot be discovered or connected.
        """
        endpoint = read_endpoint(self.paths)
        if endpoint.transport == "named_pipe":
            from multiprocessing.connection import Client

            try:
                connection = Client(endpoint.address, family="AF_PIPE")
            except OSError as error:
                msg = "Unable to connect to local IPC pipe."
                raise QueryDaemonUnavailableError(msg) from error
            return NamedPipeFrameChannel(
                connection,
                request_limit=self._response_limit,
                response_limit=self._request_limit,
            )
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(self._timeout_seconds)
        try:
            client.connect(endpoint.address)
        except OSError as error:
            client.close()
            msg = "Unable to connect to local IPC socket."
            raise QueryDaemonUnavailableError(msg) from error
        return UnixFrameChannel(
            client,
            request_limit=self._response_limit,
            response_limit=self._request_limit,
        )

    def _send_handshake(self, channel: _FrameChannel) -> None:
        """Send one identity-bound authenticated handshake frame.

        Parameters
        ----------
        channel : _FrameChannel
            Connected local frame channel.

        Returns
        -------
        None
        """
        channel.send(
            {
                "type": "handshake",
                "protocol_version": PROTOCOL_VERSION,
                "identity": self.identity.value,
                "secret": read_capability_secret(self.paths).hex(),
            }
        )

    def _validate_handshake_response(self, response: dict[str, object]) -> None:
        """Validate an identity-bound successful handshake response.

        Parameters
        ----------
        response : dict[str, object]
            Decoded server response.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonIpcError
            If the server rejects or cannot prove compatible identity/version.
        """
        if response.get("type") == "error":
            self._raise_server_error(response)
        if (
            response.get("type") != "handshake_ok"
            or response.get("protocol_version") != PROTOCOL_VERSION
            or response.get("identity") != self.identity.value
            or not isinstance(response.get("generation"), int)
            or not isinstance(response.get("capabilities"), dict)
        ):
            msg = "IPC server returned an incompatible handshake response."
            raise QueryDaemonProtocolError(msg)

    def _raise_server_error(self, response: dict[str, object]) -> None:
        """Translate one stable server error response into a typed client error.

        Parameters
        ----------
        response : dict[str, object]
            Error response supplied by the local server.

        Returns
        -------
        None

        Raises
        ------
        QueryDaemonAuthenticationError
            If the server rejected the capability secret.
        QueryDaemonUnavailableError
            If the server is unavailable or its queue is exhausted.
        QueryDaemonProtocolError
            For every other protocol rejection.
        """
        code = response.get("code")
        message = response.get("message")
        resolved_message = (
            message if isinstance(message, str) else "IPC server rejected request."
        )
        if code == "authentication_failed":
            raise QueryDaemonAuthenticationError(resolved_message)
        if code in {"unavailable", "busy"}:
            raise QueryDaemonUnavailableError(resolved_message)
        raise QueryDaemonProtocolError(resolved_message)


def _require_protocol_version(payload: dict[str, object]) -> None:
    """Require exactly the supported protocol version on a client frame.

    Parameters
    ----------
    payload : dict[str, object]
        Decoded request or handshake frame.

    Returns
    -------
    None

    Raises
    ------
    QueryDaemonProtocolError
        If the protocol version is absent or incompatible.
    """
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        msg = f"Unsupported IPC protocol version; expected {PROTOCOL_VERSION}."
        raise QueryDaemonProtocolError(msg)


def _error_payload(
    code: str,
    message: str,
    request: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one bounded credential-free protocol error response.

    Parameters
    ----------
    code : str
        Stable machine-readable error classifier.
    message : str
        Credential-free human-readable diagnostic.
    request : collections.abc.Mapping[str, object] | None, optional
        Request used only to echo a valid opaque request identifier.

    Returns
    -------
    dict[str, object]
        Versioned error response.
    """
    request_id = None if request is None else request.get("request_id")
    return {
        "type": "error",
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id if isinstance(request_id, str) else None,
        "code": code,
        "message": message,
    }
