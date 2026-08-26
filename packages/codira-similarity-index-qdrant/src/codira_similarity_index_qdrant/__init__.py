"""Authenticated remote-Qdrant similarity-index plugin foundation for Codira.

The plugin validates a server-only configuration and exposes an injectable
client boundary. It stores no authoritative vectors or repository records.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import struct
import contextlib
from dataclasses import dataclass, field
from importlib import import_module
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5

from codira.contracts import (
    SimilarityCandidate,
    SimilarityIndexIdentity,
    SimilarityIndexAuthenticationError,
    SimilarityIndexCleanupError,
    SimilarityIndexIncompatibleError,
    SimilarityIndexPublicationError,
    SimilarityIndexStaleError,
    SimilarityIndexSpec,
    SimilarityIndexUnsafeOwnershipError,
    SimilarityIndexUnavailableError,
    SimilarityPurgeRequest,
    SimilarityPurgeResult,
    SimilarityQueryProvenance,
    SimilaritySearchRequest,
    SimilaritySearchResult,
    VectorSnapshot,
)
from codira.plugin_config import plugin_json_schema
from codira.storage import get_codira_dir

__all__ = [
    "PACKAGE_VERSION",
    "QdrantClientFactory",
    "QdrantClientProtocol",
    "QdrantClientSettings",
    "QdrantSimilarityIndex",
    "build_similarity_index",
]

PACKAGE_VERSION = "2.0.0"
FORMAT_VERSION = "1"
VECTOR_DISTANCE = "cosine"
_DEFAULT_TIMEOUT_SECONDS = 30
_DEFAULT_HNSW_M = 16
_DEFAULT_HNSW_EF_CONSTRUCT = 100
_DEFAULT_UPLOAD_BATCH_SIZE = 256
_MAX_TIMEOUT_SECONDS = 120
_MIN_HNSW_M = 4
_MAX_HNSW_M = 128
_MIN_HNSW_EF_CONSTRUCT = 8
_MAX_HNSW_EF_CONSTRUCT = 1024
_MAX_UPLOAD_BATCH_SIZE = 1000
_READ_CONSISTENCY_VALUES = frozenset({"majority", "quorum", "all"})
_WRITE_ORDERING_VALUES = frozenset({"weak", "medium", "strong"})
_OWNERSHIP_LEDGER_SCHEMA_VERSION = 1
_REPOSITORY_ID_FILENAME = "qdrant-repository-id"
_QDRANT_UUID_NAMESPACE = UUID("438ba202-f677-4abf-a234-e3d1acdd76f9")


class QdrantClientProtocol(Protocol):
    """Minimal remote-client boundary owned by later lifecycle phases.

    The protocol intentionally avoids Qdrant implementation types so tests can
    inject deterministic fakes without importing or contacting a server.
    """

    def get_collections(self) -> object:
        """Return the server collection inventory for a future compatibility probe.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Client-native collection inventory.
        """

        ...

    def info(self) -> object:
        """Probe the authenticated remote server without exposing its response.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Client-native server information.
        """

        ...

    def create_collection(
        self,
        collection_name: str,
        *,
        vectors_config: object,
        hnsw_config: object,
        on_disk_payload: bool,
    ) -> object:
        """Create one immutable remote collection.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.
        vectors_config : object
            Client-native cosine vector configuration.
        hnsw_config : object
            Client-native bounded HNSW configuration.
        on_disk_payload : bool
            Derived payload storage preference.

        Returns
        -------
        object
            Client-native creation result.
        """

        ...

    def upsert(
        self,
        collection_name: str,
        points: object,
        *,
        wait: bool,
        ordering: object,
    ) -> object:
        """Write a bounded batch of collection points.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.
        points : object
            Client-native batch of immutable points.
        wait : bool
            Whether Qdrant must confirm the batch before returning.
        ordering : object
            Client-native configured write ordering.

        Returns
        -------
        object
            Client-native mutation result.
        """

        ...

    def get_collection(self, collection_name: str) -> object:
        """Return verification metadata for one physical collection.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.

        Returns
        -------
        object
            Client-native collection information.
        """

        ...

    def get_aliases(self) -> object:
        """Return remote alias records before an atomic replacement.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Client-native alias inventory.
        """

        ...

    def update_collection_aliases(self, change_aliases_operations: object) -> object:
        """Apply one atomic alias replacement batch.

        Parameters
        ----------
        change_aliases_operations : object
            Client-native delete/create alias operations.

        Returns
        -------
        object
            Client-native update result.
        """

        ...

    def retrieve(
        self,
        collection_name: str,
        ids: list[str],
        *,
        with_payload: bool,
        with_vectors: bool,
    ) -> object:
        """Retrieve a reserved manifest point for ownership verification.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.
        ids : list[str]
            Deterministic manifest point identifier.
        with_payload : bool
            Whether ownership metadata must be returned.
        with_vectors : bool
            Whether vectors should be omitted during verification.

        Returns
        -------
        object
            Client-native record list.
        """

        ...

    def delete_collection(self, collection_name: str) -> object:
        """Delete one verified superseded physical collection.

        Parameters
        ----------
        collection_name : str
            Opaque exact-owned collection name.

        Returns
        -------
        object
            Client-native deletion result.
        """

        ...

    def query_points(
        self,
        collection_name: str,
        *,
        query: list[float],
        query_filter: object,
        search_params: object,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
        score_threshold: float,
        consistency: object,
    ) -> object:
        """Query one verified immutable collection without retrieving its vectors.

        Parameters
        ----------
        collection_name : str
            Exact physical collection resolved from the stable alias.
        query : list[float]
            Query vector generated by the authoritative embedding engine.
        query_filter : object
            Native filter that excludes the reserved manifest point.
        search_params : object
            Native HNSW per-query search parameters.
        limit : int
            Maximum candidate count before structural filtering.
        with_payload : bool
            Whether stable candidate IDs are returned.
        with_vectors : bool
            Must remain false because vectors are authoritative elsewhere.
        score_threshold : float
            Minimum similarity score.
        consistency : object
            Configured native read-consistency value.

        Returns
        -------
        object
            Client-native query response.
        """

        ...


@dataclass(frozen=True)
class QdrantClientSettings:
    """Credential-free normalized settings supplied to a client factory.

    Parameters
    ----------
    url : str
        Normalized remote HTTP(S) endpoint.
    transport : str
        Explicit REST or gRPC transport choice.
    grpc_port : int | None
        Optional gRPC port used only when gRPC is selected.
    timeout_seconds : int
        Bounded client request timeout.
    """

    url: str
    transport: str
    grpc_port: int | None
    timeout_seconds: int


QdrantClientFactory = Callable[[QdrantClientSettings, str], QdrantClientProtocol]


@dataclass(frozen=True)
class _BuildConfig:
    """Validated plugin configuration excluding credential values.

    Parameters
    ----------
    settings : QdrantClientSettings
        Credential-free remote client settings.
    api_key_env : str | None
        Optional environment-variable name for Phase 5 credential resolution.
    api_key_file : str | None
        Optional credential-file path for Phase 5 credential resolution.
    namespace : str
        Required operator partition, retained only in local configuration.
    write_ordering : str
        Qdrant write consistency ordering.
    read_consistency : str
        Portable Qdrant read consistency mode.
    hnsw_m : int
        Bounded HNSW graph degree.
    hnsw_ef_construct : int
        Bounded HNSW construction exploration value.
    on_disk : bool
        Whether derived vectors may reside on disk.
    upload_batch_size : int
        Bounded mutation batch size.
    """

    settings: QdrantClientSettings
    api_key_env: str | None
    api_key_file: str | None
    namespace: str
    write_ordering: str
    read_consistency: str
    hnsw_m: int
    hnsw_ef_construct: int
    on_disk: bool
    upload_batch_size: int


@dataclass(frozen=True)
class _RemoteArtifactIdentity:
    """Opaque remote names and hashes for one immutable Qdrant revision.

    Parameters
    ----------
    artifact_hash : str
        Collision-resistant hash for one full remote build identity.
    alias_name : str
        Stable alias name for the build identity and object type.
    collection_name : str
        Immutable physical collection name for the source revision.
    repository_id_hash : str
        Opaque hash of the repository UUID used for ownership verification.
    endpoint_hash : str
        Opaque hash of the configured Qdrant endpoint.
    namespace_hash : str
        Opaque hash of the configured operator namespace.
    root_hash : str
        Opaque hash of the canonical repository root.
    point_namespace : uuid.UUID
        Deterministic UUID namespace for point and manifest identifiers.
    """

    artifact_hash: str
    alias_name: str
    collection_name: str
    repository_id_hash: str
    endpoint_hash: str
    namespace_hash: str
    root_hash: str
    point_namespace: UUID


@dataclass(frozen=True)
class _QdrantPoint:
    """One immutable Qdrant point expressed without client implementation types.

    Parameters
    ----------
    identifier : str
        Deterministic UUID point identifier.
    vector : tuple[float, ...]
        Float vector in authoritative row order.
    payload : dict[str, object]
        Credential-free ownership, freshness, and candidate metadata.
    """

    identifier: str
    vector: tuple[float, ...]
    payload: dict[str, object]


def _optional_nonempty_string(config: Mapping[str, object], key: str) -> str | None:
    """Return one optional non-empty string configuration value.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration mapping.
    key : str
        Optional string configuration key.

    Returns
    -------
    str | None
        Stripped value when configured, otherwise ``None``.

    Raises
    ------
    ValueError
        If the configured value is not a non-empty string.
    """

    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Qdrant {key} must be a non-empty string when set.")
    return value.strip()


def _required_string(config: Mapping[str, object], key: str) -> str:
    """Return one required non-empty string configuration value.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration mapping.
    key : str
        Required string configuration key.

    Returns
    -------
    str
        Stripped required configuration value.

    Raises
    ------
    ValueError
        If the value is absent, not a string, or blank.
    """

    value = _optional_nonempty_string(config, key)
    if value is None:
        raise ValueError(f"Qdrant {key} is required.")
    return value


def _bounded_int(
    config: Mapping[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Return one bounded integer setting without accepting booleans.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration mapping.
    key : str
        Integer configuration key.
    default : int
        Value used when the key is absent.
    minimum : int
        Inclusive lower bound.
    maximum : int
        Inclusive upper bound.

    Returns
    -------
    int
        Validated integer setting.

    Raises
    ------
    ValueError
        If the setting is not an integer within its inclusive bounds.
    """

    value = config.get(key, default)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f"Qdrant {key} must be an integer between {minimum} and {maximum}."
        )
    return value


