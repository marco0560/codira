"""Public configuration data model and versioned defaults.

Responsibilities
----------------
- Define stable configuration records and operator-facing errors.
- Own versioned defaults, profiles, and the public schema shape.

Architectural role
------------------
This module is the dependency-light model layer for :mod:`codira.config`.
It must not load files, read environment variables, or import plugin registries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from codira.contracts import SimilaritySearchProfile

if TYPE_CHECKING:
    from pathlib import Path

CONFIG_VERSION = 2
APP_NAME = "codira"
CONFIG_FILENAME = "config.toml"
DEFAULT_BACKEND_NAME = "sqlite"
DEFAULT_EMBEDDING_ENGINE_NAME = "sentence-transformers"
DEFAULT_VECTOR_STORE_NAME = "sqlite"
DEFAULT_SIMILARITY_INDEX_NAME = "exact"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_VERSION = "1"
DEFAULT_EMBEDDING_MODEL_ROOT = ""
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_EMBEDDING_DEVICE = "cpu"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
DEFAULT_EMBEDDING_GPU_DEVICE_ID = 0
DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB = 0
DEFAULT_EMBEDDING_INDEX_MODE = "immediate"
DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES = ("symbol", "documentation")
DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER = 256
DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_SIMILARITY_SEARCH_PROFILES = (
    SimilaritySearchProfile("default", 64, 256, 20, 256),
)
DEFAULT_INDEX_CONCURRENCY_STRATEGY = "auto"
DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS = 0
DEFAULT_INDEX_CONCURRENCY_MIN_FILES = 16
DEFAULT_DAEMON_DEBOUNCE_MS = 250
KNOWN_EMBEDDING_INDEX_MODES = frozenset({"immediate", "deferred"})
KNOWN_INDEX_CONCURRENCY_STRATEGIES = frozenset({"off", "auto", "process", "thread"})
KNOWN_EMBEDDING_OBJECT_TYPES = frozenset(DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES)
_PLUGIN_CONFIG_RESERVED_KEYS = frozenset(
    {
        "disable_third_party",
        "disabled_analyzers",
        "documentation_audit_routes",
    }
)
LevelName = Literal["system", "user", "repo", "effective"]
ProfileName = Literal["default", "low-memory", "gpu"]


class ConfigError(ValueError):
    """Stable operator-facing configuration error.

    Parameters
    ----------
    message : str
        Human-readable validation or loading failure.
    """


@dataclass(frozen=True)
class ConfigWriteResult:
    """Describe an atomic configuration replacement and its recoverable backup.

    Parameters
    ----------
    path : pathlib.Path
        Configuration file considered for update.
    backup_path : pathlib.Path | None
        Previous byte-identical content backup when a replacement occurred.
    changed : bool
        Whether the configuration file was replaced.
    """

    path: Path
    backup_path: Path | None
    changed: bool


@dataclass(frozen=True)
class BackendConfig:
    """
    Active index backend configuration.

    Parameters
    ----------
    name : str
        Stable backend plugin name.
    """

    name: str = DEFAULT_BACKEND_NAME


@dataclass(frozen=True)
class DocumentationAuditRouteConfig:
    """
    Explicit route for documentation audit plugin selection.

    Parameters
    ----------
    language : str
        Analyzer language matched by this route.
    convention : str
        Documentation convention matched by this route.
    plugin : str
        Documentation audit plugin name selected by this route.
    include_paths : tuple[str, ...]
        Repo-relative glob patterns included by this route.
    exclude_paths : tuple[str, ...]
        Repo-relative glob patterns excluded by this route.
    """

    language: str
    convention: str
    plugin: str
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginsConfig:
    """
    Plugin activation configuration.

    Parameters
    ----------
    disable_third_party : bool
        Whether third-party entry-point plugins should be skipped.
    disabled_analyzers : tuple[str, ...]
        Analyzer names to remove from the active analyzer set.
    documentation_audit_routes : tuple[DocumentationAuditRouteConfig, ...]
        Ordered documentation audit routing rules.
    configs : dict[str, dict[str, object]]
        Plugin-specific configuration tables keyed by namespaced plugin key,
        such as ``"analyzer-python"`` or ``"backend-sqlite"``.
    """

    disable_third_party: bool = False
    disabled_analyzers: tuple[str, ...] = ()
    documentation_audit_routes: tuple[DocumentationAuditRouteConfig, ...] = ()
    configs: dict[str, dict[str, object]] | None = None


@dataclass(frozen=True)
class EmbeddingsGpuConfig:
    """
    GPU-specific embedding runtime configuration.

    Parameters
    ----------
    device_id : int
        GPU device identifier selected for embedding inference.
    memory_limit_mb : int
        Maximum GPU memory budget in MiB, or ``0`` when no limit is configured.
    """

    device_id: int = DEFAULT_EMBEDDING_GPU_DEVICE_ID
    memory_limit_mb: int = DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB


@dataclass(frozen=True)
class EmbeddingsIndexingConfig:
    """
    Embedding index population controls.

    Parameters
    ----------
    mode : str
        Embedding population mode. ``"immediate"`` computes embeddings during
        ``codira index``; ``"deferred"`` records index data without computing
        embeddings during the primary pass.
    object_types : tuple[str, ...]
        Persisted object types eligible for embedding computation.
    max_text_chars : int
        Maximum text payload length eligible for embedding, or ``0`` for no
        configured limit.
    work_batch_multiplier : int
        Multiplier applied to ``embeddings.batch_size`` to bound indexing
        work segments without exposing a second absolute batch size.
    max_source_file_bytes : int
        Maximum source-file byte size accepted before hashing, parsing, or
        context rereads.
    include_paths : tuple[str, ...]
        Repo-root-relative path prefixes included in embedding computation.
        An empty tuple includes all indexed paths.
    exclude_paths : tuple[str, ...]
        Repo-root-relative path prefixes excluded from embedding computation.
    """

    mode: str = DEFAULT_EMBEDDING_INDEX_MODE
    object_types: tuple[str, ...] = DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES
    max_text_chars: int = 0
    work_batch_multiplier: int = DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddingsConfig:
    """
    Semantic embedding runtime configuration.

    Parameters
    ----------
    enabled : bool
        Whether embedding computation and retrieval channels are active.
    engine : str
        Active embedding engine plugin name.
    vector_store : str
        Active vector-store plugin name.
    similarity_index : str
        Mandatory selected similarity-index implementation.
    similarity_profiles : tuple[SimilaritySearchProfile, ...]
        Named runtime candidate and result policies.
    model : str
        Embedding model identifier.
    version : str
        Explicit embedding backend version stored with persisted vectors.
    model_root : str
        Optional absolute user-level root for shared model artifacts. An empty
        value selects the platform default or ``CODIRA_MODEL_ROOT``.
    dimension : int
        Expected vector dimension for the configured model.
    device : str
        Device string passed to sentence-transformers.
    batch_size : int
        Batch size passed to sentence-transformers encode calls.
    torch_num_threads : int
        Torch intra-op thread override, or ``0`` to leave Torch defaults.
    torch_num_interop_threads : int
        Torch inter-op thread override, or ``0`` to leave Torch defaults.
    gpu : EmbeddingsGpuConfig
        GPU-specific embedding runtime configuration.
    indexing : EmbeddingsIndexingConfig
        Embedding index population controls.
    """

    enabled: bool = True
    engine: str = DEFAULT_EMBEDDING_ENGINE_NAME
    vector_store: str = DEFAULT_VECTOR_STORE_NAME
    similarity_index: str = DEFAULT_SIMILARITY_INDEX_NAME
    similarity_profiles: tuple[SimilaritySearchProfile, ...] = (
        DEFAULT_SIMILARITY_SEARCH_PROFILES
    )
    model: str = DEFAULT_EMBEDDING_MODEL
    version: str = DEFAULT_EMBEDDING_VERSION
    model_root: str = DEFAULT_EMBEDDING_MODEL_ROOT
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    device: str = DEFAULT_EMBEDDING_DEVICE
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    torch_num_threads: int = 0
    torch_num_interop_threads: int = 0
    gpu: EmbeddingsGpuConfig = EmbeddingsGpuConfig()
    indexing: EmbeddingsIndexingConfig = EmbeddingsIndexingConfig()


@dataclass(frozen=True)
class IndexConcurrencyConfig:
    """
    Configure concurrent analyzer execution for indexing.

    Parameters
    ----------
    strategy : {"off", "auto", "process", "thread"}
        Requested analysis scheduler. ``"auto"`` prefers process workers when
        every active analyzer declares support.
    max_workers : int
        Explicit worker cap, or ``0`` to use the bounded automatic cap.
    min_files : int
        Minimum selected-file count before ``"auto"`` starts workers.
    """

    strategy: str = DEFAULT_INDEX_CONCURRENCY_STRATEGY
    max_workers: int = DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS
    min_files: int = DEFAULT_INDEX_CONCURRENCY_MIN_FILES


@dataclass(frozen=True)
class IndexCoverageConfig:
    """Configure coverage-root glob patterns and suffix exclusions.

    Parameters
    ----------
    roots : tuple[str, ...]
        Empty selects analyzer defaults; ``("-",)`` disables auditing.
    exclude_suffixes : tuple[str, ...]
        File suffixes excluded from coverage diagnostics after root selection.
    """

    roots: tuple[str, ...] = ()
    exclude_suffixes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DaemonConfig:
    """Configure the optional automatic-indexing daemon.

    Parameters
    ----------
    enabled : bool
        Whether daemon commands may start automatic indexing when their runtime
        implementation is available.
    debounce_ms : int
        Milliseconds used to coalesce filesystem-change notifications.
    include_paths : tuple[str, ...]
        Repo-root-relative path prefixes watched by the daemon. An empty tuple
        selects every path supported by active analyzers.
    exclude_paths : tuple[str, ...]
        Repo-root-relative path prefixes excluded from daemon watching.
    """

    enabled: bool = False
    debounce_ms: int = DEFAULT_DAEMON_DEBOUNCE_MS
    include_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryDaemonConfig:
    """Configure the optional repository-local warm query daemon.

    Parameters
    ----------
    enabled : bool
        Whether lifecycle commands may start the query daemon after its runtime
        is implemented. The default keeps all queries direct and independent
        from daemon availability.
    """

    enabled: bool = False


@dataclass(frozen=True)
class ConfigOrigin:
    """
    Origin metadata for one effective configuration value.

    Parameters
    ----------
    level : str
        Source level that supplied the effective value.
    path : pathlib.Path | None
        File path for file-backed values, or ``None`` for defaults/env values.
    detail : str
        Human-readable source detail.
    """

    level: str
    path: Path | None
    detail: str


@dataclass(frozen=True)
class CodiraConfig:
    """
    Effective Codira runtime configuration.

    Parameters
    ----------
    config_version : int
        Public config schema version.
    backend : BackendConfig
        Active backend configuration.
    plugins : PluginsConfig
        Plugin activation configuration.
    embeddings : EmbeddingsConfig
        Embedding runtime configuration.
    index : IndexConcurrencyConfig
        Index analysis scheduling configuration.
    coverage : IndexCoverageConfig
        Coverage-root configuration.
    daemon : DaemonConfig
        Optional automatic-indexing daemon configuration.
    query_daemon : QueryDaemonConfig
        Optional repository-local warm query daemon configuration.
    origins : dict[str, ConfigOrigin]
        Origin metadata keyed by dotted config key.
    """

    config_version: int
    backend: BackendConfig
    plugins: PluginsConfig
    embeddings: EmbeddingsConfig
    index: IndexConcurrencyConfig
    coverage: IndexCoverageConfig
    daemon: DaemonConfig
    query_daemon: QueryDaemonConfig
    origins: dict[str, ConfigOrigin]


DEFAULT_CONFIG: dict[str, object] = {
    "config_version": CONFIG_VERSION,
    "backend": {"name": DEFAULT_BACKEND_NAME},
    "plugins": {
        "disable_third_party": False,
        "disabled_analyzers": [],
        "documentation_audit_routes": [],
    },
    "embeddings": {
        "enabled": True,
        "engine": DEFAULT_EMBEDDING_ENGINE_NAME,
        "vector_store": DEFAULT_VECTOR_STORE_NAME,
        "similarity_index": DEFAULT_SIMILARITY_INDEX_NAME,
        "similarity_profiles": [
            {
                "name": profile.name,
                "ef_search": profile.ef_search,
                "candidate_limit": profile.candidate_limit,
                "default_result_limit": profile.default_result_limit,
                "max_result_limit": profile.max_result_limit,
            }
            for profile in DEFAULT_SIMILARITY_SEARCH_PROFILES
        ],
        "model": DEFAULT_EMBEDDING_MODEL,
        "version": DEFAULT_EMBEDDING_VERSION,
        "model_root": DEFAULT_EMBEDDING_MODEL_ROOT,
        "dimension": DEFAULT_EMBEDDING_DIMENSION,
        "device": DEFAULT_EMBEDDING_DEVICE,
        "batch_size": DEFAULT_EMBEDDING_BATCH_SIZE,
        "torch_num_threads": 0,
        "torch_num_interop_threads": 0,
        "gpu": {
            "device_id": DEFAULT_EMBEDDING_GPU_DEVICE_ID,
            "memory_limit_mb": DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB,
        },
        "indexing": {
            "mode": DEFAULT_EMBEDDING_INDEX_MODE,
            "object_types": list(DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES),
            "max_text_chars": 0,
            "work_batch_multiplier": DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER,
            "max_source_file_bytes": DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES,
            "include_paths": [],
            "exclude_paths": [],
        },
    },
    "index": {
        "concurrency": {
            "strategy": DEFAULT_INDEX_CONCURRENCY_STRATEGY,
            "max_workers": DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS,
            "min_files": DEFAULT_INDEX_CONCURRENCY_MIN_FILES,
        },
        "coverage": {"roots": [], "exclude_suffixes": []},
    },
    "daemon": {
        "enabled": False,
        "debounce_ms": DEFAULT_DAEMON_DEBOUNCE_MS,
        "include_paths": [],
        "exclude_paths": [],
    },
    "query_daemon": {"enabled": False},
}
FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS: dict[str, dict[str, object]] = {
    "analyzer-python": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_module_documentation": True,
        "emit_imports": True,
        "emit_constants": True,
        "emit_type_aliases": True,
    },
    "analyzer-json": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "enabled_families": ["schema", "package", "release"],
        "emit_dependencies": True,
        "emit_scripts": True,
        "emit_schema_properties": True,
    },
    "analyzer-c": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "use_leading_comments": True,
        "emit_doxygen_documentation": True,
        "include_system_includes": True,
        "emit_macros": True,
    },
    "analyzer-cpp": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "use_leading_comments": True,
        "emit_doxygen_documentation": True,
        "include_system_includes": True,
        "emit_namespaces": True,
        "emit_macros": True,
    },
    "analyzer-rust": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_macros": True,
    },
    "analyzer-javascript": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_variables": True,
        "emit_jsdoc_documentation": True,
    },
    "analyzer-typescript": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_variables": True,
        "emit_tsdoc_documentation": True,
    },
    "analyzer-go": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_variables": True,
    },
    "analyzer-bash": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "emit_functions": True,
    },
    "analyzer-markdown": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "strip_front_matter": True,
        "emit_file_artifact_without_headings": True,
        "min_heading_level": 1,
        "max_heading_level": 6,
    },
    "analyzer-text": {
        "enabled": True,
        "include_paths": [],
        "exclude_paths": [],
        "include_root_files": True,
        "include_docs_directories": True,
        "exclude_generated": True,
        "exclude_fixtures_logs": True,
    },
    "backend-sqlite": {"enabled": True},
    "backend-duckdb": {"enabled": True, "profiling_enabled": False},
    "embedding-sentence-transformers": {"enabled": True},
    "embedding-onnx": {
        "enabled": True,
        "provider": "CPUExecutionProvider",
        "precision": "float32",
        "normalize": True,
        "max_tokens": 512,
        "intra_op_num_threads": 0,
        "inter_op_num_threads": 0,
    },
    "vector-store-sqlite": {"enabled": True},
    "vector-store-duckdb": {"enabled": True},
    "documentation-audit-numpy": {"enabled": True},
    "documentation-audit-google": {"enabled": True},
    "documentation-audit-doxygen": {"enabled": True},
    "documentation-audit-rustdoc": {"enabled": True},
}
PLUGIN_CONFIG_RENDER_ORDER: tuple[str, ...] = (
    "backend-sqlite",
    "backend-duckdb",
    "embedding-sentence-transformers",
    "embedding-onnx",
    "vector-store-sqlite",
    "vector-store-duckdb",
    "documentation-audit-numpy",
    "documentation-audit-google",
    "documentation-audit-doxygen",
    "documentation-audit-rustdoc",
    "analyzer-python",
    "analyzer-json",
    "analyzer-c",
    "analyzer-cpp",
    "analyzer-rust",
    "analyzer-bash",
    "analyzer-markdown",
    "analyzer-text",
)
PROFILE_OVERRIDES: dict[ProfileName, dict[str, object]] = {
    "default": {},
    "low-memory": {
        "embeddings": {
            "device": "cpu",
            "batch_size": 8,
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
        }
    },
    "gpu": {
        "embeddings": {
            "device": "cuda",
            "batch_size": 64,
            "gpu": {
                "device_id": 0,
                "memory_limit_mb": 0,
            },
        }
    },
}
_SCHEMA: dict[str, object] = {
    "config_version": int,
    "backend": {"name": str},
    "plugins": {
        "disable_third_party": bool,
        "disabled_analyzers": list,
        "documentation_audit_routes": list,
    },
    "embeddings": {
        "enabled": bool,
        "engine": str,
        "vector_store": str,
        "similarity_index": str,
        "similarity_profiles": list,
        "model": str,
        "version": str,
        "model_root": str,
        "dimension": int,
        "device": str,
        "batch_size": int,
        "torch_num_threads": int,
        "torch_num_interop_threads": int,
        "gpu": {
            "device_id": int,
            "memory_limit_mb": int,
        },
        "indexing": {
            "mode": str,
            "object_types": list,
            "max_text_chars": int,
            "work_batch_multiplier": int,
            "max_source_file_bytes": int,
            "include_paths": list,
            "exclude_paths": list,
        },
    },
    "index": {
        "concurrency": {
            "strategy": str,
            "max_workers": int,
            "min_files": int,
        },
        "coverage": {"roots": list, "exclude_suffixes": list},
    },
    "daemon": {
        "enabled": bool,
        "debounce_ms": int,
        "include_paths": list,
        "exclude_paths": list,
    },
    "query_daemon": {"enabled": bool},
}


__all__ = (
    "APP_NAME",
    "CONFIG_FILENAME",
    "CONFIG_VERSION",
    "DEFAULT_BACKEND_NAME",
    "DEFAULT_CONFIG",
    "DEFAULT_DAEMON_DEBOUNCE_MS",
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "DEFAULT_EMBEDDING_DEVICE",
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_ENGINE_NAME",
    "DEFAULT_EMBEDDING_GPU_DEVICE_ID",
    "DEFAULT_EMBEDDING_GPU_MEMORY_LIMIT_MB",
    "DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES",
    "DEFAULT_EMBEDDING_INDEX_MODE",
    "DEFAULT_EMBEDDING_INDEX_OBJECT_TYPES",
    "DEFAULT_EMBEDDING_INDEX_WORK_BATCH_MULTIPLIER",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_MODEL_ROOT",
    "DEFAULT_EMBEDDING_VERSION",
    "DEFAULT_INDEX_CONCURRENCY_MAX_WORKERS",
    "DEFAULT_INDEX_CONCURRENCY_MIN_FILES",
    "DEFAULT_INDEX_CONCURRENCY_STRATEGY",
    "DEFAULT_SIMILARITY_INDEX_NAME",
    "DEFAULT_SIMILARITY_SEARCH_PROFILES",
    "DEFAULT_VECTOR_STORE_NAME",
    "FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS",
    "KNOWN_EMBEDDING_INDEX_MODES",
    "KNOWN_EMBEDDING_OBJECT_TYPES",
    "KNOWN_INDEX_CONCURRENCY_STRATEGIES",
    "PLUGIN_CONFIG_RENDER_ORDER",
    "PROFILE_OVERRIDES",
    "BackendConfig",
    "CodiraConfig",
    "ConfigError",
    "ConfigOrigin",
    "ConfigWriteResult",
    "DaemonConfig",
    "DocumentationAuditRouteConfig",
    "EmbeddingsConfig",
    "EmbeddingsGpuConfig",
    "EmbeddingsIndexingConfig",
    "IndexConcurrencyConfig",
    "IndexCoverageConfig",
    "LevelName",
    "PluginsConfig",
    "ProfileName",
    "QueryDaemonConfig",
    "_PLUGIN_CONFIG_RESERVED_KEYS",
    "_SCHEMA",
)
