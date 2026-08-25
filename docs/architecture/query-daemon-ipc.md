# Query-daemon local IPC protocol

Slice 4 exposes the completed warm query runtime through a repository-local,
authenticated transport. It is a transport boundary only: foreground process
 lifecycle, durable status/activity records, service-manager integration, and
 MCP discovery. CLI routing is documented separately.

## Boundary and topology

One server is fixed to one resolved repository root and one effective output
directory at startup. Its request format has no repository, output-directory,
or generic filesystem-path field. The server never indexes files or mutates the
SQLite or DuckDB index; it dispatches only explicitly registered read
operations through the existing warm runtime.

On Linux and macOS, frames use a Unix-domain stream socket. On Windows, the
adapter uses `multiprocessing.connection` named pipes only through
`send_bytes()` and `recv_bytes()`; it never uses pickle-backed `send()` or
`recv()`.

## Protocol

The current protocol version is `1`. Unix frames are a four-byte big-endian
length followed by one UTF-8 JSON object. Named-pipe messages contain that raw
UTF-8 JSON object directly. A client must first send:

```json
{
  "type": "handshake",
  "protocol_version": 1,
  "identity": "opaque repository/output digest",
  "secret": "hex capability secret"
}
```

The successful response proves the same protocol version and identity and
reports the warm generation plus the approved operation names. Requests then
carry an opaque `request_id`, an approved operation name, and JSON arguments.
Responses repeat the request identifier and generation. Credentials are never
included in responses, endpoint descriptors, logs, or errors.

Before every handshake and request, the server reads the durable generation
record. It refuses service while the record is absent or `updating`, and it
requires the warm runtime to match the current `ready` generation. This makes
an incomplete index handoff transiently unavailable rather than presenting a
stale cached connection as current.

## Local credentials and endpoints

Files reside below the effective output directory:

- `.codira/query-daemon-endpoint.json` is public local discovery metadata:
  protocol version, transport, address, and opaque identity.
- `.codira/query-daemon.key` is a separate 32-byte capability secret, created
  owner-readable only on Unix-like platforms.
- `.codira/query-daemon.sock` is the preferred Unix socket address; if a deep
  repository path exceeds portable Unix-socket limits, the descriptor names a
  short identity-derived socket below `/tmp`. Windows uses a stable named pipe
  derived from the opaque identity instead.

The descriptor is validated against the client’s own resolved identity and
expected transport/address. A descriptor copied from another repository or
output directory is rejected before a connection is attempted.

## Foreground status and recovery

`codira query-daemon run` writes separate lifecycle records below the effective
output directory: `query-daemon-status.json`, `query-daemon-activity.jsonl`,
and `query-daemon-owner.json`. They are distinct from the indexing daemon's
`daemon-status.json` and activity log. The status reports process identity and
PID, backend names, current and observed generations, connection/model warmth,
request counters, last refresh, fallback availability, and the last error.

Activity records contain lifecycle and generation transitions only: they never
record query text or source paths. A stale owner PID causes the matching public
endpoint and socket to be cleaned before a new foreground process claims the
identity. Missing, corrupt, or `updating` generation records leave the daemon
`degraded`; the IPC endpoint remains local but refuses warm reads until a
later ready generation is warmed. SIGINT and SIGTERM request graceful closure
of the server, runtime, and ownership record.

## Platform services

`install`, `uninstall`, `start`, and `stop` manage only the service whose
identity matches the current repository and effective output directory. The
systemd user unit, launchd LaunchAgent, and Windows SCM registration all invoke
the same foreground `codira query-daemon --path … --output-dir … run` command.
They are separate from the indexing daemon's service identities. User-session
services require a logged-in user session; systemd lingering or Windows SCM
startup policy remains an operator choice.

## Limits and threat model

The service is local-only, but local endpoints are still untrusted boundaries.
It applies bounded UTF-8 JSON request and response sizes, socket timeouts, and
a bounded accepted-client queue. Oversized, malformed, truncated, incompatible,
or unauthenticated frames are rejected. A client disconnect cannot poison a
later connection. The server removes only its own socket path during shutdown;
it refuses to replace a non-socket filesystem entry.

The capability secret protects against unrelated local processes that can reach
the endpoint. It is not a multi-user authorization system: directory ownership
and host access controls remain the operating-system boundary. Query text and
source paths are not persisted by this transport.

## MCP proxy and fallback

The MCP stdio server is a fixed-root proxy client. The query daemon registers
the contract's approved MCP operations only, executes their existing adapter
logic against its warm connection, and returns the normal MCP envelope. The
stdio process validates the endpoint identity, protocol, transport, and
capability secret through the IPC handshake on each request.

If there is no matching endpoint, or a warm request fails, the MCP process
executes the same request directly once. It does not auto-start the daemon.
Response provenance records `warm`, `direct`, or `fallback` execution plus the
served generation without exposing the endpoint or secret. This permits many
MCP clients to share one repository daemon while preventing cross-repository
or arbitrary-path access.

## CLI proxy and fallback

When `[query_daemon].enabled` is true, the CLI opportunistically sends only
eligible, path-free reads to the same identity-bound endpoint: `ctx`, embedding
search, `plugins`, and `caps`. `ctx` and `emb` carry an optional named
similarity search profile; MCP `emb` and `docs` expose the same field. The
daemon captures the existing command
renderer so warm output and exit codes match direct execution. Prefix-filtered
queries and every write-oriented command remain direct. A missing, stale,
incompatible, or failed endpoint performs one direct retry; the optional
`--execution-mode` diagnostic exposes `warm`, `direct`, or `fallback` without
changing standard output or revealing credentials.

## Troubleshooting

If a client reports an unavailable endpoint, first confirm that the endpoint
descriptor and key exist under the intended effective output directory. Follow
the socket address recorded in the descriptor (it can be a short `/tmp` path
for a deeply nested repository). Remove only a stale socket after confirming
no query-daemon process owns it; never delete the key merely to diagnose
connectivity. A protocol or
identity mismatch normally means the client was started for a different
repository/output pair. An `updating` generation is expected during indexing;
callers should use their direct-core fallback until a later `ready` generation
is published.