def _normalized_url(value: str) -> str:
    """Validate and normalize a remote HTTP(S) Qdrant endpoint.

    Parameters
    ----------
    value : str
        Raw configured endpoint.

    Returns
    -------
    str
        Normalized endpoint without a trailing slash.

    Raises
    ------
    ValueError
        If the endpoint selects local, embedded, anonymous, or malformed mode.
    """

    if value == ":memory:" or "\\" in value:
        raise ValueError("Qdrant url must be a remote HTTP(S) endpoint.")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Qdrant url must contain a valid remote port.") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Qdrant url must be a credential-free remote HTTP(S) endpoint."
        )
    normalized = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
    )
    return normalized.rstrip("/")


def _build_config(config: Mapping[str, object]) -> _BuildConfig:
    """Validate strict Qdrant plugin configuration before any network access.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin configuration mapping.

    Returns
    -------
    _BuildConfig
        Credential-free typed configuration.

    Raises
    ------
    ValueError
        If keys, endpoint, transport, consistency, or bounded settings are invalid.
    """

    supported = {
        "enabled",
        "url",
        "transport",
        "grpc_port",
        "api_key_env",
        "api_key_file",
        "namespace",
        "timeout_seconds",
        "write_ordering",
        "read_consistency",
        "hnsw_m",
        "hnsw_ef_construct",
        "on_disk",
        "upload_batch_size",
    }
    unsupported = sorted(set(config) - supported)
    if unsupported:
        raise ValueError(
            "Qdrant similarity index does not accept configuration keys: "
            + ", ".join(unsupported)
        )
    transport = str(config.get("transport", "rest"))
    if transport not in {"rest", "grpc"}:
        raise ValueError("Qdrant transport must be 'rest' or 'grpc'.")
    grpc_port_value = config.get("grpc_port")
    if grpc_port_value is None:
        grpc_port = None
    elif (
        not isinstance(grpc_port_value, int)
        or isinstance(grpc_port_value, bool)
        or not 1 <= grpc_port_value <= 65535
    ):
        raise ValueError("Qdrant grpc_port must be an integer between 1 and 65535.")
    else:
        grpc_port = grpc_port_value
    write_ordering = str(config.get("write_ordering", "strong"))
    if write_ordering not in _WRITE_ORDERING_VALUES:
        raise ValueError("Qdrant write_ordering must be weak, medium, or strong.")
    read_consistency = str(config.get("read_consistency", "majority"))
    if read_consistency not in _READ_CONSISTENCY_VALUES:
        raise ValueError("Qdrant read_consistency must be majority, quorum, or all.")
    on_disk = config.get("on_disk", False)
    if not isinstance(on_disk, bool):
        raise ValueError("Qdrant on_disk must be a boolean.")
    return _BuildConfig(
        settings=QdrantClientSettings(
            url=_normalized_url(_required_string(config, "url")),
            transport=transport,
            grpc_port=grpc_port,
            timeout_seconds=_bounded_int(
                config,
                "timeout_seconds",
                default=_DEFAULT_TIMEOUT_SECONDS,
                minimum=1,
                maximum=_MAX_TIMEOUT_SECONDS,
            ),
        ),
        api_key_env=_optional_nonempty_string(config, "api_key_env"),
        api_key_file=_optional_nonempty_string(config, "api_key_file"),
        namespace=_required_string(config, "namespace"),
        write_ordering=write_ordering,
        read_consistency=read_consistency,
        hnsw_m=_bounded_int(
            config,
            "hnsw_m",
            default=_DEFAULT_HNSW_M,
            minimum=_MIN_HNSW_M,
            maximum=_MAX_HNSW_M,
        ),
        hnsw_ef_construct=_bounded_int(
            config,
            "hnsw_ef_construct",
            default=_DEFAULT_HNSW_EF_CONSTRUCT,
            minimum=_MIN_HNSW_EF_CONSTRUCT,
            maximum=_MAX_HNSW_EF_CONSTRUCT,
        ),
        on_disk=on_disk,
        upload_batch_size=_bounded_int(
            config,
            "upload_batch_size",
            default=_DEFAULT_UPLOAD_BATCH_SIZE,
            minimum=1,
            maximum=_MAX_UPLOAD_BATCH_SIZE,
        ),
    )


