"""Tests for the strict, fake-client Qdrant similarity-index foundation."""

from __future__ import annotations

import json
from pathlib import Path
import struct
from typing import TYPE_CHECKING

import pytest

from codira.contracts import (
    SimilarityIndexAuthenticationError,
    SimilarityIndexUnavailableError,
)
from codira_similarity_index_qdrant import (
    QdrantClientSettings,
    QdrantSimilarityIndex,
    _build_config,
    _load_or_create_repository_id,
    _manifest_point_id,
    _ownership_ledger_path,
    _point_id,
    _remote_artifact_identity,
    build_similarity_index,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class _FakeQdrantClient:
    """Deterministic fake satisfying the minimal internal client protocol."""

    def __init__(self, *, probe_error: Exception | None = None) -> None:
        """Initialize a fake client with an optional probe failure.

        Parameters
        ----------
        probe_error : Exception | None, optional
            Error raised by ``info`` to test credential-free mapping.

        Returns
        -------
        None
            The fake starts with no observed server probes.
        """

        self.probe_error = probe_error
        self.probe_count = 0

    def get_collections(self) -> object:
        """Return a deterministic client-native stand-in.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Stable fake collection payload.
        """

        return {"collections": []}

    def info(self) -> object:
        """Record one deterministic server probe.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Stable server information when no probe failure was configured.

        Raises
        ------
        Exception
            Configured probe error for deterministic failure tests.
        """

        self.probe_count += 1
        if self.probe_error is not None:
            raise self.probe_error
        return {"version": "fake"}

    def create_collection(
        self,
        collection_name: str,
        *,
        vectors_config: object,
        hnsw_config: object,
        on_disk_payload: bool,
    ) -> object:
        """Accept a deterministic collection request without retaining it.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.
        vectors_config : object
            Client-native vector settings.
        hnsw_config : object
            Client-native HNSW settings.
        on_disk_payload : bool
            Payload-storage policy.

        Returns
        -------
        object
            Successful fake creation result.
        """

        del collection_name, vectors_config, hnsw_config, on_disk_payload
        return True

    def upsert(
        self,
        collection_name: str,
        points: object,
        *,
        wait: bool,
        ordering: object,
    ) -> object:
        """Accept a deterministic point batch without retaining it.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.
        points : object
            Client-native point batch.
        wait : bool
            Confirmed-write flag.
        ordering : object
            Client-native write ordering.

        Returns
        -------
        object
            Successful fake update result.
        """

        del collection_name, points, wait, ordering
        return {"status": "completed"}

    def get_collection(self, collection_name: str) -> object:
        """Return a deterministic placeholder collection observation.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.

        Returns
        -------
        object
            Fake collection metadata.
        """

        del collection_name
        return {"status": "green"}

    def get_aliases(self) -> object:
        """Return no existing aliases for foundation/client tests.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Empty fake alias collection.
        """

        return {"aliases": []}

    def update_collection_aliases(self, change_aliases_operations: object) -> object:
        """Accept a fake atomic alias replacement.

        Parameters
        ----------
        change_aliases_operations : object
            Client-native alias operation sequence.

        Returns
        -------
        object
            Successful fake alias update result.
        """

        del change_aliases_operations
        return True

    def retrieve(
        self,
        collection_name: str,
        ids: list[str],
        *,
        with_payload: bool,
        with_vectors: bool,
    ) -> object:
        """Return no records for non-publication fake usage.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.
        ids : list[str]
            Requested point IDs.
        with_payload : bool
            Payload request flag.
        with_vectors : bool
            Vector request flag.

        Returns
        -------
        object
            Empty fake record collection.
        """

        del collection_name, ids, with_payload, with_vectors
        return []

    def delete_collection(self, collection_name: str) -> object:
        """Accept non-publication fake deletion requests.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.

        Returns
        -------
        object
            Successful fake deletion result.
        """

        del collection_name
        return True

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
        """Return an empty deterministic query response for foundation tests.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.
        query : list[float]
            Query vector.
        query_filter : object
            Native vector-only filter.
        search_params : object
            Native HNSW parameters.
        limit : int
            Candidate limit.
        with_payload : bool
            Payload flag.
        with_vectors : bool
            Vector flag.
        score_threshold : float
            Minimum score.
        consistency : object
            Read consistency setting.

        Returns
        -------
        object
            Empty Qdrant-shaped query result.
        """

        del (
            collection_name,
            query,
            query_filter,
            search_params,
            limit,
            with_payload,
            with_vectors,
            score_threshold,
            consistency,
        )
        return {"points": []}


class _PublicationFakeQdrantClient(_FakeQdrantClient):
    """In-memory fake that records immutable Qdrant publication operations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The fake starts with no collections, aliases, or point batches.
    """

    def __init__(self) -> None:
        """Initialize mutable fake remote publication state.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Empty collection and alias maps are ready for deterministic tests.
        """

        super().__init__()
        self.collections: dict[str, list[object]] = {}
        self.collection_dimensions: dict[str, int] = {}
        self.aliases: dict[str, str] = {}
        self.upserts: list[tuple[str, list[object], bool, object]] = []
        self.queries: list[dict[str, object]] = []
        self.query_response: list[object] = []

    def create_collection(
        self,
        collection_name: str,
        *,
        vectors_config: object,
        hnsw_config: object,
        on_disk_payload: bool,
    ) -> object:
        """Create one recorded collection with its configured vector dimension.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.
        vectors_config : object
            Native vector configuration with a size field.
        hnsw_config : object
            Native HNSW configuration.
        on_disk_payload : bool
            Payload storage setting.

        Returns
        -------
        object
            Successful fake creation result.
        """

        del hnsw_config, on_disk_payload
        self.collections[collection_name] = []
        self.collection_dimensions[collection_name] = int(
            getattr(vectors_config, "size")
        )
        return True

    def upsert(
        self,
        collection_name: str,
        points: object,
        *,
        wait: bool,
        ordering: object,
    ) -> object:
        """Record one confirmed native point batch.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.
        points : object
            Native Qdrant point sequence.
        wait : bool
            Confirmed-write flag.
        ordering : object
            Native write ordering.

        Returns
        -------
        object
            Successful fake update result.
        """

        assert isinstance(points, list)
        self.collections[collection_name].extend(points)
        self.upserts.append((collection_name, points, wait, ordering))
        return {"status": "completed"}

    def get_collection(self, collection_name: str) -> object:
        """Return verification metadata for one recorded collection.

        Parameters
        ----------
        collection_name : str
            Opaque physical collection name.

        Returns
        -------
        object
            Green cosine collection metadata with exact point count.
        """

        return {
            "points_count": len(self.collections[collection_name]),
            "status": "green",
            "config": {
                "params": {
                    "vectors": {
                        "size": self.collection_dimensions[collection_name],
                        "distance": "cosine",
                    }
                }
            },
        }

    def get_aliases(self) -> object:
        """Return the deterministic current alias inventory.

        Parameters
        ----------
        None

        Returns
        -------
        object
            Qdrant-shaped alias rows.
        """

        return {
            "aliases": [
                {"alias_name": name, "collection_name": collection}
                for name, collection in sorted(self.aliases.items())
            ]
        }

    def update_collection_aliases(self, change_aliases_operations: object) -> object:
        """Apply native delete/create alias operations atomically in memory.

        Parameters
        ----------
        change_aliases_operations : object
            Native Qdrant alias operation sequence.

        Returns
        -------
        object
            Successful fake alias update result.
        """

        assert isinstance(change_aliases_operations, list)
        updated = dict(self.aliases)
        for operation in change_aliases_operations:
            deleted = getattr(operation, "delete_alias", None)
            created = getattr(operation, "create_alias", None)
            if deleted is not None:
                updated.pop(str(deleted.alias_name), None)
            if created is not None:
                updated[str(created.alias_name)] = str(created.collection_name)
        self.aliases = updated
        return True

    def retrieve(
        self,
        collection_name: str,
        ids: list[str],
        *,
        with_payload: bool,
        with_vectors: bool,
    ) -> object:
        """Return recorded points matching exact IDs.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.
        ids : list[str]
            Requested deterministic point IDs.
        with_payload : bool
            Payload request flag.
        with_vectors : bool
            Vector request flag.

        Returns
        -------
        object
            Qdrant-shaped records with payload only.
        """

        del with_payload, with_vectors
        return [
            {"payload": getattr(point, "payload")}
            for point in self.collections[collection_name]
            if str(getattr(point, "id")) in ids
        ]

    def delete_collection(self, collection_name: str) -> object:
        """Delete one recorded exact-owned fake collection.

        Parameters
        ----------
        collection_name : str
            Opaque collection name.

        Returns
        -------
        object
            Successful fake deletion result.
        """

        del self.collections[collection_name]
        del self.collection_dimensions[collection_name]
        return True

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
        """Record one fake vector-only Qdrant query response.

        Parameters
        ----------
        collection_name : str
            Verified physical collection target.
        query : list[float]
            Query vector supplied by the selected embedding engine.
        query_filter : object
            Native vector-record filter.
        search_params : object
            Native HNSW per-query settings.
        limit : int
            Requested candidate bound.
        with_payload : bool
            Whether candidate payloads were requested.
        with_vectors : bool
            Whether source vectors were requested.
        score_threshold : float
            Minimum accepted score.
        consistency : object
            Read consistency sent to Qdrant.

        Returns
        -------
        object
            Qdrant-shaped response containing configured scored points.
        """

        self.queries.append(
            {
                "collection_name": collection_name,
                "query": query,
                "query_filter": query_filter,
                "search_params": search_params,
                "limit": limit,
                "with_payload": with_payload,
                "with_vectors": with_vectors,
                "score_threshold": score_threshold,
                "consistency": consistency,
            }
        )
        return {"points": self.query_response}


def _valid_config(**overrides: object) -> dict[str, object]:
    """Return a complete valid foundation-phase Qdrant configuration.

    Parameters
    ----------
    **overrides : object
        Configuration values overriding the stable baseline.

    Returns
    -------
    dict[str, object]
        Valid plugin configuration mapping.
    """

    config: dict[str, object] = {
        "url": "https://qdrant.example.test/",
        "namespace": "team-a",
        "api_key_env": "QDRANT_API_KEY",
    }
    config.update(overrides)
    return config


def test_factory_and_schema_publish_server_only_contract() -> None:
    """Expose the entry point and strict required server configuration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the foundation is discoverable without a live client.
    """
    index = build_similarity_index()
    schema = index.configuration_json_schema()
    properties = schema["properties"]

    assert index.name == "qdrant"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["url", "namespace"]
    assert isinstance(properties, dict)
    assert {
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
    } <= set(properties)


def test_configuration_is_validated_without_constructing_a_client() -> None:
    """Keep strict configuration validation independent of server availability.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the injected factory receives no call during validation.
    """
    calls: list[tuple[QdrantClientSettings, str]] = []

    def factory(settings: QdrantClientSettings, api_key: str) -> _FakeQdrantClient:
        """Record impossible-to-use credentials if lifecycle code invokes the factory.

        Parameters
        ----------
        settings : QdrantClientSettings
            Validated remote client settings.
        api_key : str
            Deferred credential value.

        Returns
        -------
        _FakeQdrantClient
            Deterministic fake client.
        """

        calls.append((settings, api_key))
        return _FakeQdrantClient()

    index = QdrantSimilarityIndex(client_factory=factory)
    index.configure(_valid_config())
    spec = index.spec(_valid_config(url="https://qdrant.example.test"))

    assert calls == []
    assert spec.index == "qdrant"
    assert spec.build_fingerprint


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": ":memory:"}, "remote HTTP"),
        ({"url": "./qdrant"}, "remote HTTP"),
        ({"url": "ftp://qdrant.example.test"}, "remote HTTP"),
        ({"url": "https://qdrant.example.test:invalid"}, "remote port"),
        ({"url": "https://user:password@qdrant.example.test"}, "credential-free"),
        ({"transport": "embedded"}, "transport"),
        ({"grpc_port": 0}, "grpc_port"),
        ({"namespace": "   "}, "namespace"),
        ({"timeout_seconds": 121}, "timeout_seconds"),
        ({"write_ordering": "eventual"}, "write_ordering"),
        ({"read_consistency": 2}, "read_consistency"),
        ({"hnsw_m": 3}, "hnsw_m"),
        ({"hnsw_ef_construct": 1025}, "hnsw_ef_construct"),
        ({"on_disk": "yes"}, "on_disk"),
        ({"upload_batch_size": 1001}, "upload_batch_size"),
        ({"typo": True}, "does not accept"),
    ],
)
def test_configuration_rejects_unsafe_or_unbounded_values(
    overrides: Mapping[str, object], message: str
) -> None:
    """Reject invalid Qdrant settings before any possible client operation.

    Parameters
    ----------
    overrides : collections.abc.Mapping[str, object]
        Invalid configuration override mapping.
    message : str
        Stable expected validation-message fragment.

    Returns
    -------
    None
        The test asserts strict local validation.
    """
    with pytest.raises(ValueError, match=message):
        QdrantSimilarityIndex().configure(_valid_config(**dict(overrides)))


