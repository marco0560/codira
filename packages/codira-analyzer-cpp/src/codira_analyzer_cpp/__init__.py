"""C++ language analyzer with Tree-sitter default and optional Clang frontend.

Responsibilities
----------------
- Initialize the tree-sitter C++ parser and derive durable symbol identities.
- Walk C++ parse trees to extract namespaces, classes, callables, declarations,
  and imports deterministically.
- Translate the collected metadata into `AnalysisResult` objects for
  persistence.

Design principles
-----------------
Tree-sitter remains the default. An explicitly selected shared Clang frontend
can supply a source-written declaration and call subset when its exact compile
profile and dependency closure are complete.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the
first-party C++ analysis path for the Phase 2 multi-language expansion.
Parameters
----------
None

Returns
-------
None
    Defines the orchestration or plugin interfaces described above.
"""

from __future__ import annotations

import re

import hashlib
import json
from bisect import bisect_right
from dataclasses import asdict, dataclass, field, replace
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira_clang_frontend import (
        ClangFrontend,
        CompilationContext,
        CompileProfile,
        FrontendCallable,
        FrontendPreprocessorEvent,
        FrontendResult,
        SourcePoint,
        SourcePosition,
        SourceSpan,
    )
    from codira.contracts import LanguageAnalyzer
    from .cpp_macro_expansion import _MacroDefinition
    from .cpp_macro_context import MacroSelection

from .cpp_namespace_bindings import (
    _namespace_bindings_from_config,
    _parse_with_namespace_bindings,
)
from .cpp_projection import SyntaxNode as Node, _ProjectedNode
from .cpp_preprocessor_queries import (
    FeatureAnswers,
    HeaderQuerySet,
    feature_answers,
    header_query_sets,
    header_queries_schema,
)

from .cpp_typedefs import _typedef_name_nodes
from .cpp_syntax import (
    _canonical_node_text,
    _class_stable_id,
    _conditional_children,
    _cpp_external_target_kind,
    _decode_source_text,
    _declaration_stable_id,
    _enum_member_stable_id,
    _function_stable_id,
    _module_name_for_path,
    _module_stable_id,
    _new_parser,
    _node_text,
    _normalize_signature,
    _qualified_name,
    _split_qualified_name,
    _symbol_owner_id,
)

from .cpp_comments import (
    CommentMaps,
    _attached_comment_map,
    _attached_doxygen_comment_map,
    _leading_module_comment,
    _leading_module_doxygen,
    source_comment_maps,
)

from .cpp_documentation import _documentation_artifacts
from .cpp_imports import _extract_imports
from .cpp_headers import has_named_template_parameters
from .cpp_include_context import (
    IncludeContext,
    include_identity_matches,
    read_include_context,
)
from .cpp_preprocessing import (
    _is_complex_operator_call,
    _original_declaration_start,
    _parse_cpp_source,
)

from codira.analysis_inputs import validate_analysis_input_fingerprint
from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.generated import (
    CompilerObservedCallableProvenance,
    CompilerObservedMacroInvocation,
    CompilerObservedSourceCoordinate,
)
from codira.models import (
    AnalysisResult,
    AnalysisDiagnostic,
    AnalysisStatus,
    AnalysisCoverageState,
    CallSite,
    CallKind,
    ClassArtifact,
    DeclarationArtifact,
    DeclarationKind,
    DocumentationArtifact,
    EnumMemberArtifact,
    FunctionArtifact,
    ImportArtifact,
    ModuleArtifact,
    SemanticIdentity,
    tree_sitter_recovery_status,
)
from codira.plugin_config import (
    AnalyzerPathFilters,
    analyzer_json_schema,
    analyzer_path_allowed,
    analyzer_path_filters_from_config,
    boolean_property,
    plugin_configuration_fingerprint,
)

_CPP_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".h"}
__all__ = ["CppAnalyzer", "_disambiguate_callable_stable_ids", "build_analyzer"]


def _clang_profile_and_frontend(
    *,
    path: Path,
    root: Path,
    compile_commands: str | None,
    captured_profiles: str | None,
    helper_path: str | None,
    build_receipt_path: str | None,
) -> tuple[ClangFrontend, CompileProfile]:
    """Load a profile through the optional shared frontend package.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit selected by the indexer.
    root : pathlib.Path
        Repository containing the translation unit.
    compile_commands, captured_profiles : str or None
        Mutually exclusive exact profile evidence sources.
    helper_path, build_receipt_path : str or None
        Explicit frontend helper and build receipt paths.

    Returns
    -------
    tuple[codira_clang_frontend.ClangFrontend, codira_clang_frontend.CompileProfile]
        Validated frontend and source-bound profile.

    Raises
    ------
    ImportError
        If the optional frontend package is not installed.
    ValueError
        If profile or toolchain configuration is missing or invalid.
    OSError
        If an explicitly configured profile or toolchain input is unavailable.
    """
    if helper_path is None or build_receipt_path is None:
        raise ValueError("Clang helper and build receipt paths must be configured")
    if compile_commands is None and captured_profiles is None:
        raise ValueError("a compile database or captured profile file is required")
    from codira_clang_frontend import create_frontend_profile

    def configured_path(value: str) -> Path:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else root / candidate).resolve()

    return create_frontend_profile(
        path=path,
        root=root,
        language="cpp",
        compile_commands=(
            configured_path(compile_commands) if compile_commands is not None else None
        ),
        captured_profiles=(
            configured_path(captured_profiles)
            if captured_profiles is not None
            else None
        ),
        helper_path=configured_path(helper_path),
        build_receipt_path=configured_path(build_receipt_path),
    )


