"""State records owned by the test-only in-memory index backend.

These records isolate the backend's process-local persistence representation
from its lifecycle and query implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.types import DocumentationRow, SymbolRow


CallEdgeRow = tuple[str, str, str | None, str | None, str | None, str | None, int]


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
    external_target_kind: str | None
    external_target_name: str | None
    lineno: int
    col_offset: int


@dataclass(frozen=True)
class _MemoryDocIssue:
    """Stored docstring validation issue with public query metadata."""

    issue_type: str
    message: str
    audit_language: str
    audit_plugin_name: str
    audit_plugin_version: str
    convention_name: str
    convention_version: str
    rule_id: str
    severity: str
    stable_id: str
    symbol_type: str
    module_name: str
    symbol_name: str
    file_id: int
    lineno: int
    end_lineno: int | None


@dataclass(frozen=True)
class _MemoryEmbedding:
    """Stored embedding metadata for one index object."""

    object_type: str
    object_id: int
    stable_id: str
    backend: str
    version: str
    content_hash: str
    dim: int
    vector: bytes


@dataclass(frozen=True)
class _MemoryDocumentation:
    """Stored documentation artifact with public query metadata."""

    id: int
    file_id: int
    stable_id: str
    kind: str
    source_format: str
    lineno: int
    end_lineno: int | None
    title: str
    heading_path: tuple[str, ...]
    text: str
    owner_stable_id: str | None
    owner_kind: str | None
    attachment_confidence: str | None

    def row(self, file_path: str) -> DocumentationRow:
        """
        Return the backend-neutral documentation row for this stored artifact.

        Parameters
        ----------
        file_path : str
            Absolute path owning the documentation artifact.

        Returns
        -------
        codira.types.DocumentationRow
            Public documentation-row representation.
        """
        return (
            self.stable_id,
            self.kind,
            self.source_format,
            file_path,
            self.lineno,
            self.end_lineno,
            self.title,
            self.heading_path,
            self.text,
        )


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


@dataclass
class _MemoryState:
    """Mutable root-scoped backend state."""

    root: Path | None = None
    next_file_id: int = 1
    next_symbol_id: int = 1
    next_documentation_id: int = 1
    files: dict[int, _MemoryFile] = field(default_factory=dict)
    file_id_by_path: dict[str, int] = field(default_factory=dict)
    symbols: list[_MemorySymbol] = field(default_factory=list)
    functions: list[_MemoryFunction] = field(default_factory=list)
    imports: list[_MemoryImport] = field(default_factory=list)
    call_records: list[_MemoryRelation] = field(default_factory=list)
    callable_ref_records: list[_MemoryRelation] = field(default_factory=list)
    reference_scan_lines: list[tuple[int, int, str]] = field(default_factory=list)
    overloads: list[_MemoryOverload] = field(default_factory=list)
    enum_members: list[_MemoryEnumMember] = field(default_factory=list)
    doc_issues: list[_MemoryDocIssue] = field(default_factory=list)
    documentation: list[_MemoryDocumentation] = field(default_factory=list)
    embeddings: list[_MemoryEmbedding] = field(default_factory=list)
    runtime_inventory: tuple[str, str, int] | None = None
    analyzer_inventory: list[tuple[str, str, str]] = field(default_factory=list)
