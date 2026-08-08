"""Contract tests for authenticated repository-local warm-query IPC."""

from __future__ import annotations

import json
import multiprocessing
import os
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from codira.index_generation import IndexGenerationStore, transition_record
from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_ipc import (
    DEFAULT_REQUEST_LIMIT,
    PROTOCOL_VERSION,
    NamedPipeFrameChannel,
    QueryDaemonIpcClient,
    QueryDaemonIpcPaths,
    QueryDaemonIpcServer,
    QueryDaemonUnavailableError,
    UnixFrameChannel,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from codira.contracts import BackendQueryConnection


class _FakeRuntime:
    """Minimal ready runtime used to exercise transport boundaries.

    Parameters
    ----------
    generation : int
        Ready generation represented by this fake runtime.
    """

    def __init__(self, generation: int = 1) -> None:
        """Initialize a fake runtime with one opaque connection.

        Parameters
        ----------
        generation : int, optional
            Ready generation represented by this fake runtime.

        Returns
        -------
        None
        """
        self.generation = generation
        self.refreshes = 0
        self.connection = object()

    def refresh_from_generation_store(self) -> bool:
        """Record one durable-generation observation without replacement.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            ``False`` because the fake session is already current.
        """
        self.refreshes += 1
        return False

    def execute(self, operation: Callable[[BackendQueryConnection], object]) -> object:
        """Execute one operation against the stable opaque connection.

        Parameters
        ----------
        operation : collections.abc.Callable
            Test operation receiving the fake connection.

        Returns
        -------
        object
            Value returned by the supplied operation.
        """
        return operation(cast("BackendQueryConnection", self.connection))


def _echo_operation(
    arguments: dict[str, object], connection: object
) -> dict[str, object]:
    """Return test arguments while proving runtime connection dispatch occurred.

    Parameters
    ----------
    arguments : dict[str, object]
        JSON-compatible request arguments.
    connection : object
        Opaque connection supplied by the fake runtime.

    Returns
    -------
    dict[str, object]
        Deterministic test operation payload.
    """
    return {"arguments": arguments, "connection_owned": connection is not None}


def _publish_ready_generation(
    identity: QueryDaemonIdentity, generation: int = 1
) -> None:
    """Publish one ready generation for an IPC server test.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Test repository/output identity.
    generation : int, optional
        Ready generation represented by the fake runtime.

    Returns
    -------
    None
    """
    IndexGenerationStore(
        identity.repository_root, output_root=identity.output_root
    ).write(
        transition_record(
            generation=generation,
            state="ready",
            last_successful_generation=generation,
        )
    )


def _server_for(identity: QueryDaemonIdentity) -> QueryDaemonIpcServer:
    """Build a test server with one approved echo operation.

    Parameters
    ----------
    identity : codira.query_daemon.QueryDaemonIdentity
        Test repository/output identity.

    Returns
    -------
    codira.query_daemon_ipc.QueryDaemonIpcServer
        Stopped test server ready to start.
    """
    _publish_ready_generation(identity)
    return QueryDaemonIpcServer(
        identity,
        _FakeRuntime(),
        {"echo": _echo_operation},
        capabilities={"read_only": True},
    )


def _subprocess_server(
    repository_root: str,
    output_root: str,
    ready: multiprocessing.queues.Queue[bool],
    stop: multiprocessing.synchronize.Event,
) -> None:
    """Run one real child-process Unix IPC server until the parent releases it.

    Parameters
    ----------
    repository_root : str
        Repository root selected by the parent process.
    output_root : str
        Effective output directory selected by the parent process.
    ready : multiprocessing.queues.Queue[bool]
        Queue used to signal successful endpoint binding.
    stop : multiprocessing.synchronize.Event
        Parent-controlled shutdown event.

    Returns
    -------
    None
    """
    identity = QueryDaemonIdentity.from_paths(Path(repository_root), Path(output_root))
    server = _server_for(identity)
    server.start()
    ready.put(True)
    stop.wait(10)
    server.close()


def _raw_channel(paths: QueryDaemonIpcPaths) -> UnixFrameChannel:
    """Connect a raw Unix test channel to one already-started local server.

    Parameters
    ----------
    paths : codira.query_daemon_ipc.QueryDaemonIpcPaths
        Repository-local IPC paths.

    Returns
    -------
    codira.query_daemon_ipc.UnixFrameChannel
        Connected raw frame channel.
    """
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2)
    client.connect(str(paths.unix_socket_path))
    return UnixFrameChannel(client)


