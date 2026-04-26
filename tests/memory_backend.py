"""Pure-Python in-memory index backend used by backend contract tests.

Responsibilities
----------------
- Implement the complete ``IndexBackend`` protocol without SQL persistence.
- Exercise indexer/backend contracts with deterministic, process-local state.
- Provide query results compatible with the first-party SQLite backend for
  focused regression fixtures.

Design principles
-----------------
The backend is intentionally test-only. It keeps state in Python data
structures, avoids persistence concerns, and mirrors observable SQLite query
ordering where the contract tests depend on it.

Architectural role
------------------
This module belongs to the **backend contract verification layer**.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from codira.contracts import BackendGraphMetric, BackendSymbolInventoryItem
from codira.docstring import DocstringValidationRequest, validate_docstring
from codira.prefix import normalize_prefix, path_has_prefix

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path
    from typing import Protocol

    from codira.contracts import (
        BackendEmbeddingCandidatesRequest,
        BackendPersistAnalysisRequest,
        BackendRelationQueryRequest,
        BackendRuntimeInventoryRequest,
    )
    from codira.models import (
        CallableReference,
        CallSite,
        EnumMemberArtifact,
        OverloadArtifact,
    )
    from codira.semantic.embeddings import EmbeddingBackendSpec
    from codira.types import (
        ChannelResults,
        DocstringIssueRow,
        EnumMemberRow,
        IncludeEdgeRow,
        OverloadRow,
        SymbolRow,
    )

    class _ReusableEmbedding(Protocol):
        """Stored embedding shape accepted for reuse."""

        content_hash: str
        dim: int
        vector: bytes

else:
    EmbeddingBackendSpec = object


CallEdgeRow = tuple[str, str, str | None, str | None, int]


@dataclass(frozen=True)
class _MemoryConnection:
    """Connection handle carrying one root-scoped in-memory state."""

    state: _MemoryState


@dataclass
class _MemoryFile:
    """Persisted file metadata for the in-memory backend."""

    id: int
    path: str
    hash: str
    analyzer_name: str
    analyzer_version: str


@dataclass
class _MemorySymbol:
    """Indexed symbol row plus stable identity metadata."""

    id: int
    file_id: int
    stable_id: str
    type: str
    module_name: str
    name: str
    lineno: int
    logical_name: str

    def row(self, file_path: str) -> SymbolRow:
        """
        Return the backend-neutral symbol row for this stored symbol.

        Parameters
        ----------
        file_path : str
            Absolute path owning the symbol.

        Returns
        -------
        codira.types.SymbolRow
            Public symbol-row representation.
        """
        return (self.type, self.module_name, self.name, file_path, self.lineno)


@dataclass
class _MemoryFunction:
    """Stored callable metadata used for graph and logical-name resolution."""

    file_id: int
    module_name: str
    name: str
    logical_name: str
    lineno: int
    end_lineno: int | None
    class_name: str | None


@dataclass(frozen=True)
class _MemoryImport:
    """Stored import or include artifact."""

    file_id: int
    module_name: str
    name: str
    alias: str | None
    kind: str
    lineno: int


@dataclass(frozen=True)
class _MemoryRelation:
    """Raw call-style relation emitted by an analyzer."""

    file_id: int
    owner_module: str
    owner_name: str
    kind: str
    base: str
    target: str
    lineno: int
    col_offset: int


@dataclass(frozen=True)
class _MemoryDocIssue:
    """Stored docstring validation issue with public query metadata."""

    issue_type: str
    message: str
    stable_id: str
    symbol_type: str
    module_name: str
    symbol_name: str
    file_id: int
    lineno: int
    end_lineno: int | None


@dataclass(frozen=True)
class _MemoryEmbedding:
    """Stored embedding metadata for one symbol."""

    symbol_id: int
    stable_id: str
    backend: str
    version: str
    content_hash: str
    dim: int
    vector: bytes


@dataclass(frozen=True)
class _MemoryOverload:
    """Stored overload metadata attached to one canonical callable."""

    file_id: int
    module_name: str
    symbol_type: str
    symbol_name: str
    symbol_lineno: int
    stable_id: str
    parent_stable_id: str
    ordinal: int
    signature: str
    lineno: int
    end_lineno: int | None
    docstring: str | None


@dataclass(frozen=True)
class _MemoryEnumMember:
    """Stored enum-member metadata attached to one canonical enum symbol."""

    file_id: int
    module_name: str
    symbol_name: str
    symbol_lineno: int
    stable_id: str
    parent_stable_id: str
    ordinal: int
    name: str
    signature: str
    lineno: int


@dataclass(frozen=True)
class _StoredEmbedding:
    """Reusable embedding row returned by ``load_previous_embeddings_by_path``."""

    stable_id: str
    content_hash: str
    dim: int
    vector: bytes


@dataclass
class _MemoryState:
    """Mutable root-scoped backend state."""

    next_file_id: int = 1
    next_symbol_id: int = 1
    files: dict[int, _MemoryFile] = field(default_factory=dict)
    file_id_by_path: dict[str, int] = field(default_factory=dict)
    symbols: list[_MemorySymbol] = field(default_factory=list)
    functions: list[_MemoryFunction] = field(default_factory=list)
    imports: list[_MemoryImport] = field(default_factory=list)
    call_records: list[_MemoryRelation] = field(default_factory=list)
    callable_ref_records: list[_MemoryRelation] = field(default_factory=list)
    overloads: list[_MemoryOverload] = field(default_factory=list)
    enum_members: list[_MemoryEnumMember] = field(default_factory=list)
    doc_issues: list[_MemoryDocIssue] = field(default_factory=list)
    embeddings: list[_MemoryEmbedding] = field(default_factory=list)
    runtime_inventory: tuple[str, str, int] | None = None
    analyzer_inventory: list[tuple[str, str, str]] = field(default_factory=list)


def _embedding_text(
    *,
    module_name: str,
    symbol_name: str,
    symbol_type: str,
    signature: str | None = None,
    docstring: str | None = None,
) -> str:
    """
    Build the deterministic semantic payload for one symbol.

    Parameters
    ----------
    module_name : str
        Dotted module owning the symbol.
    symbol_name : str
        Logical symbol name used for retrieval.
    symbol_type : str
        Indexed symbol kind.
    signature : str | None, optional
        Callable or declaration signature.
    docstring : str | None, optional
        Parsed docstring text.

    Returns
    -------
    str
        Newline-joined semantic payload.
    """
    parts = [symbol_type, module_name, symbol_name]
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)
    return "\n".join(parts)


def _content_hash(text: str) -> str:
    """
    Return the stable hash for an embedding payload.

    Parameters
    ----------
    text : str
        Semantic payload text.

    Returns
    -------
    str
        SHA-256 hex digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pseudo_vector_blob(text: str, *, dim: int) -> bytes:
    """
    Return a deterministic normalized vector blob without external models.

    Parameters
    ----------
    text : str
        Text used as the vector seed.
    dim : int
        Vector dimensionality.

    Returns
    -------
    bytes
        Little-endian float32 vector payload.
    """
    values: list[float] = []
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    counter = 0
    while len(values) < dim:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend((byte / 127.5) - 1.0 for byte in block)
        counter += 1
    vector = values[:dim]
    norm = math.sqrt(sum(value * value for value in vector))
    normalized = [0.0 if norm == 0.0 else value / norm for value in vector]
    return struct.pack(f"<{dim}f", *normalized)


