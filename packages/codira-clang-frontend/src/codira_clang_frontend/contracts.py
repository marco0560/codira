"""Typed, core-independent records returned by the optional Clang frontend.

Parameters
----------
None

Returns
-------
None
    Module namespace for frontend profiles and result records.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ProfileOrigin = Literal["compile_commands", "captured_argv"]
ProfileStatus = Literal["complete", "partial"]
EnvironmentMode = Literal["controlled_no_ambient", "captured_allowlisted"]
EntityProvenance = Literal[
    "source_written",
    "macro_replacement",
    "implicit",
    "template_instantiation",
    "unknown",
]
FrontendStatus = Literal["parsed", "diagnostics", "held", "failed"]
CoverageState = Literal["complete", "partial"]


@dataclass(frozen=True)
class DependencyInput:
    """One externally captured dependency with a content identity.

    Parameters
    ----------
    path : pathlib.Path
        Dependency path as reported by the compile profile provider.
    sha256 : str
        SHA-256 digest of the captured dependency bytes.

    Returns
    -------
    None
        Immutable dependency identity.
    """

    path: Path
    sha256: str


@dataclass(frozen=True)
class IncludeDirectoryInput:
    """One captured include search directory and its recursive membership.

    Parameters
    ----------
    path : pathlib.Path
        Absolute include search directory.
    membership_sha256 : str
        Digest of sorted relative paths and symlink targets below the directory.
    order : int, optional
        Effective Clang header-search order.
    kind : {"directory", "framework", "header_map", "quoted_include_parent"}, optional
        Search-directory form reported by Clang or source-relative quote-search
        directory observed as the parent of a parsed file.

    Returns
    -------
    None
        Immutable include directory identity.
    """

    path: Path
    membership_sha256: str
    order: int = 0
    kind: Literal["directory", "framework", "header_map", "quoted_include_parent"] = (
        "directory"
    )


@dataclass(frozen=True)
class CompilationContext:
    """Actual target and sysroot configuration reported by Clang.

    Parameters
    ----------
    target_triple : str
        Triple from the invocation's initialized Clang TargetInfo.
    sysroot : str
        Exact sysroot value from Clang HeaderSearchOptions.
    sysroot_path : pathlib.Path or None
        Absolute sysroot path resolved against the captured working directory,
        or ``None`` when the reported sysroot value is empty.

    Returns
    -------
    None
        Immutable compiler-derived invocation context.
    """

    target_triple: str
    sysroot: str
    sysroot_path: Path | None


@dataclass(frozen=True)
class CompileProfile:
    """Exact compiler profile for one translation unit.

    Parameters
    ----------
    source_path : pathlib.Path
        Absolute translation unit path.
    source_sha256 : str
        Captured source content identity.
    working_directory : pathlib.Path
        Exact compile command working directory.
    repository_root : pathlib.Path
        Repository root used for source containment and helper coordinates.
    argv : tuple[str, ...]
        Full original compiler argument vector, including the driver at index zero.
    language : {"c", "cpp"}
        Language selected by the owning analyzer, recorded without rewriting argv.
    origin : {"compile_commands", "captured_argv"}
        Source of the profile evidence.
    status : {"complete", "partial"}
        Provider's completeness assessment; running Clang never upgrades it.
    identity : str
        Stable hash binding the original command and its capture provenance.
    evidence_path : pathlib.Path or None
        Source file that retained the original profile evidence, if available.
    evidence_sha256 : str or None
        Digest of retained profile evidence.
    dependencies : tuple[codira_clang_frontend.contracts.DependencyInput, ...]
        Dependencies independently captured by the profile provider.
    include_directories : tuple[codira_clang_frontend.contracts.IncludeDirectoryInput, ...]
        Search-root directory memberships that detect newly shadowing headers.
    include_search_complete : bool
        Whether all explicit and implicit compiler search roots are bound.
    environment : tuple[tuple[str, str], ...]
        Explicitly captured compiler environment inputs; never inherited blindly.
    environment_mode : EnvironmentMode
        Whether the frontend uses captured allowlisted values or a controlled
        environment with ambient compiler include variables cleared.
    compilation_context : CompilationContext or None
        Native Clang context bound during explicit profile preparation.

    Returns
    -------
    None
        Immutable profile for one translation unit.
    """

    source_path: Path
    source_sha256: str
    working_directory: Path
    repository_root: Path
    argv: tuple[str, ...]
    language: Literal["c", "cpp"]
    origin: ProfileOrigin
    status: ProfileStatus
    identity: str
    evidence_path: Path | None = None
    evidence_sha256: str | None = None
    dependencies: tuple[DependencyInput, ...] = ()
    include_directories: tuple[IncludeDirectoryInput, ...] = ()
    include_search_complete: bool = False
    environment: tuple[tuple[str, str], ...] = ()
    environment_mode: EnvironmentMode = "controlled_no_ambient"
    compilation_context: CompilationContext | None = None


@dataclass(frozen=True)
class SourcePosition:
    """One Clang source coordinate, preserving unavailable fields as ``None``.

    Parameters
    ----------
    path : str or None
        Source path reported by Clang.
    line : int or None
        One-based source line, when available.
    column : int or None
        One-based source column, when available.
    offset : int or None
        Clang source byte offset, when available.

    Returns
    -------
    None
        Immutable source position.
    """

    path: str | None
    line: int | None
    column: int | None
    offset: int | None


@dataclass(frozen=True)
class SourcePoint:
    """Spelling and expansion positions for one source location.

    Parameters
    ----------
    spelling : SourcePosition or None
        Physical token spelling location.
    expansion : SourcePosition or None
        Macro expansion location.
    is_macro : bool
        Whether Clang marks the location as macro-derived.

    Returns
    -------
    None
        Immutable source location.
    """

    spelling: SourcePosition | None
    expansion: SourcePosition | None
    is_macro: bool


@dataclass(frozen=True)
class SourceSpan:
    """Inclusive Clang range with separate spelling and expansion coordinates.

    Parameters
    ----------
    begin, end : SourcePoint or None
        Source range endpoints.

    Returns
    -------
    None
        Immutable source range.
    """

    begin: SourcePoint | None
    end: SourcePoint | None


@dataclass(frozen=True)
class FrontendDeclaration:
    """One source or compiler-produced nonfunction declaration record.

    Parameters
    ----------
    usr : str or None
        Clang USR when generated.
    kind, name, qualified_name, decl_kind : str
        Canonical entity, display, qualified, and native declaration kinds.
    signature, type_text : str or None
        Signature or Clang type text when emitted by the helper.
    parameters : tuple[tuple[str, str], ...]
        Ordered parameter names and types, empty for noncallable declarations.
    has_prototype, is_definition : bool or None
        Function facts when applicable.
    provenance : EntityProvenance
        Source-written, macro-generated, implicit, or template origin.
    location : SourcePoint or None
        Clang spelling and expansion location.
    span : SourceSpan or None
        Clang spelling and expansion range.

    Returns
    -------
    None
        Immutable declaration record.
    """

    usr: str | None
    kind: str
    name: str
    qualified_name: str
    decl_kind: str
    signature: str | None
    type_text: str | None
    parameters: tuple[tuple[str, str], ...]
    has_prototype: bool | None
    is_definition: bool | None
    provenance: EntityProvenance
    location: SourcePoint | None
    span: SourceSpan | None


@dataclass(frozen=True)
class FrontendCall:
    """One call expression owned by its enclosing callable when known.

    Parameters
    ----------
    target, qualified_target, target_usr : str or None
        Callee identity fields; direct resolution may be unavailable.
    caller_usr, caller_name, caller_qualified_name : str or None
        Enclosing callable identity emitted by the helper.
    origin : EntityProvenance
        Physical source or macro replacement origin.
    location : SourcePoint or None
        Call target spelling and expansion location.
    span : SourceSpan or None
        Complete call expression range.

    Returns
    -------
    None
        Immutable call record.
    """

    target: str
    qualified_target: str | None
    target_usr: str | None
    caller_usr: str | None
    caller_name: str | None
    caller_qualified_name: str | None
    origin: EntityProvenance
    location: SourcePoint | None
    span: SourceSpan | None


@dataclass(frozen=True)
class FrontendCallable:
    """Callable record with its owned call expressions.

    Parameters
    ----------
    usr : str or None
        Clang USR when generated.
    kind, name, qualified_name : str
        Canonical callable kind and source names.
    lexical_owner : str or None
        Qualified lexical owner emitted by Clang.
    decl_kind : str
        Native Clang declaration kind, for example ``FunctionDecl`` or
        ``CXXMethodDecl``.
    signature, function_type : str
        Display signature and Clang function type.
    parameters : tuple[tuple[str, str], ...]
        Ordered parameter name and type pairs.
    has_prototype, is_definition : bool
        Clang callable facts.
    is_public : bool or None
        Explicit public access or external linkage fact when known.
    provenance : EntityProvenance
        Source-written, macro-generated, implicit, or template origin.
    location : SourcePoint or None
        Clang spelling and expansion location.
    span : SourceSpan or None
        Clang source range.
    calls : tuple[FrontendCall, ...]
        Calls whose enclosing callable USR matches this record.

    Returns
    -------
    None
        Immutable callable and owned calls.
    """

    usr: str | None
    kind: str
    name: str
    qualified_name: str
    lexical_owner: str | None
    decl_kind: str
    signature: str
    function_type: str
    parameters: tuple[tuple[str, str], ...]
    has_prototype: bool
    is_definition: bool
    is_public: bool | None
    provenance: EntityProvenance
    location: SourcePoint | None
    span: SourceSpan | None
    calls: tuple[FrontendCall, ...]


@dataclass(frozen=True)
class FrontendDiagnostic:
    """One Clang diagnostic record.

    Parameters
    ----------
    severity : str
        Clang severity name.
    message : str
        Clang-rendered diagnostic message.
    location : SourcePosition or None, optional
        Diagnostic coordinate when available.

    Returns
    -------
    None
        Immutable diagnostic.
    """

    severity: str
    message: str
    location: SourcePosition | None = None


@dataclass(frozen=True)
class DependencyClosure:
    """Compiler-observed dependency closure and content identity.

    Parameters
    ----------
    status : CoverageState
        Whether every compiler-observed dependency was hashed.
    files : tuple[DependencyInput, ...]
        Sorted absolute paths and content digests.
    sha256 : str
        Hash of canonical dependency records.
    search_directories : tuple[IncludeDirectoryInput, ...], optional
        Ordered effective Clang include search roots and membership hashes.
    search_directories_complete : bool, optional
        Whether every reported search root was read and hashed.

    Returns
    -------
    None
        Immutable dependency evidence.
    """

    status: CoverageState
    files: tuple[DependencyInput, ...]
    sha256: str
    search_directories: tuple[IncludeDirectoryInput, ...] = ()
    search_directories_complete: bool = False


@dataclass(frozen=True)
class ToolchainIdentity:
    """Build and runtime identity required to reproduce one helper result.

    Parameters
    ----------
    compiler_path : pathlib.Path
        Selected Clang compiler binary.
    compiler_sha256 : str
        Compiler binary digest.
    compiler_version : str
        Version captured during helper build.
    resource_dir : pathlib.Path
        Compiler builtin resource directory.
    resource_probe_sha256 : str
        Digest of the resource header used to bind builtin headers.
    helper_path : pathlib.Path
        Built LibTooling executable.
    helper_sha256 : str
        Helper binary digest.
    helper_source_sha256 : str
        Native helper source digest used for the build.
    build_receipt_path : pathlib.Path
        Build receipt path.
    build_receipt_sha256 : str
        Build receipt digest.
    package_version : str
        Shared frontend package version.
    runtime_shared_library_identity : {"not_hashed"}
        Explicit limitation for dynamically loaded LLVM libraries.

    Returns
    -------
    None
        Immutable toolchain identity.
    """

    compiler_path: Path
    compiler_sha256: str
    compiler_version: str
    resource_dir: Path
    resource_probe_sha256: str
    helper_path: Path
    helper_sha256: str
    helper_source_sha256: str
    build_receipt_path: Path
    build_receipt_sha256: str
    package_version: str
    runtime_shared_library_identity: Literal["not_hashed"]


@dataclass(frozen=True)
class FrontendResult:
    """Explicit Clang outcome, provenance, dependencies, and typed entities.

    Parameters
    ----------
    status : FrontendStatus
        Parser, diagnostics, held, or helper failure state.
    coverage_state : CoverageState
        Profile and dependency completeness; parsing never upgrades profile status.
    reasons : tuple[str, ...]
        Stable partial-coverage or failure reasons.
    diagnostics : tuple[FrontendDiagnostic, ...]
        Native Clang diagnostics.
    declarations : tuple[FrontendDeclaration, ...]
        Nonfunction declarations from the main translation unit.
    callables : tuple[FrontendCallable, ...]
        Functions and methods with owned calls.
    dependency_closure : DependencyClosure or None
        Compiler-observed and hashed dependency set.
    profile_identity : str
        Exact compile profile identity.
    toolchain_identity : ToolchainIdentity or None
        Verified native toolchain identity.
    cache_fingerprint : str
        Stable input and output dependency identity.
    stdout_path, stderr_path : pathlib.Path or None
        Immutable captured helper output paths.
    stdout_sha256, stderr_sha256 : str or None
        Raw helper output digests.
    unowned_calls : tuple[FrontendCall, ...], optional
        Calls whose enclosing callable was not emitted by this translation unit.
    adapted_argv : tuple[str, ...], optional
        Clang arguments after the recorded syntax-only adaptation.
    argument_transformations : tuple[str, ...], optional
        Ordered transformations applied to the original argv.
    environment_mode : EnvironmentMode, optional
        Explicit process environment policy used for the helper invocation.
    compilation_context : CompilationContext or None, optional
        Actual target and sysroot reported by this helper invocation.

    Returns
    -------
    None
        Immutable Clang frontend result.
    """

    status: FrontendStatus
    coverage_state: CoverageState
    reasons: tuple[str, ...]
    diagnostics: tuple[FrontendDiagnostic, ...]
    declarations: tuple[FrontendDeclaration, ...]
    callables: tuple[FrontendCallable, ...]
    dependency_closure: DependencyClosure | None
    profile_identity: str
    toolchain_identity: ToolchainIdentity | None
    cache_fingerprint: str
    stdout_path: Path | None
    stdout_sha256: str | None
    stderr_path: Path | None
    stderr_sha256: str | None
    unowned_calls: tuple[FrontendCall, ...] = ()
    adapted_argv: tuple[str, ...] = ()
    argument_transformations: tuple[str, ...] = ()
    environment_mode: EnvironmentMode = "controlled_no_ambient"
    compilation_context: CompilationContext | None = None