def test_safety_defaults_and_cosine_spec_are_deterministic() -> None:
    """Preserve approved safety defaults and credential-free build identity.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts URL and credential sources do not change the spec.
    """
    first = QdrantSimilarityIndex().spec(_valid_config())
    second = QdrantSimilarityIndex().spec(
        _valid_config(
            url="https://another-qdrant.example.test",
            api_key_file=".secrets/qdrant-key",
        )
    )
    schema = QdrantSimilarityIndex().configuration_json_schema()
    properties = schema["properties"]

    assert first.build_fingerprint == second.build_fingerprint
    assert isinstance(properties, dict)
    assert properties["write_ordering"]["default"] == "strong"
    assert properties["read_consistency"]["default"] == "majority"
    assert properties["upload_batch_size"]["maximum"] == 1000


@pytest.mark.parametrize("read_consistency", ["majority", "quorum", "all"])
@pytest.mark.parametrize("write_ordering", ["weak", "medium", "strong"])
def test_qdrant_consistency_values_are_explicit_and_accepted(
    read_consistency: str, write_ordering: str
) -> None:
    """Accept each portable read and documented write consistency value.

    Parameters
    ----------
    read_consistency : str
        Portable Qdrant read consistency value.
    write_ordering : str
        Qdrant write ordering value.

    Returns
    -------
    None
        The test asserts explicit values survive strict configuration validation.
    """
    QdrantSimilarityIndex().configure(
        _valid_config(
            read_consistency=read_consistency,
            write_ordering=write_ordering,
        )
    )