def _deserialize_vector(blob: bytes, *, dim: int) -> list[float]:
    """
    Deserialize a float32 vector payload.

    Parameters
    ----------
    blob : bytes
        Stored vector bytes.
    dim : int
        Vector dimensionality.

    Returns
    -------
    list[float]
        Dense vector values.
    """
    return list(struct.unpack(f"<{dim}f", blob))


def _dot_similarity(left: list[float], right: list[float]) -> float:
    """
    Return the dot-product similarity for two equal-length vectors.

    Parameters
    ----------
    left : list[float]
        First vector.
    right : list[float]
        Second vector.

    Returns
    -------
    float
        Dot-product score.
    """
    return sum(a * b for a, b in zip(left, right, strict=True))


def _should_audit_docstrings(source_path: Path) -> bool:
    """
    Decide whether a source file participates in docstring auditing.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path.

    Returns
    -------
    bool
        ``True`` for files whose artifacts should be audited.
    """
    return source_path.suffix not in {".sh", ".bash"}


def _should_require_raises_section(source_path: Path, function_name: str) -> bool:
    """
    Decide whether an explicit raise should require a ``Raises`` section.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path.
    function_name : str
        Callable name.

    Returns
    -------
    bool
        ``False`` for pytest-style tests, otherwise ``True``.
    """
    return not (
        "tests" in source_path.parts
        and source_path.suffix == ".py"
        and function_name.startswith("test_")
    )