def _credential_from_file(path_value: str) -> str:
    """Read one safe, non-empty API key from a private regular file.

    Parameters
    ----------
    path_value : str
        Configured credential-file path that must not be resolved or reported.

    Returns
    -------
    str
        Credential text with one terminal line ending removed.

    Raises
    ------
    SimilarityIndexAuthenticationError
        If the file is absent, unsafe, unreadable, undecodable, or empty.
    """

    path = Path(path_value)
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise SimilarityIndexAuthenticationError(
            "Qdrant credential file is unavailable."
        ) from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SimilarityIndexAuthenticationError(
            "Qdrant credential file must be a regular non-symlink file."
        )
    if os.name == "posix" and mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SimilarityIndexAuthenticationError(
            "Qdrant credential file must not grant group or other permissions."
        )
    try:
        credential = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SimilarityIndexAuthenticationError(
            "Qdrant credential file cannot be read."
        ) from error
    if credential.endswith("\r\n"):
        credential = credential[:-2]
    elif credential.endswith(("\r", "\n")):
        credential = credential[:-1]
    if not credential.strip():
        raise SimilarityIndexAuthenticationError(
            "Qdrant credential file does not contain a usable credential."
        )
    return credential


def _resolve_api_key(build: _BuildConfig) -> str:
    """Resolve a credential from the configured environment then private file.

    Parameters
    ----------
    build : _BuildConfig
        Validated Qdrant configuration containing only credential source names.

    Returns
    -------
    str
        Non-empty credential value retained only by the command-scoped client.

    Raises
    ------
    SimilarityIndexAuthenticationError
        If neither configured source yields a usable credential.
    """

    if build.api_key_env is not None:
        environment_value = os.environ.get(build.api_key_env)
        if environment_value is not None and environment_value.strip():
            return environment_value
    if build.api_key_file is not None:
        return _credential_from_file(build.api_key_file)
    raise SimilarityIndexAuthenticationError(
        "Qdrant requires a usable api_key_env or api_key_file credential source."
    )


def _raise_mapped_client_error(error: Exception) -> None:
    """Raise one credential-free Codira error for a Qdrant-client failure.

    Parameters
    ----------
    error : Exception
        Client construction or probe exception whose detail must not be exposed.

    Returns
    -------
    None

    Raises
    ------
    SimilarityIndexAuthenticationError
        If the client reports an authentication HTTP response.
    SimilarityIndexUnavailableError
        For all other remote construction or probe failures.
    """

    status_code = getattr(error, "status_code", None)
    if status_code in {401, 403}:
        raise SimilarityIndexAuthenticationError(
            "Qdrant authentication was rejected by the selected server."
        ) from error
    raise SimilarityIndexUnavailableError(
        "Qdrant server is unavailable for the selected similarity index."
    ) from error


def _opaque_hash(value: object) -> str:
    """Return a SHA-256 hash for one canonical JSON-compatible identity value.

    Parameters
    ----------
    value : object
        JSON-compatible identity component retained only through its hash.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """

    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _repository_id_path(root: Path) -> Path:
    """Return the persistent Qdrant repository UUID path for one root.

    Parameters
    ----------
    root : pathlib.Path
        Canonical repository root owning the remote Qdrant namespace.

    Returns
    -------
    pathlib.Path
        Repository-local UUID file preserved across semantic reset.
    """

    return get_codira_dir(root) / _REPOSITORY_ID_FILENAME


def _load_or_create_repository_id(root: Path) -> UUID:
    """Load or atomically create the persistent repository UUID.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose Qdrant identity is being initialized.

    Returns
    -------
    uuid.UUID
        Stable repository UUID used only as input to opaque remote identities.

    Raises
    ------
    SimilarityIndexUnsafeOwnershipError
        If an existing identity file is unsafe, corrupt, or cannot be created.
    """

    path = _repository_id_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        mode = None
    except OSError as error:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant repository identity cannot be inspected safely."
        ) from error
    if mode is not None:
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant repository identity must be a regular non-symlink file."
            )
        try:
            return UUID(path.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant repository identity is invalid."
            ) from error

    candidate = uuid4()
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{candidate}\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return _load_or_create_repository_id(root)
        return candidate
    except OSError as error:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant repository identity cannot be created safely."
        ) from error
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _ownership_ledger_path(root: Path) -> Path:
    """Return the credential-free local Qdrant ownership ledger path.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the derived Qdrant artifacts.

    Returns
    -------
    pathlib.Path
        Ledger path populated only after successful remote publication.
    """

    return get_codira_dir(root) / "similarity-indexes" / "qdrant" / "ownership.json"


def _ensure_ownership_ledger(root: Path) -> None:
    """Create an empty, versioned ownership ledger without remote claims.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the local ledger.

    Returns
    -------
    None
        A deterministic empty ledger exists for later publication evidence.

    Raises
    ------
    SimilarityIndexUnsafeOwnershipError
        If the ledger cannot be created safely.
    """

    path = _ownership_ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    payload = {
        "schema_version": _OWNERSHIP_LEDGER_SCHEMA_VERSION,
        "records": [],
    }
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant ownership ledger cannot be created safely."
        ) from error
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _remote_artifact_identity(
    identity: SimilarityIndexIdentity,
    build: _BuildConfig,
    repository_id: UUID,
    *,
    object_type: str,
    source_revision: int,
) -> _RemoteArtifactIdentity:
    """Derive opaque aliases, immutable collection names, and point namespace.

    Parameters
    ----------
    identity : codira.contracts.SimilarityIndexIdentity
        Repository-bound vector-store and similarity-index identity.
    build : _BuildConfig
        Validated Qdrant build settings and local namespace input.
    repository_id : uuid.UUID
        Persistent root identity used as a non-rendered hash input.
    object_type : str
        Snapshot owner type for the remote collection.
    source_revision : int
        Immutable authoritative vector revision being published.

    Returns
    -------
    _RemoteArtifactIdentity
        Opaque names and verification hashes with no raw path, URL, or namespace.
    """

    engine = identity.vector_set.engine
    store = identity.vector_set.vector_store
    repository_id_hash = _opaque_hash(str(repository_id))
    endpoint_hash = _opaque_hash(build.settings.url)
    namespace_hash = _opaque_hash(build.namespace)
    root_hash = _opaque_hash(str(identity.root.resolve()))
    payload = {
        "endpoint_hash": endpoint_hash,
        "hnsw_ef_construct": build.hnsw_ef_construct,
        "hnsw_m": build.hnsw_m,
        "index": {
            "build_fingerprint": identity.index.build_fingerprint,
            "format_version": identity.index.format_version,
            "index": identity.index.index,
            "index_version": identity.index.index_version,
        },
        "namespace_hash": namespace_hash,
        "object_type": object_type,
        "on_disk": build.on_disk,
        "repository_id_hash": repository_id_hash,
        "root_hash": root_hash,
        "source_revision": source_revision,
        "vector_set": {
            "engine": engine.engine,
            "engine_version": engine.engine_version,
            "model": engine.model,
            "model_version": engine.model_version,
            "dimension": engine.dimension,
            "precision": engine.precision,
            "vector_store": {
                "format_version": store.format_version,
                "store": store.store,
                "store_version": store.store_version,
            },
        },
    }
    artifact_hash = _opaque_hash(payload)
    alias_hash = _opaque_hash(
        {key: value for key, value in payload.items() if key != "source_revision"}
    )
    point_namespace = uuid5(_QDRANT_UUID_NAMESPACE, artifact_hash)
    return _RemoteArtifactIdentity(
        artifact_hash=artifact_hash,
        alias_name=f"codira-qdrant-a-{alias_hash[:40]}",
        collection_name=f"codira-qdrant-r-{artifact_hash[:40]}",
        repository_id_hash=repository_id_hash,
        endpoint_hash=endpoint_hash,
        namespace_hash=namespace_hash,
        root_hash=root_hash,
        point_namespace=point_namespace,
    )