def test_foundation_lifecycle_methods_fail_closed() -> None:
    """Prevent accidental remote lifecycle use before the owning phases land.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts every unimplemented lifecycle operation is unavailable.
    """
    index = QdrantSimilarityIndex()

    with pytest.raises(SimilarityIndexUnavailableError, match="rebuild"):
        index.rebuild(None, None)  # type: ignore[arg-type]
    with pytest.raises(SimilarityIndexUnavailableError, match="search"):
        index.search(None)  # type: ignore[arg-type]
    with pytest.raises(SimilarityIndexUnavailableError, match="purge"):
        index.purge(None)  # type: ignore[arg-type]


def test_initialize_prefers_nonempty_environment_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prefer a non-empty environment credential without retaining its value.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        The fake factory observes the environment credential and one probe.
    """

    credential_file = tmp_path / "qdrant-key"
    credential_file.write_text("file-credential\n", encoding="utf-8")
    credential_file.chmod(0o600)
    monkeypatch.setenv("QDRANT_API_KEY", "environment-credential")
    calls: list[tuple[QdrantClientSettings, str, _FakeQdrantClient]] = []

    def factory(settings: QdrantClientSettings, api_key: str) -> _FakeQdrantClient:
        """Record the deferred client construction arguments.

        Parameters
        ----------
        settings : QdrantClientSettings
            Normalized server settings.
        api_key : str
            Resolved credential used only by the fake client.

        Returns
        -------
        _FakeQdrantClient
            Probeable deterministic client.
        """

        client = _FakeQdrantClient()
        calls.append((settings, api_key, client))
        return client

    index = QdrantSimilarityIndex(client_factory=factory)
    index.initialize(
        tmp_path,
        _valid_config(
            api_key_file=str(credential_file), transport="grpc", grpc_port=7444
        ),
    )
    index.initialize(tmp_path, _valid_config(api_key_file=str(credential_file)))

    assert len(calls) == 1
    settings, credential, client = calls[0]
    assert credential == "environment-credential"
    assert settings.transport == "grpc"
    assert settings.grpc_port == 7444
    assert client.probe_count == 1
    assert "environment-credential" not in repr(index)


def test_initialize_falls_back_to_private_file_and_resets_client_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Read a private file after an empty environment source and discard the cache.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        The fake factory receives the terminal-line-ending-normalized file key.
    """

    credential_file = tmp_path / "qdrant-key"
    credential_file.write_text("file-credential\r\n", encoding="utf-8")
    credential_file.chmod(0o600)
    monkeypatch.setenv("QDRANT_API_KEY", " ")
    credentials: list[str] = []

    def factory(settings: QdrantClientSettings, api_key: str) -> _FakeQdrantClient:
        """Capture a resolved credential for the fake client.

        Parameters
        ----------
        settings : QdrantClientSettings
            Normalized server settings.
        api_key : str
            Resolved credential supplied to the fake client.

        Returns
        -------
        _FakeQdrantClient
            Probeable deterministic client.
        """

        del settings
        credentials.append(api_key)
        return _FakeQdrantClient()

    config = _valid_config(api_key_file=str(credential_file))
    index = QdrantSimilarityIndex(client_factory=factory)
    index.initialize(tmp_path, config)
    index.reset_runtime_caches()
    index.initialize(tmp_path, config)

    assert credentials == ["file-credential", "file-credential"]