def _handshake(
    channel: UnixFrameChannel, identity: QueryDaemonIdentity, secret: bytes
) -> None:
    """Perform a valid raw handshake for frame-level protocol tests.

    Parameters
    ----------
    channel : codira.query_daemon_ipc.UnixFrameChannel
        Connected raw Unix frame channel.
    identity : codira.query_daemon.QueryDaemonIdentity
        Identity expected by the server.
    secret : bytes
        Capability secret read from the private key file.

    Returns
    -------
    None
    """
    channel.send(
        {
            "type": "handshake",
            "protocol_version": PROTOCOL_VERSION,
            "identity": identity.value,
            "secret": secret.hex(),
        }
    )
    assert channel.receive()["type"] == "handshake_ok"


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_subprocess_server_and_client_handshake_share_one_identity(
    tmp_path: Path,
) -> None:
    """Authenticate a real child-process server using only local descriptors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts a child process and client share one fixed identity.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    stop = context.Event()
    process = context.Process(
        target=_subprocess_server,
        args=(str(identity.repository_root), str(identity.output_root), ready, stop),
    )
    process.start()
    try:
        assert ready.get(timeout=10) is True
        client = QueryDaemonIpcClient(identity)
        handshake = client.handshake()
        response = client.request("echo", {"value": "hello"}, request_id="child")
    finally:
        stop.set()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=10)

    assert process.exitcode == 0
    assert handshake["identity"] == identity.value
    assert handshake["generation"] == 1
    assert handshake["capabilities"] == {"operations": ["echo"], "read_only": True}
    assert response["result"] == {
        "arguments": {"value": "hello"},
        "connection_owned": True,
    }


def test_concurrent_clients_share_one_fixed_root_daemon(tmp_path: Path) -> None:
    """Serve concurrent clients without cross-request identity contamination.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts every client receives the same ready generation.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    try:

        def request(sequence: int) -> dict[str, object]:
            """Issue one authenticated request from an independent client.

            Parameters
            ----------
            sequence : int
                Deterministic client request ordinal.

            Returns
            -------
            dict[str, object]
                Validated local IPC response.
            """
            return QueryDaemonIpcClient(identity).request(
                "echo", {"sequence": sequence}
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(request, range(24)))
    finally:
        server.close()

    assert {response["generation"] for response in responses} == {1}
    assert sorted(
        cast(
            "dict[str, int]",
            cast("dict[str, object]", response["result"])["arguments"],
        )["sequence"]
        for response in responses
    ) == list(range(24))


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_endpoint_and_secret_are_separate_and_socket_is_removed(tmp_path: Path) -> None:
    """Keep private credentials out of endpoint metadata and clean up sockets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts endpoint cleanup leaves the capability key intact.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    paths = QueryDaemonIpcPaths(identity)
    endpoint_payload = json.loads(paths.endpoint_path.read_text(encoding="utf-8"))
    assert "secret" not in endpoint_payload
    assert paths.secret_path.exists()
    assert paths.unix_socket_path.exists()
    server.close()

    assert not paths.endpoint_path.exists()
    assert not paths.unix_socket_path.exists()
    assert paths.secret_path.exists()
    assert (paths.secret_path.stat().st_mode & 0o077) == 0


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_invalid_secret_and_protocol_or_identity_mismatch_are_rejected(
    tmp_path: Path,
) -> None:
    """Reject authentication, protocol, and cross-repository handshake failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts every incompatible handshake receives an error frame.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    paths = QueryDaemonIpcPaths(identity)
    try:
        for handshake in (
            {
                "type": "handshake",
                "protocol_version": PROTOCOL_VERSION,
                "identity": identity.value,
                "secret": "00" * 32,
            },
            {
                "type": "handshake",
                "protocol_version": PROTOCOL_VERSION + 1,
                "identity": identity.value,
                "secret": paths.secret_path.read_bytes().hex(),
            },
            {
                "type": "handshake",
                "protocol_version": PROTOCOL_VERSION,
                "identity": "wrong-repository",
                "secret": paths.secret_path.read_bytes().hex(),
            },
        ):
            channel = _raw_channel(paths)
            try:
                channel.send(handshake)
                response = channel.receive()
            finally:
                channel.close()
            assert response["type"] == "error"
    finally:
        server.close()


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_malformed_truncated_oversized_and_path_requests_do_not_serve_reads(
    tmp_path: Path,
) -> None:
    """Reject malformed frames and arbitrary filesystem-path request fields.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts malformed peers cannot prevent a later valid request.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    paths = QueryDaemonIpcPaths(identity)
    try:
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.connect(str(paths.unix_socket_path))
        raw.sendall(struct.pack("!I", 12) + b"{")
        raw.close()

        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        raw.settimeout(2)
        raw.connect(str(paths.unix_socket_path))
        raw.sendall(struct.pack("!I", DEFAULT_REQUEST_LIMIT + 1))
        oversized = UnixFrameChannel(raw).receive()
        assert oversized["type"] == "error"

        channel = _raw_channel(paths)
        try:
            _handshake(channel, identity, paths.secret_path.read_bytes())
            channel.send(
                {
                    "type": "request",
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "path",
                    "operation": "echo",
                    "arguments": {"path": "/other/repository"},
                }
            )
            rejected = channel.receive()
        finally:
            channel.close()
        assert rejected["code"] == "invalid_request"

        response = QueryDaemonIpcClient(identity).request("echo", {"still": "works"})
    finally:
        server.close()
    assert response["result"] == {
        "arguments": {"still": "works"},
        "connection_owned": True,
    }


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_client_disconnect_during_request_does_not_break_later_clients(
    tmp_path: Path,
) -> None:
    """Recover after a peer disconnects after a valid handshake.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts a later client still receives a normal response.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    paths = QueryDaemonIpcPaths(identity)
    try:
        channel = _raw_channel(paths)
        _handshake(channel, identity, paths.secret_path.read_bytes())
        channel.close()
        time.sleep(0.05)
        response = QueryDaemonIpcClient(identity).request("echo", {"healthy": True})
    finally:
        server.close()
    assert response["result"] == {
        "arguments": {"healthy": True},
        "connection_owned": True,
    }


