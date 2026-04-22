"""Backend-neutral analysis models introduced for ADR-004.

Responsibilities
----------------
- Define data classes such as `FileMetadataSnapshot`, `ImportArtifact`, `DeclarationArtifact`, `CallSite`, and `FunctionArtifact`.
- Publish literal types and immutable structures used by normalization, storage, and retrieval.
- Serve as the canonical representation for normalized artifacts shared across layers.

Design principles
-----------------
Models are backend-neutral, immutable, and descriptive so analyzers and storage can share consistent type information.

Architectural role
------------------
This module belongs to the **modeling layer** that decouples normalized artifact structures from persistence details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

CallKind = Literal["name", "attribute", "unresolved"]
CallableReferenceKind = Literal[
    "mapping_value",
    "sequence_item",
    "assignment_value",
    "return_value",
]
ImportKind = Literal["import", "include_local", "include_system"]
DeclarationKind = Literal[
    "type_alias",
    "struct",
    "enum",
    "typedef",
    "json_schema_definition",
    "json_schema_property",
    "json_manifest_name",
    "json_manifest_script",
    "json_manifest_dependency",
    "json_release_plugin",
    "json_release_branch",
]


@dataclass(frozen=True)
class OverloadArtifact:
    """
    Normalized overload declaration attached to one canonical callable.

    Parameters
    ----------
    stable_id : str
        Durable analyzer-owned identity for the overload declaration.
    parent_stable_id : str
        Stable identity of the canonical function or method that owns the
        overload.
    ordinal : int
        Deterministic declaration order among overload variants for the same
        parent callable.
    signature : str
        Simplified overload signature text used for rendering.
    lineno : int
        First source line of the overload declaration.
    end_lineno : int | None
        Inclusive last source line when reported by the parser.
    docstring : str | None
        Overload docstring when present.
    """

    stable_id: str
    parent_stable_id: str
    ordinal: int
    signature: str
    lineno: int
    end_lineno: int | None
    docstring: str | None


@dataclass(frozen=True)
class FileMetadataSnapshot:
    """
    Stable file metadata used during indexing decisions.

    Parameters
    ----------
    path : pathlib.Path
        Absolute file path for the indexed source file.
    sha256 : str
        Content hash used for reuse decisions.
    mtime : float
        Last modification timestamp captured during scanning.
    size : int
        File size in bytes.
    analyzer_name : str, optional
        Analyzer name responsible for the indexed file.
    analyzer_version : str, optional
        Analyzer version responsible for the indexed file.
    """

    path: Path
    sha256: str
    mtime: float
    size: int
    analyzer_name: str = ""
    analyzer_version: str = ""


@dataclass(frozen=True)
class ImportArtifact:
    """
    Normalized import row produced by a language analyzer.

    Parameters
    ----------
    name : str
        Imported dotted target.
    alias : str | None
        Local alias bound by the import, if any.
    lineno : int
        Source line where the import appears.
    kind : {"import", "include_local", "include_system"}, optional
        Import-like artifact classifier.
    """

    name: str
    alias: str | None
    lineno: int
    kind: ImportKind = "import"


@dataclass(frozen=True)
class DeclarationArtifact:
    """
    Normalized module-level declaration artifact.

    Parameters
    ----------
    name : str
        Declaration name exposed to exact and semantic queries.
    stable_id : str
        Durable analyzer-owned identity for cross-run reuse.
    kind : {"type_alias", "struct", "enum", "typedef", "json_schema_definition", "json_schema_property", "json_manifest_name", "json_manifest_script", "json_manifest_dependency", "json_release_plugin", "json_release_branch"}
        Stable declaration classifier used as the symbol type.
    lineno : int
        Source line where the declaration begins.
    signature : str
        Collapsed declaration text used for semantic indexing.
    docstring : str | None, optional
        Leading comment summary used as semantic text when present.
    """

    name: str
    stable_id: str
    kind: DeclarationKind
    lineno: int
    signature: str
    docstring: str | None = None


@dataclass(frozen=True)
class CallSite:
    """
    Normalized call-site record for later resolution.

    Parameters
    ----------
    kind : {"name", "attribute", "unresolved"}
        Static classifier for the call target expression.
    target : str
        Resolved local target token when one is known.
    lineno : int
        Source line of the call target token.
    col_offset : int
        Source column of the call target token.
    base : str, optional
        Static attribute receiver path when the call is attribute-based.
    """

    kind: CallKind
    target: str
    lineno: int
    col_offset: int
    base: str = ""


@dataclass(frozen=True)
class CallableReference:
    """
    Normalized callable-object reference record.

    Parameters
    ----------
    kind : {"name", "attribute", "unresolved"}
        Static classifier for the referenced expression.
    target : str
        Referenced callable token when one is known.
    lineno : int
        Source line of the referenced expression.
    col_offset : int
        Source column of the referenced expression.
    ref_kind : {"mapping_value", "sequence_item", "assignment_value", "return_value"}
        Stable classifier for the owning expression context.
    base : str, optional
        Static attribute receiver path when the reference is attribute-based.
    """

    kind: CallKind
    target: str
    lineno: int
    col_offset: int
    ref_kind: CallableReferenceKind
    base: str = ""


@dataclass(frozen=True)
class FunctionArtifact:
    """
    Normalized function or method artifact.

    Parameters
    ----------
    name : str
        Unqualified function or method name.
    stable_id : str
        Durable analyzer-owned identity for cross-run reuse.
    lineno : int
        First source line of the definition.
    end_lineno : int | None
        Inclusive last source line when reported by the parser.
    signature : str
        Simplified signature text used by current rendering and indexing code.
    docstring : str | None
        Function docstring when present.
    has_docstring : int
        Integer flag compatible with the current SQLite schema.
    is_method : int
        Integer flag indicating whether the artifact belongs to a class.
    is_public : int
        Integer visibility flag compatible with current parser output.
    parameters : tuple[str, ...]
        Logical parameter names in declaration order.
    returns_value : int
        Integer flag indicating explicit value-returning paths.
    yields_value : int
        Integer flag indicating generator yield behavior.
    raises : int
        Integer flag indicating explicit ``raise`` statements.
    has_asserts : int
        Integer flag indicating explicit ``assert`` statements.
    decorators : tuple[str, ...]
        Deterministic static decorator names attached to the callable.
    calls : tuple[codira.models.CallSite, ...]
        Ordered call-site records owned by the function.
    callable_refs : tuple[codira.models.CallableReference, ...]
        Ordered callable-object reference records owned by the function.
    overloads : tuple[codira.models.OverloadArtifact, ...], optional
        Ordered overload declarations attached to the canonical callable.
    """

    name: str
    stable_id: str
    lineno: int
    end_lineno: int | None
    signature: str
    docstring: str | None
    has_docstring: int
    is_method: int
    is_public: int
    parameters: tuple[str, ...]
    returns_value: int
    yields_value: int
    raises: int
    has_asserts: int
    decorators: tuple[str, ...]
    calls: tuple[CallSite, ...]
    callable_refs: tuple[CallableReference, ...]
    overloads: tuple[OverloadArtifact, ...] = ()

    def logical_name(self, *, class_name: str | None = None) -> str:
        """
        Return the logical callable identifier used by the indexer.

        Parameters
        ----------
        class_name : str | None, optional
            Owning class name for method artifacts.

        Returns
        -------
        str
            Unqualified function name or ``Class.method`` for methods.
        """
        if class_name is None:
            return self.name
        return f"{class_name}.{self.name}"


@dataclass(frozen=True)
class ClassArtifact:
    """
    Normalized class artifact produced by a language analyzer.

    Parameters
    ----------
    name : str
        Class name.
    stable_id : str
        Durable analyzer-owned identity for cross-run reuse.
    lineno : int
        First source line of the class definition.
    end_lineno : int | None
        Inclusive last source line when reported by the parser.
    docstring : str | None
        Class docstring when present.
    has_docstring : int
        Integer flag compatible with the current SQLite schema.
    methods : tuple[codira.models.FunctionArtifact, ...]
        Ordered method artifacts owned by the class.
    """

    name: str
    stable_id: str
    lineno: int
    end_lineno: int | None
    docstring: str | None
    has_docstring: int
    methods: tuple[FunctionArtifact, ...]


@dataclass(frozen=True)
class ModuleArtifact:
    """
    Normalized module artifact produced by a language analyzer.

    Parameters
    ----------
    name : str
        Dotted module name.
    stable_id : str
        Durable analyzer-owned identity for cross-run reuse.
    docstring : str | None
        Module docstring when present.
    has_docstring : int
        Integer flag compatible with the current SQLite schema.
    """

    name: str
    stable_id: str
    docstring: str | None
    has_docstring: int


@dataclass(frozen=True)
class AnalysisResult:
    """
    Normalized analyzer output for one source file.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path that produced the analysis result.
    module : codira.models.ModuleArtifact
        Module-level artifact for the analyzed file.
    classes : tuple[codira.models.ClassArtifact, ...]
        Ordered class artifacts.
    functions : tuple[codira.models.FunctionArtifact, ...]
        Ordered top-level function artifacts.
    declarations : tuple[codira.models.DeclarationArtifact, ...]
        Ordered module-level declaration artifacts.
    imports : tuple[codira.models.ImportArtifact, ...]
        Ordered import artifacts.

    Notes
    -----
    The ordering of all artifact tuples is part of the contract. Downstream
    storage and query code may rely on that deterministic order.
    """

    source_path: Path
    module: ModuleArtifact
    classes: tuple[ClassArtifact, ...]
    functions: tuple[FunctionArtifact, ...]
    declarations: tuple[DeclarationArtifact, ...]
    imports: tuple[ImportArtifact, ...]

    def iter_functions(self) -> tuple[FunctionArtifact, ...]:
        """
        Return all top-level functions and methods in deterministic order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[codira.models.FunctionArtifact, ...]
            Top-level functions first, then class methods in class order.
        """
        methods = tuple(
            method
            for class_artifact in self.classes
            for method in class_artifact.methods
        )
        return self.functions + methods

    def iter_call_sites(self) -> tuple[CallSite, ...]:
        """
        Return all normalized call sites in deterministic ownership order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[codira.models.CallSite, ...]
            Call-site records ordered by function ownership order.
        """
        return tuple(call for fn in self.iter_functions() for call in fn.calls)

    def iter_overloads(self) -> tuple[OverloadArtifact, ...]:
        """
        Return all overload declarations in deterministic ownership order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[codira.models.OverloadArtifact, ...]
            Overload declarations ordered by callable ownership order.
        """
        return tuple(
            overload for fn in self.iter_functions() for overload in fn.overloads
        )

    def iter_callable_references(self) -> tuple[CallableReference, ...]:
        """
        Return all callable references in deterministic ownership order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[codira.models.CallableReference, ...]
            Callable-reference records ordered by function ownership order.
        """
        return tuple(ref for fn in self.iter_functions() for ref in fn.callable_refs)