@pytest.mark.parametrize("mode", [0o640, 0o604])
def test_initialize_rejects_unsafe_credential_file_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: int
) -> None:
    """Reject group- or world-accessible credential files before client creation.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.
    mode : int
        Unsafe POSIX permission mode.

    Returns
    -------
    None
        Unsafe local credential sources raise a typed credential-free error.
    """

    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    credential_file = tmp_path / "qdrant-key"
    credential_file.write_text("file-credential", encoding="utf-8")
    credential_file.chmod(mode)

    with pytest.raises(SimilarityIndexAuthenticationError, match="permissions"):
        QdrantSimilarityIndex().initialize(
            tmp_path, _valid_config(api_key_env=None, api_key_file=str(credential_file))
        )


def test_initialize_maps_probe_authentication_without_server_detail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Map an authentication response without leaking exception content.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        A 401-like fake error becomes a stable authentication failure.
    """

    class _RejectedResponse(Exception):
        """Fake response with an authentication status and sensitive detail."""

        status_code = 401

    monkeypatch.setenv("QDRANT_API_KEY", "credential-that-must-not-leak")
    index = QdrantSimilarityIndex(
        client_factory=lambda settings, api_key: _FakeQdrantClient(
            probe_error=_RejectedResponse("credential-that-must-not-leak")
        )
    )

    with pytest.raises(SimilarityIndexAuthenticationError) as error:
        index.initialize(tmp_path, _valid_config())

    assert "credential-that-must-not-leak" not in str(error.value)


def test_repository_identity_and_ownership_ledger_are_stable_across_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the repository UUID while reset clears only runtime client state.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        The persistent UUID and empty credential-free ledger remain stable.
    """

    monkeypatch.setenv("QDRANT_API_KEY", "credential")
    index = QdrantSimilarityIndex(
        client_factory=lambda settings, api_key: _FakeQdrantClient()
    )
    index.initialize(tmp_path, _valid_config())
    first = _load_or_create_repository_id(tmp_path)
    index.reset_runtime_caches()
    second = _load_or_create_repository_id(tmp_path)
    ledger_path = _ownership_ledger_path(tmp_path)

    assert first == second
    assert (
        ledger_path.read_text(encoding="utf-8") == '{"records":[],"schema_version":1}\n'
    )


