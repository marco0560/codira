"""SentenceTransformers embedding engine plugin for codira.

Responsibilities
----------------
- Publish the current SentenceTransformers/PyTorch embedding runtime through
  the `codira.embedding_engines` entry-point group.
- Preserve the existing embedding behavior while Codira migrates from a
  core-local runtime to pluggable embedding engines.
- Expose deterministic engine identity metadata for vector invalidation.

Design principles
-----------------
The plugin keeps model provisioning explicit and delegates to the current
core runtime implementation until the dispatcher migration is complete.

Architectural role
------------------
This module belongs to the **first-party embedding engine plugin layer**.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.config import load_effective_config
from codira.contracts import EmbeddingEngineSpec
from codira.semantic import embeddings as _legacy_embeddings

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira.contracts import EmbeddingEngine

__all__ = ["SentenceTransformersEmbeddingEngine", "build_engine"]

PACKAGE_VERSION = "1.0.0"


class SentenceTransformersEmbeddingEngine:
    """
    SentenceTransformers-backed embedding engine.

    Parameters
    ----------
    None

    Notes
    -----
    This first package boundary delegates to Codira's existing
    SentenceTransformers runtime. A later branch step moves the runtime
    dispatcher to instantiate this plugin as the active engine.
    """

    name = "sentence-transformers"
    version = PACKAGE_VERSION

    def spec(self, config: Mapping[str, object]) -> EmbeddingEngineSpec:
        """
        Return the active SentenceTransformers vector identity.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table. The current engine identity
            remains sourced from the effective `[embeddings]` table for
            compatibility with existing config files.

        Returns
        -------
        codira.contracts.EmbeddingEngineSpec
            Engine-aware embedding identity.
        """
        del config
        embeddings = load_effective_config().embeddings
        return EmbeddingEngineSpec(
            engine=self.name,
            engine_version=self.version,
            model=embeddings.model,
            model_version=embeddings.version,
            dimension=embeddings.dimension,
            precision="float32",
        )

    def provision(self, config: Mapping[str, object], *, quiet: bool = False) -> None:
        """
        Ensure the configured SentenceTransformers model artifact is available.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.
        quiet : bool, optional
            Whether operator-facing provisioning output should be suppressed.

        Returns
        -------
        None
            The current core provisioning routine performs the artifact check.
        """
        del config
        _legacy_embeddings.provision_embedding_model(quiet=quiet)

    def embed_texts(
        self,
        texts: Sequence[str],
        config: Mapping[str, object],
    ) -> list[list[float]]:
        """
        Embed text payloads with the current SentenceTransformers runtime.

        Parameters
        ----------
        texts : collections.abc.Sequence[str]
            Text payloads to embed.
        config : collections.abc.Mapping[str, object]
            Engine-specific configuration table.

        Returns
        -------
        list[list[float]]
            One vector per input payload.
        """
        del config
        return _legacy_embeddings.embed_texts(texts)

    def reset_runtime_caches(self) -> None:
        """
        Clear process-local SentenceTransformers runtime caches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The current core runtime caches are cleared.
        """
        _legacy_embeddings.reset_embedding_runtime_caches()


def build_engine() -> EmbeddingEngine:
    """
    Build the first-party SentenceTransformers embedding engine.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.EmbeddingEngine
        SentenceTransformers embedding engine instance.
    """
    return SentenceTransformersEmbeddingEngine()