def _clang_fallback_fingerprint(
    *,
    path: Path,
    root: Path,
    frontend_options: tuple[str | None, ...],
) -> str:
    """Hash unavailable Clang inputs so profile appearance invalidates reuse.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit whose current bytes are always included.
    root : pathlib.Path
        Repository root used to resolve relative explicit inputs.
    frontend_options : tuple[str or None, ...]
        Explicit profile, helper, receipt, and attempt-root settings.

    Returns
    -------
    str
        Deterministic unavailable-frontend identity without exposing command text.
    """
    captured_profiles, helper_path, build_receipt_path = frontend_options[1:4]
    if (
        captured_profiles is not None
        and helper_path is not None
        and build_receipt_path is not None
    ):
        try:
            from codira_clang_frontend import captured_profile_fingerprint

            def configured_path(value: str) -> Path:
                candidate = Path(value)
                return (
                    candidate if candidate.is_absolute() else root / candidate
                ).resolve()

            return captured_profile_fingerprint(
                configured_path(captured_profiles),
                path,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                helper_path=configured_path(helper_path),
                build_receipt_path=configured_path(build_receipt_path),
            )
        except (ImportError, OSError, ValueError):
            pass
    identities: list[dict[str, str | None]] = []
    for configured in frontend_options:
        if configured is None:
            identities.append({"path": None, "sha256": None})
            continue
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            digest = None
        identities.append({"path": str(candidate.resolve()), "sha256": digest})
    payload = {
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "inputs": identities,
        "package_version": _clang_package_version(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _clang_package_version() -> str | None:
    """Return the installed optional frontend version when available.

    Parameters
    ----------
    None

    Returns
    -------
    str or None
        Installed distribution version, or ``None`` when unavailable.
    """
    try:
        return distribution_version("codira-clang-frontend")
    except ImportError:
        return None


def _clang_source_position(
    point: SourcePoint | None,
    source_path: Path,
    *,
    prefer_expansion: bool = False,
) -> tuple[int, int] | None:
    """Return a verified physical source line and zero-based column.

    Parameters
    ----------
    point : codira_clang_frontend.SourcePoint or None
        Clang spelling/expansion position for a source entity.
    source_path : pathlib.Path
        Translation unit whose physical coordinates are accepted.

    Returns
    -------
    tuple[int, int] or None
        One-based source line and zero-based column only when Clang names the
        exact translation unit.
    """
    if point is None:
        return None
    positions = (
        (point.expansion, point.spelling)
        if prefer_expansion
        else (point.spelling, point.expansion)
    )
    for position in positions:
        if position is None or position.path is None or position.line is None:
            continue
        try:
            matches_source = Path(position.path).resolve() == source_path.resolve()
        except OSError:
            matches_source = False
        if matches_source and position.column is not None:
            return position.line, max(0, position.column - 1)
    return None


def _clang_fallback_result(
    result: AnalysisResult,
    reason: str,
    *,
    language: str,
    frontend_result: FrontendResult | None = None,
) -> AnalysisResult:
    """Mark Tree-sitter fallback when the selected Clang path is incomplete.

    Parameters
    ----------
    result : codira.models.AnalysisResult
        Existing Tree-sitter result to retain as the sole analyzer output.
    reason : str
        Stable frontend fallback reason, without raw command or output text.
    language : str
        Language name used for the fallback grammar identity.
    frontend_result : codira_clang_frontend.FrontendResult or None, optional
        Retained result metadata, including raw attempt paths and digests.

    Returns
    -------
    codira.models.AnalysisResult
        Original artifacts with explicit partial Clang fallback status.
    """
    prior = result.status or AnalysisStatus(
        grammar=f"tree-sitter-{language}",
        target_contract={"language": language},
    )
    return replace(
        result,
        status=replace(
            prior,
            target_contract={
                **prior.target_contract,
                "requested_frontend": "clang",
                "selected_frontend": "tree-sitter",
                "clang_attempt": (
                    _clang_result_evidence(frontend_result)
                    if frontend_result is not None
                    else None
                ),
            },
            diagnostics=(
                *prior.diagnostics,
                AnalysisDiagnostic("clang_frontend_fallback", reason),
            ),
            coverage_state=AnalysisCoverageState.PARTIAL,
        ),
    )


def _clang_result_evidence(result: FrontendResult) -> dict[str, object]:
    """Serialize provenance references for one retained Clang attempt.

    Parameters
    ----------
    result : codira_clang_frontend.FrontendResult
        Frontend response whose outputs remain in its immutable attempt folder.

    Returns
    -------
    dict[str, object]
        Stable status, cache, profile, raw-output, and dependency references.
    """
    return {
        "status": result.status,
        "coverage_state": result.coverage_state,
        "reasons": result.reasons,
        "profile_identity": result.profile_identity,
        "cache_fingerprint": result.cache_fingerprint,
        "compilation_context": _clang_compilation_context_payload(
            result.compilation_context
        ),
        "stdout_path": str(result.stdout_path) if result.stdout_path else None,
        "stdout_sha256": result.stdout_sha256,
        "stderr_path": str(result.stderr_path) if result.stderr_path else None,
        "stderr_sha256": result.stderr_sha256,
        "dependency_closure_sha256": (
            result.dependency_closure.sha256
            if result.dependency_closure is not None
            else None
        ),
    }


def _clang_compilation_context_payload(
    context: CompilationContext | None,
) -> dict[str, str | None] | None:
    """Serialize compiler-derived target and sysroot identity for status.

    Parameters
    ----------
    context : codira_clang_frontend.CompilationContext or None
        Actual target and sysroot emitted by the Clang invocation.

    Returns
    -------
    dict[str, str or None] or None
        Persistable context values, or ``None`` when the helper supplied none.
    """
    if context is None:
        return None
    return {
        "target_triple": context.target_triple,
        "sysroot": context.sysroot,
        "sysroot_path": (
            str(context.sysroot_path) if context.sysroot_path is not None else None
        ),
    }


def _clang_owner_stable_id(
    owner_location: SourcePoint | None,
    owner_name: str,
    owner_kind: str,
    root: Path,
) -> str | None:
    """Derive an external C++ owner identity from its physical declaration.

    Parameters
    ----------
    owner_location : codira_clang_frontend.SourcePoint or None
        Physical location of the owner declaration returned by Clang.
    owner_name : str
        Fully qualified C++ owner name.
    owner_kind : str
        Native owner declaration kind.
    root : pathlib.Path
        Repository root used to reject out-of-repository owner identities.

    Returns
    -------
    str or None
        Same stable identity used when the owning header is indexed, or ``None``
        when the location is unavailable or outside the repository.
    """
    if owner_location is None:
        return None
    for position in (owner_location.spelling, owner_location.expansion):
        if position is None or position.path is None:
            continue
        try:
            owner_path = Path(position.path).resolve()
            relative = owner_path.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if not owner_path.is_file():
            continue
        owner_id = relative.as_posix()
        if owner_kind in {"Record", "CXXRecord"}:
            return _class_stable_id(owner_id, owner_name)
        if owner_kind in {"Namespace", "NamespaceAlias"}:
            return _declaration_stable_id(owner_id, "namespace", owner_name)
        return None
    return None


def _clang_compiler_source_coordinate(
    position: SourcePosition | None, root: Path
) -> CompilerObservedSourceCoordinate | None:
    """Convert one compiler byte coordinate to a contained repository path.

    Parameters
    ----------
    position : codira_clang_frontend.SourcePosition or None
        Compiler-reported coordinate to preserve.
    root : pathlib.Path
        Repository boundary used to make the coordinate portable and safe.

    Returns
    -------
    codira.generated.CompilerObservedSourceCoordinate or None
        Repository-relative compiler coordinate, or ``None`` when it cannot be
        represented without reconstructing a path or byte offset.
    """
    if (
        position is None
        or position.path is None
        or position.offset is None
        or position.offset < 0
    ):
        return None
    try:
        relative_path = Path(position.path).resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return CompilerObservedSourceCoordinate(
        path=relative_path.as_posix(), byte_offset=position.offset
    )


def _clang_macro_invocation_for_callable(
    callable_item: FrontendCallable,
    result: FrontendResult,
    *,
    path: Path,
    root: Path,
    source_bytes: bytes,
    source_sha256: str,
    context_identity: str | None,
) -> (
    tuple[
        CompilerObservedCallableProvenance,
        FrontendPreprocessorEvent,
        int,
        int,
    ]
    | None
):
    """Build compiler-observed provenance for one matched source macro.

    Parameters
    ----------
    callable_item : codira_clang_frontend.FrontendCallable
        Compiler callable with macro spelling and expansion locations.
    result : codira_clang_frontend.FrontendResult
        Profile, helper receipt, and preprocessor observations for the TU.
    path : pathlib.Path
        Translation unit whose source bytes were captured by Clang.
    root : pathlib.Path
        Repository root for safe persisted source coordinates.
    source_bytes : bytes
        Current translation-unit bytes, verified against the captured digest.
    source_sha256 : str
        Source digest from the frontend dependency closure.
    context_identity : str or None
        Exact outer analyzer input identity persisted on the indexed file.

    Returns
    -------
    tuple[CompilerObservedCallableProvenance, FrontendPreprocessorEvent, int, int] or None
        Validated callable evidence, matched invocation event, and its half-open
        byte range; ``None`` means the evidence was incomplete or ambiguous.
    """
    origin = callable_item.provenance
    if origin != "macro_argument" and origin != "macro_replacement":
        return None
    location = callable_item.location
    expansion = location.expansion if location is not None else None
    expansion_coordinate = _clang_compiler_source_coordinate(expansion, root)
    if (
        expansion is None
        or expansion_coordinate is None
        or Path(expansion.path or "").resolve() != path.resolve()
        or not context_identity
        or hashlib.sha256(source_bytes).hexdigest() != source_sha256
    ):
        return None

    matching_events: list[FrontendPreprocessorEvent] = []
    for event in result.preprocessing:
        begin = event.span.begin if event.span is not None else None
        begin_position = (
            begin.expansion or begin.spelling if begin is not None else None
        )
        if (
            event.kind == "macro_expansion"
            and event.name
            and event.invocation
            and begin_position is not None
            and begin_position.path is not None
            and begin_position.offset == expansion.offset
            and Path(begin_position.path).resolve() == path.resolve()
        ):
            matching_events.append(event)
    if len(matching_events) != 1:
        return None
    event = matching_events[0]
    if event.name is None or event.invocation is None:
        return None
    if event.span is None or event.span.begin is None or event.span.end is None:
        return None
    begin_position = event.span.begin.expansion or event.span.begin.spelling
    end_position = event.span.end.expansion or event.span.end.spelling
    if (
        begin_position is None
        or end_position is None
        or begin_position.offset is None
        or end_position.offset is None
        or begin_position.offset < 0
        or end_position.offset < begin_position.offset
        or begin_position.path is None
        or end_position.path is None
        or Path(begin_position.path).resolve() != path.resolve()
        or Path(end_position.path).resolve() != path.resolve()
    ):
        return None
    start = begin_position.offset
    inclusive_end = end_position.offset
    try:
        invocation_bytes = event.invocation.encode("utf-8")
    except UnicodeEncodeError:
        return None
    half_open_end = start + len(invocation_bytes)
    if (
        not invocation_bytes
        or half_open_end - 1 != inclusive_end
        or source_bytes[start:half_open_end] != invocation_bytes
    ):
        return None

    spelling_coordinate = _clang_compiler_source_coordinate(
        location.spelling if location is not None else None, root
    )
    owner_location = (
        _clang_compiler_source_coordinate(
            callable_item.owner_location.expansion
            or callable_item.owner_location.spelling,
            root,
        )
        if callable_item.owner_location is not None
        else None
    )
    event_range = (start, half_open_end)
    invocation = CompilerObservedMacroInvocation(
        name=event.name,
        path=expansion_coordinate.path,
        byte_range=event_range,
        text=event.invocation,
    )
    receipt = {
        "schema": "clang.frontend.callable-observation.v1",
        "context": {
            "profile_identity": result.profile_identity,
            "cache_fingerprint": result.cache_fingerprint,
            "analyzer_context_identity": context_identity,
            "source_sha256": source_sha256,
            "stdout_sha256": result.stdout_sha256,
        },
        "callable": {
            "usr": callable_item.usr,
            "kind": callable_item.kind,
            "name": callable_item.name,
            "qualified_name": callable_item.qualified_name,
            "decl_kind": callable_item.decl_kind,
            "signature": callable_item.signature,
            "function_type": callable_item.function_type,
            "provenance": callable_item.provenance,
            "is_definition": callable_item.is_definition,
            "span": asdict(callable_item.span)
            if callable_item.span is not None
            else None,
            "spelling_location": asdict(spelling_coordinate)
            if spelling_coordinate is not None
            else None,
            "expansion_location": asdict(expansion_coordinate),
            "owner_usr": callable_item.owner_usr,
            "owner_location": asdict(owner_location)
            if owner_location is not None
            else None,
        },
        "macro_expansion": {
            "name": event.name,
            "invocation": event.invocation,
            "byte_range": event_range,
        },
    }
    try:
        receipt_json = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(receipt_json.encode("utf-8")) > 64 * 1024:
            return None
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    return (
        CompilerObservedCallableProvenance(
            origin=origin,
            role="definition" if callable_item.is_definition else "prototype",
            source_sha256=source_sha256,
            context_identity=context_identity,
            spelling_location=spelling_coordinate,
            expansion_location=expansion_coordinate,
            invocation=invocation,
            receipt_namespace="clang.frontend.callable-observation.v1",
            receipt_json=receipt_json,
        ),
        event,
        start,
        half_open_end,
    )


def _clang_captured_source(
    path: Path, result: FrontendResult
) -> tuple[str, bytes] | None:
    """Return translation-unit bytes bound by the frontend dependency closure.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit whose digest is required.
    result : codira_clang_frontend.FrontendResult
        Frontend result carrying hashed dependency inputs.

    Returns
    -------
    tuple[str, bytes] or None
        Captured source digest and matching current bytes.
    """
    closure = result.dependency_closure
    if closure is None:
        return None
    expected = next(
        (
            item.sha256
            for item in closure.files
            if item.path.resolve() == path.resolve()
        ),
        None,
    )
    if expected is None:
        return None
    try:
        source_bytes = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(source_bytes).hexdigest() != expected:
        return None
    return expected, source_bytes


def _analysis_from_clang_result(
    path: Path,
    root: Path,
    result: FrontendResult,
    *,
    context_identity: str | None = None,
) -> AnalysisResult | None:
    """Map supported source-written Clang declarations and calls into C++ DTOs.

    Parameters
    ----------
    path : pathlib.Path
        Original C++ translation unit.
    root : pathlib.Path
        Repository root used for durable analyzer identities.
    result : codira_clang_frontend.FrontendResult
        Complete frontend result with verified source coordinates.
    context_identity : str or None, optional
        Outer C++ analyzer input fingerprint that binds frontend results to the
        complete configuration and dependency context.

    Returns
    -------
    codira.models.AnalysisResult or None
        Clang-backed output, or ``None`` when required ownership, visibility,
        or physical source coordinates cannot be represented faithfully.
    """
    if result.status != "parsed" or result.coverage_state != "complete":
        return None
    owner_id = _symbol_owner_id(path, root)
    module_name = _module_name_for_path(path, root)
    module_stable_id = _module_stable_id(path, root)
    documentation: list[DocumentationArtifact] = []

    def add_documentation(
        stable_id: str,
        owner_kind: str,
        title: str,
        text: str | None,
        location: SourcePoint | None,
        span: SourceSpan | None,
    ) -> None:
        """Attach one Clang comment at its physical spelling location.

        Parameters
        ----------
        stable_id : str
            Identity of the function, declaration, or module owner.
        owner_kind : str
            Canonical kind of the documented owner.
        title : str
            Human-readable owner name.
        text : str or None
            Clang-formatted Doxygen text.
        location : codira_clang_frontend.SourcePoint or None
            Comment start coordinate.
        span : codira_clang_frontend.SourceSpan or None
            Comment source range.

        Returns
        -------
        None
            A documentation artifact is appended when a physical comment path
            and line are available.
        """
        if not text or location is None:
            return
        point = next(
            (
                item
                for item in (location.spelling, location.expansion)
                if item is not None and item.path is not None and item.line is not None
            ),
            None,
        )
        if point is None or point.line is None:
            return
        source_path = Path(point.path or "")
        try:
            source_path = source_path.resolve()
        except OSError:
            return
        end_line = None
        if span is not None and span.end is not None:
            end_point = next(
                (
                    item
                    for item in (span.end.spelling, span.end.expansion)
                    if item is not None
                    and item.path is not None
                    and item.line is not None
                    and Path(item.path).resolve() == source_path
                ),
                None,
            )
            end_line = end_point.line if end_point is not None else None
        documentation.append(
            DocumentationArtifact(
                stable_id=(
                    f"doc:{'module' if owner_kind == 'module' else 'declaration'}:{stable_id}:doxygen"
                ),
                kind="declaration" if owner_kind != "module" else "module",
                source_format="doxygen",
                source_path=source_path,
                lineno=point.line,
                end_lineno=end_line,
                title=title,
                heading_path=(),
                text=text,
                owner_stable_id=stable_id,
                owner_kind=owner_kind,
                attachment_confidence="explicit",
            )
        )

    module_comment = next(
        (
            comment
            for comment in getattr(result, "documentation_comments", ())
            if any(
                line.lstrip().startswith(("\\file", "@file"))
                for line in comment.text.splitlines()
            )
        ),
        None,
    )
    if module_comment is not None:
        add_documentation(
            module_stable_id,
            "module",
            module_name,
            module_comment.text,
            module_comment.location,
            module_comment.span,
        )
    class_declarations = {
        item.qualified_name: item
        for item in result.declarations
        if item.provenance == "source_written"
        and item.kind in {"class", "struct", "union"}
    }
    class_rows: dict[str, ClassArtifact] = {}
    for qualified_name, declaration in class_declarations.items():
        position = _clang_source_position(declaration.location, path)
        if position is None:
            return None
        end_position = _clang_source_position(
            declaration.span.end if declaration.span is not None else None, path
        )
        class_rows[qualified_name] = ClassArtifact(
            name=qualified_name,
            stable_id=_class_stable_id(owner_id, qualified_name),
            lineno=position[0],
            end_lineno=end_position[0] if end_position is not None else None,
            docstring=declaration.documentation,
            has_docstring=int(declaration.documentation is not None),
            methods=(),
        )
        add_documentation(
            _class_stable_id(owner_id, qualified_name),
            "type",
            qualified_name,
            declaration.documentation,
            declaration.documentation_location,
            declaration.documentation_span,
        )
    functions: list[FunctionArtifact] = []
    methods: dict[str, list[FunctionArtifact]] = {name: [] for name in class_rows}
    captured_source = (
        _clang_captured_source(path, result)
        if any(
            item.provenance in {"macro_argument", "macro_replacement"}
            for item in result.callables
        )
        else None
    )
    callable_rows: dict[
        str,
        tuple[
            FrontendCallable,
            CompilerObservedCallableProvenance | None,
            FrontendPreprocessorEvent | None,
        ],
    ] = {}
    omitted_generated_callable = False
    for callable_item in result.callables:
        if callable_item.provenance in {"implicit", "template_instantiation"}:
            continue
        generated_provenance: CompilerObservedCallableProvenance | None = None
        generated_event: FrontendPreprocessorEvent | None = None
        if callable_item.provenance in {"macro_argument", "macro_replacement"}:
            evidence = (
                _clang_macro_invocation_for_callable(
                    callable_item,
                    result,
                    path=path,
                    root=root,
                    source_bytes=captured_source[1],
                    source_sha256=captured_source[0],
                    context_identity=context_identity,
                )
                if captured_source is not None
                else None
            )
            if evidence is None:
                omitted_generated_callable = True
                continue
            generated_provenance, generated_event, _, _ = evidence
        elif callable_item.provenance != "source_written":
            omitted_generated_callable = True
            continue
        identity_key = callable_item.usr or (
            f"{callable_item.qualified_name}:{callable_item.signature}:"
            f"{callable_item.location!r}"
        )
        current = callable_rows.get(identity_key)
        if current is None or callable_item.is_definition:
            callable_rows[identity_key] = (
                callable_item,
                generated_provenance,
                generated_event,
            )
    omitted_generated = (
        any(
            item.provenance in {"macro_argument", "macro_replacement", "unknown"}
            for item in result.declarations
        )
        or omitted_generated_callable
    )
    generated_diagnostics = (
        [
            AnalysisDiagnostic(
                category="clang_generated_provenance",
                message=(
                    "compiler-observed macro callable evidence was ambiguous, "
                    "incomplete, or exceeded the receipt bound"
                ),
            )
        ]
        if omitted_generated_callable
        else []
    )
    for callable_item, generated_provenance, generated_event in callable_rows.values():
        if (
            callable_item.kind
            not in {
                "function",
                "method",
                "constructor",
                "destructor",
                "conversion",
            }
            or callable_item.is_public is None
        ):
            return None
        position = _clang_source_position(
            callable_item.location,
            path,
            prefer_expansion=generated_provenance is not None,
        )
        if position is None:
            return None
        class_name = (
            callable_item.lexical_owner
            if callable_item.kind
            in {"method", "constructor", "destructor", "conversion"}
            else None
        )
        if (
            callable_item.kind
            in {
                "method",
                "constructor",
                "destructor",
                "conversion",
            }
            and class_name is None
        ):
            return None
        class_stable_id = (
            class_rows[class_name].stable_id
            if class_name in class_rows
            else _clang_owner_stable_id(
                callable_item.owner_location, class_name, "CXXRecord", root
            )
            if class_name is not None
            else None
        )
        end_position = (
            _clang_source_position(
                generated_event.span.end
                if generated_event is not None and generated_event.span is not None
                else None,
                path,
                prefer_expansion=True,
            )
            if generated_event is not None
            else _clang_source_position(
                callable_item.span.end if callable_item.span is not None else None,
                path,
            )
        )
        calls: list[CallSite] = []
        for call in callable_item.calls:
            if not call.target:
                return None
            call_position = _clang_source_position(
                call.location,
                path,
                prefer_expansion=call.origin == "macro_replacement",
            )
            if call_position is None:
                return None
            qualified_target = call.qualified_target or call.target
            if call.target_usr is None:
                call_kind = "unresolved"
                base = ""
                target = call.target
            elif "::" in qualified_target:
                base, target = qualified_target.rsplit("::", 1)
                call_kind = "attribute"
            else:
                base, target, call_kind = "", call.target, "name"
            calls.append(
                CallSite(
                    kind=cast("CallKind", call_kind),
                    target=target,
                    base=base,
                    lineno=call_position[0],
                    col_offset=call_position[1],
                    external_target_kind=_cpp_external_target_kind(base, target),
                    external_target_name=qualified_target,
                    target_identity=(
                        SemanticIdentity(
                            namespace="clang.usr.v1", value=call.target_usr
                        )
                        if call.target_usr is not None
                        else None
                    ),
                    resolution_mode="exact",
                    origin=call.origin,
                )
            )
        function = FunctionArtifact(
            name=(
                callable_item.name
                if class_name is not None
                else callable_item.qualified_name or callable_item.name
            ),
            stable_id=_function_stable_id(
                owner_id,
                (
                    callable_item.name
                    if class_name is not None
                    else callable_item.qualified_name or callable_item.name
                ),
                class_name=class_name,
            ),
            lineno=position[0],
            end_lineno=end_position[0] if end_position is not None else None,
            signature=(
                (
                    "explicit "
                    if getattr(
                        getattr(callable_item, "qualifiers", None), "is_explicit", False
                    )
                    else ""
                )
                + (
                    "virtual "
                    if getattr(
                        getattr(callable_item, "qualifiers", None), "is_virtual", False
                    )
                    else ""
                )
                + (
                    "static "
                    if getattr(
                        getattr(callable_item, "qualifiers", None), "is_static", False
                    )
                    else ""
                )
                + callable_item.signature
            ),
            docstring=getattr(callable_item, "documentation", None),
            has_docstring=int(
                getattr(callable_item, "documentation", None) is not None
            ),
            is_method=int(class_name is not None),
            is_public=int(callable_item.is_public),
            parameters=tuple(name for name, _ in callable_item.parameters if name),
            returns_value=int(getattr(callable_item, "returns_value", False)),
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=tuple(sorted(calls, key=lambda item: (item.lineno, item.col_offset))),
            callable_refs=(),
            owner_name=class_name,
            owner_stable_id=class_stable_id,
            semantic_identity=(
                SemanticIdentity(namespace="clang.usr.v1", value=callable_item.usr)
                if callable_item.is_definition and callable_item.usr is not None
                else None
            ),
            generated=generated_provenance,
        )
        if class_name is None or class_name not in class_rows:
            functions.append(function)
        else:
            methods[class_name].append(function)
    classes = tuple(
        replace(
            class_rows[name],
            methods=_disambiguate_callable_stable_ids(
                tuple(
                    sorted(
                        methods[name],
                        key=lambda item: (item.lineno, item.name, item.signature),
                    )
                )
            ),
        )
        for name in sorted(class_rows, key=lambda key: (class_rows[key].lineno, key))
    )
    for function in (
        *functions,
        *(method for class_artifact in classes for method in class_artifact.methods),
    ):
        matched_callable = next(
            (
                item
                for item, _, _ in callable_rows.values()
                if (
                    item.usr is not None
                    and function.semantic_identity is not None
                    and item.usr == function.semantic_identity.value
                )
                or (
                    item.name == function.name
                    and (
                        item_position := _clang_source_position(
                            item.location,
                            path,
                            prefer_expansion=item.provenance
                            in {"macro_argument", "macro_replacement"},
                        )
                    )
                    is not None
                    and item_position[0] == function.lineno
                )
            ),
            None,
        )
        if matched_callable is not None:
            add_documentation(
                function.stable_id,
                "function",
                function.name,
                getattr(matched_callable, "documentation", None),
                getattr(matched_callable, "documentation_location", None),
                getattr(matched_callable, "documentation_span", None),
            )
    declaration_kinds = {
        "constant",
        "enum",
        "macro",
        "namespace",
        "type_alias",
        "typedef",
        "variable",
    }
    enum_members: dict[str, list[EnumMemberArtifact]] = {}
    enum_names = {
        item.usr: item.qualified_name or item.name
        for item in result.declarations
        if getattr(item, "usr", None) is not None and item.kind == "enum"
    }
    for member in result.declarations:
        if (
            member.kind != "constant"
            or member.owner_usr not in enum_names
            or member.enum_ordinal is None
        ):
            continue
        enum_name = enum_names[cast("str", member.owner_usr)]
        enum_stable_id = _declaration_stable_id(owner_id, "enum", enum_name)
        member_stable_id = _enum_member_stable_id(
            owner_id, enum_name, member.enum_ordinal
        )
        position = _clang_source_position(member.location, path)
        if position is None:
            return None
        enum_members.setdefault(cast("str", member.owner_usr), []).append(
            EnumMemberArtifact(
                stable_id=member_stable_id,
                parent_stable_id=enum_stable_id,
                ordinal=member.enum_ordinal,
                name=member.name,
                signature=member.source_text or member.type_text or member.name,
                lineno=position[0],
            )
        )
        add_documentation(
            member_stable_id,
            "enum_member",
            member.name,
            member.documentation,
            member.documentation_location,
            member.documentation_span,
        )
    declarations: list[DeclarationArtifact] = []
    for declaration in result.declarations:
        if declaration.provenance != "source_written":
            continue
        if declaration.kind in {"class", "struct", "union"}:
            continue
        if declaration.kind not in declaration_kinds:
            continue
        if declaration.kind == "constant" and declaration.owner_usr in enum_names:
            continue
        if declaration.kind in {"variable", "constant"} and not (
            declaration.is_file_scope
            or declaration.owner_kind in {"CXXRecord", "Record"}
            or declaration.owner_kind in {"Namespace", "NamespaceAlias"}
        ):
            continue
        position = _clang_source_position(declaration.location, path)
        if position is None:
            return None
        qualified_name = declaration.qualified_name or declaration.name
        signature = (
            declaration.signature
            or (declaration.source_text if declaration.kind != "namespace" else None)
            or declaration.type_text
            or declaration.name
        )
        owner_stable_id = None
        owner_name = getattr(declaration, "owner_name", None)
        owner_location = getattr(declaration, "owner_location", None)
        if owner_name is not None and owner_location is not None:
            owner_stable_id = _clang_owner_stable_id(
                owner_location,
                owner_name,
                getattr(declaration, "owner_kind", "") or "",
                root,
            )
        enum_members_for_declaration = (
            tuple(
                sorted(
                    enum_members.get(declaration.usr or "", ()),
                    key=lambda item: item.ordinal,
                )
            )
            if declaration.kind == "enum"
            else ()
        )
        stable_id = _declaration_stable_id(
            owner_id,
            cast("DeclarationKind", declaration.kind),
            qualified_name,
        )
        declarations.append(
            DeclarationArtifact(
                name=qualified_name,
                stable_id=stable_id,
                kind=cast("DeclarationKind", declaration.kind),
                lineno=position[0],
                signature=signature,
                docstring=getattr(declaration, "documentation", None),
                enum_members=enum_members_for_declaration,
                type_text=declaration.type_text,
                owner_name=getattr(declaration, "owner_name", None),
                owner_stable_id=owner_stable_id,
                access=getattr(declaration, "access", None),
            )
        )
        add_documentation(
            stable_id,
            "variable" if declaration.kind == "variable" else declaration.kind,
            qualified_name,
            getattr(declaration, "documentation", None),
            getattr(declaration, "documentation_location", None),
            getattr(declaration, "documentation_span", None),
        )
    macro_declarations: list[DeclarationArtifact] = []
    for event in getattr(result, "preprocessing", ()):
        if event.kind != "macro_definition" or not event.name:
            continue
        macro_position = _clang_source_position(event.location, path)
        if macro_position is None:
            continue
        macro_signature = event.source_text or " ".join(
            ("#define", event.name, *event.parameters, *event.replacement)
        )
        stable_id = _declaration_stable_id(owner_id, "macro", event.name)
        macro_declarations.append(
            DeclarationArtifact(
                name=event.name,
                stable_id=stable_id,
                kind="macro",
                lineno=macro_position[0],
                signature=macro_signature,
            )
        )
    declarations.extend(macro_declarations)
    imports = tuple(
        ImportArtifact(
            name=item.spelled_path,
            alias=None,
            lineno=position[0],
            kind="include_system" if item.angled else "include_local",
        )
        for item in getattr(result, "includes", ())
        if (position := _clang_source_position(item.location, path)) is not None
    )
    status_diagnostics = tuple(
        AnalysisDiagnostic(
            category="clang_diagnostic",
            message=diagnostic.message,
            line=diagnostic.location.line if diagnostic.location else None,
            column=(diagnostic.location.column - 1)
            if diagnostic.location and diagnostic.location.column is not None
            else None,
        )
        for diagnostic in result.diagnostics
    ) + tuple(generated_diagnostics)
    omitted_categories: list[str] = []
    if omitted_generated:
        omitted_categories.append("generated_declaration")
    if any(
        function.is_method and function.owner_stable_id is None
        for function in (
            *functions,
            *(method for cls in classes for method in cls.methods),
        )
    ):
        omitted_categories.append("method_owner_identity")
    coverage_state = (
        AnalysisCoverageState.PARTIAL
        if omitted_categories
        else AnalysisCoverageState.COMPLETE
    )
    toolchain = result.toolchain_identity
    dependency_closure = result.dependency_closure
    return AnalysisResult(
        source_path=path,
        module=ModuleArtifact(
            name=module_name,
            stable_id=module_stable_id,
            docstring=module_comment.text if module_comment is not None else None,
            has_docstring=int(module_comment is not None),
        ),
        classes=classes,
        functions=_disambiguate_callable_stable_ids(
            tuple(
                sorted(
                    functions, key=lambda item: (item.lineno, item.name, item.signature)
                )
            )
        ),
        declarations=tuple(
            sorted(declarations, key=lambda item: (item.lineno, item.name, item.kind))
        ),
        imports=imports,
        documentation=tuple(
            sorted(documentation, key=lambda item: (item.lineno, item.stable_id))
        ),
        index_symbols=True,
        status=AnalysisStatus(
            grammar="clang-cpp-frontend",
            target_contract={
                "language": "cpp",
                "frontend": "clang",
                "profile_identity": result.profile_identity,
                "cache_fingerprint": result.cache_fingerprint,
                "compilation_context": _clang_compilation_context_payload(
                    result.compilation_context
                ),
                "attempt_evidence": _clang_result_evidence(result),
                "toolchain_identity": (
                    {
                        "compiler_path": str(toolchain.compiler_path),
                        "compiler_sha256": toolchain.compiler_sha256,
                        "compiler_version": toolchain.compiler_version,
                        "resource_dir": str(toolchain.resource_dir),
                        "resource_probe_sha256": toolchain.resource_probe_sha256,
                        "helper_path": str(toolchain.helper_path),
                        "helper_sha256": toolchain.helper_sha256,
                        "build_receipt_sha256": toolchain.build_receipt_sha256,
                        "package_version": toolchain.package_version,
                        "runtime_shared_library_identity": toolchain.runtime_shared_library_identity,
                    }
                    if toolchain is not None
                    else None
                ),
                "dependency_closure": (
                    {
                        "status": dependency_closure.status,
                        "sha256": dependency_closure.sha256,
                        "file_count": len(dependency_closure.files),
                    }
                    if dependency_closure is not None
                    else None
                ),
            },
            diagnostics=status_diagnostics,
            reliable_categories=(
                "module",
                "class",
                "function",
                "declaration",
                "import",
                "documentation",
            ),
            omitted_categories=tuple(omitted_categories),
            coverage_state=coverage_state,
        ),
    )


_TYPE_LIKE_NAMES = {
    "auto",
    "bool",
    "char",
    "char16_t",
    "char32_t",
    "double",
    "float",
    "int",
    "long",
    "short",
    "size_t",
    "signed",
    "std",
    "uint8_t",
    "uint16_t",
    "uint32_t",
    "uint64_t",
    "int8_t",
    "int16_t",
    "int32_t",
    "int64_t",
    "unsigned",
    "void",
    "wchar_t",
}


@dataclass(frozen=True)
class _PendingFunction:
    """Hold a callable candidate awaiting ownership and redeclaration merging.

    Parameters
    ----------
    artifact : codira.models.FunctionArtifact
        Original-source callable artifacts.
    class_name : str | None
        Known class-like owner, if any.
    is_definition : bool
        Whether the candidate has a body or an explicit default/delete definition.
    binding_key : tuple[str, ...]
        Source-syntax parameter types and cv/ref/constraint qualifiers. Parameter
        names and default values do not distinguish redeclarations. Conditional
        branch identity keeps alternative source definitions separate.

    Returns
    -------
    None
        Initializes an immutable candidate.
    """

    artifact: FunctionArtifact
    class_name: str | None
    is_definition: bool
    binding_key: tuple[str, ...]


@dataclass
class _ClassBuilder:
    """Accumulate one logical record with coherent primary-source metadata.

    Parameters
    ----------
    qualified_name, stable_id : str
        Logical name and source-offset-independent identity.
    lineno : int
        Starting line of the represented definition, declaration or owner.
    end_lineno : int or None
        Matching ending line, absent for synthesized method owners.
    docstring : str or None
        Attached documentation when available.
    has_docstring : int
        Whether documentation is present.
    has_definition : bool, optional
        Whether the represented source range belongs to a complete record.
    methods_by_key : dict, optional
        Source methods grouped by semantic identity and declarator binding.

    Returns
    -------
    None
        Creates a mutable accumulator before immutable artifact finalization.
    """

    qualified_name: str
    stable_id: str
    lineno: int
    end_lineno: int | None
    docstring: str | None
    has_docstring: int
    has_definition: bool = False
    methods_by_key: dict[tuple[str, tuple[str, ...]], _PendingFunction] = field(
        default_factory=dict
    )

    def absorb_metadata(
        self,
        *,
        lineno: int,
        end_lineno: int | None,
        docstring: str | None,
        is_definition: bool = False,
    ) -> None:
        """
        Select coherent metadata from definitions, declarations or owners.

        Parameters
        ----------
        lineno : int
            Candidate starting line for the class artifact.
        end_lineno : int | None
            Candidate ending line for the class artifact.
        docstring : str | None
            Candidate class docstring from an attached comment.
        is_definition : bool, optional
            Whether the candidate range contains a complete record body.

        Returns
        -------
        None
            Definitions take precedence over forward declarations and synthesized
            owners. Equal source roles retain the earliest complete range.
        """
        candidate_role = (is_definition, end_lineno is not None)
        current_role = (self.has_definition, self.end_lineno is not None)
        if candidate_role > current_role or (
            candidate_role == current_role and lineno < self.lineno
        ):
            self.lineno = lineno
            self.end_lineno = end_lineno
            self.has_definition = is_definition
            if docstring is not None:
                self.docstring = docstring
                self.has_docstring = 1
        if self.docstring is None and docstring is not None:
            self.docstring = docstring
            self.has_docstring = 1

    def record_method(self, pending: _PendingFunction) -> None:
        """
        Record one method candidate for the class.

        Parameters
        ----------
        pending : _PendingFunction
            Method candidate to store.

        Returns
        -------
        None
            The method map is updated in place.
        """
        key = (pending.artifact.stable_id, pending.binding_key)
        current = self.methods_by_key.get(key)
        if current is None or _prefer_pending_function(current, pending) is pending:
            self.methods_by_key[key] = pending

    def build(self) -> ClassArtifact:
        """
        Finalize the immutable class artifact.

        Parameters
        ----------
        None

        Returns
        -------
        codira.models.ClassArtifact
            Class artifact with deterministically ordered methods.
        """
        methods = tuple(
            pending.artifact
            for pending in sorted(
                self.methods_by_key.values(),
                key=lambda item: (
                    item.artifact.lineno,
                    item.artifact.name,
                    item.artifact.signature,
                ),
            )
        )
        methods = _disambiguate_callable_stable_ids(methods)
        return ClassArtifact(
            name=self.qualified_name,
            stable_id=self.stable_id,
            lineno=self.lineno,
            end_lineno=self.end_lineno,
            docstring=self.docstring,
            has_docstring=self.has_docstring,
            methods=methods,
        )


def _named_descendants(node: Node) -> list[Node]:
    """
    Collect named descendants of one syntax node in source order.

    Parameters
    ----------
    node : tree_sitter.Node
        Parent syntax node.

    Returns
    -------
    list[tree_sitter.Node]
        Named descendant nodes in deterministic source order.
    """
    descendants: list[Node] = []
    stack: list[Node] = [*node.named_children]
    stack.reverse()
    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(reversed(current.named_children))
    return descendants


def _template_inner_node(node: Node) -> Node | None:
    """
    Return the wrapped declaration inside one template declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        `template_declaration` node.

    Returns
    -------
    tree_sitter.Node | None
        Wrapped declaration node when present.
    """
    children: list[Node] = [*node.named_children]
    for child in reversed(children):
        if child.type != "template_parameter_list":
            return child
    return None


def _namespace_parts(node: Node, source: bytes) -> tuple[str, ...]:
    """
    Resolve the namespace path declared by one namespace-definition node.

    Parameters
    ----------
    node : tree_sitter.Node
        `namespace_definition` node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, ...]
        Namespace path components in declaration order. An unnamed namespace
        uses an explicit component to avoid collisions with its enclosing scope.
    """
    for child in node.named_children:
        if child.type in {"namespace_identifier", "nested_namespace_specifier"}:
            return _split_qualified_name(
                child.syntax_text.decode("utf-8", errors="replace")
                if isinstance(child, _ProjectedNode)
                else _node_text(child, source)
            )
    return ("(anonymous namespace)",)


def _find_parameter_list(node: Node | None) -> Node | None:
    """
    Find the parameter-list node nested inside one declarator tree.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Declarator subtree that may own a function declarator.

    Returns
    -------
    tree_sitter.Node | None
        Nested `parameter_list` node when present.
    """
    if node is None:
        return None
    if node.type == "parameter_list":
        return node

    parameter_list = node.child_by_field_name("parameters")
    if parameter_list is not None:
        return parameter_list

    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        nested = _find_parameter_list(declarator)
        if nested is not None:
            return nested

    for child in node.named_children:
        nested = _find_parameter_list(child)
        if nested is not None:
            return nested
    return None


def _function_macro_wrapper_name(node: Node, source: bytes) -> str | None:
    """
    Resolve a function name wrapped by a macro-style declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator that may wrap the real name in a macro call.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Wrapped function name when the declarator matches the macro pattern.
    """
    nested = node.child_by_field_name("declarator")
    if nested is None or nested.type != "function_declarator":
        return None

    parameter_list = nested.child_by_field_name("parameters")
    if parameter_list is None or len(parameter_list.named_children) != 1:
        return None

    parameter = parameter_list.named_children[0]
    if parameter.type != "parameter_declaration":
        return None
    if parameter.child_by_field_name("declarator") is not None:
        return None

    for named_child in parameter.named_children:
        if named_child.type in {
            "identifier",
            "type_identifier",
            "field_identifier",
            "namespace_identifier",
        }:
            return _node_text(named_child, source)
    return None


def _looks_like_annotation_macro_name(name: str) -> bool:
    """
    Decide whether one declarator token looks like an annotation macro.

    Parameters
    ----------
    name : str
        Candidate declarator token.

    Returns
    -------
    bool
        ``True`` when the token is all-uppercase or underscore-style text.
    """
    has_alpha = any(char.isalpha() for char in name)
    if not has_alpha:
        return False
    return all(not char.isalpha() or char.isupper() for char in name)


def _looks_like_macro_or_type_name(name: str) -> bool:
    """
    Decide whether one declarator token looks like a macro or type name.

    Parameters
    ----------
    name : str
        Candidate declarator token.

    Returns
    -------
    bool
        ``True`` when the token is unlikely to be the real callable name.
    """
    if name in _TYPE_LIKE_NAMES or name.endswith("_t"):
        return True
    return _looks_like_annotation_macro_name(name)


def _error_identifier_name(node: Node, source: bytes) -> str | None:
    """
    Extract one identifier-like token from an `ERROR` child when present.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may include a parse-error placeholder.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Recovered identifier text when the `ERROR` child looks usable.
    """
    for named_child in node.named_children:
        if named_child.type != "ERROR":
            continue
        text = _node_text(named_child, source).strip()
        if not text:
            continue
        if "(" in text or ")" in text or "[" in text or "]" in text:
            continue
        if not (text[0].isalpha() or text[0] in {"_", "~"}):
            continue
        if any(not (char.isalnum() or char in {"_", ":", "~"}) for char in text):
            continue
        return text
    return None


def _annotated_function_call_name(node: Node, source: bytes) -> str | None:
    """
    Resolve a callable name from a macro-annotated call-like declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator whose real callable name may appear in a nested
        call expression.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Callable identifier text when the annotation pattern is present.
    """
    for named_child in reversed([*node.named_children]):
        if named_child.type != "call_expression":
            continue
        arguments = named_child.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            continue
        function_node = named_child.child_by_field_name("function")
        if function_node is None:
            continue
        name = _unwrap_declarator_name(function_node, source)
        if name is not None:
            return name
    return None


def _function_declarator_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the callable identifier owned by one function declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator that may include annotations or parse errors.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Callable identifier text when resolvable.
    """
    direct_declarator = node.child_by_field_name("declarator")
    if direct_declarator is not None and direct_declarator.type in {
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
    }:
        direct_name = _canonical_node_text(direct_declarator, source)
        error_name = _error_identifier_name(node, source)
        if error_name is not None and _looks_like_macro_or_type_name(direct_name):
            return error_name
        return direct_name

    macro_wrapped_name = _function_macro_wrapper_name(node, source)
    if macro_wrapped_name is not None:
        return macro_wrapped_name

    if direct_declarator is None or direct_declarator.type != "identifier":
        return None
    if not _looks_like_annotation_macro_name(_node_text(direct_declarator, source)):
        return None
    return _annotated_function_call_name(node, source)


def _unwrap_declarator_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the identifier owned by one declarator node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may nest pointers, references, or arrays.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Identifier text when resolvable.
    """
    if node.type == "function_declarator":
        function_name = _function_declarator_name(node, source)
        if function_name is not None:
            return function_name

    if node.type in {
        "identifier",
        "field_identifier",
        "type_identifier",
        "namespace_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
    }:
        return _canonical_node_text(node, source)

    child = node.child_by_field_name("declarator")
    if child is not None:
        return _unwrap_declarator_name(child, source)

    for named_child in node.named_children:
        name = _unwrap_declarator_name(named_child, source)
        if name is not None:
            return name
    return None


def _extract_parameter_names(
    parameter_list: Node | None,
    source: bytes,
) -> tuple[str, ...]:
    """
    Extract deterministic parameter names from one parameter list.

    Parameters
    ----------
    parameter_list : tree_sitter.Node | None
        Parameter list node from a function declarator.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, ...]
        Parameter names in declaration order.
    """
    if parameter_list is None:
        return ()

    parameters: list[str] = []
    for child in parameter_list.named_children:
        if child.type not in {
            "parameter_declaration",
            "optional_parameter_declaration",
            "variadic_parameter_declaration",
        }:
            continue
        declarator = child.child_by_field_name("declarator")
        if declarator is None:
            continue
        name = _parameter_name_node(declarator)
        if name is not None:
            parameters.append(_node_text(name, source))
    return tuple(parameters)


def _parameter_name_node(declarator: Node) -> Node | None:
    """Follow the declarator chain to an explicitly named parameter.

    Parameters
    ----------
    declarator : tree_sitter.Node
        Parameter declarator, possibly a pointer, array or callback signature.

    Returns
    -------
    tree_sitter.Node | None
        Declared parameter identifier, excluding type and nested parameter names.
    """
    current: Node | None = declarator
    while current is not None:
        if current.type in {"identifier", "field_identifier"}:
            return current
        nested = current.child_by_field_name("declarator")
        if nested is None and current.type in {
            "parenthesized_declarator",
            "reference_declarator",
            "variadic_declarator",
        }:
            nested = next(
                (
                    child
                    for child in current.named_children
                    if child.type.endswith("_declarator")
                    or child.type in {"identifier", "field_identifier"}
                ),
                None,
            )
        current = nested
    return None


def _callable_binding_key(declarator: Node, source: bytes) -> tuple[str, ...]:
    """Distinguish written overload types while merging named redeclarations.

    Parameters
    ----------
    declarator : tree_sitter.Node
        Function declarator selected by declared-name binding.
    source : bytes
        Original source used to retain explicit annotation/type spelling.

    Returns
    -------
    tuple[str, ...]
        Parameter, cv/ref/constraint and lexical conditional-branch syntax. This
        does not resolve type aliases or compiler-dependent type equivalence.
    """
    parameters = declarator.child_by_field_name("parameters")
    if parameters is None:
        return ()
    types: list[str] = []
    for parameter in parameters.named_children:
        if parameter.type == "comment":
            continue
        excluded: set[tuple[int, int]] = set()
        pending = [parameter]
        while pending:
            child = pending.pop()
            if child.type == "parameter_list":
                written = [
                    item for item in child.named_children if item.type != "comment"
                ]
                if (
                    len(written) == 1
                    and written[0].type == "parameter_declaration"
                    and _canonical_node_text(written[0], source) == "void"
                ):
                    excluded.add((written[0].start_byte, written[0].end_byte))
            if child.type in {
                "parameter_declaration",
                "optional_parameter_declaration",
                "variadic_parameter_declaration",
            }:
                named = child.child_by_field_name("declarator")
                name = _parameter_name_node(named) if named is not None else None
                if name is not None:
                    excluded.add((name.start_byte, name.end_byte))
                default = child.child_by_field_name("default_value")
                if default is not None:
                    excluded.add((default.start_byte, default.end_byte))
                    excluded.update(
                        (item.start_byte, item.end_byte)
                        for item in child.children
                        if item.type == "="
                    )
            pending.extend(child.named_children)
        types.append(
            _canonical_node_text(parameter, source, excluded=frozenset(excluded))
        )
    if types == ["void"]:
        types.clear()
    if any(child.type == "..." for child in parameters.children):
        types.append("...")
    qualifiers = " ".join(
        _canonical_node_text(child, source)
        for child in declarator.named_children
        if child.type in {"type_qualifier", "ref_qualifier", "requires_clause"}
    )
    conditions: list[str] = []
    parent = declarator.parent
    while parent is not None:
        if parent.type in {
            "preproc_if",
            "preproc_ifdef",
            "preproc_else",
            "preproc_elif",
        }:
            conditions.append(f"{parent.type}:{parent.start_byte}")
        parent = parent.parent
    return (*types, qualifiers, "/".join(conditions))


def _qualified_call_parts(node: Node, source: bytes) -> tuple[str, ...]:
    """Read qualified call components without splitting template arguments.

    Parameters
    ----------
    node : tree_sitter.Node
        Qualified function expression, including nested scope components.
    source : bytes
        Original source buffer used for target and template argument spelling.

    Returns
    -------
    tuple[str, ...]
        Ordered scope components and final target, preserving argument text.
    """
    parts: list[str] = []
    current = node
    while current.type == "qualified_identifier":
        scope = current.child_by_field_name("scope")
        if scope is not None:
            parts.append(_node_text(scope, source).strip())
        name = current.child_by_field_name("name")
        if name is None:
            return ()
        current = name
    parts.append(_node_text(current, source).strip())
    return tuple(part for part in parts if part)


def _call_site_from_expression(node: Node, source: bytes) -> CallSite | None:
    """
    Convert one tree-sitter call expression into a normalized call record.

    Parameters
    ----------
    node : tree_sitter.Node
        Call-expression node.
    source : bytes
        Full source buffer.

    Returns
    -------
    codira.models.CallSite | None
        Normalized call record, excluding primitive conversions, named casts,
        noexcept expressions and unsupported operators.
        Calls inside their operands are collected separately by body traversal.
    """
    if _is_complex_operator_call(node, source):
        return None
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return None
    function_text = (
        _decode_source_text(function_node.syntax_text)
        if isinstance(function_node, _ProjectedNode)
        else _node_text(function_node, source)
    )
    if function_node.type == "identifier" and function_text == "noexcept":
        return None
    type_operator_text = (
        _node_text(function_node, source).encode()
        if isinstance(function_node, _ProjectedNode)
        else function_text.encode()
    )
    if _may_be_type_operator_expression(type_operator_text) and (
        _is_type_operator_expression(type_operator_text)
    ):
        return None
    if function_node.type == "primitive_type" or (
        function_node.type == "identifier"
        and function_text in {"short", "long", "signed", "unsigned", "wchar_t"}
    ):
        return None

    if function_node.type == "template_function":
        name = function_node.child_by_field_name("name")
        name_text = (
            _decode_source_text(name.syntax_text)
            if isinstance(name, _ProjectedNode)
            else _node_text(name, source)
            if name is not None
            else ""
        )
        if name is not None and name_text in {
            "static_cast",
            "reinterpret_cast",
            "const_cast",
            "dynamic_cast",
        }:
            return None

    if function_node.type in {"identifier", "template_function"}:
        target = _node_text(function_node, source)
        return CallSite(
            kind="name",
            target=target,
            lineno=function_node.start_point.row + 1,
            col_offset=function_node.start_point.column,
            external_target_kind=_cpp_external_target_kind("", target),
            external_target_name=target,
        )

    if function_node.type == "qualified_identifier":
        target_parts = _qualified_call_parts(function_node, source)
        if not target_parts:
            return None
        base = "::".join(target_parts[:-1])
        return CallSite(
            kind="name",
            target=target_parts[-1],
            lineno=function_node.start_point.row + 1,
            col_offset=function_node.start_point.column,
            base=base,
            external_target_kind=_cpp_external_target_kind(base, target_parts[-1]),
            external_target_name="::".join(target_parts),
        )

    if function_node.type == "field_expression":
        receiver = function_node.child_by_field_name("argument")
        field = function_node.child_by_field_name("field")
        if receiver is None or field is None:
            return None
        target = _node_text(field, source)
        base = _node_text(receiver, source)
        return CallSite(
            kind="attribute",
            target=target,
            lineno=field.start_point.row + 1,
            col_offset=field.start_point.column,
            base=base,
            external_target_kind=_cpp_external_target_kind(base, target),
            external_target_name=f"{base}.{target}",
        )

    return CallSite(
        kind="unresolved",
        target="",
        lineno=function_node.start_point.row + 1,
        col_offset=function_node.start_point.column,
    )


def _initializer_argument_calls(
    body: Node,
    source: bytes,
    parameter_names: tuple[str, ...],
    initializer_value_bindings: Mapping[str, tuple[int, ...]],
) -> tuple[CallSite, ...]:
    """Recover nested expression calls after a visible value binding proves initialization.

    Parameters
    ----------
    body : Node
        Function compound statement whose nested lexical scopes are inspected.
    source : bytes
        Coordinate-aligned original source.
    parameter_names : tuple[str, ...]
        Explicit value parameters belonging to this function.
    initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]]
        Captured source/header value names and the offsets at which they are available.

    Returns
    -------
    tuple[CallSite, ...]
        Nested argument calls at original byte positions. Unknown or shadowed
        first arguments remain conservative; declared variables and synthetic
        expression wrappers never acquire call records.
    """
    recovered: list[CallSite] = []
    original_lines: list[int] | None = None
    prefix = b"void __codira_probe() { __codira_probe"
    for declaration in _initializer_candidate_declarations(body):
        declarator = declaration.child_by_field_name("declarator")
        if declarator is None or declarator.type != "function_declarator":
            continue
        parameters = declarator.child_by_field_name("parameters")
        if parameters is None:
            continue
        arguments = [n for n in parameters.named_children if n.type != "comment"]
        if len(arguments) < 2 or arguments[0].type != "parameter_declaration":
            continue
        first = arguments[0]
        written = [n for n in first.named_children if n.type != "comment"]
        value = first.child_by_field_name("type")
        if value is None:
            continue
        first_name = _node_text(value, source).strip()
        values, types = _initializer_visible_bindings(
            body, declaration, source, parameter_names
        )
        if value.type not in {"type_identifier", "qualified_identifier"}:
            continue
        qualified_value = (
            value.type == "qualified_identifier"
            and declaration.start_byte in initializer_value_bindings.get(first_name, ())
        )
        if len(written) != 1 and not (
            qualified_value
            and _initializer_parenthesized_call_shape(first, value, source)
        ):
            continue
        if (first_name not in values or first_name in types) and not (qualified_value):
            continue
        # Reparse only the proven initializer arguments, excluding its variable.
        fragment = prefix + source[parameters.start_byte : parameters.end_byte]
        fragment += b"; }"
        root = _new_parser().parse(fragment).root_node
        if root.has_error:
            continue
        fragment_lines = [0, *(i + 1 for i, byte in enumerate(fragment) if byte == 10)]
        for node in _named_descendants(root):
            if node.type != "call_expression" or node.start_byte < len(prefix):
                continue
            call = _call_site_from_expression(node, fragment)
            if call is None:
                continue
            offset = (
                parameters.start_byte
                + fragment_lines[call.lineno - 1]
                + call.col_offset
                - len(prefix)
            )
            if not parameters.start_byte <= offset < parameters.end_byte:
                continue
            if original_lines is None:
                original_lines = [
                    0,
                    *(i + 1 for i, byte in enumerate(source) if byte == 10),
                ]
            line = bisect_right(original_lines, offset)
            recovered.append(
                replace(call, lineno=line, col_offset=offset - original_lines[line - 1])
            )
    return tuple(recovered)


def _initializer_parenthesized_call_shape(
    declaration: Node,
    value: Node,
    source: bytes,
) -> bool:
    """Recognize a qualified call-shaped node misparsed as a declarator.

    Parameters
    ----------
    declaration : tree_sitter.Node
        First parameter-like node inside a declaration-shaped initializer.
    value : tree_sitter.Node
        Qualified function name parsed as the parameter type.
    source : bytes
        Coordinate-aligned original source.

    Returns
    -------
    bool
        Whether the qualified name has the specific abstract-function shape
        produced by a call expression; a separately captured declaration proof
        is still required before this shape can license call extraction.
    """
    if value.type != "qualified_identifier":
        return False
    declarator = declaration.child_by_field_name("declarator")
    if declarator is None or declarator.type != "abstract_function_declarator":
        return False
    parameters = declarator.child_by_field_name("parameters")
    if parameters is None:
        return False
    arguments = [node for node in parameters.named_children if node.type != "comment"]
    if len(arguments) != 1 or arguments[0].type != "parameter_declaration":
        return False
    argument_type = arguments[0].child_by_field_name("type")
    argument_declarator = arguments[0].child_by_field_name("declarator")
    if (
        argument_type is None
        or argument_type.type != "type_identifier"
        or argument_declarator is not None
    ):
        return False
    return bool(_node_text(argument_type, source).strip())


def _initializer_candidate_declarations(body: Node) -> tuple[Node, ...]:
    """Find declaration-shaped candidates in executable lexical blocks.

    Parameters
    ----------
    body : tree_sitter.Node
        Function body to inspect without entering nested lambdas or functions.

    Returns
    -------
    tuple[tree_sitter.Node, ...]
        Source-ordered declaration nodes that may represent direct initialization.
    """
    candidates: list[Node] = []

    def visit(node: Node, *, root: bool = False) -> None:
        """Walk statement containers while preserving nested callable boundaries.

        Parameters
        ----------
        node : tree_sitter.Node
            Current statement or compound scope.
        root : bool, optional
            Whether this is the body whose parameter bindings are supplied.

        Returns
        -------
        None
            Candidate declarations are appended in source order.
        """
        if not root and node.type in {"lambda_expression", "function_definition"}:
            return
        if node.type == "declaration":
            if any(
                child.type == "function_declarator" for child in node.named_children
            ):
                candidates.append(node)
            return
        for child in node.named_children:
            visit(child)

    visit(body, root=True)
    return tuple(candidates)


def _initializer_visible_bindings(
    body: Node,
    candidate: Node,
    source: bytes,
    parameter_names: tuple[str, ...],
) -> tuple[set[str], set[str]]:
    """Resolve simple value and type names visible before one candidate.

    Parameters
    ----------
    body : tree_sitter.Node
        Owning function compound statement.
    candidate : tree_sitter.Node
        Declaration whose first parameter-like argument is being checked.
    source : bytes
        Original coordinate-aligned translation unit.
    parameter_names : tuple[str, ...]
        Value parameters belonging to the owning function.

    Returns
    -------
    tuple[set[str], set[str]]
        Visible value and type names after lexical shadowing.

    Notes
    -----
    Only declarations in the candidate's enclosing compound scopes and before
    the candidate are considered. Preprocessor branches and nested lambdas are
    not used as binding evidence.
    """
    values = set(parameter_names)
    types: set[str] = set()
    scopes: list[Node] = []
    current: Node | None = candidate.parent
    while current is not None:
        if current.type == "compound_statement":
            scopes.append(current)
        if current == body:
            break
        current = current.parent
    if not scopes or scopes[-1] != body:
        return values, types

    for scope in reversed(scopes):
        direct_child: Node = candidate
        while direct_child.parent is not None and direct_child.parent != scope:
            direct_child = direct_child.parent
        for sibling in scope.named_children:
            if sibling.start_byte >= direct_child.start_byte:
                break
            if sibling.type == "preproc_if":
                continue
            _update_initializer_bindings(sibling, source, values, types)
    return values, types


def _update_initializer_bindings(
    node: Node,
    source: bytes,
    values: set[str],
    types: set[str],
) -> None:
    """Apply one preceding declaration to the visible local name sets.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration or type declaration in the current lexical scope.
    source : bytes
        Original translation-unit bytes.
    values : set[str]
        Mutable visible value names.
    types : set[str]
        Mutable visible type names.

    Returns
    -------
    None
        The visible bindings are updated in place.
    """
    if node.type == "alias_declaration":
        name = node.child_by_field_name("name")
        if name is not None:
            identifier = _node_text(name, source).strip()
            values.discard(identifier)
            types.add(identifier)
        return
    if node.type == "type_definition":
        for name in _typedef_name_nodes(node):
            identifier = _node_text(name, source).strip()
            values.discard(identifier)
            types.add(identifier)
        return
    if node.type in {
        "class_specifier",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
    }:
        name = node.child_by_field_name("name")
        if name is not None:
            identifier = _node_text(name, source).strip()
            values.discard(identifier)
            types.add(identifier)
        return
    if node.type != "declaration":
        return
    declarator = node.child_by_field_name("declarator")
    if declarator is None or _find_function_declarator(node) is not None:
        return
    names = _initializer_declarator_names(declarator, source)
    for identifier in names:
        types.discard(identifier)
        values.add(identifier)


def _initializer_declarator_names(node: Node, source: bytes) -> tuple[str, ...]:
    """Collect written variable names from declarator structure only.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator or initialized declarator node.
    source : bytes
        Original source bytes.

    Returns
    -------
    tuple[str, ...]
        Written identifier names, excluding names nested in types or expressions.
    """
    if node.type in {"identifier", "field_identifier"}:
        return (_node_text(node, source).strip(),)
    child = node.child_by_field_name("declarator")
    if child is not None:
        return _initializer_declarator_names(child, source)
    for child in node.named_children:
        if child.type.endswith("_declarator") or child.type in {
            "identifier",
            "field_identifier",
        }:
            names = _initializer_declarator_names(child, source)
            if names:
                return names
    return ()


@dataclass(frozen=True)
class _InitializerHeaderValuePlan:
    """Bounded syntax queries needed for qualified initializer value proof."""

    root_offsets: tuple[int, ...]
    root_spans: Mapping[int, int]
    header_query_offsets: Mapping[str, tuple[int, ...]]
    requested_by_leaf: Mapping[bytes, frozenset[str]]
    declarations_by_header: Mapping[str, tuple[tuple[Node, str, bytes, bool], ...]]
    macro_offsets_by_header: Mapping[str, tuple[int, ...]]


def _initializer_header_value_query_plan(
    analyzer: CppAnalyzer,
    source_root: Node,
    source: bytes,
    context: IncludeContext,
    root: Path,
) -> _InitializerHeaderValuePlan:
    """Collect bounded declaration and wrapper queries for one captured TU.

    Parameters
    ----------
    source_root : tree_sitter.Node
        Parsed translation unit used to discover qualified first arguments.
    source : bytes
        Original translation-unit bytes.
    context : IncludeContext
        Immutable source and contained header snapshots with resolution identity.
    root : pathlib.Path
        Repository boundary for relative paths in the include identity.
    analyzer : CppAnalyzer
        Profile owner whose configured macro and pure-query state drives the
        same captured primary translation-unit traversal.

    Returns
    -------
    _InitializerHeaderValuePlan
        Original-source candidate offsets and captured header queries.
    """
    requested: set[str] = set()
    root_queries: set[int] = set()
    root_spans: dict[int, int] = {}
    for node in _named_descendants(source_root):
        if node.type != "function_definition":
            continue
        body = node.child_by_field_name("body")
        if body is None:
            continue
        for declaration in _initializer_candidate_declarations(body):
            declarator = declaration.child_by_field_name("declarator")
            parameters = (
                declarator.child_by_field_name("parameters")
                if declarator is not None
                else None
            )
            arguments = (
                [item for item in parameters.named_children if item.type != "comment"]
                if parameters is not None
                else []
            )
            first = arguments[0] if arguments else None
            value = first.child_by_field_name("type") if first is not None else None
            if value is not None and value.type == "qualified_identifier":
                requested.add(_node_text(value, source).strip())
                root_queries.add(declaration.start_byte)
                root_spans[declaration.start_byte] = declaration.end_byte
    requested_by_leaf: dict[bytes, set[str]] = {}
    for name in requested:
        requested_by_leaf.setdefault(name.split("::")[-1].encode(), set()).add(name)

    declarations_by_header: dict[str, tuple[tuple[Node, str, bytes, bool], ...]] = {}
    header_queries: dict[str, set[int]] = {}
    macro_offsets_by_header: dict[str, tuple[int, ...]] = {}
    for header in context.headers:
        raw = header.source
        leaves = [
            leaf for leaf in requested_by_leaf if re.search(rb"\b" + leaf + rb"\b", raw)
        ]
        if not leaves:
            continue
        relative = header.path.resolve().relative_to(root.resolve()).as_posix()
        header_root = _parse_with_namespace_bindings(
            raw, bindings=analyzer._namespace_macro_definitions
        )
        declarations: list[tuple[Node, str, bool]] = []
        for node in _named_descendants(header_root):
            if (
                node.type != "declaration"
                or not _initializer_namespace_visible_declaration(node)
            ):
                continue
            function_declaration = _find_function_declarator(node) is not None
            if not function_declaration and any(
                child.type == "storage_class_specifier"
                and _node_text(child, raw).strip() == "typedef"
                for child in node.named_children
            ):
                continue
            declarator = node.child_by_field_name("declarator")
            if declarator is None:
                continue
            for name in _initializer_declarator_names(declarator, raw):
                encoded = name.encode()
                if encoded in requested_by_leaf:
                    declarations.append((node, name, function_declaration))
        if not declarations:
            continue
        declarations_by_header[relative] = tuple(
            (node, leaf_name, raw, function_declaration)
            for node, leaf_name, function_declaration in declarations
        )
        macros = _initializer_macro_line_offsets(header_root, raw)
        macro_offsets_by_header[relative] = macros
        header_queries[relative] = {
            *(node.start_byte for node, _leaf_name, _is_function in declarations),
            *macros,
        }
    return _InitializerHeaderValuePlan(
        root_offsets=tuple(sorted(root_queries)),
        root_spans=root_spans,
        header_query_offsets={
            owner: tuple(sorted(offsets)) for owner, offsets in header_queries.items()
        },
        requested_by_leaf={
            leaf: frozenset(values) for leaf, values in requested_by_leaf.items()
        },
        declarations_by_header=declarations_by_header,
        macro_offsets_by_header=macro_offsets_by_header,
    )


def _initializer_namespace_visible_declaration(node: Node) -> bool:
    """Require a declaration to occur at namespace or translation-unit scope.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration candidate from a captured header.

    Returns
    -------
    bool
        Whether only namespace-level wrappers enclose the declaration.
    """
    parent = node.parent
    while parent is not None:
        if parent.type == "translation_unit":
            return True
        if parent.type not in {
            "declaration_list",
            "namespace_definition",
            "linkage_specification",
            "template_declaration",
            "export_declaration",
            "preproc_if",
            "preproc_ifdef",
            "preproc_ifndef",
            "preproc_elif",
            "preproc_elifdef",
            "preproc_elifndef",
            "preproc_else",
        }:
            return False
        parent = parent.parent
    return False


def _initializer_header_value_bindings_from_walk(
    analyzer: CppAnalyzer,
    source_root: Node,
    source: bytes,
    context: IncludeContext,
    root: Path,
    captures: Mapping[str, bytes],
    walk: object,
    plan: _InitializerHeaderValuePlan,
) -> dict[str, tuple[int, ...]]:
    """Prove qualified values from per-visit state in the primary TU walk.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Configured profile owner.
    source_root : tree_sitter.Node
        Parsed primary translation unit.
    source : bytes
        Original primary translation-unit bytes.
    context : IncludeContext
        Immutable source and contained header snapshots.
    root : pathlib.Path
        Trusted repository boundary.
    captures : collections.abc.Mapping[str, bytes]
        Exact captured bytes supplied to the primary include walk.
    walk : object
        The one primary translation-unit ``_ContextWalk``.
    plan : _InitializerHeaderValuePlan
        Declaration offsets requested from that walk.

    Returns
    -------
    dict[str, tuple[int, ...]]
        Qualified values mapped to exact root declaration offsets proven by an
        active prior header visit. Conflicting and unknown visits are omitted.
    """
    from .cpp_macro_context import _ContextWalk

    if not isinstance(walk, _ContextWalk) or not plan.root_offsets:
        return {}
    identity = json.loads(context.identity)
    root_key = identity["source_path"]
    available: dict[str, set[int]] = {}

    for relative, declarations in plan.declarations_by_header.items():
        macro_offsets = set(plan.macro_offsets_by_header[relative])
        for declaration, leaf_name, raw, _function_declaration in declarations:
            selections = walk.file_results.get((relative, declaration.start_byte), ())
            events = walk.query_events.get((relative, declaration.start_byte), ())
            if len(selections) != 1 or len(selections) != len(events):
                continue
            if any(selection.active is None for selection in selections):
                continue
            for selected, event in zip(selections, events, strict=True):
                if selected.active is not True:
                    continue
                scopes = _initializer_namespace_scopes(declaration, raw)
                macro_namespaces = _initializer_header_macro_namespaces_for_event(
                    declaration.start_byte,
                    raw,
                    macro_offsets,
                    event,
                    walk,
                    relative,
                )
                if macro_namespaces is None:
                    continue
                for qualified in plan.requested_by_leaf[leaf_name.encode()]:
                    requested_scope = tuple(qualified.split("::")[:-1])
                    if not _initializer_namespace_matches(
                        (*macro_namespaces, *scopes), requested_scope
                    ):
                        continue
                    for root_offset in plan.root_offsets:
                        if not _initializer_namespace_aliases_allow(
                            source_root,
                            source,
                            root_offset,
                            requested_scope,
                        ):
                            continue
                        root_events = walk.query_events.get((root_key, root_offset), ())
                        if not root_events or event >= root_events[0]:
                            continue
                        available.setdefault(qualified, set()).add(root_offset)
    return {
        name: tuple(sorted(offsets)) for name, offsets in available.items() if offsets
    }


def _initializer_header_macro_namespaces_for_event(
    declaration_offset: int,
    source: bytes,
    macro_offsets: set[int],
    declaration_event: int,
    walk: object,
    path: str,
) -> tuple[tuple[str, bool], ...] | None:
    """Resolve namespace wrapper macros from the same header visit as a declaration.

    Parameters
    ----------
    declaration_offset : int
        Original byte offset of the declaration query.
    source : bytes
        Exact captured header bytes.
    macro_offsets : set[int]
        Standalone namespace-wrapper macro offsets in the header.
    declaration_event : int
        Primary-walk query sequence number for this declaration visit.
    walk : object
        The primary translation-unit ``_ContextWalk`` retaining query events.
    path : str
        Captured repository-relative header key.

    Returns
    -------
    tuple[tuple[str, bool], ...] | None
        Namespace wrappers proven at this visit, or ``None`` when a required
        query is absent or uncertain.
    """
    from .cpp_macro_context import _ContextWalk

    if not isinstance(walk, _ContextWalk):
        return None
    selections: dict[int, MacroSelection] = {}
    for offset in macro_offsets:
        if offset >= declaration_offset:
            continue
        events = walk.query_events.get((path, offset), ())
        visits = walk.file_results.get((path, offset), ())
        preceding = [
            (event, selection)
            for event, selection in zip(events, visits, strict=True)
            if event < declaration_event
        ]
        if not preceding:
            continue
        event, selection = max(preceding, key=lambda item: item[0])
        del event
        selections[offset] = selection
    return _initializer_header_macro_namespaces(
        declaration_offset, source, macro_offsets, selections
    )


def _initializer_namespace_aliases_allow(
    root: Node, source: bytes, declaration_offset: int, requested_scope: tuple[str, ...]
) -> bool:
    """Reject qualified header proofs shadowed by a visible namespace alias.

    Parameters
    ----------
    root : tree_sitter.Node
        Primary translation-unit syntax tree.
    source : bytes
        Original primary translation-unit bytes.
    declaration_offset : int
        Original byte offset of the candidate call declaration.
    requested_scope : tuple[str, ...]
        Namespace components written before the qualified value leaf.

    Returns
    -------
    bool
        Whether no visible namespace alias rebinds the qualified root names.
    """
    ancestors: set[tuple[str, int, int]] = set()
    node: Node | _ProjectedNode | None = max(
        (
            candidate
            for candidate in _named_descendants(root)
            if candidate.start_byte <= declaration_offset < candidate.end_byte
        ),
        key=lambda candidate: (candidate.start_byte, -candidate.end_byte),
        default=root,
    )
    while node is not None:
        ancestors.add((node.type, node.start_byte, node.end_byte))
        node = node.parent
    for candidate in _named_descendants(root):
        if candidate.type != "namespace_alias_definition":
            continue
        name = candidate.child_by_field_name("name")
        if name is None or _node_text(name, source).strip() not in requested_scope:
            continue
        if candidate.start_byte >= declaration_offset:
            continue
        parent = candidate.parent
        if (
            parent is not None
            and (
                parent.type,
                parent.start_byte,
                parent.end_byte,
            )
            in ancestors
        ):
            return False
    return True


def _select_initializer_macro_environments(
    path: str,
    offsets: tuple[int, ...],
    captures: Mapping[str, bytes],
    resolutions: Mapping[tuple[str, str, bool], str | None],
    initial: Mapping[bytes, _MacroDefinition | None],
) -> Mapping[int, MacroSelection]:
    """Use the shared source macro walker for captured declaration locations.

    Parameters
    ----------
    path : str
        Repository-relative captured header path.
    offsets : tuple[int, ...]
        Declaration and macro invocation offsets to resolve.
    captures : collections.abc.Mapping[str, bytes]
        Exact source/header snapshots from the include context.
    resolutions : collections.abc.Mapping[tuple[str, str, bool | None], str | None]
        Captured include resolution outcomes.
    initial : collections.abc.Mapping[bytes, _MacroDefinition | None]
        Explicit initial macro environment.

    Returns
    -------
    collections.abc.Mapping[int, MacroSelection]
        Macro selections at the requested original offsets.
    """
    from .cpp_macro_context import select_macro_environments

    return select_macro_environments(path, offsets, captures, resolutions, initial)


def _initializer_macro_line_offsets(root: Node, source: bytes) -> tuple[int, ...]:
    """Find standalone macro invocation lines before declaration parsing.

    Parameters
    ----------
    root : tree_sitter.Node
        Parsed captured header.
    source : bytes
        Exact captured header bytes.

    Returns
    -------
    tuple[int, ...]
        Source offsets of standalone identifier invocations outside comments.
    """
    from bisect import bisect_right

    comments = sorted(
        (node.start_byte, node.end_byte)
        for node in _named_descendants(root)
        if node.type == "comment"
    )
    comment_starts = [start for start, _end in comments]
    offsets: set[int] = set()
    for match in re.finditer(rb"(?m)^[ \t]*([A-Za-z_][A-Za-z_0-9]*)[ \t]*\r?$", source):
        start = match.start(1)
        comment_index = bisect_right(comment_starts, start) - 1
        in_comment = comment_index >= 0 and start < comments[comment_index][1]
        if not in_comment:
            offsets.add(start)
    return tuple(sorted(offsets))


def _initializer_namespace_scopes(
    node: Node, source: bytes
) -> tuple[tuple[str, bool], ...]:
    """Return explicit namespace ancestors for a captured declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration whose qualified owner is needed.
    source : bytes
        Captured source bytes.

    Returns
    -------
    tuple[tuple[str, bool], ...]
        Namespace names and whether each is inline, ordered outermost first.
    """
    scopes: list[tuple[str, bool]] = []
    parent = node.parent
    while parent is not None:
        if parent.type == "namespace_definition":
            name = parent.child_by_field_name("name")
            if name is not None:
                prefix = source[parent.start_byte : name.start_byte]
                scopes.append((_node_text(name, source).strip(), b"inline" in prefix))
        parent = parent.parent
    scopes.reverse()
    return tuple(scopes)


def _initializer_header_macro_namespaces(
    declaration_offset: int,
    source: bytes,
    macro_offsets: set[int],
    selections: Mapping[int, MacroSelection],
) -> tuple[tuple[str, bool], ...] | None:
    """Expand active namespace wrapper macros before one captured declaration.

    Parameters
    ----------
    declaration_offset : int
        Original byte offset of the declaration.
    source : bytes
        Captured header bytes.
    macro_offsets : set[int]
        Candidate standalone macro invocation locations.
    selections : collections.abc.Mapping[int, object]
        Source-based activity and macro selections at those locations.

    Returns
    -------
    tuple[tuple[str, bool], ...] | None
        Proven macro namespace stack, or ``None`` when expansion is uncertain.
    """
    from .cpp_macro_expansion import _MacroExpander, _macro_tokens

    scopes: list[tuple[str, bool]] = []
    for offset in sorted(item for item in macro_offsets if item < declaration_offset):
        selected = selections.get(offset)
        if selected is None or selected.active is None:
            return None
        if selected.active is False:
            continue
        line_end = source.find(b"\n", offset)
        if line_end < 0:
            line_end = len(source)
        macro = source[offset:line_end].strip()
        bindings = dict(selected.bindings)
        binding = bindings.get(macro)
        if binding is None or binding.definition is None:
            continue
        definitions = {
            name: item.definition
            for name, item in selected.bindings
            if item.definition is not None
        }
        try:
            tokens = _MacroExpander(definitions).expand(
                _macro_tokens(macro, offset=offset)
            )
        except ValueError:
            return None
        spellings = tuple(token.spelling for token in tokens)
        if b"namespace" in spellings:
            position = 0
            while position < len(spellings):
                if spellings[position] != b"namespace":
                    position += 1
                    continue
                cursor = position + 1
                while cursor < len(spellings) and spellings[cursor] in {
                    b"__attribute__",
                    b"__declspec",
                }:
                    cursor += 1
                    if cursor >= len(spellings) or spellings[cursor] != b"(":
                        return None
                    depth = 0
                    while cursor < len(spellings):
                        if spellings[cursor] == b"(":
                            depth += 1
                        elif spellings[cursor] == b")":
                            depth -= 1
                            if depth == 0:
                                cursor += 1
                                break
                        cursor += 1
                    else:
                        return None
                names: list[bytes] = []
                if cursor >= len(spellings) or not re.fullmatch(
                    rb"[A-Za-z_][A-Za-z_0-9]*", spellings[cursor]
                ):
                    return None
                is_inline = position > 0 and spellings[position - 1] == b"inline"
                names.append(spellings[cursor])
                cursor += 1
                while cursor < len(spellings) and spellings[cursor] == b"::":
                    cursor += 1
                    if cursor >= len(spellings) or not re.fullmatch(
                        rb"[A-Za-z_][A-Za-z_0-9]*", spellings[cursor]
                    ):
                        return None
                    names.append(spellings[cursor])
                    cursor += 1
                if cursor >= len(spellings) or spellings[cursor] != b"{":
                    return None
                if is_inline and len(names) != 1:
                    return None
                scopes.extend(
                    (name.decode(), is_inline and index == len(names) - 1)
                    for index, name in enumerate(names)
                )
                position = cursor + 1
        elif b"}" in spellings and not any(token not in {b"}"} for token in spellings):
            for _ in spellings:
                if not scopes:
                    return None
                scopes.pop()
    return tuple(scopes)


def _initializer_namespace_matches(
    scopes: tuple[tuple[str, bool], ...], requested: tuple[str, ...]
) -> bool:
    """Check a qualified name against explicit and inline namespace scopes.

    Parameters
    ----------
    scopes : tuple[tuple[str, bool], ...]
        Namespace path, with inline namespace flags.
    requested : tuple[str, ...]
        Qualified namespace prefix written at the call site.

    Returns
    -------
    bool
        Whether inline namespace elision yields the requested exact prefix.
    """
    paths: set[tuple[str, ...]] = {()}
    for name, is_inline in scopes:
        paths = {(*path, name) for path in paths}
        if is_inline:
            paths.update(path[:-1] for path in tuple(paths) if path[-1] == name)
    return requested in paths


def _extract_calls(
    body: Node | None,
    source: bytes,
    *,
    parameter_names: tuple[str, ...] = (),
    initializer_value_bindings: Mapping[str, tuple[int, ...]] | None = None,
) -> tuple[CallSite, ...]:
    """
    Extract normalized calls from one function body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Compound-statement node owning the function body.
    source : bytes
        Full source buffer.
    parameter_names : tuple[str, ...], optional
        Explicit value parameters licensing direct initializer disambiguation.
    initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]] | None, optional
        Qualified source/header values proven for original declaration offsets.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Call records in deterministic source order, including written operands
        erased by a source-selected statement macro.
    """
    if body is None:
        return ()
    value_bindings = (
        {} if initializer_value_bindings is None else initializer_value_bindings
    )

    calls: list[CallSite] = []
    statement_hints = False
    for node in _named_descendants(body):
        if isinstance(node, _ProjectedNode) and node.macro_hint is not None:
            statement_hints = True
            calls.append(
                CallSite(
                    kind="name",
                    target=node.macro_hint,
                    lineno=node.start_point.row + 1,
                    col_offset=node.start_point.column,
                    external_target_kind="C++:<macro>",
                    external_target_name=node.macro_hint,
                )
            )
            if node.macro_arguments is not None:
                calls.extend(
                    _extract_calls(
                        node.macro_arguments,
                        source,
                        parameter_names=parameter_names,
                        initializer_value_bindings=value_bindings,
                    )
                )
        if node.type != "call_expression":
            continue
        call = _call_site_from_expression(node, source)
        if call is not None:
            calls.append(call)
    if statement_hints:
        calls = list(dict.fromkeys(calls))
    seen = set(calls)
    recovered: list[CallSite] = []
    for call in _initializer_argument_calls(
        body, source, parameter_names, value_bindings
    ):
        if call not in seen:
            seen.add(call)
            recovered.append(call)
    if not recovered:
        return tuple(calls)
    recovered.sort(key=lambda call: (call.lineno, call.col_offset))
    merged: list[CallSite] = []
    pending = iter(recovered)
    next_call = next(pending, None)
    for call in calls:
        while next_call is not None and (next_call.lineno, next_call.col_offset) < (
            call.lineno,
            call.col_offset,
        ):
            merged.append(next_call)
            next_call = next(pending, None)
        merged.append(call)
    if next_call is not None:
        merged.append(next_call)
    merged.extend(pending)
    return tuple(merged)


def _returns_value(body: Node | None) -> int:
    """
    Detect whether one function body contains a value-returning statement.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Compound-statement node owning the function body.

    Returns
    -------
    int
        ``1`` when the body contains `return <expr>;`, else ``0``.
    """
    if body is None:
        return 0
    for node in _named_descendants(body):
        if node.type == "return_statement" and len(node.named_children) > 0:
            return 1
    return 0


def _find_function_declarator(node: Node) -> Node | None:
    """
    Follow the declared name's binding to distinguish functions from pointers.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration-like node to inspect.

    Returns
    -------
    tree_sitter.Node | None
        Callable declarator when the name binds as a function. Function-pointer
        variables and parameter or initializer subtrees are not callable owners.
    """
    current = (
        node
        if node.type == "function_declarator"
        else node.child_by_field_name("declarator")
    )
    function: Node | None = None
    binds_as_function = False
    while current is not None:
        if current.type == "function_declarator":
            if function is None:
                function = current
            binds_as_function = True
        elif current.type in {
            "pointer_declarator",
            "reference_declarator",
            "array_declarator",
        }:
            function = None
            binds_as_function = False
        nested = current.child_by_field_name("declarator")
        if nested is None and current.type in {
            "parenthesized_declarator",
            "reference_declarator",
        }:
            nested = next(
                (
                    child
                    for child in current.named_children
                    if child.type.endswith("_declarator")
                    or child.type
                    in {"identifier", "field_identifier", "qualified_identifier"}
                ),
                None,
            )
        current = nested
    return function if binds_as_function else None


def _declared_type_specifier(node: Node) -> Node | None:
    """Find an explicitly declared record or enum without entering nested scopes.

    Parameters
    ----------
    node : tree_sitter.Node
        Type specifier or declaration that may also declare a variable.

    Returns
    -------
    tree_sitter.Node | None
        Direct record/enum specifier, excluding types hidden in initializers.
    """
    types = {"class_specifier", "struct_specifier", "union_specifier", "enum_specifier"}
    if node.type in types:
        return node
    if node.type in {"declaration", "field_declaration", "type_definition"}:
        declared_type = node.child_by_field_name("type")
        if declared_type is not None and declared_type.type in types:
            return declared_type
    return None


def _may_be_type_operator_expression(source: bytes) -> bool:
    """Gate syntax parsing to expressions beginning with the decltype keyword.

    Parameters
    ----------
    source : bytes
        Candidate function spelling from physical or projected syntax.

    Returns
    -------
    bool
        Whether the spelling begins with the exact language-operator token.
    """
    return re.match(rb"\s*decltype\b\s*\(", source) is not None


def _is_type_operator_expression(source: bytes) -> bool:
    """Check whether source spelling is exactly one C++ decltype operand.

    Parameters
    ----------
    source : bytes
        Function-node spelling to classify from syntax rather than its name.

    Returns
    -------
    bool
        Whether the complete spelling parses as a decltype language construct.
    """
    prefix = b"void codira_type_operator_probe() { "
    tree = _new_parser().parse(prefix + source + b"; }").root_node
    return any(
        node.type == "decltype"
        and node.start_byte == len(prefix)
        and node.end_byte == len(prefix) + len(source)
        for node in _named_descendants(tree)
    )


def _extract_enum_members(
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    enum_name: str,
    parent_stable_id: str,
) -> tuple[EnumMemberArtifact, ...]:
    """
    Extract deterministic enum members from one named enum declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        Enum-specifier node that owns the enumerator list.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    enum_name : str
        Owning enum declaration name.
    parent_stable_id : str
        Stable identity of the owning enum declaration artifact.

    Returns
    -------
    tuple[codira.models.EnumMemberArtifact, ...]
        Ordered enum-member artifacts attached to the enum declaration.
    """
    enumerator_list = next(
        (child for child in node.named_children if child.type == "enumerator_list"),
        None,
    )
    if enumerator_list is None:
        return ()

    members: list[EnumMemberArtifact] = []
    for ordinal, enumerator in enumerate(
        (
            child
            for child in enumerator_list.named_children
            if child.type == "enumerator"
        ),
        start=1,
    ):
        name = next(
            (
                _node_text(child, source)
                for child in enumerator.named_children
                if child.type in {"identifier", "field_identifier"}
            ),
            None,
        )
        if name is None:
            continue
        members.append(
            EnumMemberArtifact(
                stable_id=_enum_member_stable_id(owner_id, enum_name, ordinal),
                parent_stable_id=parent_stable_id,
                ordinal=ordinal,
                name=name,
                signature=_normalize_signature(_node_text(enumerator, source)),
                lineno=enumerator.start_point.row + 1,
            )
        )
    return tuple(members)


def _prefer_pending_function(
    current: _PendingFunction,
    candidate: _PendingFunction,
) -> _PendingFunction:
    """
    Choose the richer callable candidate for one logical signature slot.

    Parameters
    ----------
    current : _PendingFunction
        Previously recorded callable candidate.
    candidate : _PendingFunction
        New callable candidate competing for the same slot.

    Returns
    -------
    _PendingFunction
        Preferred callable candidate.
    """
    if current.is_definition != candidate.is_definition:
        preferred = candidate if candidate.is_definition else current
        alternate = current if candidate.is_definition else candidate
    elif (
        current.artifact.docstring is None and candidate.artifact.docstring is not None
    ):
        preferred = candidate
        alternate = current
    elif (
        current.artifact.end_lineno is None
        and candidate.artifact.end_lineno is not None
    ):
        preferred = candidate
        alternate = current
    elif len(current.artifact.calls) < len(candidate.artifact.calls):
        preferred = candidate
        alternate = current
    else:
        preferred = current
        alternate = candidate

    if (
        preferred.artifact.docstring is None
        and alternate.artifact.docstring is not None
    ):
        preferred = replace(
            preferred,
            artifact=replace(
                preferred.artifact,
                docstring=alternate.artifact.docstring,
                has_docstring=alternate.artifact.has_docstring,
            ),
        )
    return preferred


def _disambiguate_callable_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Disambiguate duplicate callable stable IDs within one file analysis.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Extracted callable artifacts in deterministic order.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Callable artifacts with duplicate stable IDs rewritten deterministically.
    """
    counts: dict[str, int] = {}
    for function in functions:
        counts[function.stable_id] = counts.get(function.stable_id, 0) + 1

    if all(count == 1 for count in counts.values()):
        return functions

    used_ids: set[str] = set()
    disambiguated: list[FunctionArtifact] = []
    for function in functions:
        stable_id = function.stable_id
        if counts[stable_id] > 1:
            digest = hashlib.sha256(function.signature.encode("utf-8")).hexdigest()[:12]
            stable_id = f"{stable_id}:{digest}"
            if stable_id in used_ids:
                stable_id = f"{stable_id}:{function.lineno}"
            function = replace(function, stable_id=stable_id)
        used_ids.add(stable_id)
        disambiguated.append(function)
    return tuple(disambiguated)


def _is_likely_public_definition(node: Node, source: bytes) -> int:
    """
    Infer whether one free function definition should be treated as public.

    Parameters
    ----------
    node : tree_sitter.Node
        Function-definition node.
    source : bytes
        Full source buffer.

    Returns
    -------
    int
        ``1`` when the definition does not carry `static`, else ``0``.
    """
    return int(
        not any(
            child.type == "storage_class_specifier"
            and _node_text(child, source) == "static"
            for child in node.children
        )
    )


def _build_namespace_declaration(
    namespace_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one namespace declaration artifact.

    Parameters
    ----------
    namespace_name : str
        Qualified namespace name.
    node : tree_sitter.Node
        Namespace-definition node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the namespace declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized namespace declaration artifact.
    """
    return DeclarationArtifact(
        name=namespace_name,
        stable_id=_declaration_stable_id(owner_id, "namespace", namespace_name),
        kind="namespace",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _build_alias_declaration(
    alias_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one alias-declaration artifact.

    Parameters
    ----------
    alias_name : str
        Qualified alias name.
    node : tree_sitter.Node
        Alias-declaration node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the alias declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized alias declaration artifact.
    """
    return DeclarationArtifact(
        name=alias_name,
        stable_id=_declaration_stable_id(owner_id, "type_alias", alias_name),
        kind="type_alias",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _macro_name(node: Node, source: bytes) -> str | None:
    """
    Extract the declared macro name from one preprocessor definition.

    Parameters
    ----------
    node : tree_sitter.Node
        Preprocessor definition node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Macro identifier when present.
    """
    identifier = next(
        (child for child in node.named_children if child.type == "identifier"),
        None,
    )
    if identifier is None:
        return None
    return _node_text(identifier, source)


def _build_macro_declaration(
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact | None:
    """
    Build one preprocessor macro declaration artifact when named.

    Parameters
    ----------
    node : tree_sitter.Node
        Preprocessor definition node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the macro declaration.

    Returns
    -------
    codira.models.DeclarationArtifact | None
        Normalized macro declaration artifact, or ``None`` when no macro name is
        present.
    """
    name = _macro_name(node, source)
    if name is None:
        return None
    return DeclarationArtifact(
        name=name,
        stable_id=_declaration_stable_id(owner_id, "macro", name),
        kind="macro",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _build_type_declaration(
    kind: DeclarationKind,
    qualified_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one enum, struct, or union declaration artifact.

    Parameters
    ----------
    kind : codira.models.DeclarationKind
        Stable declaration classifier.
    qualified_name : str
        Qualified declaration name.
    node : tree_sitter.Node
        Type-specifier node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized declaration artifact.
    """
    stable_id = _declaration_stable_id(owner_id, kind, qualified_name)
    return DeclarationArtifact(
        name=qualified_name,
        stable_id=stable_id,
        kind=kind,
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
        enum_members=(
            _extract_enum_members(
                node,
                source,
                owner_id=owner_id,
                enum_name=qualified_name,
                parent_stable_id=stable_id,
            )
            if kind == "enum"
            else ()
        ),
    )


def _class_name_from_specifier(node: Node, source: bytes) -> str | None:
    """
    Extract the declared class name from one class specifier.

    Parameters
    ----------
    node : tree_sitter.Node
        Class-specifier node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Declared class name, including explicit template specialization arguments.
    """
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _canonical_node_text(name_node, source)


def _type_specifier_name(node: Node, source: bytes) -> str | None:
    """
    Extract the declared enum, struct, or union name from one specifier.

    Parameters
    ----------
    node : tree_sitter.Node
        Type-specifier node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Declared type name, including explicit template specialization arguments.
    """
    name = node.child_by_field_name("name")
    if name is None:
        return None
    return _canonical_node_text(name, source)


def _is_function_definition(node: Node) -> bool:
    """
    Decide whether one parsed node is a usable function definition.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate node.

    Returns
    -------
    bool
        ``True`` when the node exposes a callable declarator with parameters.
    """
    if node.type != "function_definition":
        return False
    declarator = node.child_by_field_name("declarator")
    return _find_parameter_list(declarator) is not None


def _resolve_callable_identity(
    raw_name: str,
    *,
    namespace: Sequence[str],
    known_class_names: set[str],
) -> tuple[str, str | None]:
    """
    Resolve the qualified callable name and optional owning class.

    Parameters
    ----------
    raw_name : str
        Declarator-owned callable text.
    namespace : collections.abc.Sequence[str]
        Active namespace context.
    known_class_names : set[str]
        Qualified class names collected from the file.

    Returns
    -------
    tuple[str, str | None]
        Resolved callable name plus owning class when identified.
    """
    parts = _split_qualified_name(raw_name)
    if not parts:
        return raw_name, None
    if len(parts) == 1:
        if namespace:
            return _qualified_name((*namespace, parts[0])), None
        return parts[0], None

    relative_owner = _qualified_name((*namespace, *parts[:-1]))
    if relative_owner in known_class_names:
        return parts[-1], relative_owner
    if any(relative_owner.startswith(name + "<") for name in known_class_names):
        return parts[-1], relative_owner

    qualified_name = _qualified_name((*namespace, *parts))
    return qualified_name, None


def _build_function_artifact(
    node: Node,
    source: bytes,
    *,
    namespace: Sequence[str],
    known_class_names: set[str],
    owner_id: str,
    docstring: str | None,
    is_public: int,
    signature_node: Node,
    initializer_value_bindings: Mapping[str, tuple[int, ...]],
) -> _PendingFunction | None:
    """
    Build one function or method artifact from a definition or declaration node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration-like node that owns the callable.
    source : bytes
        Full source buffer.
    namespace : collections.abc.Sequence[str]
        Active namespace context.
    known_class_names : set[str]
        Qualified class names collected from the file.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Attached comment summary when present.
    is_public : int
        Public-visibility flag for the callable.
    signature_node : tree_sitter.Node
        Node whose source span should be used for signature extraction.
    initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]]
        Qualified source/header values proven at original declaration offsets.

    Returns
    -------
    _PendingFunction | None
        Callable candidate when the node exposes a supported declarator.
    """
    declarator = _find_function_declarator(node)
    if declarator is None:
        return None

    raw_name = _unwrap_declarator_name(declarator, source)
    if raw_name is None:
        return None

    resolved_name, class_name = _resolve_callable_identity(
        raw_name,
        namespace=namespace,
        known_class_names=known_class_names,
    )
    method_name = resolved_name.split("::")[-1]
    parameter_list = _find_parameter_list(declarator)
    parameters = _extract_parameter_names(parameter_list, source)
    body = node.child_by_field_name("body")
    children: Sequence[Node] = node.named_children
    bodyless_definition = node.type == "function_definition" and any(
        child.type in {"default_method_clause", "delete_method_clause"}
        for child in children
    )
    if node.type in {"declaration", "field_declaration"}:
        suffix = source[declarator.end_byte : node.end_byte]
        suffix = re.sub(rb"/\*[\s\S]*?\*/|//[^\r\n]*", b" ", suffix)
        bodyless_definition = re.fullmatch(rb"\s*=\s*delete\s*;", suffix) is not None
    definition_end = (
        body.end_point.row + 1
        if body is not None
        else node.end_point.row + 1
        if bodyless_definition
        else None
    )
    signature_end = body.start_byte if body is not None else signature_node.end_byte
    signature_start = _original_declaration_start(signature_node, source)
    signature = _decode_source_text(source[signature_start:signature_end]).strip()

    artifact = FunctionArtifact(
        name=method_name if class_name is not None else resolved_name,
        stable_id=_function_stable_id(
            owner_id,
            method_name if class_name is not None else resolved_name,
            class_name=class_name,
        ),
        lineno=(
            signature_node.start_point.row
            + 1
            - source.count(b"\n", signature_start, signature_node.start_byte)
        ),
        end_lineno=definition_end,
        signature=_normalize_signature(signature),
        docstring=docstring,
        has_docstring=int(docstring is not None),
        is_method=int(class_name is not None),
        is_public=is_public,
        parameters=parameters,
        returns_value=_returns_value(body),
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=_extract_calls(
            body,
            source,
            parameter_names=parameters,
            initializer_value_bindings=initializer_value_bindings,
        ),
        callable_refs=(),
    )
    return _PendingFunction(
        artifact=artifact,
        class_name=class_name,
        is_definition=definition_end is not None,
        binding_key=_callable_binding_key(declarator, source),
    )


def _collect_known_class_names(
    children: Sequence[Node],
    source: bytes,
    *,
    namespace: Sequence[str] = (),
) -> set[str]:
    """
    Collect qualified class names declared within one subtree.

    Parameters
    ----------
    children : collections.abc.Sequence[tree_sitter.Node]
        Sibling nodes to inspect.
    source : bytes
        Full source buffer.
    namespace : collections.abc.Sequence[str], optional
        Active namespace prefix for the current subtree.

    Returns
    -------
    set[str]
        Qualified class names declared in the subtree.
    """
    known: set[str] = set()
    for child in _conditional_children(children):
        if child.type == "linkage_specification":
            body = child.child_by_field_name("body")
            if body is not None:
                known.update(
                    _collect_known_class_names(
                        body.named_children
                        if body.type == "declaration_list"
                        else (body,),
                        source,
                        namespace=namespace,
                    )
                )
            continue
        if child.type == "template_declaration":
            inner = _template_inner_node(child)
            if inner is not None:
                known.update(
                    _collect_known_class_names((inner,), source, namespace=namespace)
                )
            continue

        if child.type == "namespace_definition":
            declaration_list = next(
                (
                    grandchild
                    for grandchild in child.named_children
                    if grandchild.type == "declaration_list"
                ),
                None,
            )
            if declaration_list is None:
                continue
            namespace_parts = _namespace_parts(child, source)
            known.update(
                _collect_known_class_names(
                    declaration_list.named_children,
                    source,
                    namespace=(*namespace, *namespace_parts),
                )
            )
            continue

        record = _declared_type_specifier(child)
        if record is None or record.type == "enum_specifier":
            continue
        class_name = _class_name_from_specifier(record, source)
        if class_name is None:
            continue
        known.add(_qualified_name((*namespace, class_name)))
        body = record.child_by_field_name("body")
        if body is not None:
            known.update(
                _collect_known_class_names(
                    body.named_children, source, namespace=(*namespace, class_name)
                )
            )
    return known


class _CppAnalysisBuilder:
    """
    Mutable builder for one C++ analysis result.

    Parameters
    ----------
    source : bytes
        Full source buffer for the analyzed file.
    root : tree_sitter.Node
        Translation-unit root node.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    known_class_names : set[str]
        Qualified class names collected from the file.
    comment_maps : CommentMaps or None, optional
        Unmasked source attachment facts, independent of syntax visibility.

    Returns
    -------
    None
    """

    def __init__(
        self,
        *,
        source: bytes,
        root: Node,
        owner_id: str,
        known_class_names: set[str],
        comment_maps: CommentMaps | None = None,
        initializer_value_bindings: Mapping[str, tuple[int, ...]] | None = None,
    ) -> None:
        """Initialize artifact accumulators and optional physical comment facts.

        Parameters
        ----------
        source : bytes
            Buffer used for declaration and callable extraction.
        root : SyntaxNode
            Syntax view rooted in the same coordinate space.
        owner_id : str
            File-scoped symbol identity.
        known_class_names : set[str]
            Collected qualified class names.
        comment_maps : CommentMaps or None, optional
            Attachments captured before visibility projection.
        initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]] | None, optional
            Profile-bound qualified value names proven by the primary include walk.

        Returns
        -------
        None
        """
        self.source = source
        self.root = root
        self.owner_id = owner_id
        self.known_class_names = known_class_names
        self.initializer_value_bindings = (
            {} if initializer_value_bindings is None else initializer_value_bindings
        )
        self.class_builders: dict[str, _ClassBuilder] = {}
        self.functions_by_key: dict[tuple[str, tuple[str, ...]], _PendingFunction] = {}
        self.declarations_by_id: dict[str, DeclarationArtifact] = {}
        self.type_definition_ids: set[str] = set()
        self.doxygen_by_lineno: dict[int, tuple[str, int, int | None]] = {}
        self.source_comments = comment_maps[0] if comment_maps is not None else None
        if comment_maps is not None:
            self.doxygen_by_lineno.update(comment_maps[1])

    def _ensure_class_builder(
        self,
        *,
        qualified_name: str,
        lineno: int,
        end_lineno: int | None,
        docstring: str | None,
        is_definition: bool = False,
    ) -> _ClassBuilder:
        """
        Return the mutable builder for one class, creating it when needed.

        Parameters
        ----------
        qualified_name : str
            Qualified class name.
        lineno : int
            Candidate starting line for the class.
        end_lineno : int | None
            Candidate ending line for the class.
        docstring : str | None
            Candidate docstring attached to the class.
        is_definition : bool, optional
            Whether the candidate range contains a complete record body.

        Returns
        -------
        _ClassBuilder
            Mutable class accumulator.
        """
        stable_id = _class_stable_id(self.owner_id, qualified_name)
        builder = self.class_builders.get(qualified_name)
        if builder is None:
            builder = _ClassBuilder(
                qualified_name=qualified_name,
                stable_id=stable_id,
                lineno=lineno,
                end_lineno=end_lineno,
                docstring=docstring,
                has_docstring=int(docstring is not None),
                has_definition=is_definition,
            )
            self.class_builders[qualified_name] = builder
            return builder
        builder.absorb_metadata(
            lineno=lineno,
            end_lineno=end_lineno,
            docstring=docstring,
            is_definition=is_definition,
        )
        return builder

    def _record_function(self, pending: _PendingFunction) -> None:
        """
        Record one function or method candidate.

        Parameters
        ----------
        pending : _PendingFunction
            Callable candidate to store.

        Returns
        -------
        None
            The appropriate function accumulator is updated in place.
        """
        if pending.class_name is None:
            key = (pending.artifact.stable_id, pending.binding_key)
            current = self.functions_by_key.get(key)
            if current is None or _prefer_pending_function(current, pending) is pending:
                self.functions_by_key[key] = pending
            return

        builder = self._ensure_class_builder(
            qualified_name=pending.class_name,
            lineno=pending.artifact.lineno,
            end_lineno=None,
            docstring=None,
        )
        builder.record_method(pending)

    def _record_declaration(self, declaration: DeclarationArtifact | None) -> None:
        """
        Record one declaration artifact when present.

        Parameters
        ----------
        declaration : codira.models.DeclarationArtifact | None
            Declaration artifact to store.

        Returns
        -------
        None
            The declaration map is updated in place when a declaration exists.
        """
        if declaration is not None:
            self.declarations_by_id[declaration.stable_id] = declaration

    def _handle_type_declaration(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Prefer a complete enum, struct or union over its forward declarations.

        Parameters
        ----------
        node : tree_sitter.Node
            Type-specifier node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            One logical type retains its first complete definition, otherwise its
            first forward declaration.
        """
        if node.type == "enum_specifier":
            kind: DeclarationKind = "enum"
        elif node.type == "struct_specifier":
            kind = "struct"
        elif node.type == "union_specifier":
            kind = "union"
        else:
            return

        name = _type_specifier_name(node, self.source)
        if name is None:
            return
        qualified_name = _qualified_name((*namespace, name))
        declaration = _build_type_declaration(
            kind,
            qualified_name,
            node,
            self.source,
            owner_id=self.owner_id,
            docstring=docstring,
        )
        is_definition = any(
            child.type in {"field_declaration_list", "enumerator_list"}
            for child in node.named_children
        )
        current = self.declarations_by_id.get(declaration.stable_id)
        if current is None or (
            is_definition and declaration.stable_id not in self.type_definition_ids
        ):
            self._record_declaration(declaration)
        if is_definition:
            self.type_definition_ids.add(declaration.stable_id)

    def _handle_typedef_definition(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """Record every written alias in one module or class typedef.

        Parameters
        ----------
        node : SyntaxNode
            Complete typedef declaration, including its original signature.
        namespace : collections.abc.Sequence[str]
            Enclosing namespace and class path.
        docstring : str | None
            Leading declaration documentation when present.

        Returns
        -------
        None
            Qualified typedef artifacts are stored without visiting local scopes.
        """
        for name in _typedef_name_nodes(node):
            self._record_declaration(
                _build_type_declaration(
                    "typedef",
                    _qualified_name((*namespace, _node_text(name, self.source))),
                    node,
                    self.source,
                    owner_id=self.owner_id,
                    docstring=docstring,
                )
            )

    def _handle_alias_declaration(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record one `using` alias declaration.

        Parameters
        ----------
        node : tree_sitter.Node
            Alias-declaration node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Matching declaration artifacts are stored in place.
        """
        alias_name = next(
            (
                _node_text(child, self.source)
                for child in node.named_children
                if child.type in {"type_identifier", "identifier"}
            ),
            None,
        )
        if alias_name is None:
            return
        self._record_declaration(
            _build_alias_declaration(
                _qualified_name((*namespace, alias_name)),
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )

    def _handle_macro_declaration(
        self,
        node: Node,
        *,
        docstring: str | None,
    ) -> None:
        """
        Record one named preprocessor macro declaration.

        Parameters
        ----------
        node : tree_sitter.Node
            Preprocessor definition node.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Matching macro declaration artifacts are stored in place.
        """
        self._record_declaration(
            _build_macro_declaration(
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )

    def _handle_namespace(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record one namespace declaration and recurse into its body.

        Parameters
        ----------
        node : tree_sitter.Node
            Namespace-definition node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Namespace artifacts and nested declarations are stored in place.
        """
        namespace_parts = _namespace_parts(node, self.source)
        if not namespace_parts:
            return
        full_namespace = (*namespace, *namespace_parts)
        self._record_declaration(
            _build_namespace_declaration(
                _qualified_name(full_namespace),
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )
        declaration_list = next(
            (
                child
                for child in node.named_children
                if child.type == "declaration_list"
            ),
            None,
        )
        if declaration_list is None:
            return
        self._visit_children(
            declaration_list.named_children,
            namespace=full_namespace,
        )

    def _handle_class_specifier(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record class-like methods, member type aliases and nested record declarations.

        Parameters
        ----------
        node : tree_sitter.Node
            Class, struct or union specifier. Struct/union method containers
            are created only when explicit methods are present.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Class, method and qualified member-alias artifacts are stored in place.
        """
        class_name = _class_name_from_specifier(node, self.source)
        if class_name is None:
            return
        qualified_name = _qualified_name((*namespace, class_name))
        field_list = next(
            (
                child
                for child in node.named_children
                if child.type == "field_declaration_list"
            ),
            None,
        )
        builder = (
            self._ensure_class_builder(
                qualified_name=qualified_name,
                lineno=node.start_point.row + 1,
                end_lineno=node.end_point.row + 1,
                docstring=docstring,
                is_definition=field_list is not None,
            )
            if node.type == "class_specifier"
            else None
        )
        if field_list is None:
            return

        current_public = node.type in {"struct_specifier", "union_specifier"}
        children = tuple(_conditional_children(field_list.children))
        attached_comments = self.source_comments
        if attached_comments is None:
            attached_comments = _attached_comment_map(children, self.source)
            self.doxygen_by_lineno.update(
                _attached_doxygen_comment_map(children, self.source)
            )
        friend_sibling_starts: set[int] = set()
        for child in children:
            if child.start_byte in friend_sibling_starts:
                continue
            if child.type == "access_specifier":
                current_public = _node_text(child, self.source) in {
                    "public",
                    "protected",
                }
                continue

            child_docstring = attached_comments.get(child.start_byte)
            candidate = (
                _template_inner_node(child)
                if child.type == "template_declaration"
                else child
            )
            if candidate is not None and candidate.type == "friend_declaration":
                self._handle_friend_declaration(
                    candidate,
                    namespace=namespace,
                    docstring=child_docstring,
                    signature_node=child,
                )
                continue
            if child.type == "field_declaration":
                sibling = self._friend_prefix_has_callable_sibling(children, child)
                if sibling is not None:
                    friend_sibling_starts.add(sibling.start_byte)
                    self._handle_friend_declaration(
                        sibling,
                        namespace=namespace,
                        docstring=child_docstring,
                        signature_node=sibling,
                    )
                    continue
            if candidate is not None and candidate.type == "type_definition":
                self._dispatch_node(
                    candidate,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                    signature_node=child,
                )
                continue
            if candidate is not None and candidate.type == "alias_declaration":
                self._handle_alias_declaration(
                    candidate,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                )
                continue
            nested_type = (
                _declared_type_specifier(candidate) if candidate is not None else None
            )
            if nested_type is not None:
                self._dispatch_node(
                    nested_type,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                    signature_node=child,
                )
                continue
            if child.type == "template_declaration":
                inner = _template_inner_node(child)
                if inner is None:
                    continue
                pending = _build_function_artifact(
                    inner,
                    self.source,
                    namespace=namespace,
                    known_class_names=self.known_class_names,
                    owner_id=self.owner_id,
                    docstring=child_docstring,
                    is_public=int(current_public),
                    signature_node=child,
                    initializer_value_bindings=self.initializer_value_bindings,
                )
                if pending is not None:
                    pending = replace(
                        pending,
                        class_name=qualified_name,
                        artifact=replace(
                            pending.artifact,
                            name=pending.artifact.name.split("::")[-1],
                            stable_id=_function_stable_id(
                                self.owner_id,
                                pending.artifact.name.split("::")[-1],
                                class_name=qualified_name,
                            ),
                            is_method=1,
                        ),
                    )
                    if builder is None:
                        builder = self._ensure_class_builder(
                            qualified_name=qualified_name,
                            lineno=node.start_point.row + 1,
                            end_lineno=node.end_point.row + 1,
                            docstring=docstring,
                            is_definition=True,
                        )
                    builder.record_method(pending)
                continue

            pending = _build_function_artifact(
                child,
                self.source,
                namespace=namespace,
                known_class_names=self.known_class_names,
                owner_id=self.owner_id,
                docstring=child_docstring,
                is_public=int(current_public),
                signature_node=child,
                initializer_value_bindings=self.initializer_value_bindings,
            )
            if pending is None:
                continue
            pending = replace(
                pending,
                class_name=qualified_name,
                artifact=replace(
                    pending.artifact,
                    name=pending.artifact.name.split("::")[-1],
                    stable_id=_function_stable_id(
                        self.owner_id,
                        pending.artifact.name.split("::")[-1],
                        class_name=qualified_name,
                    ),
                    is_method=1,
                ),
            )
            if builder is None:
                builder = self._ensure_class_builder(
                    qualified_name=qualified_name,
                    lineno=node.start_point.row + 1,
                    end_lineno=node.end_point.row + 1,
                    docstring=docstring,
                    is_definition=True,
                )
            builder.record_method(pending)

    def _friend_prefix_has_callable_sibling(
        self, children: Sequence[Node], prefix: Node
    ) -> Node | None:
        """Return a parser-split friend declarator following its prefix node.

        Parameters
        ----------
        children : collections.abc.Sequence[tree_sitter.Node]
            Class-body children in source order.
        prefix : tree_sitter.Node
            Field node containing a trailing `friend` token.

        Returns
        -------
        tree_sitter.Node | None
            Adjacent callable field node when the grammar split the declaration.
        """
        leaf = next(
            (
                item
                for item in reversed(_named_descendants(prefix))
                if _node_text(item, self.source) == "friend"
            ),
            None,
        )
        if leaf is None or leaf.end_byte != prefix.end_byte:
            return None
        position = children.index(prefix)
        if position + 1 >= len(children):
            return None
        candidate = children[position + 1]
        if candidate.type not in {
            "declaration",
            "field_declaration",
            "function_definition",
        }:
            return None
        between = self.source[prefix.end_byte : candidate.start_byte]
        if b"\n" in between or between.strip():
            return None
        if _find_function_declarator(candidate) is None:
            return None
        return candidate

    def _handle_friend_declaration(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
        signature_node: Node,
    ) -> None:
        """Record a callable friend with its namespace or qualified owner.

        Parameters
        ----------
        node : tree_sitter.Node
            Friend wrapper or parser-split callable declaration.
        namespace : collections.abc.Sequence[str]
            Enclosing namespace path; the befriending class is excluded.
        docstring : str | None
            Attached comment summary when present.
        signature_node : tree_sitter.Node
            Original syntax node used for signature and source position.

        Returns
        -------
        None
            Callable friends are stored using ordinary declaration coalescing.
        """
        callable_node = next(
            (
                candidate
                for candidate in _named_descendants(node)
                if candidate.type
                in {"function_definition", "declaration", "field_declaration"}
                and _find_function_declarator(candidate) is not None
            ),
            None,
        )
        if callable_node is None:
            return
        friend_namespace = list(namespace)
        while (
            friend_namespace
            and _qualified_name(friend_namespace) in self.known_class_names
        ):
            friend_namespace.pop()
        pending = _build_function_artifact(
            callable_node,
            self.source,
            namespace=friend_namespace,
            known_class_names=self.known_class_names,
            owner_id=self.owner_id,
            docstring=docstring,
            is_public=_is_likely_public_definition(callable_node, self.source),
            signature_node=signature_node,
            initializer_value_bindings=self.initializer_value_bindings,
        )
        if pending is not None:
            self._record_function(pending)

    def _handle_callable_node(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
        signature_node: Node,
    ) -> None:
        """
        Record one free function or out-of-class method candidate.

        Parameters
        ----------
        node : tree_sitter.Node
            Function-definition or declaration node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.
        signature_node : tree_sitter.Node
            Node whose source span should seed signature extraction.

        Returns
        -------
        None
            Matching callable artifacts are stored in place.
        """
        pending = _build_function_artifact(
            node,
            self.source,
            namespace=namespace,
            known_class_names=self.known_class_names,
            owner_id=self.owner_id,
            docstring=docstring,
            is_public=_is_likely_public_definition(node, self.source),
            signature_node=signature_node,
            initializer_value_bindings=self.initializer_value_bindings,
        )
        if pending is not None:
            self._record_function(pending)

    def _dispatch_node(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
        signature_node: Node,
    ) -> None:
        """
        Dispatch one node to the matching C++ extraction handler.

        Parameters
        ----------
        node : tree_sitter.Node
            Node to inspect.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.
        signature_node : tree_sitter.Node
            Node whose source span should seed signature extraction when needed.

        Returns
        -------
        None
            Matching artifacts are stored in place.
        """
        if node.type in {"preproc_def", "preproc_function_def"}:
            self._handle_macro_declaration(node, docstring=docstring)
            return
        if node.type == "template_declaration":
            inner = _template_inner_node(node)
            if inner is not None:
                self._dispatch_node(
                    inner,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
            return
        if node.type == "linkage_specification":
            body = node.child_by_field_name("body")
            if body is not None:
                if body.type == "declaration_list":
                    self._visit_children(body.named_children, namespace=namespace)
                else:
                    self._dispatch_node(
                        body,
                        namespace=namespace,
                        docstring=docstring,
                        signature_node=signature_node,
                    )
            return
        if node.type == "namespace_definition":
            self._handle_namespace(node, namespace=namespace, docstring=docstring)
            return
        if node.type == "class_specifier":
            self._handle_class_specifier(node, namespace=namespace, docstring=docstring)
            return
        if node.type == "type_definition":
            self._handle_typedef_definition(
                node, namespace=namespace, docstring=docstring
            )
            declared_type = _declared_type_specifier(node)
            if declared_type is not None:
                self._dispatch_node(
                    declared_type,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
            return
        if node.type in {"declaration", "field_declaration"}:
            declared_type = _declared_type_specifier(node)
            if declared_type is not None:
                self._dispatch_node(
                    declared_type,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
                if _find_function_declarator(node) is None:
                    return
        if node.type == "alias_declaration":
            self._handle_alias_declaration(
                node, namespace=namespace, docstring=docstring
            )
            return
        if node.type in {"enum_specifier", "struct_specifier", "union_specifier"}:
            self._handle_type_declaration(
                node, namespace=namespace, docstring=docstring
            )
            if node.type in {"struct_specifier", "union_specifier"}:
                self._handle_class_specifier(
                    node, namespace=namespace, docstring=docstring
                )
            return
        if _is_function_definition(node):
            self._handle_callable_node(
                node,
                namespace=namespace,
                docstring=docstring,
                signature_node=signature_node,
            )
            return
        if (
            node.type in {"declaration", "field_declaration"}
            and _find_function_declarator(node) is not None
        ):
            self._handle_callable_node(
                node,
                namespace=namespace,
                docstring=docstring,
                signature_node=signature_node,
            )

    def _visit_children(
        self,
        children: Sequence[Node],
        *,
        namespace: Sequence[str],
    ) -> None:
        """
        Visit one sibling list under a shared namespace context.

        Parameters
        ----------
        children : collections.abc.Sequence[tree_sitter.Node]
            Sibling nodes to visit.
        namespace : collections.abc.Sequence[str]
            Active namespace path.

        Returns
        -------
        None
            Matching artifacts are stored in place.
        """
        children = tuple(_conditional_children(children))
        attached_comments = self.source_comments
        if attached_comments is None:
            attached_comments = _attached_comment_map(children, self.source)
            self.doxygen_by_lineno.update(
                _attached_doxygen_comment_map(children, self.source)
            )
        for child in children:
            if child.type in {"comment", "preproc_include"}:
                continue
            docstring = attached_comments.get(child.start_byte)
            if child.type == "template_declaration":
                inner = _template_inner_node(child)
                if inner is None:
                    continue
                self._dispatch_node(
                    inner,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=child,
                )
                continue
            self._dispatch_node(
                child,
                namespace=namespace,
                docstring=docstring,
                signature_node=child,
            )

    def build(
        self,
        *,
        source_path: Path,
        module_name: str,
        module_stable_id: str,
        module_docstring: str | None,
    ) -> AnalysisResult:
        """
        Finalize the immutable analysis result.

        Parameters
        ----------
        source_path : pathlib.Path
            Source file associated with the analysis.
        module_name : str
            Logical module name for the file.
        module_stable_id : str
            Durable module identity derived from the repository-relative path.
        module_docstring : str | None
            Leading module comment when present.

        Returns
        -------
        codira.models.AnalysisResult
            Final normalized analyzer output.
        """
        imports = _extract_imports(self.root, self.source)
        self._visit_children(self.root.children, namespace=())
        classes = tuple(
            builder.build()
            for builder in sorted(
                self.class_builders.values(),
                key=lambda item: (item.lineno, item.qualified_name),
            )
        )
        functions = tuple(
            pending.artifact
            for pending in sorted(
                self.functions_by_key.values(),
                key=lambda item: (
                    item.artifact.lineno,
                    item.artifact.name,
                    item.artifact.signature,
                ),
            )
        )
        functions = _disambiguate_callable_stable_ids(functions)
        declarations = tuple(
            sorted(
                self.declarations_by_id.values(),
                key=lambda item: (item.lineno, item.name, item.stable_id),
            )
        )
        return AnalysisResult(
            source_path=source_path,
            module=ModuleArtifact(
                name=module_name,
                stable_id=module_stable_id,
                docstring=module_docstring,
                has_docstring=int(module_docstring is not None),
            ),
            classes=classes,
            functions=functions,
            declarations=declarations,
            imports=imports,
        )


_CPP_HEADER_NODES = frozenset(
    {
        "namespace_definition",
        "template_declaration",
        "class_specifier",
        "qualified_identifier",
        "using_declaration",
        "alias_declaration",
        "reference_declarator",
        "rvalue_reference_declarator",
    }
)


def _is_cpp_header(path: Path) -> bool:
    """Recognize C++ headers using neighbouring units and parsed syntax.

    Parameters
    ----------
    path : pathlib.Path
        Ambiguous .h file to inspect; comment and string contents are not hints.

    Returns
    -------
    bool
        True for a C++-only same-stem neighbour, a C++ syntax node or an
        independently parsed named template parameter list. Shared C/C++
        neighbours and syntax without such evidence retain the C default.
    """
    if not path.is_file():
        return False
    cpp_neighbour = any(
        path.with_suffix(suffix).is_file() for suffix in (".cpp", ".cc", ".cxx")
    )
    if cpp_neighbour and not path.with_suffix(".c").is_file():
        return True
    source = path.read_bytes()
    root = _parse_cpp_source(source)
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in _CPP_HEADER_NODES:
            return True
        if node.type not in {"comment", "string_literal", "raw_string_literal"}:
            pending.extend(node.named_children)
    return root.has_error and has_named_template_parameters(source, root)


@dataclass
class _ExternalOwner:
    """Collect source-proven class declarations without emitting their symbols.

    Parameters
    ----------
    stable_ids : set[str]
        Candidate declaration identities from contained headers.
    visibility : dict[str, set[int]]
        Observed access flags for each explicitly declared method name.

    Returns
    -------
    None
        Header evidence for external owner references only.
    """

    stable_ids: set[str] = field(default_factory=set)
    visibility: dict[str, set[int]] = field(default_factory=dict)


def _external_owner_alternatives(result: AnalysisResult) -> set[str]:
    """Retain namespace/alias conflicts without treating member aliases as owners.

    Parameters
    ----------
    result : codira.models.AnalysisResult
        Source-local or captured-header artifacts.

    Returns
    -------
    set[str]
        Existing namespace and nonmember alias alternatives. An alias whose
        direct owner is a written record does not invalidate that record or
        change the legacy treatment of namespace alias prefixes. If a written
        namespace shares the record name in another alternative, its aliases
        retain their conflict evidence.
    """
    namespaces = {
        declaration.name
        for declaration in result.declarations
        if declaration.kind == "namespace"
    }
    records = {cls.name for cls in result.classes} | {
        declaration.name
        for declaration in result.declarations
        if declaration.kind in {"class", "struct", "union"}
    }
    return {
        declaration.name
        for declaration in result.declarations
        if declaration.kind == "namespace"
        or (
            declaration.kind == "type_alias"
            and (
                declaration.name.rpartition("::")[0] not in records
                or declaration.name.rpartition("::")[0] in namespaces
            )
        )
    }


def _external_method_owners(
    context: IncludeContext, root: Path, source_result: AnalysisResult
) -> dict[str, _ExternalOwner]:
    """Find unambiguous class-owner evidence in clean captured header trees.

    Parameters
    ----------
    context : IncludeContext
        Exact source and header snapshot already used for syntax recovery.
    root : pathlib.Path
        Repository boundary used to derive declaration identities.
    source_result : AnalysisResult
        Source-local artifacts whose namespace and alias evidence takes priority.

    Returns
    -------
    dict[str, _ExternalOwner]
        Qualified class names and declaration/access evidence. Header artifacts
        are not copied into the source result. Member aliases are excluded from
        conflicting alternatives so their parent records remain valid owners.
    """
    owners: dict[str, _ExternalOwner] = {}
    alternatives = _external_owner_alternatives(source_result)
    for header in context.headers:
        tree = _parse_cpp_source(header.source)
        if tree.has_error:
            continue
        header_result = _CppAnalysisBuilder(
            source=header.source,
            root=tree,
            owner_id=_symbol_owner_id(header.path, root),
            known_class_names=_collect_known_class_names(tree.children, header.source),
        ).build(
            source_path=header.path,
            module_name=_module_name_for_path(header.path, root),
            module_stable_id=_module_stable_id(header.path, root),
            module_docstring=None,
        )
        alternatives.update(_external_owner_alternatives(header_result))
        for cls in header_result.classes:
            owner = owners.setdefault(cls.name, _ExternalOwner())
            owner.stable_ids.add(cls.stable_id)
            for method in cls.methods:
                owner.visibility.setdefault(method.name, set()).add(method.is_public)
    conflicting_names = {
        _qualified_name(_split_qualified_name(name)[:end])
        for name in alternatives
        for end in range(1, len(_split_qualified_name(name)) + 1)
    }
    return {
        name: owner for name, owner in owners.items() if name not in conflicting_names
    }


def _external_member_calls(
    function: FunctionArtifact,
    owner_name: str,
    owner: _ExternalOwner,
    source: bytes,
    source_tree: Node,
) -> tuple[CallSite, ...]:
    """Qualify proven member calls while retaining ambiguous lexical bindings.

    Parameters
    ----------
    function : FunctionArtifact
        Source-owned method definition and original call sites.
    owner_name : str
        Header-declared qualified class name.
    owner : _ExternalOwner
        Captured method declarations for that class.
    source : bytes
        Original source bytes for lexical names.
    source_tree : tree_sitter.Node
        Recovered source tree with original byte and line positions.

    Returns
    -------
    tuple[CallSite, ...]
        Explicit class-member records where unqualified lookup is proven.
        Local declarations, parameters and nested scopes prevent inference.
    """
    bodies = [
        node.child_by_field_name("body")
        for node in _named_descendants(source_tree)
        if node.type == "function_definition"
        and node.end_point.row + 1 == function.end_lineno
        and node.start_point.row + 1 >= function.lineno
    ]
    if len(bodies) != 1 or bodies[0] is None or len(owner.stable_ids) != 1:
        return function.calls
    nodes = _named_descendants(bodies[0])
    nested_scopes = [
        node
        for node in nodes
        if node.type in {"lambda_expression", "class_specifier", "struct_specifier"}
    ]
    if any(
        node.type == "call_expression"
        and (callee := node.child_by_field_name("function")) is not None
        and callee.type == "primitive_type"
        for node in nodes
    ):
        # The grammar can parse a local function-pointer declaration as nested
        # primitive-type calls. Its lexical bindings are then not proven.
        return function.calls
    shadowed = set(function.parameters)
    for node in nodes:
        if node.type in {"using_declaration", "type_definition"}:
            shadowed.update(
                _node_text(child, source)
                for child in _named_descendants(node)
                if child.type in {"identifier", "type_identifier"}
            )
        for index, declarator in enumerate([*node.children]):
            if node.field_name_for_child(index) != "declarator":
                continue
            name = _parameter_name_node(declarator)
            if name is not None:
                shadowed.add(_node_text(name, source))
            else:
                shadowed.update(
                    _node_text(child, source)
                    for binding in (declarator, *_named_descendants(declarator))
                    if binding.type == "structured_binding_declarator"
                    for child in binding.named_children
                    if child.type == "identifier"
                )
    source_lines = source.splitlines()
    return tuple(
        replace(call, kind="attribute", base=owner_name)
        if call.target in owner.visibility
        and not any(
            (scope.start_point.row, scope.start_point.column)
            <= (call.lineno - 1, call.col_offset)
            < (scope.end_point.row, scope.end_point.column)
            for scope in nested_scopes
        )
        and (
            (
                call.kind == "name"
                and not call.base
                and call.target not in shadowed
                and not source_lines[call.lineno - 1][call.col_offset :]
                .lstrip()
                .startswith(b"::")
                and not source_lines[call.lineno - 1][: call.col_offset]
                .rstrip()
                .endswith(b"::")
            )
            or (call.kind == "attribute" and call.base == "this")
        )
        else call
        for call in function.calls
    )


def _attach_external_method_owners(
    result: AnalysisResult,
    context: IncludeContext,
    root: Path,
    owner_id: str,
    source_tree: Node,
) -> AnalysisResult:
    """Attach proven owners to qualified definitions without fake class rows.

    Parameters
    ----------
    result : AnalysisResult
        Source-local normalized output.
    context : IncludeContext
        Captured include inputs.
    root : pathlib.Path
        Repository root for declaration identities.
    owner_id : str
        Source-owned identity prefix for callable definitions.
    source_tree : tree_sitter.Node
        Recovered tree used to check lexical call bindings.

    Returns
    -------
    AnalysisResult
        Methods retain source spans and refer to the original header declaration.
        Header owner discovery is skipped when source namespace or alias
        evidence already excludes every requested owner. Callable identities
        still receive the same final disambiguation.
    """
    if not any("::" in function.name for function in result.functions):
        return result
    requested_owners = {
        _qualified_name(_split_qualified_name(function.name)[:-1])
        for function in result.functions
    }
    source_conflicts = {
        _qualified_name(_split_qualified_name(name)[:end])
        for name in _external_owner_alternatives(result)
        for end in range(1, len(_split_qualified_name(name)) + 1)
    }
    # Header alternatives can only add conflicts, never remove source evidence.
    # Include unqualified functions above so mixed inputs retain header lookup.
    owners = (
        {}
        if requested_owners <= source_conflicts
        else _external_method_owners(context, root, result)
    )
    functions: list[FunctionArtifact] = []
    for function in result.functions:
        parts = _split_qualified_name(function.name)
        owner_name = _qualified_name(parts[:-1])
        owner = owners.get(owner_name)
        if owner is None:
            functions.append(function)
            continue
        name = parts[-1]
        visibility = owner.visibility.get(name, set())
        functions.append(
            replace(
                function,
                name=name,
                stable_id=_function_stable_id(owner_id, name, class_name=owner_name),
                is_method=1,
                is_public=next(iter(visibility))
                if len(visibility) == 1
                else function.is_public,
                owner_name=owner_name,
                owner_stable_id=next(iter(owner.stable_ids))
                if len(owner.stable_ids) == 1
                else None,
                calls=_external_member_calls(
                    function, owner_name, owner, context.source, source_tree
                ),
            )
        )
    return replace(
        result, functions=_disambiguate_callable_stable_ids(tuple(functions))
    )


class CppAnalyzer:
    """
    Concrete C++ analyzer for repository indexing.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Creates a configured C++ analyzer.

    Notes
    -----
    The default analyzer uses `tree-sitter-cpp`. An explicitly configured
    Clang frontend is optional and falls back to Tree-sitter with partial
    status when its profile, helper, or source mapping is incomplete.
    """

    name = "cpp"
    version = "45"
    discovery_globs: tuple[str, ...] = (
        "*.cpp",
        "*.cc",
        "*.cxx",
        "*.hpp",
        "*.hh",
        "*.hxx",
        "*.ipp",
        "*.h",
    )
    default_coverage_roots: tuple[str, ...] = ("src", "include", "tests")

    def __init__(self) -> None:
        """Initialize default analyzer and header-routing options.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Automatic header detection is enabled by default.
        """
        self._path_filters = AnalyzerPathFilters()
        self._header_language = "auto"
        self._include_search_paths: tuple[Path, ...] = ()
        self._namespace_macro_definitions: tuple[tuple[bytes, bytes], ...] = ()
        self._preprocessor_definitions: dict[bytes, _MacroDefinition | None] | None = (
            None
        )
        self._preprocessor_features: FeatureAnswers = {}
        self._preprocessor_header_queries: dict[str, HeaderQuerySet] = {}
        self._preprocessor_query_profile_fingerprint = plugin_configuration_fingerprint(
            {}
        )
        self._use_leading_comments = True
        self._emit_doxygen_documentation = True
        self._include_system_includes = True
        self._emit_namespaces = True
        self._emit_macros = True
        self._frontend = "tree-sitter"
        self._clang_compile_commands: str | None = None
        self._clang_captured_profiles: str | None = None
        self._clang_helper_path: str | None = None
        self._clang_build_receipt_path: str | None = None
        self._clang_attempt_root = ".artifacts/clang-frontend"
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the C++ analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for C++ analyzer options.
        """

        return analyzer_json_schema(
            {
                "use_leading_comments": boolean_property(True),
                "emit_doxygen_documentation": boolean_property(True),
                "include_system_includes": boolean_property(True),
                "include_search_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                    "description": (
                        "Ordered include search roots, relative to the repository "
                        "or absolute inside it. Quoted includes search their "
                        "own directory first."
                    ),
                },
                "namespace_macro_definitions": {
                    "type": "object",
                    "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "additionalProperties": {
                        "type": "string",
                        "pattern": "^[A-Za-z_][A-Za-z_0-9]*$",
                    },
                    "default": {},
                    "description": "Explicit identifier bindings for namespace declaration names; no branch selection or general expression expansion.",
                },
                "preprocessor_definitions": {
                    "type": "object",
                    "maxProperties": 4096,
                    "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "boolean"},
                            {
                                "type": "object",
                                "properties": {"defined": {"const": True}},
                                "required": ["defined"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "description": "Opt-in bounded captured declaration-macro analysis. Strings are object replacements, true is 1, false is explicitly undefined, and {defined: true} supplies opaque definedness. Missing names remain unknown.",
                },
                "preprocessor_features": {
                    "type": "object",
                    "maxProperties": 4096,
                    "additionalProperties": {"type": "string", "maxLength": 32},
                    "description": "Explicit exact native integer answers for pure compiler feature queries. Source overrides and changed argument macros remain unsupported.",
                },
                "preprocessor_header_queries": header_queries_schema(),
                "emit_namespaces": boolean_property(True),
                "emit_macros": boolean_property(True),
                "header_language": {
                    "type": "string",
                    "enum": ["auto", "c", "cpp"],
                    "default": "auto",
                    "description": "Language selection for ambiguous .h headers.",
                },
                "frontend": {
                    "type": "string",
                    "enum": ["tree-sitter", "clang"],
                    "default": "tree-sitter",
                    "description": "Select the optional Clang frontend explicitly; Tree-sitter remains the default.",
                },
                "clang_compile_commands": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Explicit compilation database used to select the exact C++ profile for each source file.",
                },
                "clang_captured_profiles": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Explicit generic captured-profile JSON file, selected by exact source path and digest.",
                },
                "clang_helper_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Explicit path to the packaged Clang frontend helper executable.",
                },
                "clang_build_receipt_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Explicit path to the helper build receipt used for toolchain identity.",
                },
                "clang_attempt_root": {
                    "type": "string",
                    "minLength": 1,
                    "default": ".artifacts/clang-frontend",
                    "description": "Durable root for immutable per-attempt Clang evidence; may be repository-relative or an explicit absolute path.",
                },
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply C++ analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.

        Raises
        ------
        ValueError
            If header_language is not auto, c or cpp, or include_search_paths
            is not a list of nonempty strings, or namespace_macro_definitions
            is not an identifier mapping. Repository containment is checked
            when analysis inputs are read. Invalid compiler query literals,
            observation identities, ranges or bounds are rejected explicitly.
        """

        frontend = config.get("frontend", "tree-sitter")
        if not isinstance(frontend, str) or frontend not in {"tree-sitter", "clang"}:
            raise ValueError("frontend must be tree-sitter or clang")
        clang_options: dict[str, str | None] = {}
        for option in (
            "clang_compile_commands",
            "clang_captured_profiles",
            "clang_helper_path",
            "clang_build_receipt_path",
        ):
            value = config.get(option)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{option} must be a nonempty string when provided")
            clang_options[option] = value if isinstance(value, str) else None
        attempt_root = config.get("clang_attempt_root", ".artifacts/clang-frontend")
        if not isinstance(attempt_root, str) or not attempt_root:
            raise ValueError("clang_attempt_root must be a nonempty string")
        if (
            clang_options["clang_compile_commands"]
            and clang_options["clang_captured_profiles"]
        ):
            raise ValueError(
                "configure only one of clang_compile_commands or clang_captured_profiles"
            )
        self._path_filters = analyzer_path_filters_from_config(config)
        self._header_language = str(config.get("header_language", "auto"))
        if self._header_language not in {"auto", "c", "cpp"}:
            raise ValueError("header_language must be auto, c or cpp")
        search_paths = config.get("include_search_paths", [])
        if not isinstance(search_paths, list) or any(
            not isinstance(item, str) or not item for item in search_paths
        ):
            raise ValueError("include_search_paths must be a list of nonempty strings")
        self._include_search_paths = tuple(Path(item) for item in search_paths)
        self._namespace_macro_definitions = _namespace_bindings_from_config(
            config.get("namespace_macro_definitions", {})
        )
        from .cpp_generated_analysis import preprocessor_definitions

        self._preprocessor_definitions = (
            preprocessor_definitions(config["preprocessor_definitions"])
            if "preprocessor_definitions" in config
            else None
        )
        self._preprocessor_features = feature_answers(
            config.get("preprocessor_features", {}), self._preprocessor_definitions
        )
        self._preprocessor_header_queries = header_query_sets(
            config.get("preprocessor_header_queries", {})
        )
        if self._preprocessor_header_queries and self._preprocessor_definitions is None:
            raise ValueError(
                "header query observations require explicit preprocessor_definitions"
            )
        self._preprocessor_query_profile_fingerprint = plugin_configuration_fingerprint(
            {
                key: value
                for key, value in config.items()
                if key != "preprocessor_header_queries"
            }
        )
        self._use_leading_comments = bool(config.get("use_leading_comments", True))
        self._emit_doxygen_documentation = bool(
            config.get("emit_doxygen_documentation", True)
        )
        self._include_system_includes = bool(
            config.get("include_system_includes", True)
        )
        self._emit_namespaces = bool(config.get("emit_namespaces", True))
        self._emit_macros = bool(config.get("emit_macros", True))
        self._frontend = frontend
        self._clang_compile_commands = clang_options["clang_compile_commands"]
        self._clang_captured_profiles = clang_options["clang_captured_profiles"]
        self._clang_helper_path = clang_options["clang_helper_path"]
        self._clang_build_receipt_path = clang_options["clang_build_receipt_path"]
        self._clang_attempt_root = attempt_root
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return C++ analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from C++ artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_cpp:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "namespace",
                "documentation",
                *(("variable",) if self._frontend == "clang" else ()),
            ),
            does_not_support=(() if self._frontend == "clang" else ("variable",)),
            mappings={
                "module": "module",
                "class": "type",
                "struct": "type",
                "union": "type",
                "enum": "type",
                "type_alias": "type",
                "function": "callable",
                "method": "callable",
                "namespace": "namespace",
                "macro": "constant",
                "include_local": "import",
                "include_system": "import",
                "doxygen": "documentation",
                **(
                    {"variable": "variable", "field": "variable"}
                    if self._frontend == "clang"
                    else {}
                ),
            },
        )

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """
        Return analyzer execution-safety guarantees.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Declaration permitting isolated process and thread workers.
        """

        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a C++ source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file carries a supported C++ suffix.
        """
        return path.suffix in _CPP_SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported C++ path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when filters allow the path and header routing claims it.
        """

        if not analyzer_path_allowed(path=path, root=root, filters=self._path_filters):
            return False
        if path.suffix != ".h":
            return True
        if self._header_language != "auto":
            return self._header_language == "cpp"
        return _is_cpp_header(path)

    def path_priority(self, path: Path, root: Path) -> int:
        """Prefer this plugin for accepted C++ headers over generic C claims.

        Parameters
        ----------
        path : pathlib.Path
            Already accepted source path.
        root : pathlib.Path
            Repository root supplied by the indexing contract.

        Returns
        -------
        int
            C++ headers have priority one; other paths retain default precedence.
        """
        return 1 if path.suffix == ".h" else 0

    def analysis_input_fingerprint(self, path: Path, root: Path) -> str:
        """Identify literal include inputs using the same snapshot as analysis.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit considered for incremental reuse.
        root : pathlib.Path
            Repository boundary for contained include resolution.

        Returns
        -------
        str
            Dependency identity including header bytes and negative lookups.
        """
        from .cpp_generated_analysis import captured_identity

        payload = json.loads(
            captured_identity(
                read_include_context(
                    path, root, include_paths=self._include_search_paths
                ),
                self.configuration_fingerprint,
            )
        )
        if self._frontend == "clang":
            try:
                frontend, profile = _clang_profile_and_frontend(
                    path=path,
                    root=root,
                    compile_commands=self._clang_compile_commands,
                    captured_profiles=self._clang_captured_profiles,
                    helper_path=self._clang_helper_path,
                    build_receipt_path=self._clang_build_receipt_path,
                )
                from codira_clang_frontend import frontend_profile_fingerprint

                clang_identity = frontend_profile_fingerprint(frontend, profile)
            except (ImportError, OSError, ValueError):
                clang_identity = _clang_fallback_fingerprint(
                    path=path,
                    root=root,
                    frontend_options=(
                        self._clang_compile_commands,
                        self._clang_captured_profiles,
                        self._clang_helper_path,
                        self._clang_build_receipt_path,
                        self._clang_attempt_root,
                    ),
                )
            payload["clang_frontend_fingerprint"] = clang_identity
        return validate_analysis_input_fingerprint(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            )
        )

    def analysis_input_fingerprint_matches(
        self, path: Path, root: Path, expected: str
    ) -> bool:
        """Check captured input content and resolutions without reparsing C++.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit being checked.
        root : pathlib.Path
            Repository boundary.
        expected : str
            Captured versioned include-input manifest.

        Returns
        -------
        bool
            Whether source/header bytes and resolution outcomes remain current.
        """
        try:
            payload = json.loads(expected)
        except ValueError:
            return False
        if self._frontend == "clang":
            try:
                return self.analysis_input_fingerprint(path, root) == expected
            except (OSError, ValueError):
                return False
        return (
            isinstance(payload, dict)
            and payload.get("generated_provenance_version") == 1
            and payload.get("configuration_fingerprint")
            == self.configuration_fingerprint
            and include_identity_matches(
                path,
                root,
                json.dumps(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "generated_provenance_version"
                    }
                ),
                include_paths=self._include_search_paths,
            )
        )

    def _try_clang_frontend(
        self, path: Path, root: Path
    ) -> tuple[FrontendResult | None, str]:
        """Run the optional frontend once with a fresh durable evidence leaf.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit selected for analysis.
        root : pathlib.Path
            Repository root used to resolve configured relative paths.

        Returns
        -------
        tuple[codira_clang_frontend.FrontendResult or None, str]
            Frontend result, or ``None``, and a stable fallback reason.

        Notes
        -----
        Failed and successful attempt directories are retained. There is no
        temporary-directory fallback for raw Clang evidence.
        """
        try:
            frontend, profile = _clang_profile_and_frontend(
                path=path,
                root=root,
                compile_commands=self._clang_compile_commands,
                captured_profiles=self._clang_captured_profiles,
                helper_path=self._clang_helper_path,
                build_receipt_path=self._clang_build_receipt_path,
            )
        except ImportError:
            return None, "optional_clang_frontend_package_unavailable"
        except (OSError, ValueError):
            return None, "clang_profile_or_toolchain_unavailable"
        attempt_root = Path(self._clang_attempt_root)
        if not attempt_root.is_absolute():
            attempt_root = root / attempt_root
        source_key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16]
        attempt_id = uuid4().hex
        attempt_dir = attempt_root / source_key / attempt_id
        try:
            attempt_dir.mkdir(parents=True, exist_ok=False)
            result = frontend.analyze(
                profile, attempt_dir=attempt_dir, attempt_id=attempt_id
            )
        except (OSError, ValueError):
            return None, "clang_attempt_evidence_or_execution_unavailable"
        if result.status != "parsed" or result.coverage_state != "complete":
            reason = result.reasons[0] if result.reasons else "clang_result_incomplete"
            return result, reason
        return result, ""

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one C++ source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            C++ source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        clang_fallback_reason: str | None = None
        clang_result: FrontendResult | None = None
        if self._frontend == "clang":
            clang_result, clang_fallback_reason = self._try_clang_frontend(path, root)
            if clang_result is not None and not clang_fallback_reason:
                context_identity = None
                if any(
                    item.provenance in {"macro_argument", "macro_replacement"}
                    for item in clang_result.callables
                ):
                    try:
                        context_identity = self.analysis_input_fingerprint(path, root)
                    except (OSError, ValueError):
                        context_identity = None
                mapped = _analysis_from_clang_result(
                    path,
                    root,
                    clang_result,
                    context_identity=context_identity,
                )
                if mapped is not None:
                    return mapped
                clang_fallback_reason = "clang_entities_outside_supported_cpp_dto_scope"
        context = read_include_context(
            path, root, include_paths=self._include_search_paths
        )
        if self._preprocessor_definitions is not None:
            from .cpp_generated_analysis import analyze_generated_file

            try:
                generated = analyze_generated_file(self, path, root, context)
                if clang_fallback_reason is not None:
                    return _clang_fallback_result(
                        generated,
                        clang_fallback_reason,
                        language="cpp",
                        frontend_result=clang_result,
                    )
                return generated
            except ValueError as error:
                result = self._analyze_captured_file(path, root, context)
                status = result.status
                diagnostic = AnalysisDiagnostic(
                    category="macro_context", message=str(error)
                )
                failed = replace(
                    result,
                    index_symbols=False,
                    status=AnalysisStatus(
                        grammar="tree-sitter-cpp",
                        target_contract={"language": "cpp"},
                        diagnostics=(
                            *(status.diagnostics if status is not None else ()),
                            diagnostic,
                        ),
                        reliable_categories=(),
                        omitted_categories=(
                            "module",
                            "class",
                            "function",
                            "declaration",
                            "import",
                            "documentation",
                        ),
                        coverage_state=AnalysisCoverageState.PARTIAL,
                    ),
                )
                if clang_fallback_reason is not None:
                    return _clang_fallback_result(
                        failed,
                        clang_fallback_reason,
                        language="cpp",
                        frontend_result=clang_result,
                    )
                return failed
        result = self._analyze_captured_file(path, root, context)
        if clang_fallback_reason is not None:
            result = _clang_fallback_result(
                result,
                clang_fallback_reason,
                language="cpp",
                frontend_result=clang_result,
            )
        return result

    def _analyze_captured_file(
        self,
        path: Path,
        root: Path,
        context: IncludeContext,
        *,
        syntax_root: Node | None = None,
        comment_source: bytes | None = None,
        initializer_value_bindings: Mapping[str, tuple[int, ...]] | None = None,
    ) -> AnalysisResult:
        """Extract ordinary syntax from an explicitly supplied immutable snapshot.

        Parameters
        ----------
        path, root : pathlib.Path
            Original file and trusted repository root.
        context : IncludeContext
            Exact source/header bytes, possibly a generated parser projection.
        syntax_root : SyntaxNode or None, optional
            Statement-only syntax already mapped to the original source buffer.
        comment_source : bytes or None, optional
            Unmasked source in the same coordinate space for physical attachment.
        initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]] | None, optional
            Qualified header values proven by the primary macro-context walk.

        Returns
        -------
        AnalysisResult
            Ordinary normalized extraction before generated coordinate repair.
        """
        source = context.source
        root_node = (
            syntax_root
            if syntax_root is not None
            else _parse_with_namespace_bindings(
                source,
                bindings=self._namespace_macro_definitions,
                included_sources=tuple(
                    (header.source, header.available_after)
                    for header in context.headers
                ),
            )
        )
        comment_root = root_node
        if comment_source is not None:
            comment_root = _parse_with_namespace_bindings(
                comment_source,
                bindings=self._namespace_macro_definitions,
                included_sources=tuple(
                    (header.source, header.available_after)
                    for header in context.headers
                ),
            )
        comment_bytes = source if comment_source is None else comment_source
        module_comment = (
            _leading_module_comment(comment_root, comment_bytes)
            if self._use_leading_comments
            else None
        )
        module_doxygen = _leading_module_doxygen(comment_root, comment_bytes)
        module_name = _module_name_for_path(path, root)
        module_stable_id = _module_stable_id(path, root)
        owner_id = _symbol_owner_id(path, root)
        known_class_names = _collect_known_class_names(root_node.children, source)
        builder = _CppAnalysisBuilder(
            source=source,
            root=root_node,
            owner_id=owner_id,
            known_class_names=known_class_names,
            initializer_value_bindings=(
                {} if initializer_value_bindings is None else initializer_value_bindings
            ),
            comment_maps=(
                source_comment_maps(comment_root, comment_bytes)
                if comment_source is not None
                else None
            ),
        )
        result = builder.build(
            source_path=path,
            module_name=module_name,
            module_stable_id=module_stable_id,
            module_docstring=module_comment,
        )
        result = _attach_external_method_owners(
            result, context, root, owner_id, root_node
        )
        if not self._use_leading_comments:
            result = replace(
                result,
                module=replace(result.module, docstring=None, has_docstring=0),
                classes=tuple(replace(cls, docstring=None) for cls in result.classes),
                functions=tuple(
                    replace(function, docstring=None) for function in result.functions
                ),
                declarations=tuple(
                    replace(declaration, docstring=None)
                    for declaration in result.declarations
                ),
            )
        if not self._include_system_includes:
            result = replace(
                result,
                imports=tuple(
                    item for item in result.imports if item.kind != "include_system"
                ),
            )
        if not self._emit_namespaces:
            result = replace(
                result,
                declarations=tuple(
                    declaration
                    for declaration in result.declarations
                    if declaration.kind != "namespace"
                ),
            )
        if not self._emit_macros:
            result = replace(
                result,
                declarations=tuple(
                    declaration
                    for declaration in result.declarations
                    if declaration.kind != "macro"
                ),
            )
        return replace(
            result,
            documentation=(
                _documentation_artifacts(
                    path=path,
                    analysis=result,
                    module_doxygen=module_doxygen,
                    doxygen_by_lineno=builder.doxygen_by_lineno,
                )
                if self._emit_doxygen_documentation
                else ()
            ),
            index_symbols=not root_node.has_error,
            status=tree_sitter_recovery_status(
                language="cpp", has_error=root_node.has_error
            ),
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party C++ analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        First-party C++ analyzer instance.
    """
    return CppAnalyzer()