def test_remote_identity_uses_opaque_names_and_deterministic_point_ids(
    tmp_path: Path,
) -> None:
    """Bind remote identities to every required source dimension without leakage.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        Alias, collection, manifest, and row point identifiers are deterministic.
    """

    from codira.contracts import (
        EmbeddingEngineSpec,
        SimilarityIndexIdentity,
        SimilarityIndexSpec,
        VectorSetIdentity,
        VectorStoreSpec,
    )

    root = tmp_path / "repository with spaces"
    root.mkdir()
    identity = SimilarityIndexIdentity(
        root=root,
        vector_set=VectorSetIdentity(
            EmbeddingEngineSpec("engine", "1", "model/name", "r1", 3),
            VectorStoreSpec("store", "1", "1"),
        ),
        index=SimilarityIndexSpec("qdrant", "2.0.0", "1", "build-hash"),
    )
    config = _valid_config(
        url="https://qdrant.example.test:7443/base",
        namespace="operator namespace",
        hnsw_m=24,
        hnsw_ef_construct=200,
        on_disk=True,
    )
    remote = _remote_artifact_identity(
        identity,
        _build_config(config),
        _load_or_create_repository_id(root),
        object_type="symbol",
        source_revision=7,
    )

    assert remote.alias_name.startswith("codira-qdrant-a-")
    assert remote.collection_name.startswith("codira-qdrant-r-")
    assert all(
        value not in remote.collection_name
        for value in ("repository", "namespace", "qdrant.example")
    )
    assert _point_id(remote, "stable-id") == _point_id(remote, "stable-id")
    assert _point_id(remote, "stable-id") != _manifest_point_id(remote)


