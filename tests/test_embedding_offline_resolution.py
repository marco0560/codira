"""Protect explicit artifact precedence, legacy reuse and strict offline loading.

Parameters
----------
None

Returns
-------
None
    Factory tests never load or download a model.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from codira.model_store import SharedModelStore
from codira.semantic import embeddings as runtime

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("explicit_root", [False, True])
def test_legacy_cache_reuse_respects_model_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit_root: bool
) -> None:
    """Reuse a legacy model only when no explicit store was selected.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned cache fixtures.
    monkeypatch : pytest.MonkeyPatch
        Supplies configuration and deterministic cache roots.
    explicit_root : bool
        Operator explicitly selected a store.

    Returns
    -------
    None
        No cache files are copied or created by resolution.
    """
    legacy = tmp_path / "legacy"
    (legacy / "models--BAAI--bge-small-en-v1.5").mkdir(parents=True)
    store = SharedModelStore(tmp_path / "shared")
    config = SimpleNamespace(
        embeddings=SimpleNamespace(model_root=str(store.root) if explicit_root else ""),
        plugins=SimpleNamespace(configs={}),
    )
    monkeypatch.setenv("HF_HUB_CACHE", str(legacy))
    monkeypatch.delenv("CODIRA_MODEL_ROOT", raising=False)
    monkeypatch.setattr(runtime, "load_effective_config", lambda **kwargs: config)
    monkeypatch.setattr(runtime, "_shared_model_store", lambda root: store)
    monkeypatch.setattr(
        runtime,
        "get_embedding_backend",
        lambda **kwargs: SimpleNamespace(name="BAAI/bge-small-en-v1.5"),
    )
    source, cache = runtime._sentence_transformer_location(tmp_path)
    assert source == "BAAI/bge-small-en-v1.5"
    assert cache == (store.sentence_transformers_cache() if explicit_root else legacy)
    assert not store.root.exists()
    monkeypatch.setenv("CODIRA_MODEL_ROOT", str(store.root))
    assert (
        runtime._sentence_transformer_location(tmp_path)[1]
        == store.sentence_transformers_cache()
    )


def test_explicit_snapshot_preserves_logical_model_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the selected immutable snapshot without replacing the model ID.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned local snapshot directory.
    monkeypatch : pytest.MonkeyPatch
        Captures factory inputs while retaining logical identity metadata.

    Returns
    -------
    None
        A local path is passed only to the loader; configured identity is unchanged.
    """
    store = SharedModelStore(tmp_path / "store")
    config = SimpleNamespace(
        embeddings=SimpleNamespace(model_root=""),
        plugins=SimpleNamespace(
            configs={"embedding-sentence-transformers": {"model_path": str(tmp_path)}}
        ),
    )
    monkeypatch.setattr(runtime, "load_effective_config", lambda **kwargs: config)
    monkeypatch.setattr(runtime, "_shared_model_store", lambda root: store)
    backend = SimpleNamespace(name="BAAI/bge-small-en-v1.5")
    monkeypatch.setattr(runtime, "get_embedding_backend", lambda **kwargs: backend)
    monkeypatch.setattr(runtime, "_configured_embedding_device", lambda **kwargs: "cpu")
    monkeypatch.setattr(runtime, "_configured_trust_remote_code", lambda root: False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    factory = Mock()
    runtime._load_sentence_transformer(factory, offline=False, root=tmp_path)
    assert factory.call_args.args == (str(tmp_path.resolve()),)
    assert factory.call_args.kwargs["local_files_only"] is True
    assert backend.name == "BAAI/bge-small-en-v1.5"
    assert os.environ["HF_HUB_OFFLINE"] == "1"


@pytest.mark.parametrize("flag", ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"])
def test_strict_offline_miss_never_provisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """Preserve an offline miss without any automatic provisioning attempt.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned context root.
    monkeypatch : pytest.MonkeyPatch
        Replaces model boundaries rather than contacting a provider.
    flag : str
        Supported explicit offline control.

    Returns
    -------
    None
        Original local failure is diagnosed and provisioning remains untouched.
    """
    runtime.reset_embedding_runtime_caches()
    monkeypatch.setenv(flag, "1")
    monkeypatch.setattr(runtime, "_sentence_transformer_factory", Mock())
    monkeypatch.setattr(runtime, "_configure_transformers_logging_once", Mock())
    monkeypatch.setattr(runtime, "_configure_torch_runtime_once", Mock())
    monkeypatch.setattr(
        runtime,
        "_load_sentence_transformer",
        Mock(side_effect=OSError("missing local weights")),
    )
    monkeypatch.setattr(
        runtime,
        "_sentence_transformer_location",
        lambda root: ("BAAI/bge-small-en-v1.5", tmp_path),
    )
    provision = Mock()
    monkeypatch.setattr(runtime, "provision_embedding_model", provision)
    with pytest.raises(
        runtime.EmbeddingBackendError, match="Automatic provisioning is disabled"
    ):
        runtime._load_model(tmp_path)
    provision.assert_not_called()
    assert os.environ[flag] == "1"
    runtime.reset_embedding_runtime_caches()
