"""Provide a shared, verified, content-addressed model artifact store.

This host-owned store keeps model payloads out of workspaces and managed
environments while allowing providers to reuse verified artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from codira.platform_paths import PlatformPaths, platform_paths

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

MODEL_ROOT_ENV = "CODIRA_MODEL_ROOT"
_MANIFEST_VERSION = 1
_LOCK_TIMEOUT_SECONDS = 30.0


class ModelStoreError(RuntimeError):
    """Report a stable model-store publication or verification failure.

    Parameters
    ----------
    message : str
        Operator-facing error detail.
    """


@dataclass(frozen=True)
class ModelIdentity:
    """Identify one immutable model artifact independently from its location.

    Parameters
    ----------
    engine : str
        Embedding engine that consumes the artifact.
    model : str
        Upstream model identifier.
    version : str
        Immutable model revision or Codira model version.
    artifact : str
        Logical artifact filename or role.
    """

    engine: str
    model: str
    version: str
    artifact: str

    def key(self) -> str:
        """Return the deterministic manifest key for this identity.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 key over canonical identity fields.
        """
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelArtifactManifest:
    """Record the verified blob that satisfies a model identity.

    Parameters
    ----------
    identity : ModelIdentity
        Immutable identity resolved by this manifest.
    sha256 : str
        SHA-256 digest of the published blob.
    size : int
        Published blob size in bytes.
    """

    identity: ModelIdentity
    sha256: str
    size: int

    def to_json(self) -> str:
        """Render a deterministic versioned manifest document.

        Parameters
        ----------
        None

        Returns
        -------
        str
            JSON content ending with one newline.
        """
        return (
            json.dumps(
                {
                    "schema_version": _MANIFEST_VERSION,
                    "identity": asdict(self.identity),
                    "sha256": self.sha256,
                    "size": self.size,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )


def resolve_model_root(
    *,
    explicit_root: Path | None = None,
    configured_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    paths: PlatformPaths | None = None,
) -> Path:
    """Resolve a root by explicit, environment, config, then platform order.

    Parameters
    ----------
    explicit_root : pathlib.Path | None, optional
        Per-operation root override.
    configured_root : str | pathlib.Path | None, optional
        User-configured global root.
    environ : collections.abc.Mapping[str, str] | None, optional
        Environment mapping; ``None`` uses the process environment.
    paths : codira.platform_paths.PlatformPaths | None, optional
        Injected platform roots for deterministic callers.

    Returns
    -------
    pathlib.Path
        Absolute normalized store root without creating it.

    Raises
    ------
    ModelStoreError
        If the selected root is blank or relative.
    """
    if explicit_root is not None:
        candidate = explicit_root
    else:
        environment = os.environ if environ is None else environ
        environment_root = environment.get(MODEL_ROOT_ENV, "").strip()
        if environment_root:
            candidate = Path(environment_root)
        elif configured_root is not None and str(configured_root).strip():
            candidate = Path(configured_root)
        else:
            candidate = (paths or platform_paths()).model_root
    if not str(candidate).strip() or not candidate.is_absolute():
        msg = "Codira model root must be a non-empty absolute path."
        raise ModelStoreError(msg)
    return candidate.resolve(strict=False)


def _sha256(path: Path) -> str:
    """Return a file SHA-256 digest.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SharedModelStore:
    """Publish and resolve verified immutable model blobs under one user root.

    Parameters
    ----------
    root : pathlib.Path
        Absolute shared model-store root.
    """

    def __init__(self, root: Path) -> None:
        """Initialize store paths without publishing artifacts.

        Parameters
        ----------
        root : pathlib.Path
            Absolute shared model-store root.
        """
        self.root = resolve_model_root(explicit_root=root)
        self._blobs = self.root / "blobs"
        self._manifests = self.root / "manifests"
        self._locks = self.root / "locks"
        self._staging = self.root / "staging"

    def sentence_transformers_cache(self) -> Path:
        """Return the provider cache owned by this shared store.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            SentenceTransformers and Hugging Face cache root.
        """
        return self.root / "sentence-transformers"

    def manifest_path(self, identity: ModelIdentity) -> Path:
        """Return the manifest path for an artifact identity.

        Parameters
        ----------
        identity : ModelIdentity
            Artifact identity to locate.

        Returns
        -------
        pathlib.Path
            Identity manifest path.
        """
        return self._manifests / f"{identity.key()}.json"

    def artifact_path(self, identity: ModelIdentity) -> Path | None:
        """Return a verified blob, or ``None`` for absent or corrupt state.

        Parameters
        ----------
        identity : ModelIdentity
            Artifact identity to resolve.

        Returns
        -------
        pathlib.Path | None
            Verified blob path, or ``None`` when unavailable.
        """
        try:
            payload = json.loads(
                self.manifest_path(identity).read_text(encoding="utf-8")
            )
            if payload.get("schema_version") != _MANIFEST_VERSION:
                return None
            if payload.get("identity") != asdict(identity):
                return None
            digest, size = payload.get("sha256"), payload.get("size")
            if not isinstance(digest, str) or not isinstance(size, int):
                return None
            blob = self._blobs / digest
            if not blob.is_file() or blob.stat().st_size != size:
                return None
            return blob if _sha256(blob) == digest else None
        except (OSError, ValueError, TypeError):
            return None

    def ensure(
        self,
        identity: ModelIdentity,
        fetch: Callable[[Path], object],
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        """Fetch, verify, and atomically publish an artifact exactly once.

        Parameters
        ----------
        identity : ModelIdentity
            Artifact identity to satisfy.
        fetch : collections.abc.Callable[[pathlib.Path], object]
            Callback that writes a complete candidate file at the given path.
        expected_sha256 : str | None, optional
            Required checksum when integrity metadata is available.

        Returns
        -------
        pathlib.Path
            Verified content-addressed blob path.

        Raises
        ------
        ModelStoreError
            If fetching, checksum verification, or publication fails.
        """
        ready = self.artifact_path(identity)
        if ready is not None:
            return ready
        lock = self._acquire_lock(identity)
        try:
            ready = self.artifact_path(identity)
            if ready is not None:
                return ready
            self._staging.mkdir(parents=True, exist_ok=True)
            candidate = self._staging / f"{identity.key()}-{uuid.uuid4().hex}.part"
            try:
                fetch(candidate)
                if not candidate.is_file():
                    msg = "Model fetcher did not publish a candidate artifact."
                    raise ModelStoreError(msg)
                digest = _sha256(candidate)
                if expected_sha256 is not None and digest != expected_sha256.lower():
                    msg = f"Checksum verification failed for {identity.artifact}."
                    raise ModelStoreError(msg)
                self._blobs.mkdir(parents=True, exist_ok=True)
                blob = self._blobs / digest
                if not blob.is_file() or _sha256(blob) != digest:
                    candidate.replace(blob)
                manifest = ModelArtifactManifest(identity, digest, blob.stat().st_size)
                self._publish_manifest(identity, manifest)
            except OSError as exc:
                msg = f"Failed to publish {identity.artifact}: {exc}"
                raise ModelStoreError(msg) from exc
            finally:
                candidate.unlink(missing_ok=True)
            return blob
        finally:
            lock.unlink(missing_ok=True)

    def import_existing(
        self,
        identity: ModelIdentity,
        source: Path,
        *,
        expected_sha256: str | None = None,
    ) -> Path:
        """Copy an existing artifact without modifying its source.

        Parameters
        ----------
        identity : ModelIdentity
            Identity to bind to the imported source.
        source : pathlib.Path
            Existing artifact retained intact after import.
        expected_sha256 : str | None, optional
            Required source checksum.

        Returns
        -------
        pathlib.Path
            Verified blob published in the shared store.

        Raises
        ------
        ModelStoreError
            If the source is missing or cannot be published and verified.
        """
        if not source.is_file():
            msg = f"Existing model artifact is not a file: {source}"
            raise ModelStoreError(msg)
        return self.ensure(
            identity,
            lambda candidate: shutil.copyfile(source, candidate),
            expected_sha256=expected_sha256,
        )

    def _publish_manifest(
        self, identity: ModelIdentity, manifest: ModelArtifactManifest
    ) -> None:
        """Atomically publish a manifest after its verified blob exists.

        Parameters
        ----------
        identity : ModelIdentity
            Identity represented by the manifest.
        manifest : ModelArtifactManifest
            Verified manifest to publish.

        Returns
        -------
        None
            A complete manifest becomes visible atomically.
        """
        self._manifests.mkdir(parents=True, exist_ok=True)
        target = self.manifest_path(identity)
        temporary = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(manifest.to_json(), encoding="utf-8")
        temporary.replace(target)

    def _acquire_lock(self, identity: ModelIdentity) -> Path:
        """Acquire an identity-scoped filesystem lock with bounded waiting.

        Parameters
        ----------
        identity : ModelIdentity
            Artifact identity whose publication is serialized.

        Returns
        -------
        pathlib.Path
            Created lock path that the caller must remove.

        Raises
        ------
        ModelStoreError
            If another publisher exceeds the lock timeout.
        """
        self._locks.mkdir(parents=True, exist_ok=True)
        lock = self._locks / f"{identity.key()}.lock"
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    msg = f"Timed out waiting to provision {identity.artifact}."
                    raise ModelStoreError(msg) from None
                time.sleep(0.05)
                continue
            os.close(descriptor)
            return lock