def test_rebuild_publishes_verified_immutable_revisions_and_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Publish manifest/vector batches before atomically replacing one alias.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated environment mutation fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        Two source revisions retain distinct physical collections and one alias.
    """

    from codira.contracts import (
        EmbeddingEngineSpec,
        SimilarityIndexIdentity,
        VectorSetIdentity,
        VectorSnapshot,
        VectorSnapshotMetadata,
        VectorStoreSpec,
        StoredVectorRow,
    )

    monkeypatch.setenv("QDRANT_API_KEY", "credential")
    fake = _PublicationFakeQdrantClient()
    index = QdrantSimilarityIndex(client_factory=lambda settings, api_key: fake)
    config = _valid_config(upload_batch_size=2, write_ordering="strong")
    vector_set = VectorSetIdentity(
        EmbeddingEngineSpec("engine", "1", "model", "r1", 2),
        VectorStoreSpec("store", "1", "1"),
    )
    identity = SimilarityIndexIdentity(tmp_path, vector_set, index.spec(config))
    index.initialize(tmp_path, config)

    def snapshot(revision: int) -> VectorSnapshot:
        """Create a stable two-row authoritative snapshot for one revision.

        Parameters
        ----------
        revision : int
            Durable source revision to publish.

        Returns
        -------
        codira.contracts.VectorSnapshot
            Deterministic source rows with two-dimensional float32 vectors.
        """

        rows = (
            StoredVectorRow(
                "symbol", "stable-a", "hash-a", 2, struct.pack("<2f", 1, 0)
            ),
            StoredVectorRow(
                "symbol", "stable-b", "hash-b", 2, struct.pack("<2f", 0, 1)
            ),
        )
        return VectorSnapshot(
            VectorSnapshotMetadata(vector_set, revision, "symbol", 2), rows
        )

    index.rebuild(snapshot(1), identity)
    first_alias = next(iter(fake.aliases))
    first_collection = fake.aliases[first_alias]
    index.rebuild(snapshot(2), identity)
    second_collection = fake.aliases[first_alias]
    index.rebuild(snapshot(3), identity)

    assert len(fake.collections) == 2
    assert fake.aliases[first_alias] != first_collection
    assert fake.aliases[first_alias] != second_collection
    assert first_collection not in fake.collections
    assert all(wait is True for _, _, wait, _ in fake.upserts)
    assert all(len(points) <= 2 for _, points, _, _ in fake.upserts)
    ledger = json.loads(_ownership_ledger_path(tmp_path).read_text(encoding="utf-8"))
    assert [
        item["collection_name"] for item in ledger["records"][0]["retained_collections"]
    ] == [
        fake.aliases[first_alias],
        second_collection,
    ]
    assert "qdrant.example" not in json.dumps(ledger)


def test_search_verifies_revision_and_maps_profile_to_native_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Search only the verified immutable revision with bounded native settings.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated API-key environment fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        The typed result retains deterministic Qdrant candidate provenance.
    """

    from codira.contracts import (
        EmbeddingEngineSpec,
        SimilarityIndexIdentity,
        SimilaritySearchProfile,
        SimilaritySearchRequest,
        StoredVectorRow,
        VectorSetIdentity,
        VectorSnapshot,
        VectorSnapshotMetadata,
        VectorStoreSpec,
    )

    monkeypatch.setenv("QDRANT_API_KEY", "credential")
    fake = _PublicationFakeQdrantClient()
    index = QdrantSimilarityIndex(client_factory=lambda settings, api_key: fake)
    config = _valid_config(read_consistency="quorum")
    vector_set = VectorSetIdentity(
        EmbeddingEngineSpec("engine", "1", "model", "r1", 2),
        VectorStoreSpec("store", "1", "1"),
    )
    identity = SimilarityIndexIdentity(tmp_path, vector_set, index.spec(config))
    snapshot = VectorSnapshot(
        VectorSnapshotMetadata(vector_set, 4, "symbol", 2),
        (
            StoredVectorRow(
                "symbol", "stable-a", "hash-a", 2, struct.pack("<2f", 1, 0)
            ),
            StoredVectorRow(
                "symbol", "stable-b", "hash-b", 2, struct.pack("<2f", 0, 1)
            ),
        ),
    )
    index.initialize(tmp_path, config)
    index.rebuild(snapshot, identity)
    collection_name = next(iter(fake.collections))
    vector_points = [
        point
        for point in fake.collections[collection_name]
        if getattr(point, "payload")["kind"] == "vector"
    ]
    fake.query_response = [
        {
            "id": getattr(vector_points[1], "id"),
            "score": 0.7,
            "payload": getattr(vector_points[1], "payload"),
        },
        {
            "id": getattr(vector_points[0], "id"),
            "score": 0.7,
            "payload": getattr(vector_points[0], "payload"),
        },
    ]

    result = index.search(
        SimilaritySearchRequest(
            identity=identity,
            snapshot=snapshot,
            query_vector=(0.5, 0.5),
            profile=SimilaritySearchProfile("fast", 77, 3, 1, 2),
            min_score=0.2,
        )
    )

    assert [candidate.stable_id for candidate in result.candidates] == [
        "stable-a",
        "stable-b",
    ]
    assert result.query.source_revision == 4
    assert result.query.transport == "rest"
    assert fake.queries[0]["collection_name"] == collection_name
    assert fake.queries[0]["limit"] == 3
    assert fake.queries[0]["score_threshold"] == 0.2
    assert fake.queries[0]["consistency"] == "quorum"
    assert fake.queries[0]["with_vectors"] is False
    assert getattr(fake.queries[0]["search_params"], "hnsw_ef") == 77