def _point_id(remote: _RemoteArtifactIdentity, stable_id: str) -> str:
    """Return a deterministic opaque UUID point identifier for one stable row.

    Parameters
    ----------
    remote : _RemoteArtifactIdentity
        Opaque remote artifact identity and point namespace.
    stable_id : str
        Durable structural row identity retained only as UUID input.

    Returns
    -------
    str
        Deterministic UUID string suitable for Qdrant point insertion.
    """

    return str(uuid5(remote.point_namespace, f"point:{stable_id}"))


def _manifest_point_id(remote: _RemoteArtifactIdentity) -> str:
    """Return the deterministic reserved manifest point UUID for one collection.

    Parameters
    ----------
    remote : _RemoteArtifactIdentity
        Opaque remote artifact identity and point namespace.

    Returns
    -------
    str
        Deterministic manifest-point UUID distinct from vector point IDs.
    """

    return str(uuid5(remote.point_namespace, "manifest"))


def _vector_values(row: object, *, dimension: int) -> tuple[float, ...]:
    """Deserialize one authoritative float32 vector without guessing its shape.

    Parameters
    ----------
    row : object
        Stored-vector row exposing serialized native float32 bytes.
    dimension : int
        Expected immutable embedding dimension.

    Returns
    -------
    tuple[float, ...]
        Exactly ``dimension`` float values in stored byte order.

    Raises
    ------
    SimilarityIndexIncompatibleError
        If the authoritative row cannot represent the declared dimension.
    """

    vector = getattr(row, "vector", None)
    if not isinstance(vector, bytes) or len(vector) != dimension * 4:
        raise SimilarityIndexIncompatibleError(
            "Qdrant source vector does not match its declared dimension."
        )
    return tuple(struct.unpack(f"<{dimension}f", vector))


def _manifest_payload(
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
) -> dict[str, object]:
    """Return credential-free ownership and freshness metadata for one revision.

    Parameters
    ----------
    remote : _RemoteArtifactIdentity
        Opaque remote artifact identity.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative rows and source revision being published.

    Returns
    -------
    dict[str, object]
        Remote manifest payload containing only opaque identity data.
    """

    return {
        "artifact_hash": remote.artifact_hash,
        "endpoint_hash": remote.endpoint_hash,
        "kind": "manifest",
        "namespace_hash": remote.namespace_hash,
        "object_type": snapshot.metadata.object_type,
        "repository_id_hash": remote.repository_id_hash,
        "root_hash": remote.root_hash,
        "row_count": snapshot.metadata.row_count,
        "source_revision": snapshot.metadata.revision,
    }


def _publication_points(
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
) -> tuple[_QdrantPoint, ...]:
    """Return the reserved manifest followed by deterministic vector points.

    Parameters
    ----------
    remote : _RemoteArtifactIdentity
        Opaque remote collection identity.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative vector rows and source revision.

    Returns
    -------
    tuple[_QdrantPoint, ...]
        Manifest point plus one exact point per authoritative vector row.
    """

    dimension = snapshot.metadata.identity.engine.dimension
    manifest = _QdrantPoint(
        identifier=_manifest_point_id(remote),
        vector=tuple(0.0 for _ in range(dimension)),
        payload=_manifest_payload(remote, snapshot),
    )
    points = [manifest]
    for row in snapshot.rows:
        points.append(
            _QdrantPoint(
                identifier=_point_id(remote, row.stable_id),
                vector=_vector_values(row, dimension=dimension),
                payload={
                    "artifact_hash": remote.artifact_hash,
                    "kind": "vector",
                    "source_revision": snapshot.metadata.revision,
                    "stable_id": row.stable_id,
                },
            )
        )
    return tuple(points)


def _client_models() -> object:
    """Return Qdrant client models only within the plugin distribution boundary.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Imported ``qdrant_client.models`` module.
    """

    return import_module("qdrant_client.models")


def _client_points(points: tuple[_QdrantPoint, ...]) -> list[object]:
    """Convert plugin-owned point values to native Qdrant point structures.

    Parameters
    ----------
    points : tuple[_QdrantPoint, ...]
        Immutable credential-free point batch.

    Returns
    -------
    list[object]
        Client-native point structures in deterministic order.
    """

    models = _client_models()
    point_type = getattr(models, "PointStruct")
    return [
        point_type(
            id=point.identifier, vector=list(point.vector), payload=point.payload
        )
        for point in points
    ]


def _create_collection(
    client: QdrantClientProtocol,
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
    build: _BuildConfig,
) -> None:
    """Create one immutable cosine collection with bounded HNSW settings.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized fixed-root remote client.
    remote : _RemoteArtifactIdentity
        Opaque physical collection name.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative dimension for the collection vector contract.
    build : _BuildConfig
        Validated HNSW and storage configuration.

    Returns
    -------
    None

    Raises
    ------
    SimilarityIndexPublicationError
        If Qdrant declines collection creation.
    """

    models = _client_models()
    try:
        created = client.create_collection(
            remote.collection_name,
            vectors_config=getattr(models, "VectorParams")(
                size=snapshot.metadata.identity.engine.dimension,
                distance=getattr(getattr(models, "Distance"), "COSINE"),
                on_disk=build.on_disk,
            ),
            hnsw_config=getattr(models, "HnswConfigDiff")(
                m=build.hnsw_m,
                ef_construct=build.hnsw_ef_construct,
            ),
            on_disk_payload=False,
        )
    except Exception as error:
        _raise_mapped_client_error(error)
    if created is False:
        raise SimilarityIndexPublicationError(
            "Qdrant refused immutable collection creation."
        )