class MemoryIndexBackend:
    """
    Minimal in-memory backend implementing the complete index contract.

    The backend persists data only for the lifetime of this Python object and
    is suitable for deterministic contract validation, not production use.
    """

    name = "memory"
    version = "1"

    def __init__(self) -> None:
        """
        Initialize empty root-scoped backend storage.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The backend starts with no root state.
        """
        self._states: dict[Path, _MemoryState] = {}

    def _state(self, root: Path) -> _MemoryState:
        """
        Return mutable state for a repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        _MemoryState
            Mutable root-scoped state.
        """
        return self._states.setdefault(root.resolve(), _MemoryState())

    def _conn_state(self, root: Path, conn: object | None) -> _MemoryState:
        """
        Resolve state from an optional connection handle.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None
            Optional backend connection.

        Returns
        -------
        _MemoryState
            Mutable root-scoped state.

        Raises
        ------
        TypeError
            If ``conn`` is not an in-memory backend connection.
        """
        if conn is None:
            return self._state(root)
        if not isinstance(conn, _MemoryConnection):
            msg = "MemoryIndexBackend received an incompatible connection handle."
            raise TypeError(msg)
        return conn.state

    def open_connection(self, root: Path) -> _MemoryConnection:
        """
        Open a root-scoped in-memory connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        _MemoryConnection
            Lightweight state handle.
        """
        return _MemoryConnection(self._state(root))

    def load_runtime_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> tuple[str, str, int] | None:
        """
        Return stored runtime inventory for ``root``.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        tuple[str, str, int] | None
            Stored runtime inventory, or ``None`` when unavailable.
        """
        return self._conn_state(root, conn).runtime_inventory

    def load_analyzer_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> list[tuple[str, str, str]]:
        """
        Return stored analyzer inventory for ``root``.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[tuple[str, str, str]]
            Analyzer inventory rows.
        """
        return list(self._conn_state(root, conn).analyzer_inventory)

    def initialize(self, root: Path) -> None:
        """
        Ensure root-scoped memory state exists.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.

        Returns
        -------
        None
            State is created in place when missing.
        """
        self._state(root)

    def load_existing_file_hashes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, str]:
        """
        Return indexed file hashes keyed by absolute path.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        dict[str, str]
            File hashes keyed by absolute source path.
        """
        state = self._conn_state(root, conn)
        return {file.path: file.hash for file in state.files.values()}

    def load_existing_file_ownership(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> dict[str, tuple[str, str]]:
        """
        Return analyzer ownership keyed by absolute path.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        dict[str, tuple[str, str]]
            Analyzer name and version keyed by absolute source path.
        """
        state = self._conn_state(root, conn)
        return {
            file.path: (file.analyzer_name, file.analyzer_version)
            for file in state.files.values()
        }

    def delete_paths(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        conn: object | None = None,
    ) -> None:
        """
        Remove artifacts owned by the supplied file paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : collections.abc.Sequence[str]
            Absolute file paths whose indexed artifacts should be removed.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            Matching artifacts are deleted in place.
        """
        state = self._conn_state(root, conn)
        for path in sorted(paths):
            file_id = state.file_id_by_path.pop(path, None)
            if file_id is None:
                continue
            state.files.pop(file_id, None)
            self._delete_file_artifacts(state, file_id)

    def clear_index(self, root: Path, *, conn: object | None = None) -> None:
        """
        Remove all indexed artifacts while retaining runtime inventory.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            Indexed artifacts are cleared in place.
        """
        state = self._conn_state(root, conn)
        state.next_file_id = 1
        state.next_symbol_id = 1
        state.files.clear()
        state.file_id_by_path.clear()
        state.symbols.clear()
        state.functions.clear()
        state.imports.clear()
        state.call_records.clear()
        state.callable_ref_records.clear()
        state.overloads.clear()
        state.enum_members.clear()
        state.doc_issues.clear()
        state.embeddings.clear()

    def purge_skipped_docstring_issues(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Remove persisted docstring issues for files skipped by policy.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            Skipped-file docstring issues are removed in place.
        """
        state = self._conn_state(root, conn)
        skipped_ids = {
            file.id
            for file in state.files.values()
            if file.analyzer_name == "bash" or file.path.endswith((".sh", ".bash"))
        }
        state.doc_issues = [
            issue for issue in state.doc_issues if issue.file_id not in skipped_ids
        ]

    def load_previous_embeddings_by_path(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        embedding_backend: EmbeddingBackendSpec,
        conn: object | None = None,
    ) -> dict[str, dict[str, object]]:
        """
        Load reusable embeddings for paths selected for replacement.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : collections.abc.Sequence[str]
            Absolute file paths selected for replacement.
        embedding_backend : codira.contracts.EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        dict[str, dict[str, object]]
            Reusable embeddings keyed by path and stable symbol id.
        """
        state = self._conn_state(root, conn)
        path_set = set(paths)
        symbol_by_id = {symbol.id: symbol for symbol in state.symbols}
        results: dict[str, dict[str, object]] = {}
        for embedding in state.embeddings:
            if (
                embedding.backend != embedding_backend.name
                or embedding.version != embedding_backend.version
            ):
                continue
            symbol = symbol_by_id.get(embedding.symbol_id)
            if symbol is None:
                continue
            file_path = state.files[symbol.file_id].path
            if file_path not in path_set:
                continue
            results.setdefault(file_path, {})[embedding.stable_id] = _StoredEmbedding(
                stable_id=embedding.stable_id,
                content_hash=embedding.content_hash,
                dim=embedding.dim,
                vector=embedding.vector,
            )
        return results

    def persist_analysis(
        self,
        request: BackendPersistAnalysisRequest,
    ) -> tuple[int, int]:
        """
        Persist one normalized analysis result into memory.

        Parameters
        ----------
        request : BackendPersistAnalysisRequest
            Persistence request carrying metadata, normalized analysis,
            embedding backend metadata, reusable embeddings, and an optional
            backend connection.

        Returns
        -------
        tuple[int, int]
            Recomputed and reused embedding counts.

        Raises
        ------
        ValueError
            If embedding backend metadata is not provided.
        """
        if request.embedding_backend is None:
            msg = "MemoryIndexBackend requires explicit embedding backend metadata."
            raise ValueError(msg)

        state = self._conn_state(request.root, request.conn)
        file_id = state.next_file_id
        state.next_file_id += 1
        path_text = str(request.file_metadata.path)
        state.files[file_id] = _MemoryFile(
            id=file_id,
            path=path_text,
            hash=request.file_metadata.sha256,
            analyzer_name=request.file_metadata.analyzer_name,
            analyzer_version=request.file_metadata.analyzer_version,
        )
        state.file_id_by_path[path_text] = file_id

        embedding_payloads: list[tuple[int, str, str]] = []
        analysis = request.analysis
        module_name = analysis.module.name
        module_symbol_id = self._append_symbol(
            state,
            file_id=file_id,
            stable_id=analysis.module.stable_id,
            symbol_type="module",
            module_name=module_name,
            name=module_name,
            lineno=1,
            logical_name=module_name,
        )
        embedding_payloads.append(
            (
                module_symbol_id,
                analysis.module.stable_id,
                _embedding_text(
                    module_name=module_name,
                    symbol_name=module_name,
                    symbol_type="module",
                    docstring=analysis.module.docstring,
                ),
            )
        )
        self._append_doc_issues(
            state,
            file_id=file_id,
            label=f"Module {module_name}",
            docstring=analysis.module.docstring,
            is_public=int(_should_audit_docstrings(analysis.source_path)),
            stable_id=analysis.module.stable_id,
            symbol_type="module",
            module_name=module_name,
            symbol_name=module_name,
            lineno=1,
            end_lineno=None,
        )

        for cls in analysis.classes:
            class_symbol_id = self._append_symbol(
                state,
                file_id=file_id,
                stable_id=cls.stable_id,
                symbol_type="class",
                module_name=module_name,
                name=cls.name,
                lineno=cls.lineno,
                logical_name=cls.name,
            )
            embedding_payloads.append(
                (
                    class_symbol_id,
                    cls.stable_id,
                    _embedding_text(
                        module_name=module_name,
                        symbol_name=cls.name,
                        symbol_type="class",
                        docstring=cls.docstring,
                    ),
                )
            )
            if _should_audit_docstrings(analysis.source_path):
                self._append_doc_issues(
                    state,
                    file_id=file_id,
                    label=f"Class {cls.name}",
                    docstring=cls.docstring,
                    is_public=1,
                    stable_id=cls.stable_id,
                    symbol_type="class",
                    module_name=module_name,
                    symbol_name=cls.name,
                    lineno=cls.lineno,
                    end_lineno=cls.end_lineno,
                )
            for method in cls.methods:
                logical_name = f"{cls.name}.{method.name}"
                method_symbol_id = self._append_symbol(
                    state,
                    file_id=file_id,
                    stable_id=method.stable_id,
                    symbol_type="method",
                    module_name=module_name,
                    name=method.name,
                    lineno=method.lineno,
                    logical_name=logical_name,
                )
                state.functions.append(
                    _MemoryFunction(
                        file_id=file_id,
                        module_name=module_name,
                        name=method.name,
                        logical_name=logical_name,
                        lineno=method.lineno,
                        end_lineno=method.end_lineno,
                        class_name=cls.name,
                    )
                )
                embedding_payloads.append(
                    (
                        method_symbol_id,
                        method.stable_id,
                        _embedding_text(
                            module_name=module_name,
                            symbol_name=logical_name,
                            symbol_type="method",
                            signature=method.signature,
                            docstring=method.docstring,
                        ),
                    )
                )
                if _should_audit_docstrings(analysis.source_path):
                    self._append_doc_issues(
                        state,
                        file_id=file_id,
                        label=f"Method {logical_name}",
                        docstring=method.docstring,
                        is_public=method.is_public,
                        stable_id=method.stable_id,
                        symbol_type="method",
                        module_name=module_name,
                        symbol_name=logical_name,
                        lineno=method.lineno,
                        end_lineno=method.end_lineno,
                        parameters=method.parameters,
                        require_callable_sections=True,
                        yields_value=bool(method.yields_value),
                        returns_value=bool(method.returns_value),
                        raises_exception=bool(method.raises)
                        and _should_require_raises_section(
                            analysis.source_path,
                            method.name,
                        ),
                    )
                self._append_relations(
                    state,
                    file_id=file_id,
                    module_name=module_name,
                    owner_name=logical_name,
                    calls=method.calls,
                    refs=method.callable_refs,
                )
                self._append_overloads(
                    state,
                    file_id=file_id,
                    module_name=module_name,
                    symbol_type="method",
                    symbol_name=method.name,
                    symbol_lineno=method.lineno,
                    overloads=method.overloads,
                )

        for fn in analysis.functions:
            function_symbol_id = self._append_symbol(
                state,
                file_id=file_id,
                stable_id=fn.stable_id,
                symbol_type="function",
                module_name=module_name,
                name=fn.name,
                lineno=fn.lineno,
                logical_name=fn.name,
            )
            state.functions.append(
                _MemoryFunction(
                    file_id=file_id,
                    module_name=module_name,
                    name=fn.name,
                    logical_name=fn.name,
                    lineno=fn.lineno,
                    end_lineno=fn.end_lineno,
                    class_name=None,
                )
            )
            embedding_payloads.append(
                (
                    function_symbol_id,
                    fn.stable_id,
                    _embedding_text(
                        module_name=module_name,
                        symbol_name=fn.name,
                        symbol_type="function",
                        signature=fn.signature,
                        docstring=fn.docstring,
                    ),
                )
            )
            if _should_audit_docstrings(analysis.source_path):
                self._append_doc_issues(
                    state,
                    file_id=file_id,
                    label=f"Function {fn.name}",
                    docstring=fn.docstring,
                    is_public=fn.is_public,
                    stable_id=fn.stable_id,
                    symbol_type="function",
                    module_name=module_name,
                    symbol_name=fn.name,
                    lineno=fn.lineno,
                    end_lineno=fn.end_lineno,
                    parameters=fn.parameters,
                    require_callable_sections=True,
                    yields_value=bool(fn.yields_value),
                    returns_value=bool(fn.returns_value),
                    raises_exception=bool(fn.raises)
                    and _should_require_raises_section(analysis.source_path, fn.name),
                )
            self._append_relations(
                state,
                file_id=file_id,
                module_name=module_name,
                owner_name=fn.name,
                calls=fn.calls,
                refs=fn.callable_refs,
            )
            self._append_overloads(
                state,
                file_id=file_id,
                module_name=module_name,
                symbol_type="function",
                symbol_name=fn.name,
                symbol_lineno=fn.lineno,
                overloads=fn.overloads,
            )

        for decl in analysis.declarations:
            declaration_symbol_id = self._append_symbol(
                state,
                file_id=file_id,
                stable_id=decl.stable_id,
                symbol_type=decl.kind,
                module_name=module_name,
                name=decl.name,
                lineno=decl.lineno,
                logical_name=decl.name,
            )
            embedding_payloads.append(
                (
                    declaration_symbol_id,
                    decl.stable_id,
                    _embedding_text(
                        module_name=module_name,
                        symbol_name=decl.name,
                        symbol_type=decl.kind,
                        signature=decl.signature,
                        docstring=decl.docstring,
                    ),
                )
            )
            self._append_enum_members(
                state,
                file_id=file_id,
                module_name=module_name,
                symbol_name=decl.name,
                symbol_lineno=decl.lineno,
                enum_members=decl.enum_members,
            )

        for imp in analysis.imports:
            state.imports.append(
                _MemoryImport(
                    file_id=file_id,
                    module_name=module_name,
                    name=imp.name,
                    alias=imp.alias,
                    kind=imp.kind,
                    lineno=imp.lineno,
                )
            )

        return self._persist_embeddings(
            state,
            embedding_payloads=embedding_payloads,
            embedding_backend=request.embedding_backend,
            previous_embeddings=request.previous_embeddings or {},
        )

    def count_reusable_embeddings(
        self,
        root: Path,
        *,
        paths: Sequence[str],
        conn: object | None = None,
    ) -> int:
        """
        Count embedding rows owned by unchanged paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        paths : collections.abc.Sequence[str]
            Absolute file paths that were reused.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        int
            Number of reusable embedding rows.
        """
        state = self._conn_state(root, conn)
        path_set = set(paths)
        symbol_by_id = {symbol.id: symbol for symbol in state.symbols}
        return sum(
            1
            for embedding in state.embeddings
            if (
                (symbol := symbol_by_id.get(embedding.symbol_id)) is not None
                and state.files[symbol.file_id].path in path_set
            )
        )

    def rebuild_derived_indexes(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Derive graph edges lazily, so no rebuild work is required.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            The backend state is validated but not mutated.
        """
        self._conn_state(root, conn)

    def persist_runtime_inventory(
        self,
        request: BackendRuntimeInventoryRequest,
    ) -> None:
        """
        Persist runtime and analyzer inventory for the last index run.

        Parameters
        ----------
        request : BackendRuntimeInventoryRequest
            Runtime inventory persistence request.

        Returns
        -------
        None
            Runtime inventory is replaced in place.
        """
        root = request.root
        state = self._conn_state(root, request.conn)
        state.runtime_inventory = (
            request.backend_name,
            request.backend_version,
            int(request.coverage_complete),
        )
        state.analyzer_inventory = [
            (
                str(analyzer.name),
                str(analyzer.version),
                json.dumps(tuple(analyzer.discovery_globs)),
            )
            for analyzer in sorted(request.analyzers, key=lambda item: str(item.name))
        ]

    def commit(self, root: Path, *, conn: object) -> None:
        """
        Commit pending writes for an in-memory connection.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object
            Backend connection handle.

        Returns
        -------
        None
            Commit is a no-op for in-memory state.
        """
        self._conn_state(root, conn)

    def close_connection(self, conn: object) -> None:
        """
        Close an in-memory backend connection.

        Parameters
        ----------
        conn : object
            Backend connection handle.

        Returns
        -------
        None
            Close is a no-op for in-memory state.

        Raises
        ------
        TypeError
            If ``conn`` is not an in-memory backend connection.
        """
        if not isinstance(conn, _MemoryConnection):
            msg = "MemoryIndexBackend received an incompatible connection handle."
            raise TypeError(msg)

    def find_include_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[IncludeEdgeRow]:
        """
        Find include-like edges by owner module or target name.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[codira.contracts.IncludeEdgeRow]
            Matching include edge rows.
        """
        root = request.root
        state = self._conn_state(root, request.conn)
        normalized_prefix = normalize_prefix(root, request.prefix)
        rows = [
            (imp.module_name, imp.name, imp.kind, imp.lineno)
            for imp in state.imports
            if imp.kind in {"include_local", "include_system"}
            and path_has_prefix(state.files[imp.file_id].path, normalized_prefix)
            and (
                (
                    request.incoming
                    and imp.name == request.name
                    and (request.module is None or request.module == imp.module_name)
                )
                or (not request.incoming and imp.module_name == request.name)
            )
        ]
        return sorted(rows, key=lambda row: (row[0], row[3], row[1], row[2]))

    def find_logical_symbols(
        self,
        root: Path,
        module_name: str,
        logical_name: str,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Resolve a logical symbol identity to indexed symbol rows.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module_name : str
            Module that owns the logical symbol.
        logical_name : str
            Logical symbol name.
        prefix : str | None, optional
            Optional repository-relative path prefix.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.SymbolRow]
            Matching symbol rows.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        if "." in logical_name:
            rows = [
                symbol.row(state.files[symbol.file_id].path)
                for symbol in state.symbols
                if symbol.module_name == module_name
                and symbol.logical_name == logical_name
                and symbol.type == "method"
                and path_has_prefix(state.files[symbol.file_id].path, normalized_prefix)
            ]
            return sorted(rows, key=lambda row: (row[3], row[4], row[2]))

        rows = [
            symbol.row(state.files[symbol.file_id].path)
            for symbol in state.symbols
            if symbol.module_name == module_name
            and (
                symbol.name == logical_name
                or (symbol.type == "module" and symbol.module_name == logical_name)
            )
            and path_has_prefix(state.files[symbol.file_id].path, normalized_prefix)
        ]
        return sorted(rows, key=lambda row: (row[0], row[1], row[3], row[4]))

    def logical_symbol_name(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> str:
        """
        Return graph logical identity for one symbol row.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : codira.contracts.SymbolRow
            Symbol row whose logical identity should be resolved.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        str
            Logical symbol name used in graph rows.
        """
        self._conn_state(root, conn)
        symbol_type, module_name, name, file_path, lineno = symbol
        if symbol_type == "module":
            return module_name
        if symbol_type != "method":
            return name
        state = self._conn_state(root, conn)
        for stored in state.symbols:
            if (
                stored.type == "method"
                and stored.module_name == module_name
                and stored.name == name
                and stored.lineno == lineno
                and state.files[stored.file_id].path == file_path
            ):
                return stored.logical_name
        return name

    def embedding_inventory(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> list[tuple[str, str, int, int]]:
        """
        Return embedding counts grouped by backend metadata.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[tuple[str, str, int, int]]
            Backend name, version, vector dimension, and count rows.
        """
        state = self._conn_state(root, conn)
        counts: dict[tuple[str, str, int], int] = {}
        for embedding in state.embeddings:
            key = (embedding.backend, embedding.version, embedding.dim)
            counts[key] = counts.get(key, 0) + 1
        return [
            (backend, version, dim, counts[(backend, version, dim)])
            for backend, version, dim in sorted(counts)
        ]

    def embedding_candidates(
        self,
        request: BackendEmbeddingCandidatesRequest,
    ) -> ChannelResults:
        """
        Return deterministic pseudo-vector embedding candidates.

        Parameters
        ----------
        request : BackendEmbeddingCandidatesRequest
            Embedding candidate lookup request.

        Returns
        -------
        codira.contracts.ChannelResults
            Ranked embedding candidate rows.
        """
        root = request.root
        state = self._conn_state(root, request.conn)
        normalized_prefix = normalize_prefix(root, request.prefix)
        active = self.embedding_inventory(root, conn=request.conn)
        if not active:
            return []
        backend_name, backend_version, dim, _count = active[0]
        query_vector = _deserialize_vector(
            _pseudo_vector_blob(request.query, dim=dim),
            dim=dim,
        )
        symbol_by_id = {symbol.id: symbol for symbol in state.symbols}
        results: ChannelResults = []
        for embedding in state.embeddings:
            if (
                embedding.backend != backend_name
                or embedding.version != backend_version
            ):
                continue
            symbol = symbol_by_id.get(embedding.symbol_id)
            if symbol is None:
                continue
            file_path = state.files[symbol.file_id].path
            if not path_has_prefix(file_path, normalized_prefix):
                continue
            score = _dot_similarity(
                query_vector,
                _deserialize_vector(embedding.vector, dim=embedding.dim),
            )
            if score < request.min_score:
                continue
            results.append((score, symbol.row(file_path)))
        results.sort(
            key=lambda item: (
                -item[0],
                item[1][1],
                item[1][2],
                item[1][3],
                item[1][4],
                item[1][0],
            )
        )
        return results[: request.limit]

    def prune_orphaned_embeddings(
        self,
        root: Path,
        *,
        conn: object | None = None,
    ) -> None:
        """
        Remove embeddings whose owning symbol no longer exists.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        None
            Orphaned embeddings are removed in place.
        """
        state = self._conn_state(root, conn)
        symbol_ids = {symbol.id for symbol in state.symbols}
        state.embeddings = [
            embedding
            for embedding in state.embeddings
            if embedding.symbol_id in symbol_ids
        ]

    def current_embedding_state_matches(
        self,
        root: Path,
        *,
        embedding_backend: EmbeddingBackendSpec,
        conn: object | None = None,
    ) -> bool:
        """
        Return whether stored embeddings match the active backend.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        embedding_backend : codira.contracts.EmbeddingBackendSpec
            Active embedding backend metadata.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        bool
            ``True`` when stored embeddings are empty or match the backend.
        """
        state = self._conn_state(root, conn)
        observed = {(row.backend, row.version) for row in state.embeddings}
        return not observed or observed == {
            (embedding_backend.name, embedding_backend.version)
        }

    def list_symbols_in_module(
        self,
        root: Path,
        module: str,
        *,
        prefix: str | None = None,
        limit: int = 20,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Return indexed symbols belonging to one module.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        module : str
            Module name to list.
        prefix : str | None, optional
            Optional repository-relative path prefix.
        limit : int, optional
            Maximum number of rows to return.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.SymbolRow]
            Matching symbol rows.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        rows = [
            symbol.row(state.files[symbol.file_id].path)
            for symbol in state.symbols
            if symbol.module_name == module
            and path_has_prefix(state.files[symbol.file_id].path, normalized_prefix)
        ]
        return rows[:limit]

    def find_symbol(
        self,
        root: Path,
        name: str,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[SymbolRow]:
        """
        Find exact symbol-name matches.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Symbol name to match.
        prefix : str | None, optional
            Optional repository-relative path prefix.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.SymbolRow]
            Matching symbol rows.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        rows = [
            symbol.row(state.files[symbol.file_id].path)
            for symbol in state.symbols
            if symbol.name == name
            and path_has_prefix(state.files[symbol.file_id].path, normalized_prefix)
        ]
        return sorted(rows, key=lambda row: (row[0], row[1], row[3], row[4]))

    def symbol_inventory(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        include_tests: bool = False,
        limit: int = 1000,
        conn: object | None = None,
    ) -> list[BackendSymbolInventoryItem]:
        """
        Return indexed symbols with graph connectivity metrics.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional repository-relative path prefix.
        include_tests : bool, optional
            Whether symbols from ``tests`` modules are included.
        limit : int, optional
            Maximum number of rows to return.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.BackendSymbolInventoryItem]
            Matching symbol inventory rows.

        Raises
        ------
        ValueError
            If ``limit`` is negative.
        """
        if limit < 0:
            msg = "Limit must be non-negative."
            raise ValueError(msg)

        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        rows = [
            symbol.row(state.files[symbol.file_id].path)
            for symbol in state.symbols
            if path_has_prefix(state.files[symbol.file_id].path, normalized_prefix)
            and (
                include_tests
                or (
                    symbol.module_name != "tests"
                    and not symbol.module_name.startswith("tests.")
                )
            )
        ]
        sorted_rows = sorted(
            rows,
            key=lambda row: (row[1], row[2], row[0], row[3], row[4]),
        )
        symbols: list[SymbolRow] = []
        seen_identities: set[tuple[str, str]] = set()
        for row in sorted_rows:
            identity = (row[1], row[2])
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            symbols.append(row)

        call_edges = self._derived_relations(state, state.call_records)
        callable_refs = self._derived_relations(state, state.callable_ref_records)
        return [
            BackendSymbolInventoryItem(
                symbol_type=symbol_type,
                module=module_name,
                name=symbol_name,
                file=file_path,
                lineno=lineno,
                calls_out=self._inventory_metric(
                    call_edges,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    module_index=0,
                    name_index=1,
                ),
                calls_in=self._inventory_metric(
                    call_edges,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    module_index=2,
                    name_index=3,
                ),
                refs_out=self._inventory_metric(
                    callable_refs,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    module_index=0,
                    name_index=1,
                ),
                refs_in=self._inventory_metric(
                    callable_refs,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    module_index=2,
                    name_index=3,
                ),
            )
            for symbol_type, module_name, symbol_name, file_path, lineno in symbols[
                :limit
            ]
        ]

    def _inventory_metric(
        self,
        rows: Sequence[CallEdgeRow],
        *,
        module_name: str,
        symbol_name: str,
        module_index: int,
        name_index: int,
    ) -> BackendGraphMetric:
        """
        Count inventory graph edges for one symbol identity.

        Parameters
        ----------
        rows : collections.abc.Sequence[CallEdgeRow]
            Derived relation rows to inspect.
        module_name : str
            Module component of the symbol identity.
        symbol_name : str
            Name component of the symbol identity.
        module_index : int
            Relation tuple index containing the endpoint module.
        name_index : int
            Relation tuple index containing the endpoint name.

        Returns
        -------
        codira.contracts.BackendGraphMetric
            Total and unresolved counts for the selected endpoint.
        """
        matched_rows = [
            row
            for row in rows
            if row[module_index] == module_name and row[name_index] == symbol_name
        ]
        return BackendGraphMetric(
            total=len(matched_rows),
            unresolved=sum(1 for row in matched_rows if row[4] == 0),
        )

    def find_symbol_overloads(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> list[OverloadRow]:
        """
        Return overload metadata attached to one canonical callable symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : codira.types.SymbolRow
            Canonical function or method symbol row.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.types.OverloadRow]
            Ordered overload metadata rows for the symbol.
        """
        state = self._conn_state(root, conn)
        symbol_type, module_name, symbol_name, file_path, lineno = symbol
        if symbol_type not in {"function", "method"}:
            return []
        rows = [
            (
                overload.stable_id,
                overload.parent_stable_id,
                overload.ordinal,
                overload.signature,
                overload.lineno,
                overload.end_lineno,
                overload.docstring,
            )
            for overload in state.overloads
            if overload.symbol_type == symbol_type
            and overload.module_name == module_name
            and overload.symbol_name == symbol_name
            and overload.symbol_lineno == lineno
            and state.files[overload.file_id].path == file_path
        ]
        return sorted(rows, key=lambda row: (row[4], row[2], row[0]))

    def find_symbol_enum_members(
        self,
        root: Path,
        symbol: SymbolRow,
        *,
        conn: object | None = None,
    ) -> list[EnumMemberRow]:
        """
        Return enum-member metadata attached to one canonical enum symbol.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        symbol : codira.types.SymbolRow
            Canonical enum symbol row.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.types.EnumMemberRow]
            Ordered enum-member metadata rows for the symbol.
        """
        state = self._conn_state(root, conn)
        symbol_type, module_name, symbol_name, file_path, lineno = symbol
        if symbol_type != "enum":
            return []
        rows = [
            (
                enum_member.stable_id,
                enum_member.parent_stable_id,
                enum_member.ordinal,
                enum_member.name,
                enum_member.signature,
                enum_member.lineno,
            )
            for enum_member in state.enum_members
            if enum_member.module_name == module_name
            and enum_member.symbol_name == symbol_name
            and enum_member.symbol_lineno == lineno
            and state.files[enum_member.file_id].path == file_path
        ]
        return sorted(rows, key=lambda row: (row[2], row[5], row[3]))

    def docstring_issues(
        self,
        root: Path,
        *,
        prefix: str | None = None,
        conn: object | None = None,
    ) -> list[DocstringIssueRow]:
        """
        Return indexed docstring validation issues.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        prefix : str | None, optional
            Optional repository-relative path prefix.
        conn : object | None, optional
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.DocstringIssueRow]
            Matching docstring issue rows.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        rows = [
            (
                issue.issue_type,
                issue.message,
                issue.stable_id,
                issue.symbol_type,
                issue.module_name,
                issue.symbol_name,
                state.files[issue.file_id].path,
                issue.lineno,
                issue.end_lineno,
            )
            for issue in state.doc_issues
            if path_has_prefix(state.files[issue.file_id].path, normalized_prefix)
        ]
        return sorted(rows, key=lambda row: (row[0], row[6], row[7], row[1]))

    def find_call_edges(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[CallEdgeRow]:
        """
        Find exact call edges by caller or callee logical name.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Matching call edge rows.
        """
        return self._find_relations(
            request.root,
            request.name,
            records_attr="call_records",
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            conn=request.conn,
        )

    def find_callable_refs(
        self,
        request: BackendRelationQueryRequest,
    ) -> list[CallEdgeRow]:
        """
        Find exact callable-reference edges by owner or target name.

        Parameters
        ----------
        request : BackendRelationQueryRequest
            Exact relation lookup request.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Matching callable-reference edge rows.
        """
        return self._find_relations(
            request.root,
            request.name,
            records_attr="callable_ref_records",
            module=request.module,
            incoming=request.incoming,
            prefix=request.prefix,
            conn=request.conn,
        )

    def _append_symbol(
        self,
        state: _MemoryState,
        *,
        file_id: int,
        stable_id: str,
        symbol_type: str,
        module_name: str,
        name: str,
        lineno: int,
        logical_name: str,
    ) -> int:
        """
        Append one symbol row and return its identifier.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            Owning file identifier.
        stable_id : str
            Durable symbol identifier.
        symbol_type : str
            Symbol kind.
        module_name : str
            Owning module name.
        name : str
            Symbol display name.
        lineno : int
            Source line number.
        logical_name : str
            Graph-facing logical symbol name.

        Returns
        -------
        int
            Allocated in-memory symbol identifier.
        """
        symbol_id = state.next_symbol_id
        state.next_symbol_id += 1
        state.symbols.append(
            _MemorySymbol(
                id=symbol_id,
                file_id=file_id,
                stable_id=stable_id,
                type=symbol_type,
                module_name=module_name,
                name=name,
                lineno=lineno,
                logical_name=logical_name,
            )
        )
        return symbol_id

    def _append_doc_issues(
        self,
        state: _MemoryState,
        *,
        file_id: int,
        label: str,
        docstring: str | None,
        is_public: int,
        stable_id: str,
        symbol_type: str,
        module_name: str,
        symbol_name: str,
        lineno: int,
        end_lineno: int | None,
        parameters: Sequence[str] = (),
        require_callable_sections: bool = False,
        yields_value: bool = False,
        returns_value: bool = False,
        raises_exception: bool = False,
    ) -> None:
        """
        Append validator findings for one artifact.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            Owning file identifier.
        label : str
            Artifact label prefixed onto issue messages.
        docstring : str | None
            Artifact docstring to validate.
        is_public : int
            Public visibility flag passed to the validator.
        stable_id : str
            Durable symbol identifier.
        symbol_type : str
            Symbol kind.
        module_name : str
            Owning module name.
        symbol_name : str
            Symbol name stored on the issue row.
        lineno : int
            Source line number.
        end_lineno : int | None
            Ending source line number when available.
        parameters : collections.abc.Sequence[str], optional
            Callable parameters used by the validator.
        require_callable_sections : bool, optional
            Whether callable-specific sections must be present.
        yields_value : bool, optional
            Whether the callable yields values.
        returns_value : bool, optional
            Whether the callable returns values.
        raises_exception : bool, optional
            Whether the callable raises exceptions.

        Returns
        -------
        None
            Matching docstring issues are appended in place.
        """
        for issue_type, message in validate_docstring(
            DocstringValidationRequest(
                doc=docstring,
                is_public=is_public,
                parameters=list(parameters),
                require_callable_sections=require_callable_sections,
                yields_value=yields_value,
                returns_value=returns_value,
                raises_exception=raises_exception,
            )
        ):
            state.doc_issues.append(
                _MemoryDocIssue(
                    issue_type=issue_type,
                    message=f"{label}: {message}",
                    stable_id=stable_id,
                    symbol_type=symbol_type,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    file_id=file_id,
                    lineno=lineno,
                    end_lineno=end_lineno,
                )
            )

    def _append_overloads(
        self,
        state: _MemoryState,
        *,
        file_id: int,
        module_name: str,
        symbol_type: str,
        symbol_name: str,
        symbol_lineno: int,
        overloads: Sequence[OverloadArtifact],
    ) -> None:
        """
        Append overload metadata rows for one canonical callable.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            Owning file identifier.
        module_name : str
            Owning module name.
        symbol_type : str
            Canonical callable kind.
        symbol_name : str
            Canonical callable name.
        symbol_lineno : int
            Canonical callable definition line number.
        overloads : collections.abc.Sequence[codira.models.OverloadArtifact]
            Ordered overload artifacts attached to the callable.

        Returns
        -------
        None
            Overload rows are appended in place.
        """
        for overload in overloads:
            state.overloads.append(
                _MemoryOverload(
                    file_id=file_id,
                    module_name=module_name,
                    symbol_type=symbol_type,
                    symbol_name=symbol_name,
                    symbol_lineno=symbol_lineno,
                    stable_id=str(overload.stable_id),
                    parent_stable_id=str(overload.parent_stable_id),
                    ordinal=int(overload.ordinal),
                    signature=str(overload.signature),
                    lineno=int(overload.lineno),
                    end_lineno=overload.end_lineno,
                    docstring=overload.docstring,
                )
            )

    def _append_enum_members(
        self,
        state: _MemoryState,
        *,
        file_id: int,
        module_name: str,
        symbol_name: str,
        symbol_lineno: int,
        enum_members: Sequence[EnumMemberArtifact],
    ) -> None:
        """
        Append enum-member metadata rows for one canonical enum declaration.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            Owning file identifier.
        module_name : str
            Owning module name.
        symbol_name : str
            Canonical enum declaration name.
        symbol_lineno : int
            Canonical enum declaration line number.
        enum_members : collections.abc.Sequence[codira.models.EnumMemberArtifact]
            Ordered enum members attached to the declaration.

        Returns
        -------
        None
            Enum-member rows are appended in place.
        """
        for enum_member in enum_members:
            state.enum_members.append(
                _MemoryEnumMember(
                    file_id=file_id,
                    module_name=module_name,
                    symbol_name=symbol_name,
                    symbol_lineno=symbol_lineno,
                    stable_id=str(enum_member.stable_id),
                    parent_stable_id=str(enum_member.parent_stable_id),
                    ordinal=int(enum_member.ordinal),
                    name=str(enum_member.name),
                    signature=str(enum_member.signature),
                    lineno=int(enum_member.lineno),
                )
            )

    def _append_relations(
        self,
        state: _MemoryState,
        *,
        file_id: int,
        module_name: str,
        owner_name: str,
        calls: Sequence[CallSite],
        refs: Sequence[CallableReference],
    ) -> None:
        """
        Append raw call and callable-reference records.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            Owning file identifier.
        module_name : str
            Owning module name.
        owner_name : str
            Logical owner name.
        calls : collections.abc.Sequence[codira.contracts.CallSite]
            Raw call sites to append.
        refs : collections.abc.Sequence[codira.contracts.CallableReference]
            Raw callable references to append.

        Returns
        -------
        None
            Relation records are appended in place.
        """
        for call in calls:
            state.call_records.append(
                _MemoryRelation(
                    file_id=file_id,
                    owner_module=module_name,
                    owner_name=owner_name,
                    kind=str(call.kind),
                    base=str(call.base),
                    target=str(call.target),
                    lineno=int(call.lineno),
                    col_offset=int(call.col_offset),
                )
            )
        for ref in refs:
            state.callable_ref_records.append(
                _MemoryRelation(
                    file_id=file_id,
                    owner_module=module_name,
                    owner_name=owner_name,
                    kind=str(ref.kind),
                    base=str(ref.base),
                    target=str(ref.target),
                    lineno=int(ref.lineno),
                    col_offset=int(ref.col_offset),
                )
            )

    def _persist_embeddings(
        self,
        state: _MemoryState,
        *,
        embedding_payloads: list[tuple[int, str, str]],
        embedding_backend: EmbeddingBackendSpec,
        previous_embeddings: Mapping[str, object],
    ) -> tuple[int, int]:
        """
        Persist deterministic embedding rows and report reuse counts.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        embedding_payloads : list[tuple[int, str, str]]
            Symbol id, stable id, and embedding text rows to persist.
        embedding_backend : codira.contracts.EmbeddingBackendSpec
            Active embedding backend metadata.
        previous_embeddings : collections.abc.Mapping[str, object]
            Previously persisted embeddings keyed by stable symbol id.

        Returns
        -------
        tuple[int, int]
            Recomputed and reused embedding counts.
        """
        recomputed = 0
        reused = 0
        for symbol_id, stable_id, text in sorted(embedding_payloads):
            content_hash = _content_hash(text)
            reusable = previous_embeddings.get(stable_id)
            reusable_row = cast("_ReusableEmbedding", reusable)
            if (
                reusable is not None
                and str(reusable_row.content_hash) == content_hash
                and int(reusable_row.dim) == embedding_backend.dim
            ):
                vector = bytes(reusable_row.vector)
                reused += 1
            else:
                vector = _pseudo_vector_blob(text, dim=embedding_backend.dim)
                recomputed += 1
            state.embeddings.append(
                _MemoryEmbedding(
                    symbol_id=symbol_id,
                    stable_id=stable_id,
                    backend=embedding_backend.name,
                    version=embedding_backend.version,
                    content_hash=content_hash,
                    dim=embedding_backend.dim,
                    vector=vector,
                )
            )
        return (recomputed, reused)

    def _delete_file_artifacts(self, state: _MemoryState, file_id: int) -> None:
        """
        Delete all artifacts owned by one file id.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        file_id : int
            File identifier whose artifacts should be removed.

        Returns
        -------
        None
            Matching artifacts are deleted in place.
        """
        deleted_symbol_ids = {
            symbol.id for symbol in state.symbols if symbol.file_id == file_id
        }
        state.symbols = [
            symbol for symbol in state.symbols if symbol.file_id != file_id
        ]
        state.functions = [
            function for function in state.functions if function.file_id != file_id
        ]
        state.imports = [imp for imp in state.imports if imp.file_id != file_id]
        state.call_records = [
            record for record in state.call_records if record.file_id != file_id
        ]
        state.callable_ref_records = [
            record for record in state.callable_ref_records if record.file_id != file_id
        ]
        state.overloads = [
            overload for overload in state.overloads if overload.file_id != file_id
        ]
        state.enum_members = [
            enum_member
            for enum_member in state.enum_members
            if enum_member.file_id != file_id
        ]
        state.doc_issues = [
            issue for issue in state.doc_issues if issue.file_id != file_id
        ]
        state.embeddings = [
            embedding
            for embedding in state.embeddings
            if embedding.symbol_id not in deleted_symbol_ids
        ]

    def _module_functions(self, state: _MemoryState) -> dict[str, set[str]]:
        """
        Return top-level functions keyed by module name.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[str, set[str]]
            Top-level function names keyed by module name.
        """
        module_functions: dict[str, set[str]] = {}
        for function in state.functions:
            if function.class_name is None:
                module_functions.setdefault(function.module_name, set()).add(
                    function.name
                )
        return module_functions

    def _class_methods(self, state: _MemoryState) -> dict[tuple[str, str], set[str]]:
        """
        Return method names keyed by ``(module, class)``.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[tuple[str, str], set[str]]
            Method names keyed by module and class name.
        """
        class_methods: dict[tuple[str, str], set[str]] = {}
        for function in state.functions:
            if function.class_name is not None:
                class_methods.setdefault(
                    (function.module_name, function.class_name),
                    set(),
                ).add(function.name)
        return class_methods

    def _import_aliases(self, state: _MemoryState) -> dict[str, dict[str, str]]:
        """
        Return import aliases keyed by owning module.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.

        Returns
        -------
        dict[str, dict[str, str]]
            Import alias maps keyed by owning module.
        """
        aliases_by_module: dict[str, dict[str, str]] = {}
        for imp in sorted(
            state.imports,
            key=lambda item: (
                item.module_name,
                item.lineno,
                item.name,
                item.alias or "",
            ),
        ):
            if imp.kind != "import":
                continue
            aliases = aliases_by_module.setdefault(imp.module_name, {})
            local_name = imp.alias if imp.alias is not None else imp.name.split(".")[-1]
            if "." in imp.name and imp.alias is None and "." not in local_name:
                aliases[imp.name] = imp.name
            aliases[local_name] = imp.name
        return aliases_by_module

    def _resolve_relation(
        self,
        state: _MemoryState,
        record: _MemoryRelation,
    ) -> tuple[str | None, str | None, int]:
        """
        Resolve one raw call-style relation conservatively.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        record : _MemoryRelation
            Raw relation record to resolve.

        Returns
        -------
        tuple[str | None, str | None, int]
            Target module, target logical name, and certainty flag.
        """
        module_functions = self._module_functions(state)
        class_methods = self._class_methods(state)
        import_aliases = self._import_aliases(state).get(record.owner_module, {})
        candidates: set[tuple[str, str]] = set()

        if record.kind == "name" and record.target:
            imported = import_aliases.get(record.target)
            if imported is not None and "." in imported:
                imported_module, imported_name = imported.rsplit(".", 1)
                if imported_name in module_functions.get(imported_module, set()):
                    candidates.add((imported_module, imported_name))
            if record.target in module_functions.get(record.owner_module, set()):
                candidates.add((record.owner_module, record.target))

        if record.kind == "attribute" and record.target:
            caller_class = (
                record.owner_name.rsplit(".", 1)[0]
                if "." in record.owner_name
                else None
            )
            if caller_class is not None and record.base in {"self", "cls"}:
                methods = class_methods.get((record.owner_module, caller_class), set())
                if record.target in methods:
                    candidates.add(
                        (record.owner_module, f"{caller_class}.{record.target}")
                    )
            methods = class_methods.get((record.owner_module, record.base), set())
            if record.target in methods:
                candidates.add((record.owner_module, f"{record.base}.{record.target}"))
            imported = import_aliases.get(record.base)
            if imported is not None and record.target in module_functions.get(
                imported,
                set(),
            ):
                candidates.add((imported, record.target))

        if len(candidates) == 1:
            module_name, name = next(iter(candidates))
            return (module_name, name, 1)
        return (None, None, 0)

    def _derived_relations(
        self,
        state: _MemoryState,
        records: Sequence[_MemoryRelation],
    ) -> list[CallEdgeRow]:
        """
        Resolve raw relation records into public edge rows.

        Parameters
        ----------
        state : _MemoryState
            Mutable backend state.
        records : collections.abc.Sequence[_MemoryRelation]
            Raw relation records to resolve.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Derived graph edge rows.
        """
        rows = {
            (
                record.owner_module,
                record.owner_name,
                *self._resolve_relation(state, record),
            )
            for record in records
        }
        return sorted(
            rows,
            key=lambda row: (row[0], row[1], row[2] or "", row[3] or "", row[4]),
        )

    def _find_relations(
        self,
        root: Path,
        name: str,
        *,
        records_attr: str,
        module: str | None,
        incoming: bool,
        prefix: str | None,
        conn: object | None,
    ) -> list[CallEdgeRow]:
        """
        Find derived relation rows for calls or callable refs.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        name : str
            Owner or target logical name to match.
        records_attr : str
            State attribute containing raw relation records.
        module : str | None
            Optional module filter.
        incoming : bool
            Whether to search incoming relations.
        prefix : str | None
            Optional repository-relative path prefix.
        conn : object | None
            Optional backend connection.

        Returns
        -------
        list[codira.contracts.CallEdgeRow]
            Matching derived relation rows.

        Raises
        ------
        TypeError
            If ``records_attr`` does not resolve to a relation list.
        """
        state = self._conn_state(root, conn)
        normalized_prefix = normalize_prefix(root, prefix)
        records = getattr(state, records_attr)
        if not isinstance(records, list):
            msg = f"Unknown relation collection: {records_attr}"
            raise TypeError(msg)
        file_path_by_owner = {
            (record.owner_module, record.owner_name): state.files[record.file_id].path
            for record in records
        }
        rows = [
            row
            for row in self._derived_relations(state, records)
            if path_has_prefix(file_path_by_owner[(row[0], row[1])], normalized_prefix)
            and (
                (incoming and row[3] == name and (module is None or row[2] == module))
                or (
                    not incoming
                    and row[1] == name
                    and (module is None or row[0] == module)
                )
            )
        ]
        return sorted(
            rows,
            key=lambda row: (row[0], row[1], row[2] or "", row[3] or "", row[4]),
        )


def build_backend() -> MemoryIndexBackend:
    """
    Build the test-only in-memory backend.

    Parameters
    ----------
    None

    Returns
    -------
    MemoryIndexBackend
        Fresh backend instance with empty state.
    """
    return MemoryIndexBackend()