@pytest.mark.skipif(os.name == "nt", reason="Unix socket frame contract")
def test_updating_generation_never_serves_the_previous_warm_connection(
    tmp_path: Path,
) -> None:
    """Reject clients while durable handoff reports an incomplete generation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts an old warm runtime is not presented as current.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    runtime = _FakeRuntime()
    _publish_ready_generation(identity)
    server = QueryDaemonIpcServer(identity, runtime, {"echo": _echo_operation})
    server.start()
    try:
        IndexGenerationStore(
            identity.repository_root,
            output_root=identity.output_root,
        ).write(
            transition_record(
                generation=2,
                state="updating",
                last_successful_generation=1,
            )
        )
        with pytest.raises(QueryDaemonUnavailableError, match="updating"):
            QueryDaemonIpcClient(identity).handshake()
    finally:
        server.close()


def test_named_pipe_adapter_uses_bytes_methods_without_pickle() -> None:
    """Keep the named-pipe adapter on the ``send_bytes``/``recv_bytes`` API.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts object-level serialization methods are never called.
    """

    class Connection:
        """Bytes-only connection test double.

        Parameters
        ----------
        None
        """

        def __init__(self) -> None:
            """Initialize one inbound JSON frame and an outbound buffer.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """
            self.sent: list[bytes] = []

        def recv_bytes(self) -> bytes:
            """Return one raw JSON frame.

            Parameters
            ----------
            None

            Returns
            -------
            bytes
                Raw JSON request frame.
            """
            return b'{"message":"from-pipe"}'

        def send_bytes(self, payload: bytes) -> None:
            """Record one outgoing raw JSON frame.

            Parameters
            ----------
            payload : bytes
                Raw JSON payload sent by the adapter.

            Returns
            -------
            None
            """
            self.sent.append(payload)

        def close(self) -> None:
            """Accept adapter cleanup.

            Parameters
            ----------
            None

            Returns
            -------
            None
            """

        def recv(self) -> object:
            """Reject pickle-based object receive calls.

            Parameters
            ----------
            None

            Returns
            -------
            object
                This method always raises instead.

            Raises
            ------
            AssertionError
                Always, because object receive is forbidden.
            """
            msg = "pickle recv() must not be used"
            raise AssertionError(msg)

        def send(self, payload: object) -> None:
            """Reject pickle-based object send calls.

            Parameters
            ----------
            payload : object
                Ignored forbidden object payload.

            Returns
            -------
            None

            Raises
            ------
            AssertionError
                Always, because object send is forbidden.
            """
            del payload
            msg = "pickle send() must not be used"
            raise AssertionError(msg)

    connection = Connection()
    channel = NamedPipeFrameChannel(connection)
    assert channel.receive() == {"message": "from-pipe"}
    channel.send({"message": "to-pipe"})
    channel.close()
    assert connection.sent == [b'{"message":"to-pipe"}']


@pytest.mark.skipif(os.name != "nt", reason="native Windows named-pipe coverage")
def test_windows_named_pipe_server_and_client_handshake(tmp_path: Path) -> None:
    """Exercise the native Windows named-pipe server and client path.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository/output root.

    Returns
    -------
    None
        The test asserts the platform adapter serves authenticated requests.
    """
    identity = QueryDaemonIdentity.from_paths(tmp_path / "repo", tmp_path / "out")
    server = _server_for(identity)
    server.start()
    try:
        response = QueryDaemonIpcClient(identity).request("echo", {"windows": True})
    finally:
        server.close()
    assert response["result"] == {
        "arguments": {"windows": True},
        "connection_owned": True,
    }