def _write_points(
    client: QdrantClientProtocol,
    remote: _RemoteArtifactIdentity,
    points: tuple[_QdrantPoint, ...],
    build: _BuildConfig,
) -> None:
    """Upsert manifest and vectors in confirmed bounded batches.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized fixed-root remote client.
    remote : _RemoteArtifactIdentity
        Opaque physical collection destination.
    points : tuple[_QdrantPoint, ...]
        Deterministic manifest/vector point sequence.
    build : _BuildConfig
        Validated batch bound and write-ordering choice.

    Returns
    -------
    None

    Raises
    ------
    SimilarityIndexPublicationError
        If a confirmed point batch cannot be written.
    """

    ordering = getattr(
        getattr(_client_models(), "WriteOrdering"), build.write_ordering.upper()
    )
    for start in range(0, len(points), build.upload_batch_size):
        batch = points[start : start + build.upload_batch_size]
        try:
            client.upsert(
                remote.collection_name,
                _client_points(batch),
                wait=True,
                ordering=ordering,
            )
        except Exception as error:
            _raise_mapped_client_error(error)


def _field(value: object, name: str, default: object = None) -> object:
    """Return one client-native field from a mapping or attribute object.

    Parameters
    ----------
    value : object
        Native Qdrant response or nested model object.
    name : str
        Expected field name.
    default : object, optional
        Value returned when the field is absent.

    Returns
    -------
    object
        Native field value or the supplied default.
    """

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _verify_collection(
    client: QdrantClientProtocol,
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
) -> None:
    """Verify immutable collection readiness before alias publication.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized remote client.
    remote : _RemoteArtifactIdentity
        Opaque collection identity to inspect.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative expected point count and dimension.

    Returns
    -------
    None

    Raises
    ------
    SimilarityIndexPublicationError
        If collection readiness, count, vector size, or cosine distance differs.
    """

    try:
        info = client.get_collection(remote.collection_name)
    except Exception as error:
        _raise_mapped_client_error(error)
    expected_count = snapshot.metadata.row_count + 1
    if _field(info, "points_count") != expected_count:
        raise SimilarityIndexPublicationError(
            "Qdrant collection point count did not match the authoritative snapshot."
        )
    status = str(_field(info, "status", "")).lower()
    if status not in {"green", "collectionstatus.green"}:
        raise SimilarityIndexPublicationError(
            "Qdrant collection did not become ready before publication."
        )
    config = _field(info, "config")
    params = _field(config, "params")
    vectors = _field(params, "vectors")
    dimension = _field(vectors, "size")
    distance = str(_field(vectors, "distance", "")).lower()
    if (
        dimension != snapshot.metadata.identity.engine.dimension
        or "cosine" not in distance
    ):
        raise SimilarityIndexPublicationError(
            "Qdrant collection vector contract is incompatible with the snapshot."
        )


def _alias_target(client: QdrantClientProtocol, alias_name: str) -> str | None:
    """Return the current physical target for one alias without trusting local state.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized remote client.
    alias_name : str
        Opaque alias name to resolve.

    Returns
    -------
    str | None
        Current opaque collection target, or ``None`` when the alias is absent.
    """

    try:
        aliases = _field(client.get_aliases(), "aliases", ())
    except Exception as error:
        _raise_mapped_client_error(error)
    if not isinstance(aliases, (list, tuple)):
        raise SimilarityIndexPublicationError("Qdrant alias inventory is malformed.")
    for alias in aliases:
        if _field(alias, "alias_name") == alias_name:
            target = _field(alias, "collection_name")
            if not isinstance(target, str) or not target:
                raise SimilarityIndexPublicationError(
                    "Qdrant alias target is malformed."
                )
            return target
    return None


def _publish_alias(
    client: QdrantClientProtocol,
    remote: _RemoteArtifactIdentity,
) -> str | None:
    """Atomically point one alias at a verified immutable collection.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized remote client.
    remote : _RemoteArtifactIdentity
        Verified collection and stable alias identity.

    Returns
    -------
    str | None
        Previous physical collection target when an alias existed.

    Raises
    ------
    SimilarityIndexPublicationError
        If the atomic Qdrant alias update is rejected.
    """

    previous = _alias_target(client, remote.alias_name)
    models = _client_models()
    operations: list[object] = []
    if previous is not None:
        operations.append(
            getattr(models, "DeleteAliasOperation")(
                delete_alias=getattr(models, "DeleteAlias")(
                    alias_name=remote.alias_name
                )
            )
        )
    operations.append(
        getattr(models, "CreateAliasOperation")(
            create_alias=getattr(models, "CreateAlias")(
                collection_name=remote.collection_name,
                alias_name=remote.alias_name,
            )
        )
    )
    try:
        published = client.update_collection_aliases(operations)
    except Exception as error:
        _raise_mapped_client_error(error)
    if published is False:
        raise SimilarityIndexPublicationError(
            "Qdrant refused the atomic alias publication."
        )
    return previous


def _record_publication(
    root: Path,
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
    previous_collection: str | None,
) -> tuple[dict[str, object], ...]:
    """Atomically persist credential-free local publication evidence.

    Parameters
    ----------
    root : pathlib.Path
        Repository root owning the local ownership ledger.
    remote : _RemoteArtifactIdentity
        Opaque current remote identity.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative snapshot metadata represented by the publication.
    previous_collection : str | None
        Prior alias target observed remotely before publication.

    Returns
    -------
    tuple[dict[str, object], ...]
        Exact-owned superseded records eligible for remote verification/deletion.
    """

    path = _ownership_ledger_path(root)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant ownership ledger is unavailable or invalid."
        ) from error
    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list):
        raise SimilarityIndexUnsafeOwnershipError("Qdrant ownership ledger is invalid.")
    current = {
        "alias_name": remote.alias_name,
        "artifact_hash": remote.artifact_hash,
        "collection_name": remote.collection_name,
        "manifest_point_id": _manifest_point_id(remote),
        "object_type": snapshot.metadata.object_type,
        "repository_id_hash": remote.repository_id_hash,
        "root_hash": remote.root_hash,
        "source_revision": snapshot.metadata.revision,
    }
    existing = next(
        (
            item
            for item in records
            if isinstance(item, dict)
            and item.get("object_type") == snapshot.metadata.object_type
        ),
        None,
    )
    prior: list[dict[str, object]] = []
    if isinstance(existing, dict):
        retained_collections = existing.get("retained_collections")
        if isinstance(retained_collections, list):
            prior = [item for item in retained_collections if isinstance(item, dict)]
        elif existing.get("collection_name") == previous_collection:
            prior = [existing]
    retained_collections = [current, *prior]
    obsolete = tuple(retained_collections[2:])
    record = {
        "alias_name": remote.alias_name,
        "object_type": snapshot.metadata.object_type,
        "retained_collections": retained_collections[:2],
    }
    retained = [
        item
        for item in records
        if not isinstance(item, dict)
        or item.get("object_type") != snapshot.metadata.object_type
    ]
    retained.append(record)
    document["records"] = sorted(
        retained, key=lambda item: str(item.get("object_type", ""))
    )
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as error:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant ownership ledger cannot be updated safely."
        ) from error
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    return obsolete


