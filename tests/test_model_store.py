"""Tests for shared verified model artifact storage."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import TYPE_CHECKING

import pytest

from codira.model_store import (
    MODEL_ROOT_ENV,
    ModelIdentity,
    ModelStoreError,
    SharedModelStore,
    resolve_model_root,
)
from codira.platform_paths import PlatformPaths

if TYPE_CHECKING:
    from pathlib import Path


def _identity() -> ModelIdentity:
    """Return one deterministic test artifact identity.

    Returns
    -------
    codira.model_store.ModelIdentity
        Immutable ONNX artifact identity used by this module.
    """
    return ModelIdentity("onnx", "example/model", "revision-1", "model.onnx")


def _paths(root: Path) -> PlatformPaths:
    """Return isolated platform paths with a deterministic model root.

    Parameters
    ----------
    root : pathlib.Path
        Temporary root for all synthetic platform locations.

    Returns
    -------
    codira.platform_paths.PlatformPaths
        Isolated platform path contract.
    """
    return PlatformPaths(
        config_root=root / "config",
        data_root=root / "data",
        state_root=root / "state",
        cache_root=root / "cache",
        runtime_root=root / "runtime",
        managed_runtime_root=root / "data" / "runtimes",
        workspace_config_root=root / "config" / "workspaces",
        workspace_state_root=root / "state" / "workspaces",
        model_root=root / "cache" / "models",
    )


def test_model_root_resolution_has_explicit_environment_config_default_order(
    tmp_path: Path,
) -> None:
    """Resolve each supported root override in its documented precedence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary absolute base path.

    Returns
    -------
    None
        The test asserts exact root precedence without creating directories.
    """
    paths = _paths(tmp_path)
    configured = tmp_path / "configured"
    environment = tmp_path / "environment"
    explicit = tmp_path / "explicit"

    assert resolve_model_root(paths=paths) == paths.model_root
    assert resolve_model_root(configured_root=configured, paths=paths) == configured
    assert (
        resolve_model_root(
            configured_root=configured,
            environ={MODEL_ROOT_ENV: str(environment)},
            paths=paths,
        )
        == environment
    )
    assert (
        resolve_model_root(
            explicit_root=explicit,
            configured_root=configured,
            environ={MODEL_ROOT_ENV: str(environment)},
            paths=paths,
        )
        == explicit
    )


def test_model_root_rejects_relative_overrides(tmp_path: Path) -> None:
    """Reject a root that could place payloads under a workspace by accident.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary path used only to construct platform roots.

    Returns
    -------
    None
        The test asserts relative root rejection.
    """
    with pytest.raises(ModelStoreError, match="absolute"):
        resolve_model_root(configured_root=".codira/models", paths=_paths(tmp_path))


def test_two_isolated_runtimes_reuse_the_same_verified_blob(tmp_path: Path) -> None:
    """Publish one identity once and reuse its content-addressed blob.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary user-owned model root.

    Returns
    -------
    None
        The test asserts runtime isolation does not duplicate a blob.
    """
    store_one = SharedModelStore(tmp_path / "models")
    store_two = SharedModelStore(tmp_path / "models")
    identity = _identity()
    payload = b"verified model payload"
    digest = hashlib.sha256(payload).hexdigest()
    calls = 0

    def fetch(target: Path) -> None:
        """Write the deterministic test payload.

        Parameters
        ----------
        target : pathlib.Path
            Candidate file path owned by the store.

        Returns
        -------
        None
            The payload is written completely.
        """
        nonlocal calls
        calls += 1
        target.write_bytes(payload)

    first = store_one.ensure(identity, fetch, expected_sha256=digest)
    second = store_two.ensure(identity, fetch, expected_sha256=digest)

    assert first == second
    assert first.parent == tmp_path / "models" / "blobs"
    assert first.read_bytes() == payload
    assert calls == 1


def test_concurrent_provisioning_publishes_only_one_candidate(tmp_path: Path) -> None:
    """Serialize concurrent publishers before any manifest becomes visible.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary shared store root.

    Returns
    -------
    None
        The test asserts one successful fetch and one published blob.
    """
    store = SharedModelStore(tmp_path / "models")
    identity = _identity()
    payload = b"parallel payload"
    digest = hashlib.sha256(payload).hexdigest()
    calls = 0
    lock = threading.Lock()
    results: list[Path] = []

    def fetch(target: Path) -> None:
        """Write once while deliberately holding the store lock briefly.

        Parameters
        ----------
        target : pathlib.Path
            Candidate file path owned by the store.

        Returns
        -------
        None
            The candidate becomes a complete payload.
        """
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.05)
        target.write_bytes(payload)

    def provision() -> None:
        """Provision the shared identity in one competing thread.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The verified blob path is appended for comparison.
        """
        results.append(store.ensure(identity, fetch, expected_sha256=digest))

    threads = [threading.Thread(target=provision) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == 1
    assert results[0] == results[1]
    assert store.artifact_path(identity) == results[0]


def test_partial_and_checksum_failed_candidates_are_never_installed(
    tmp_path: Path,
) -> None:
    """Reject interrupted and corrupt candidates before publishing a manifest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary shared store root.

    Returns
    -------
    None
        The test asserts failed candidates cannot be resolved as installed.
    """
    store = SharedModelStore(tmp_path / "models")
    identity = _identity()

    with pytest.raises(ModelStoreError, match="did not publish"):
        store.ensure(identity, lambda target: None)
    assert store.artifact_path(identity) is None

    with pytest.raises(ModelStoreError, match="Checksum verification failed"):
        store.ensure(
            identity,
            lambda target: target.write_bytes(b"corrupt"),
            expected_sha256="0" * 64,
        )
    assert store.artifact_path(identity) is None


def test_corrupt_published_blob_is_repaired_before_republication(
    tmp_path: Path,
) -> None:
    """Repair a corrupt blob before exposing it through a manifest again.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary shared store root.

    Returns
    -------
    None
        The test asserts corruption is not visible as an installed artifact.
    """
    store = SharedModelStore(tmp_path / "models")
    identity = _identity()
    payload = b"verified payload"
    digest = hashlib.sha256(payload).hexdigest()
    published = store.ensure(
        identity,
        lambda target: target.write_bytes(payload),
        expected_sha256=digest,
    )
    published.write_bytes(b"corrupt")

    assert store.artifact_path(identity) is None
    repaired = store.ensure(
        identity,
        lambda target: target.write_bytes(payload),
        expected_sha256=digest,
    )

    assert repaired == published
    assert store.artifact_path(identity) == published
    assert published.read_bytes() == payload


def test_import_keeps_legacy_artifact_unchanged(tmp_path: Path) -> None:
    """Import an existing managed copy without deleting or modifying it.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary legacy and shared-store roots.

    Returns
    -------
    None
        The test asserts import is copy-only and verified.
    """
    source = tmp_path / "legacy" / "model.onnx"
    source.parent.mkdir()
    source.write_bytes(b"legacy payload")
    original = source.read_bytes()
    destination = SharedModelStore(tmp_path / "models").import_existing(
        _identity(), source
    )

    assert source.exists()
    assert source.read_bytes() == original
    assert destination.read_bytes() == original