def test_search_rejects_stale_alias_without_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reject an alias that no longer targets the requested source revision.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated API-key environment fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        The selected Qdrant index fails closed rather than falling back.
    """

    from codira.contracts import (
        EmbeddingEngineSpec,
        SimilarityIndexIdentity,
        SimilarityIndexStaleError,
        SimilaritySearchProfile,
        SimilaritySearchRequest,
        StoredVectorRow,
        VectorSetIdentity,
        VectorSnapshot,
        VectorSnapshotMetadata,
        VectorStoreSpec,
    )

    monkeypatch.setenv("QDRANT_API_KEY", "credential")
    fake = _PublicationFakeQdrantClient()
    index = QdrantSimilarityIndex(client_factory=lambda settings, api_key: fake)
    config = _valid_config()
    vector_set = VectorSetIdentity(
        EmbeddingEngineSpec("engine", "1", "model", "r1", 2),
        VectorStoreSpec("store", "1", "1"),
    )
    identity = SimilarityIndexIdentity(tmp_path, vector_set, index.spec(config))
    snapshot = VectorSnapshot(
        VectorSnapshotMetadata(vector_set, 1, "symbol", 1),
        (StoredVectorRow("symbol", "stable-a", "hash-a", 2, struct.pack("<2f", 1, 0)),),
    )
    index.initialize(tmp_path, config)
    index.rebuild(snapshot, identity)
    fake.aliases = {}

    with pytest.raises(SimilarityIndexStaleError):
        index.search(
            SimilaritySearchRequest(
                identity,
                snapshot,
                (1.0, 0.0),
                SimilaritySearchProfile("p", 10, 1, 1, 1),
            )
        )
    assert not fake.queries


def test_purge_previews_then_deletes_only_manifest_owned_collections(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep foreign manifest state while deleting explicitly confirmed ownership.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Isolated API-key environment fixture.
    tmp_path : pathlib.Path
        Fixed repository root fixture.

    Returns
    -------
    None
        Preview is non-mutating and confirmed cleanup removes exact-owned state.
    """

    from codira.contracts import (
        EmbeddingEngineSpec,
        SimilarityIndexIdentity,
        SimilarityPurgeRequest,
        StoredVectorRow,
        VectorSetIdentity,
        VectorSnapshot,
        VectorSnapshotMetadata,
        VectorStoreSpec,
    )

    monkeypatch.setenv("QDRANT_API_KEY", "credential")
    fake = _PublicationFakeQdrantClient()
    index = QdrantSimilarityIndex(client_factory=lambda settings, api_key: fake)
    config = _valid_config()
    vector_set = VectorSetIdentity(
        EmbeddingEngineSpec("engine", "1", "model", "r1", 2),
        VectorStoreSpec("store", "1", "1"),
    )
    identity = SimilarityIndexIdentity(tmp_path, vector_set, index.spec(config))
    snapshot = VectorSnapshot(
        VectorSnapshotMetadata(vector_set, 1, "symbol", 1),
        (StoredVectorRow("symbol", "stable", "hash", 2, struct.pack("<2f", 1, 0)),),
    )
    index.initialize(tmp_path, config)
    index.rebuild(snapshot, identity)
    collection = next(iter(fake.collections))

    preview = index.purge(SimilarityPurgeRequest(tmp_path, identity))

    assert preview.preview is True
    assert len(preview.removed_artifact_hashes) == 1
    assert collection in fake.collections
    confirmed = index.purge(SimilarityPurgeRequest(tmp_path, identity, preview=False))
    assert confirmed.preview is False
    assert collection not in fake.collections
    assert not _ownership_ledger_path(tmp_path).exists()