def _retire_verified_collections(
    client: QdrantClientProtocol, obsolete: tuple[dict[str, object], ...]
) -> None:
    """Delete only superseded collections with matching reserved remote manifests.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized fixed-root Qdrant client.
    obsolete : tuple[dict[str, object], ...]
        Locally recorded candidates beyond the current-plus-previous bound.

    Returns
    -------
    None
        Every exact-owned candidate is deleted; ambiguous state is retained.
    """

    for record in obsolete:
        collection = record.get("collection_name")
        manifest_id = record.get("manifest_point_id")
        if not isinstance(collection, str) or not isinstance(manifest_id, str):
            continue
        try:
            rows = client.retrieve(
                collection, [manifest_id], with_payload=True, with_vectors=False
            )
        except Exception:
            continue
        if not isinstance(rows, list) or len(rows) != 1:
            continue
        payload = _field(rows[0], "payload")
        if not isinstance(payload, Mapping) or any(
            payload.get(key) != record.get(key)
            for key in (
                "artifact_hash",
                "repository_id_hash",
                "root_hash",
                "source_revision",
            )
        ):
            continue
        try:
            client.delete_collection(collection)
        except Exception:
            continue


def _default_client_factory(
    settings: QdrantClientSettings, api_key: str
) -> QdrantClientProtocol:
    """Construct one remote Qdrant client only after credential resolution.

    Parameters
    ----------
    settings : QdrantClientSettings
        Validated remote transport settings.
    api_key : str
        Resolved non-empty API key supplied by the Phase 5 credential boundary.

    Returns
    -------
    QdrantClientProtocol
        Client implementation configured for remote REST or gRPC transport.
    """

    client_type = getattr(import_module("qdrant_client"), "QdrantClient")

    return cast(
        "QdrantClientProtocol",
        client_type(
            url=settings.url,
            api_key=api_key,
            timeout=settings.timeout_seconds,
            grpc_port=settings.grpc_port or 6334,
            prefer_grpc=settings.transport == "grpc",
            check_compatibility=True,
        ),
    )


def _verified_search_collection(
    client: QdrantClientProtocol,
    remote: _RemoteArtifactIdentity,
    snapshot: VectorSnapshot,
) -> str:
    """Resolve and verify one exact immutable collection before searching.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized fixed-root remote client.
    remote : _RemoteArtifactIdentity
        Expected opaque identity for the authoritative source revision.
    snapshot : codira.contracts.VectorSnapshot
        Authoritative vector metadata to bind to the remote artifact.

    Returns
    -------
    str
        Exact verified physical collection name, never a mutable alias.

    Raises
    ------
    SimilarityIndexStaleError
        If the selected alias is absent or points at a different source revision.
    SimilarityIndexUnsafeOwnershipError
        If collection ownership evidence is missing or mismatched.
    SimilarityIndexIncompatibleError
        If the remote collection vector contract differs from the snapshot.
    """

    target = _alias_target(client, remote.alias_name)
    if target is None:
        raise SimilarityIndexStaleError(
            "Qdrant has no published collection for the selected source revision."
        )
    if target != remote.collection_name:
        raise SimilarityIndexStaleError(
            "Qdrant published collection does not match the selected source revision."
        )
    try:
        info = client.get_collection(target)
        rows = client.retrieve(
            target,
            [_manifest_point_id(remote)],
            with_payload=True,
            with_vectors=False,
        )
    except Exception as error:
        _raise_mapped_client_error(error)
    config = _field(info, "config")
    params = _field(config, "params")
    vectors = _field(params, "vectors")
    if (
        _field(vectors, "size") != snapshot.metadata.identity.engine.dimension
        or "cosine" not in str(_field(vectors, "distance", "")).lower()
    ):
        raise SimilarityIndexIncompatibleError(
            "Qdrant collection vector contract is incompatible with the snapshot."
        )
    if not isinstance(rows, list) or len(rows) != 1:
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant collection ownership manifest is unavailable."
        )
    payload = _field(rows[0], "payload")
    if not isinstance(payload, Mapping):
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant collection ownership manifest is malformed."
        )
    expected = _manifest_payload(remote, snapshot)
    if any(payload.get(key) != value for key, value in expected.items()):
        raise SimilarityIndexUnsafeOwnershipError(
            "Qdrant collection ownership manifest does not match this repository."
        )
    return target


def _search_points(
    client: QdrantClientProtocol,
    collection_name: str,
    request: SimilaritySearchRequest,
    build: _BuildConfig,
) -> tuple[SimilarityCandidate, ...]:
    """Query a verified collection and convert its vector-only results safely.

    Parameters
    ----------
    client : QdrantClientProtocol
        Initialized remote client.
    collection_name : str
        Previously verified physical collection name.
    request : codira.contracts.SimilaritySearchRequest
        Authoritative per-query vector, profile, and candidate policy.
    build : _BuildConfig
        Selected credential-free Qdrant runtime configuration.

    Returns
    -------
    tuple[codira.contracts.SimilarityCandidate, ...]
        Deterministically ordered and bounded native candidates.

    Raises
    ------
    SimilarityIndexIncompatibleError
        If the query vector or returned Qdrant payload is malformed.
    """

    dimension = request.snapshot.metadata.identity.engine.dimension
    query = tuple(request.query_vector)
    if len(query) != dimension or any(not math.isfinite(value) for value in query):
        raise SimilarityIndexIncompatibleError(
            "Qdrant query vector does not match the authoritative embedding dimension."
        )
    models = _client_models()
    vector_filter = getattr(models, "Filter")(
        must=[
            getattr(models, "FieldCondition")(
                key="kind",
                match=getattr(models, "MatchValue")(value="vector"),
            )
        ]
    )
    try:
        response = client.query_points(
            collection_name,
            query=list(query),
            query_filter=vector_filter,
            search_params=getattr(models, "SearchParams")(
                hnsw_ef=request.profile.ef_search
            ),
            limit=request.profile.candidate_limit,
            with_payload=True,
            with_vectors=False,
            score_threshold=request.min_score,
            consistency=build.read_consistency,
        )
    except Exception as error:
        _raise_mapped_client_error(error)
    rows = _field(response, "points", response)
    if not isinstance(rows, (list, tuple)):
        raise SimilarityIndexIncompatibleError("Qdrant query response is malformed.")
    candidates: list[SimilarityCandidate] = []
    seen: set[str] = set()
    for row in rows:
        payload = _field(row, "payload")
        stable_id = (
            _field(payload, "stable_id") if isinstance(payload, Mapping) else None
        )
        score = _field(row, "score")
        point_id = _field(row, "id")
        if (
            not isinstance(payload, Mapping)
            or not isinstance(stable_id, str)
            or not stable_id
            or stable_id in seen
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or not isinstance(point_id, (str, int))
        ):
            raise SimilarityIndexIncompatibleError(
                "Qdrant query response contains an invalid vector candidate."
            )
        if payload.get("kind") != "vector":
            raise SimilarityIndexIncompatibleError(
                "Qdrant query response included a non-vector record."
            )
        seen.add(stable_id)
        candidates.append(
            SimilarityCandidate(
                stable_id=stable_id,
                score=float(score),
                native_provenance=(("qdrant_point_id", str(point_id)),),
            )
        )
    return tuple(
        sorted(
            candidates, key=lambda candidate: (-candidate.score, candidate.stable_id)
        )
    )[: request.profile.candidate_limit]


