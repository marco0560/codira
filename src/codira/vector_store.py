"""Helpers for active vector-store selection and identity construction.

Responsibilities
----------------
- Build the active vector-store context from effective repository config.
- Keep embedding engine, vector store, and plugin-config identity logic shared.

Architectural role
------------------
This module belongs to the semantic persistence boundary between indexing,
CLI orchestration, and vector-store plugins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.config import load_effective_config
from codira.contracts import VectorSetIdentity, VectorStore
from codira.registry import (
    active_embedding_engine,
    active_vector_store,
    plugin_config_key,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ActiveVectorStoreContext:
    """
    Active vector-store runtime context for one repository.

    Parameters
    ----------
    store : codira.contracts.VectorStore
        Configured active vector-store plugin.
    identity : codira.contracts.VectorSetIdentity
        Complete active engine and vector-store identity.
    config : dict[str, object]
        Vector-store-specific configuration table.
    """

    store: VectorStore
    identity: VectorSetIdentity
    config: dict[str, object]


def active_vector_store_context(
    root: Path,
    *,
    vector_store_name: str | None = None,
) -> ActiveVectorStoreContext:
    """
    Build and initialize the active vector-store context.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective configuration should be used.
    vector_store_name : str | None, optional
        Explicit vector-store plugin name. When omitted, the effective
        repository config selects the store.

    Returns
    -------
    codira.vector_store.ActiveVectorStoreContext
        Active vector-store plugin, identity, and store configuration.
    """
    effective_config = load_effective_config(root=root)
    plugin_configs = effective_config.plugins.configs or {}
    configured_vector_store = effective_config.embeddings.vector_store.strip()
    selected_vector_store = (
        configured_vector_store
        if vector_store_name is None
        else vector_store_name.strip()
    )
    store = active_vector_store(root=root, name=selected_vector_store)
    engine = active_embedding_engine(root=root)
    engine_config_key = plugin_config_key(
        family="embedding",
        name=effective_config.embeddings.engine.strip(),
    )
    vector_store_config_key = plugin_config_key(
        family="vector-store",
        name=selected_vector_store,
    )
    engine_config = dict(plugin_configs.get(engine_config_key, {}))
    engine_config["_codira_model"] = effective_config.embeddings.model
    engine_config["_codira_model_version"] = effective_config.embeddings.version
    engine_config["_codira_dimension"] = effective_config.embeddings.dimension
    vector_store_config = dict(plugin_configs.get(vector_store_config_key, {}))
    store.initialize(root, vector_store_config)
    return ActiveVectorStoreContext(
        store=store,
        identity=VectorSetIdentity(
            engine=engine.spec(engine_config),
            vector_store=store.spec(vector_store_config),
        ),
        config=vector_store_config,
    )
