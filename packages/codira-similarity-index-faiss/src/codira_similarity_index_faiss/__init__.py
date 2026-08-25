"""FAISS-backed, repository-local derived similarity indexes for Codira.

The plugin owns only rebuildable FAISS artifacts. Durable vector rows remain in
the selected vector-store plugin and are always supplied as immutable snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import faiss
import numpy as np

from codira.contracts import (
    SimilarityIndexIdentity,
    SimilarityIndexSpec,
    SimilaritySearchRequest,
    VectorSimilarityScore,
    VectorSnapshot,
)
from codira.plugin_config import plugin_json_schema
from codira.storage import get_codira_dir

if TYPE_CHECKING:
    from collections.abc import Mapping

    from codira.contracts import SimilarityIndex

__all__ = [
    "PACKAGE_VERSION",
    "FaissSimilarityIndex",
    "build_similarity_index",
]

PACKAGE_VERSION = "1.68.0"
FORMAT_VERSION = "1"
_METRIC = "inner_product_cosine"
_DEFAULT_HNSW_M = 32
_DEFAULT_HNSW_EF_CONSTRUCTION = 200


@dataclass(frozen=True)
class _BuildConfig:
    """Validated FAISS build-time configuration.

    Parameters
    ----------
    index_type : str
        Exact ``flat`` or approximate ``hnsw`` index strategy.
    m : int
        HNSW graph degree used only for HNSW builds.
    ef_construction : int
        HNSW construction exploration used only for HNSW builds.
    """

    index_type: str
    m: int
    ef_construction: int


@dataclass(frozen=True)
class _LoadedArtifact:
    """One verified warm FAISS artifact.

    Parameters
    ----------
    index : object
        Loaded FAISS index object.
    labels : tuple[str, ...]
        Stable-ID label map aligned to FAISS integer labels.
    manifest : Mapping[str, object]
        Verified immutable artifact manifest.
    """

    index: faiss.Index
    labels: tuple[str, ...]
    manifest: Mapping[str, object]


def _build_config(config: Mapping[str, object]) -> _BuildConfig:
    """Validate one plugin configuration mapping.

    Parameters
    ----------
    config : collections.abc.Mapping[str, object]
        Plugin-scoped configuration table.

    Returns
    -------
    _BuildConfig
        Typed build-time configuration.

    Raises
    ------
    ValueError
        If configuration keys, modes, or HNSW limits are invalid.
    """

    unsupported = sorted(set(config) - {"enabled", "index_type", "M", "efConstruction"})
    if unsupported:
        raise ValueError(
            "FAISS similarity index does not accept configuration keys: "
            + ", ".join(unsupported)
        )
    index_type = str(config.get("index_type", "flat"))
    if index_type not in {"flat", "hnsw"}:
        raise ValueError("FAISS index_type must be 'flat' or 'hnsw'.")
    m = config.get("M", _DEFAULT_HNSW_M)
    ef_construction = config.get("efConstruction", _DEFAULT_HNSW_EF_CONSTRUCTION)
    if not isinstance(m, int) or isinstance(m, bool) or m <= 0:
        raise ValueError("FAISS M must be a positive integer.")
    if (
        not isinstance(ef_construction, int)
        or isinstance(ef_construction, bool)
        or ef_construction <= 0
    ):
        raise ValueError("FAISS efConstruction must be a positive integer.")
    return _BuildConfig(index_type, m, ef_construction)


def _identity_payload(
    identity: SimilarityIndexIdentity,
    *,
    object_type: str,
) -> dict[str, object]:
    """Return canonical identity data for one derived artifact.

    Parameters
    ----------
    identity : codira.contracts.SimilarityIndexIdentity
        Repository-bound vector/index identity.
    object_type : str
        Snapshot owner kind.

    Returns
    -------
    dict[str, object]
        JSON-compatible immutable identity data.
    """

    engine = identity.vector_set.engine
    store = identity.vector_set.vector_store
    index = identity.index
    return {
        "root": str(identity.root.resolve()),
        "object_type": object_type,
        "vector_set": {
            "engine": engine.engine,
            "engine_version": engine.engine_version,
            "model": engine.model,
            "model_version": engine.model_version,
            "dimension": engine.dimension,
            "precision": engine.precision,
            "vector_store": {
                "store": store.store,
                "store_version": store.store_version,
                "format_version": store.format_version,
            },
        },
        "index": {
            "index": index.index,
            "index_version": index.index_version,
            "format_version": index.format_version,
            "build_fingerprint": index.build_fingerprint,
        },
    }


def _artifact_key(identity: SimilarityIndexIdentity, *, object_type: str) -> str:
    """Return the deterministic filesystem key for one artifact identity.

    Parameters
    ----------
    identity : codira.contracts.SimilarityIndexIdentity
        Repository-bound vector/index identity.
    object_type : str
        Snapshot owner kind.

    Returns
    -------
    str
        SHA-256 key suitable for a repository-local artifact directory.
    """

    payload = _identity_payload(identity, object_type=object_type)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _artifact_root(identity: SimilarityIndexIdentity, *, object_type: str) -> Path:
    """Return the root holding all published revisions for one artifact.

    Parameters
    ----------
    identity : codira.contracts.SimilarityIndexIdentity
        Repository-bound vector/index identity.
    object_type : str
        Snapshot owner kind.

    Returns
    -------
    pathlib.Path
        Repository-local FAISS artifact directory.
    """

    return (
        get_codira_dir(identity.root)
        / "similarity-indexes"
        / "faiss"
        / _artifact_key(identity, object_type=object_type)
    )


def _canonical_json(value: Mapping[str, object]) -> str:
    """Render deterministic JSON for manifests and checksums.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        JSON-compatible payload.

    Returns
    -------
    str
        Canonical one-line JSON plus a newline.
    """

    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    """Write one deterministic JSON artifact.

    Parameters
    ----------
    path : pathlib.Path
        Output file owned by a temporary artifact directory.
    value : collections.abc.Mapping[str, object]
        JSON-compatible artifact payload.

    Returns
    -------
    None
        The output file is written.
    """

    path.write_text(_canonical_json(value), encoding="utf-8")


def _read_json(path: Path, *, repair: str) -> dict[str, object]:
    """Read one strict JSON artifact with deterministic repair guidance.

    Parameters
    ----------
    path : pathlib.Path
        Expected JSON artifact path.
    repair : str
        Deterministic operator repair command.

    Returns
    -------
    dict[str, object]
        Parsed JSON object.

    Raises
    ------
    ValueError
        If the artifact is missing, malformed, or not a JSON object.
    """

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"FAISS artifact {path} is missing or corrupt. {repair}"
        ) from error
    if not isinstance(loaded, dict):
        raise ValueError(f"FAISS artifact {path} is corrupt. {repair}")
    return cast("dict[str, object]", loaded)


@dataclass
class FaissSimilarityIndex:
    """Repository-local FAISS exact-flat or approximate-HNSW implementation."""

    name: str = "faiss"
    version: str = PACKAGE_VERSION
    _cache: dict[tuple[str, str, int, str], _LoadedArtifact] = field(
        default_factory=dict
    )
    _build: _BuildConfig = field(
        default_factory=lambda: _BuildConfig(
            "flat", _DEFAULT_HNSW_M, _DEFAULT_HNSW_EF_CONSTRUCTION
        )
    )

    def configuration_json_schema(self) -> dict[str, object]:
        """Return the shared JSON schema for FAISS build settings.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Plugin configuration schema.
        """

        return plugin_json_schema(
            {
                "index_type": {
                    "type": "string",
                    "enum": ["flat", "hnsw"],
                    "default": "flat",
                    "description": "FAISS build strategy; hnsw is approximate.",
                },
                "M": {
                    "type": "integer",
                    "minimum": 1,
                    "default": _DEFAULT_HNSW_M,
                    "description": "HNSW graph degree used when index_type is hnsw.",
                },
                "efConstruction": {
                    "type": "integer",
                    "minimum": 1,
                    "default": _DEFAULT_HNSW_EF_CONSTRUCTION,
                    "description": "HNSW construction exploration used when index_type is hnsw.",
                },
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """Validate injected plugin settings without retaining mutable state.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Plugin-scoped configuration table.

        Returns
        -------
        None
            Invalid settings raise before runtime use.
        """

        self._build = _build_config(config)

    def spec(self, config: Mapping[str, object]) -> SimilarityIndexSpec:
        """Return build identity including FAISS and HNSW parameters.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Plugin-scoped build configuration.

        Returns
        -------
        codira.contracts.SimilarityIndexSpec
            Configuration-sensitive derived-index specification.
        """

        build = _build_config(config)
        self._build = build
        fingerprint = _canonical_json(
            {
                "efConstruction": build.ef_construction,
                "faiss_version": str(getattr(faiss, "__version__", "unknown")),
                "index_type": build.index_type,
                "m": build.m,
                "metric": _METRIC,
            }
        ).strip()
        return SimilarityIndexSpec(
            index=self.name,
            index_version=self.version,
            format_version=FORMAT_VERSION,
            build_fingerprint=hashlib.sha256(fingerprint.encode()).hexdigest(),
        )

    def initialize(self, root: Path, config: Mapping[str, object]) -> None:
        """Validate settings and create the repository-local artifact root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root owning derived FAISS state.
        config : collections.abc.Mapping[str, object]
            Plugin-scoped build configuration.

        Returns
        -------
        None
            The artifact parent directory exists after validation.
        """

        self._build = _build_config(config)
        (get_codira_dir(root) / "similarity-indexes" / "faiss").mkdir(
            parents=True, exist_ok=True
        )

    def rebuild(
        self, snapshot: VectorSnapshot, identity: SimilarityIndexIdentity
    ) -> None:
        """Build and atomically publish one revisioned FAISS artifact.

        Parameters
        ----------
        snapshot : codira.contracts.VectorSnapshot
            Ordered authoritative source vectors and durable revision.
        identity : codira.contracts.SimilarityIndexIdentity
            Repository-bound FAISS build identity.

        Returns
        -------
        None
            A current manifest pointer is replaced only after complete artifact
            files have been written and validated.

        Raises
        ------
        ValueError
            If source vectors do not match the declared dimension.
        """

        expected_identity = _identity_payload(
            identity, object_type=snapshot.metadata.object_type
        )
        root = _artifact_root(identity, object_type=snapshot.metadata.object_type)
        root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
        try:
            vectors = self._matrix(snapshot)
            labels = tuple(row.stable_id for row in snapshot.rows)
            build = self._build_from_identity(identity)
            index = self._new_index(
                dimension=snapshot.metadata.identity.engine.dimension,
                build=build,
            )
            if len(labels):
                index.add(vectors)
            index_path = temporary / "index.faiss"
            faiss.write_index(index, str(index_path))
            labels_payload: dict[str, object] = {"labels": list(labels)}
            _write_json(temporary / "labels.json", labels_payload)
            labels_checksum = hashlib.sha256(
                _canonical_json(labels_payload).encode()
            ).hexdigest()
            manifest: dict[str, object] = {
                "artifact_format_version": FORMAT_VERSION,
                "build": {
                    "efConstruction": build.ef_construction,
                    "faiss_version": str(getattr(faiss, "__version__", "unknown")),
                    "index_type": build.index_type,
                    "m": build.m,
                    "metric": _METRIC,
                },
                "identity": expected_identity,
                "labels_checksum": labels_checksum,
                "object_count": len(labels),
                "source_revision": snapshot.metadata.revision,
            }
            _write_json(temporary / "manifest.json", manifest)
            artifact_name = f"r{snapshot.metadata.revision}-{uuid4_hex()}"
            published = root / artifact_name
            os.replace(temporary, published)
            pointer = {
                "artifact": artifact_name,
                "identity": expected_identity,
                "source_revision": snapshot.metadata.revision,
            }
            pointer_temp = root / f".current-{uuid4_hex()}.tmp"
            _write_json(pointer_temp, pointer)
            os.replace(pointer_temp, root / "current.json")
            self._cache.pop(self._cache_key(identity, snapshot), None)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def search(self, request: SimilaritySearchRequest) -> list[VectorSimilarityScore]:
        """Search one verified FAISS artifact using per-query HNSW settings.

        Parameters
        ----------
        request : codira.contracts.SimilaritySearchRequest
            Snapshot-bound query, profile, and threshold.

        Returns
        -------
        list[codira.contracts.VectorSimilarityScore]
            Candidate-limited scores with deterministic score/stable-ID ties.

        Raises
        ------
        ValueError
            If the required artifact is missing, corrupt, stale, or incompatible.
        """

        artifact = self._load(request)
        query = np.asarray([request.query_vector], dtype=np.float32)
        if query.shape[1] != request.snapshot.metadata.identity.engine.dimension:
            raise ValueError(
                "FAISS query dimension does not match the durable vector set. "
                "Run `codira emb rebuild`."
            )
        faiss.normalize_L2(query)
        count = min(request.profile.candidate_limit, len(artifact.labels))
        if count == 0:
            return []
        distances, positions = self._search(
            artifact.index,
            query,
            count,
            ef_search=request.profile.ef_search,
            index_type=cast(
                "str",
                cast("Mapping[str, object]", artifact.manifest["build"])["index_type"],
            ),
        )
        scores = [
            VectorSimilarityScore(artifact.labels[int(position)], float(distance))
            for distance, position in zip(distances[0], positions[0], strict=True)
            if int(position) >= 0 and float(distance) >= request.min_score
        ]
        return sorted(scores, key=lambda item: (-item.score, item.stable_id))

    def purge(self, root: Path, identity: SimilarityIndexIdentity) -> None:
        """Remove all derived FAISS revisions for one exact identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root supplied by the lifecycle caller.
        identity : codira.contracts.SimilarityIndexIdentity
            Derived index identity to remove.

        Returns
        -------
        None
            Matching persisted artifacts and warm cache entries are removed.

        Raises
        ------
        ValueError
            If the supplied root differs from the artifact identity root.
        """

        if root.resolve() != identity.root.resolve():
            raise ValueError("FAISS purge root does not match its index identity.")
        for object_type in ("symbol", "documentation"):
            shutil.rmtree(
                _artifact_root(identity, object_type=object_type), ignore_errors=True
            )
        self.reset_runtime_caches()

    def reset_runtime_caches(self) -> None:
        """Discard every process-local loaded FAISS artifact.

        Parameters
        ----------
        None

        Returns
        -------
        None
            No persisted FAISS artifact is changed.
        """

        self._cache.clear()

    def _build_from_identity(self, identity: SimilarityIndexIdentity) -> _BuildConfig:
        """Recover build settings encoded by the immutable index specification.

        Parameters
        ----------
        identity : codira.contracts.SimilarityIndexIdentity
            Selected index identity.

        Returns
        -------
        _BuildConfig
            Build configuration represented by the current plugin instance.

        Raises
        ------
        ValueError
            If the identity is not owned by this FAISS implementation.
        """

        if identity.index.index != self.name:
            raise ValueError("FAISS identity selects a different similarity index.")
        expected = self.spec(
            {
                "index_type": self._build.index_type,
                "M": self._build.m,
                "efConstruction": self._build.ef_construction,
            }
        )
        if identity.index != expected:
            raise ValueError(
                "FAISS build configuration does not match its selected identity. "
                "Run `codira emb rebuild`."
            )
        return self._build

    @staticmethod
    def _matrix(snapshot: VectorSnapshot) -> np.ndarray:
        """Decode and normalize one ordered authoritative vector snapshot.

        Parameters
        ----------
        snapshot : codira.contracts.VectorSnapshot
            Durable float32 vectors for one object type.

        Returns
        -------
        numpy.ndarray
            C-contiguous, L2-normalized float32 matrix.

        Raises
        ------
        ValueError
            If a stored vector has an incompatible byte length or dimension.
        """

        dimension = snapshot.metadata.identity.engine.dimension
        rows: list[np.ndarray] = []
        for row in snapshot.rows:
            vector = np.frombuffer(row.vector, dtype=np.float32)
            if row.dimension != dimension or vector.size != dimension:
                raise ValueError(
                    "FAISS source vector does not match durable vector-set dimension."
                )
            rows.append(vector)
        matrix = (
            np.ascontiguousarray(np.vstack(rows), dtype=np.float32)
            if rows
            else np.empty((0, dimension), dtype=np.float32)
        )
        if len(matrix):
            faiss.normalize_L2(matrix)
        return matrix

    @staticmethod
    def _new_index(*, dimension: int, build: _BuildConfig) -> faiss.Index:
        """Construct one unpopulated FAISS index for the requested build mode.

        Parameters
        ----------
        dimension : int
            Vector dimensionality.
        build : _BuildConfig
            Validated FAISS build settings.

        Returns
        -------
        object
            FAISS index ready to receive normalized vectors.
        """

        if build.index_type == "flat":
            return faiss.IndexFlatIP(dimension)
        index = faiss.IndexHNSWFlat(dimension, build.m, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = build.ef_construction
        return index

    @staticmethod
    def _search(
        index: faiss.Index,
        query: np.ndarray,
        count: int,
        *,
        ef_search: int,
        index_type: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Issue one search without mutating shared HNSW runtime state.

        Parameters
        ----------
        index : object
            Loaded FAISS index.
        query : numpy.ndarray
            One normalized float32 query vector.
        count : int
            Candidate count requested before structural filtering.
        ef_search : int
            Per-query HNSW graph-exploration effort.
        index_type : str
            Persisted index mode.

        Returns
        -------
        tuple[numpy.ndarray, numpy.ndarray]
            FAISS scores and integer positions.
        """

        if index_type != "hnsw":
            return cast("tuple[np.ndarray, np.ndarray]", index.search(query, count))
        parameter_type = getattr(
            faiss,
            "SearchParametersHNSW",
            getattr(faiss, "SearchParameterHNSW", None),
        )
        if parameter_type is None:
            raise ValueError(
                "Installed FAISS lacks per-query HNSW parameters. "
                "Install faiss-cpu==1.15.0 and run `codira emb rebuild`."
            )
        parameters = parameter_type()
        parameters.efSearch = ef_search
        return cast(
            "tuple[np.ndarray, np.ndarray]",
            index.search(query, count, params=parameters),
        )

    def _load(self, request: SimilaritySearchRequest) -> _LoadedArtifact:
        """Load and verify the artifact required by one snapshot-bound query.

        Parameters
        ----------
        request : codira.contracts.SimilaritySearchRequest
            Snapshot and selected index identity.

        Returns
        -------
        _LoadedArtifact
            Verified warmed artifact.

        Raises
        ------
        ValueError
            If durable state and the selected derived artifact disagree.
        """

        key = self._cache_key(request.identity, request.snapshot)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        repair = "Run `codira emb rebuild`."
        root = _artifact_root(
            request.identity, object_type=request.snapshot.metadata.object_type
        )
        pointer = _read_json(root / "current.json", repair=repair)
        expected_identity = _identity_payload(
            request.identity, object_type=request.snapshot.metadata.object_type
        )
        if (
            pointer.get("identity") != expected_identity
            or pointer.get("source_revision") != request.snapshot.metadata.revision
        ):
            raise ValueError(
                "FAISS artifact is stale for durable vector state. " + repair
            )
        artifact_name = pointer.get("artifact")
        if not isinstance(artifact_name, str) or "/" in artifact_name:
            raise ValueError("FAISS current artifact pointer is corrupt. " + repair)
        artifact_dir = root / artifact_name
        manifest = _read_json(artifact_dir / "manifest.json", repair=repair)
        if (
            manifest.get("identity") != expected_identity
            or manifest.get("source_revision") != request.snapshot.metadata.revision
            or manifest.get("artifact_format_version") != FORMAT_VERSION
        ):
            raise ValueError(
                "FAISS artifact manifest is stale or incompatible. " + repair
            )
        labels_payload = _read_json(artifact_dir / "labels.json", repair=repair)
        labels = labels_payload.get("labels")
        if not isinstance(labels, list) or not all(
            isinstance(item, str) for item in labels
        ):
            raise ValueError("FAISS label map is corrupt. " + repair)
        checksum = hashlib.sha256(_canonical_json(labels_payload).encode()).hexdigest()
        if checksum != manifest.get("labels_checksum"):
            raise ValueError("FAISS label map checksum is corrupt. " + repair)
        try:
            index = faiss.read_index(str(artifact_dir / "index.faiss"))
        except (OSError, RuntimeError) as error:
            raise ValueError(
                "FAISS index artifact is missing or corrupt. " + repair
            ) from error
        if int(index.ntotal) != len(labels):
            raise ValueError("FAISS label map does not match index size. " + repair)
        loaded = _LoadedArtifact(index, tuple(labels), manifest)
        self._cache[key] = loaded
        return loaded

    @staticmethod
    def _cache_key(
        identity: SimilarityIndexIdentity, snapshot: VectorSnapshot
    ) -> tuple[str, str, int, str]:
        """Return a fixed-root, identity, revision, and object-type cache key.

        Parameters
        ----------
        identity : codira.contracts.SimilarityIndexIdentity
            Selected repository/index identity.
        snapshot : codira.contracts.VectorSnapshot
            Durable snapshot whose revision owns the cached artifact.

        Returns
        -------
        tuple[str, str, int, str]
            Cache key that prevents cross-root or stale artifact reuse.
        """

        return (
            str(identity.root.resolve()),
            _artifact_key(identity, object_type=snapshot.metadata.object_type),
            snapshot.metadata.revision,
            snapshot.metadata.object_type,
        )


def uuid4_hex() -> str:
    """Return a collision-resistant opaque publication suffix.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Random hexadecimal suffix used only for temporary/published artifact names.
    """

    from uuid import uuid4

    return uuid4().hex


def build_similarity_index() -> SimilarityIndex:
    """Build the first-party FAISS similarity-index plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.SimilarityIndex
        Fresh FAISS implementation instance.
    """

    return FaissSimilarityIndex()