@dataclass
class QdrantSimilarityIndex:
    """Strict remote-Qdrant plugin with fixed-root client initialization.

    Parameters
    ----------
    client_factory : QdrantClientFactory
        Injectable Qdrant client factory; tests supply deterministic fakes.
    """

    client_factory: QdrantClientFactory = _default_client_factory
    name: str = "qdrant"
    version: str = PACKAGE_VERSION
    _build: _BuildConfig | None = field(default=None, init=False, repr=False)
    _client: QdrantClientProtocol | None = field(default=None, init=False, repr=False)
    _client_root: Path | None = field(default=None, init=False, repr=False)

    def configuration_json_schema(self) -> dict[str, object]:
        """Return the strict Qdrant plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Shared strict schema with server-only Qdrant settings.
        """

        schema = plugin_json_schema(
            {
                "url": {"type": "string", "minLength": 1},
                "transport": {
                    "type": "string",
                    "enum": ["rest", "grpc"],
                    "default": "rest",
                },
                "grpc_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "api_key_env": {"type": "string", "minLength": 1},
                "api_key_file": {"type": "string", "minLength": 1},
                "namespace": {"type": "string", "minLength": 1},
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_TIMEOUT_SECONDS,
                    "default": _DEFAULT_TIMEOUT_SECONDS,
                },
                "write_ordering": {
                    "type": "string",
                    "enum": ["weak", "medium", "strong"],
                    "default": "strong",
                },
                "read_consistency": {
                    "type": "string",
                    "enum": ["majority", "quorum", "all"],
                    "default": "majority",
                },
                "hnsw_m": {
                    "type": "integer",
                    "minimum": _MIN_HNSW_M,
                    "maximum": _MAX_HNSW_M,
                    "default": _DEFAULT_HNSW_M,
                },
                "hnsw_ef_construct": {
                    "type": "integer",
                    "minimum": _MIN_HNSW_EF_CONSTRUCT,
                    "maximum": _MAX_HNSW_EF_CONSTRUCT,
                    "default": _DEFAULT_HNSW_EF_CONSTRUCT,
                },
                "on_disk": {"type": "boolean", "default": False},
                "upload_batch_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_UPLOAD_BATCH_SIZE,
                    "default": _DEFAULT_UPLOAD_BATCH_SIZE,
                },
            }
        )
        schema["required"] = ["url", "namespace"]
        return schema

    def configure(self, config: Mapping[str, object]) -> None:
        """Validate and retain configuration without contacting Qdrant.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Plugin-scoped Qdrant configuration.

        Returns
        -------
        None
            The validated credential-free configuration is retained.
        """

        self._build = _build_config(config)

    def spec(self, config: Mapping[str, object]) -> SimilarityIndexSpec:
        """Return a credential-free Qdrant build specification.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Plugin-scoped Qdrant configuration.

        Returns
        -------
        codira.contracts.SimilarityIndexSpec
            Configuration-sensitive derived-index specification.
        """

        build = _build_config(config)
        self._build = build
        fingerprint_payload = {
            "distance": VECTOR_DISTANCE,
            "format_version": FORMAT_VERSION,
            "hnsw_ef_construct": build.hnsw_ef_construct,
            "hnsw_m": build.hnsw_m,
            "on_disk": build.on_disk,
        }
        fingerprint = json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":")
        )
        return SimilarityIndexSpec(
            index=self.name,
            index_version=self.version,
            format_version=FORMAT_VERSION,
            build_fingerprint=hashlib.sha256(fingerprint.encode()).hexdigest(),
        )

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """Initialize and probe one credentialed client for a fixed repository root.

        Parameters
        ----------
        root : pathlib.Path
            Fixed repository root, retained for the protocol boundary.
        config : collections.abc.Mapping[str, object]
            Plugin-scoped Qdrant configuration.

        Returns
        -------
        None
            A command-scoped client has passed a credential-free availability probe.

        Raises
        ------
        SimilarityIndexAuthenticationError
            If no safe configured credential is usable or the server rejects it.
        SimilarityIndexUnavailableError
            If the client cannot be constructed or the server cannot be probed.
        """

        build = _build_config(config)
        resolved_root = root.resolve()
        if self._client is not None and self._client_root == resolved_root:
            self._build = build
            return
        credential = _resolve_api_key(build)
        try:
            client = self.client_factory(build.settings, credential)
            client.info()
        except SimilarityIndexAuthenticationError:
            raise
        except Exception as error:
            _raise_mapped_client_error(error)
        _load_or_create_repository_id(resolved_root)
        _ensure_ownership_ledger(resolved_root)
        self._build = build
        self._client = client
        self._client_root = resolved_root

    def rebuild(
        self, snapshot: VectorSnapshot, identity: SimilarityIndexIdentity
    ) -> None:
        """Build and atomically publish one verified immutable Qdrant revision.

        Parameters
        ----------
        snapshot : codira.contracts.VectorSnapshot
            Authoritative vector snapshot that later phases will publish.
        identity : codira.contracts.SimilarityIndexIdentity
            Root-bound Qdrant identity that later phases will verify.

        Returns
        -------
        None
            The stable object-type alias points to the verified new collection.

        Raises
        ------
        SimilarityIndexIncompatibleError
            If the initialized root or authoritative identity cannot match.
        SimilarityIndexPublicationError
            If creation, upload, verification, or alias publication fails.
        """

        if self._client is None or self._client_root is None or self._build is None:
            raise SimilarityIndexUnavailableError(
                "Qdrant rebuild requires successful client initialization."
            )
        if identity.root.resolve() != self._client_root:
            raise SimilarityIndexIncompatibleError(
                "Qdrant rebuild identity does not match the initialized repository root."
            )
        if snapshot.metadata.identity != identity.vector_set:
            raise SimilarityIndexIncompatibleError(
                "Qdrant snapshot identity does not match the selected vector set."
            )
        if snapshot.metadata.object_type not in {"symbol", "documentation"}:
            raise SimilarityIndexIncompatibleError(
                "Qdrant rebuild supports symbol and documentation snapshots only."
            )
        if snapshot.metadata.row_count != len(snapshot.rows):
            raise SimilarityIndexIncompatibleError(
                "Qdrant snapshot row count does not match its authoritative rows."
            )
        repository_id = _load_or_create_repository_id(identity.root)
        remote = _remote_artifact_identity(
            identity,
            self._build,
            repository_id,
            object_type=snapshot.metadata.object_type,
            source_revision=snapshot.metadata.revision,
        )
        try:
            _create_collection(self._client, remote, snapshot, self._build)
            _write_points(
                self._client,
                remote,
                _publication_points(remote, snapshot),
                self._build,
            )
            _verify_collection(self._client, remote, snapshot)
            previous = _publish_alias(self._client, remote)
            obsolete = _record_publication(identity.root, remote, snapshot, previous)
            _retire_verified_collections(self._client, obsolete)
        except (
            SimilarityIndexAuthenticationError,
            SimilarityIndexIncompatibleError,
            SimilarityIndexPublicationError,
            SimilarityIndexUnavailableError,
            SimilarityIndexUnsafeOwnershipError,
        ):
            raise
        except Exception as error:
            raise SimilarityIndexPublicationError(
                "Qdrant immutable revision publication failed before alias replacement."
            ) from error

    def search(self, request: SimilaritySearchRequest) -> SimilaritySearchResult:
        """Search one verified immutable Qdrant revision without vector fallback.

        Parameters
        ----------
        request : codira.contracts.SimilaritySearchRequest
            Query request that later phases will bind to a verified collection.

        Returns
        -------
        codira.contracts.SimilaritySearchResult
            Typed bounded candidates with credential-free native provenance.

        Raises
        ------
        SimilarityIndexUnavailableError
            If initialization or a remote query is unavailable.
        SimilarityIndexStaleError
            If the selected source revision is not the published alias target.
        """

        if self._client is None or self._client_root is None or self._build is None:
            raise SimilarityIndexUnavailableError(
                "Qdrant search requires successful client initialization."
            )
        if request.identity.root.resolve() != self._client_root:
            raise SimilarityIndexIncompatibleError(
                "Qdrant search identity does not match the initialized repository root."
            )
        if request.snapshot.metadata.identity != request.identity.vector_set:
            raise SimilarityIndexIncompatibleError(
                "Qdrant search snapshot identity does not match the selected vector set."
            )
        if request.snapshot.metadata.object_type not in {"symbol", "documentation"}:
            raise SimilarityIndexIncompatibleError(
                "Qdrant search supports symbol and documentation snapshots only."
            )
        repository_id = _load_or_create_repository_id(request.identity.root)
        remote = _remote_artifact_identity(
            request.identity,
            self._build,
            repository_id,
            object_type=request.snapshot.metadata.object_type,
            source_revision=request.snapshot.metadata.revision,
        )
        collection_name = _verified_search_collection(
            self._client, remote, request.snapshot
        )
        candidates = _search_points(self._client, collection_name, request, self._build)
        return SimilaritySearchResult(
            query=SimilarityQueryProvenance(
                plugin_name=self.name,
                plugin_version=self.version,
                object_type=request.snapshot.metadata.object_type,
                source_revision=request.snapshot.metadata.revision,
                profile_name=request.profile.name,
                candidate_limit=request.profile.candidate_limit,
                artifact_hash=remote.artifact_hash,
                transport=self._build.settings.transport,
                native_provenance=(
                    ("qdrant_alias_hash", _opaque_hash(remote.alias_name)),
                    ("qdrant_collection_hash", _opaque_hash(collection_name)),
                ),
            ),
            candidates=candidates,
        )

    def purge(self, request: SimilarityPurgeRequest) -> SimilarityPurgeResult:
        """Preview or remove only remotely manifest-verified Qdrant artifacts.

        Parameters
        ----------
        request : codira.contracts.SimilarityPurgeRequest
            Cleanup request that later phases will validate against ownership evidence.

        Returns
        -------
        codira.contracts.SimilarityPurgeResult
            Opaque removed and retained artifact identities.

        Raises
        ------
        SimilarityIndexUnsafeOwnershipError
            If local ownership evidence is malformed or belongs to another root.
        SimilarityIndexCleanupError
            If a verified remote collection cannot be deleted.
        """

        if self._client is None or self._client_root is None:
            raise SimilarityIndexUnavailableError(
                "Qdrant purge requires successful client initialization."
            )
        if request.root.resolve() != self._client_root or (
            request.identity.root.resolve() != self._client_root
        ):
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant purge root does not match the initialized repository."
            )
        if request.identity.index.index != self.name:
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant purge identity does not select the Qdrant plugin."
            )
        try:
            document = json.loads(
                _ownership_ledger_path(self._client_root).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant ownership ledger is unavailable or invalid."
            ) from error
        records = document.get("records") if isinstance(document, dict) else None
        if not isinstance(records, list):
            raise SimilarityIndexUnsafeOwnershipError(
                "Qdrant ownership ledger is invalid."
            )
        removable: list[tuple[str, str]] = []
        skipped: list[str] = []
        for group in records:
            collections = (
                group.get("retained_collections") if isinstance(group, dict) else None
            )
            if not isinstance(collections, list):
                raise SimilarityIndexUnsafeOwnershipError(
                    "Qdrant ownership ledger contains an invalid collection record."
                )
            for record in collections:
                if not isinstance(record, dict):
                    raise SimilarityIndexUnsafeOwnershipError(
                        "Qdrant ownership ledger contains an invalid collection record."
                    )
                collection = record.get("collection_name")
                manifest_id = record.get("manifest_point_id")
                artifact_hash = record.get("artifact_hash")
                if (
                    not isinstance(collection, str)
                    or not collection
                    or not isinstance(manifest_id, str)
                    or not manifest_id
                    or not isinstance(artifact_hash, str)
                    or not artifact_hash
                ):
                    raise SimilarityIndexUnsafeOwnershipError(
                        "Qdrant ownership ledger contains an unsafe collection record."
                    )
                try:
                    rows = self._client.retrieve(
                        collection, [manifest_id], with_payload=True, with_vectors=False
                    )
                except Exception as error:
                    _raise_mapped_client_error(error)
                payload = (
                    _field(rows[0], "payload")
                    if isinstance(rows, list) and len(rows) == 1
                    else None
                )
                required = (
                    "artifact_hash",
                    "repository_id_hash",
                    "root_hash",
                    "source_revision",
                    "object_type",
                )
                if not isinstance(payload, Mapping) or any(
                    payload.get(key) != record.get(key) for key in required
                ):
                    skipped.append(artifact_hash)
                    continue
                removable.append((collection, artifact_hash))
        if not request.preview:
            for collection, artifact_hash in removable:
                try:
                    deleted = self._client.delete_collection(collection)
                except Exception as error:
                    _raise_mapped_client_error(error)
                if deleted is False:
                    raise SimilarityIndexCleanupError(
                        "Qdrant refused deletion of a verified derived collection."
                    )
            try:
                _ownership_ledger_path(self._client_root).unlink()
            except OSError as error:
                raise SimilarityIndexCleanupError(
                    "Qdrant ownership ledger could not be removed after remote cleanup."
                ) from error
        return SimilarityPurgeResult(
            index=self.name,
            preview=request.preview,
            removed_artifact_hashes=tuple(
                sorted(hash_value for _, hash_value in removable)
            ),
            skipped_artifact_hashes=tuple(sorted(skipped)),
        )

    def reset_runtime_caches(self) -> None:
        """Discard retained configuration and the command-scoped client cache.

        Parameters
        ----------
        None

        Returns
        -------
        None
            No remote client or credential is retained.
        """

        self._build = None
        self._client = None
        self._client_root = None


def build_similarity_index() -> QdrantSimilarityIndex:
    """Build the first-party Qdrant similarity-index plugin.

    Parameters
    ----------
    None

    Returns
    -------
    QdrantSimilarityIndex
        Fresh strict server-only similarity-index plugin instance.
    """

    return QdrantSimilarityIndex()
