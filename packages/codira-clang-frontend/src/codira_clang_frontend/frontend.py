"""Run the fixed LibTooling helper against a captured C or C++ profile.

Parameters
----------
None

Returns
-------
None
    Module namespace for profile-bound Clang execution and response decoding.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Literal, cast

from .contracts import (
    CompilationContext,
    CoverageState,
    CompileProfile,
    DependencyClosure,
    DependencyInput,
    EntityProvenance,
    FrontendCall,
    FrontendCallable,
    FrontendCallableQualifiers,
    FrontendDeclaration,
    FrontendDiagnostic,
    FrontendDocumentationComment,
    FrontendInclude,
    FrontendPreprocessorEvent,
    FrontendResult,
    FrontendStatus,
    HeaderProjectionRequest,
    IncludeDirectoryInput,
    PreprocessorEventKind,
    SourcePoint,
    SourcePosition,
    SourceSpan,
    ToolchainIdentity,
)
from .profile import directory_membership_sha256, write_prepared_profile

_ACTION_FLAGS = {
    "-c",
    "-S",
    "-E",
    "-M",
    "-MM",
    "-MD",
    "-MMD",
    "-MP",
    "-MG",
    "-emit-llvm",
}
_ACTION_FLAGS_WITH_VALUE = {
    "-o",
    "-MF",
    "-MT",
    "-MQ",
    "-MJ",
    "-dependency-file",
    "-serialize-diagnostics",
    "-fmodule-output",
    "-ftime-trace-granularity",
    "-foptimization-record-file",
}
_ACTION_PREFIXES = ("-MF", "-MT", "-MQ", "-MJ", "-dependency-file=")
_DENIED_EXECUTION_FLAGS = {
    "-Xclang",
    "-cc1",
    "-cc1as",
    "-load",
    "-plugin",
    "-add-plugin",
    "-wrapper",
    "-specs",
    "-B",
    "-mllvm",
}
_DENIED_EXECUTION_PREFIXES = (
    "-fplugin",
    "-fpass-plugin",
    "-plugin-arg-",
    "--config=",
)
_VALUE_FLAGS = {
    "-D",
    "-U",
    "-I",
    "-isystem",
    "-iquote",
    "-idirafter",
    "-include",
    "-imacros",
    "-isysroot",
    "--sysroot",
    "-std",
    "-target",
    "--target",
    "-x",
    "-resource-dir",
    "-F",
    "-iframework",
    "-fmodule-map-file",
    "-fmodule-file",
    "-include-pch",
    "-stdlib",
    "-arch",
    "-gcc-toolchain",
    "--gcc-toolchain",
}


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once.

    Parameters
    ----------
    path : pathlib.Path
        File whose current bytes are hashed.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_json(value: object) -> str:
    """Hash a JSON-compatible value with deterministic key ordering.

    Parameters
    ----------
    value : object
        JSON-compatible value to serialize.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _same_path(value: object, expected: Path) -> bool:
    """Compare a native path value with a canonical expected path.

    Parameters
    ----------
    value : object
        Untrusted native JSON field.
    expected : pathlib.Path
        Expected local path.

    Returns
    -------
    bool
        Whether both values resolve to the same physical path.
    """
    return isinstance(value, str) and Path(value).resolve() == expected.resolve()


def _mapping(value: object) -> dict[str, object] | None:
    """Return a JSON object when the runtime value has the expected shape.

    Parameters
    ----------
    value : object
        Decoded JSON value.

    Returns
    -------
    dict[str, object] or None
        String-key mapping, or ``None`` for another shape.
    """
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return cast("dict[str, object]", value)
    return None


def _optional_string(value: object) -> str | None:
    """Return a value only when it is a string.

    Parameters
    ----------
    value : object
        Candidate decoded protocol value.

    Returns
    -------
    str or None
        Original string value or ``None`` for another JSON shape.
    """
    return value if isinstance(value, str) else None


def _optional_bool(value: object) -> bool | None:
    """Return a value only when it is a boolean.

    Parameters
    ----------
    value : object
        Candidate decoded protocol value.

    Returns
    -------
    bool or None
        Original boolean value or ``None`` for another JSON shape.
    """
    return value if isinstance(value, bool) else None


def _validate_response(response: dict[str, object]) -> str | None:
    """Validate the native protocol before trusting frontend coverage.

    Parameters
    ----------
    response : dict[str, object]
        Parsed helper response object.

    Returns
    -------
    str or None
        Stable protocol failure reason, or ``None`` when required fields have
        the expected version and JSON shapes.
    """
    if response.get("schema_version") not in {
        "codira.clang-frontend-native/3",
        "codira.clang-frontend-native/4",
        "codira.clang-frontend-native/5",
    }:
        return "unsupported_native_protocol_version"
    array_fields = (
        "declarations",
        "non_function_declarations",
        "calls",
        "diagnostics",
        "dependency_paths",
        "search_directories",
        "includes",
        "preprocessing",
        "documentation_comments",
    )
    if any(not isinstance(response.get(field), list) for field in array_fields):
        return "invalid_native_protocol_array_field"
    object_fields = (
        "declarations",
        "non_function_declarations",
        "calls",
        "diagnostics",
        "search_directories",
        "includes",
        "preprocessing",
        "documentation_comments",
    )
    if any(
        any(_mapping(item) is None for item in cast("list[object]", response[field]))
        for field in object_fields
    ):
        return "invalid_native_protocol_record_shape"
    if any(
        not isinstance(cast("dict[str, object]", _mapping(item)).get("text"), str)
        for item in cast("list[object]", response["documentation_comments"])
    ):
        return "invalid_native_protocol_documentation_comment_shape"
    if any(
        not isinstance(item, str)
        for item in cast("list[object]", response["dependency_paths"])
    ):
        return "invalid_native_protocol_dependency_path_shape"
    for item in cast("list[object]", response["includes"]):
        row = cast("dict[str, object]", _mapping(item))
        if (
            not isinstance(row.get("spelled_path"), str)
            or not isinstance(row.get("angled"), bool)
            or not isinstance(row.get("search_path"), str)
            or not isinstance(row.get("relative_path"), str)
            or not isinstance(row.get("module_imported"), bool)
        ):
            return "invalid_native_protocol_include_shape"
        if row.get("resolved_path") is not None and not isinstance(
            row.get("resolved_path"), str
        ):
            return "invalid_native_protocol_include_shape"
    allowed_events = {
        "macro_definition",
        "macro_undefinition",
        "macro_expansion",
        "if",
        "elif",
        "ifdef",
        "ifndef",
        "else",
        "endif",
    }
    allowed_condition_results = {"true", "false", "not_evaluated", "unknown"}
    for item in cast("list[object]", response["preprocessing"]):
        row = cast("dict[str, object]", _mapping(item))
        if row.get("kind") not in allowed_events:
            return "invalid_native_protocol_preprocessing_kind"
        if "replacement" in row and (
            not isinstance(row["replacement"], list)
            or any(not isinstance(token, str) for token in row["replacement"])
        ):
            return "invalid_native_protocol_preprocessing_replacement"
        if "replacement_truncated" in row and not isinstance(
            row["replacement_truncated"], bool
        ):
            return "invalid_native_protocol_preprocessing_truncation"
        if "function_like" in row and not isinstance(row["function_like"], bool):
            return "invalid_native_protocol_preprocessing_function_like"
        if "parameters" in row and (
            not isinstance(row["parameters"], list)
            or any(not isinstance(name, str) for name in row["parameters"])
        ):
            return "invalid_native_protocol_preprocessing_parameters"
        if "source_text" in row and not isinstance(row["source_text"], str):
            return "invalid_native_protocol_preprocessing_source_text"
        if "result" in row and row["result"] not in allowed_condition_results:
            return "invalid_native_protocol_preprocessing_result"
        if "macro_defined" in row and not isinstance(row["macro_defined"], bool):
            return "invalid_native_protocol_preprocessing_definedness"
    if response.get("capture_mode") != "source_relevant":
        return "invalid_native_protocol_capture_mode"
    result_code = response.get("tool_return_code")
    if not isinstance(result_code, int) or isinstance(result_code, bool):
        return "invalid_native_protocol_tool_return_code"
    if (
        not isinstance(response.get("clang_version"), str)
        or not response["clang_version"]
    ):
        return "invalid_native_protocol_clang_version"
    if (
        not isinstance(response.get("target_triple"), str)
        or not response["target_triple"]
        or not isinstance(response.get("sysroot"), str)
    ):
        return "invalid_native_protocol_compilation_context"
    if _mapping(response.get("capture_projection")) is None:
        return "invalid_native_protocol_capture_projection"
    if response.get("schema_version") in {
        "codira.clang-frontend-native/4",
        "codira.clang-frontend-native/5",
    }:
        if not isinstance(response.get("translation_unit_file"), str):
            return "invalid_native_protocol_translation_unit_file"
        if response.get("projection_file") is not None and not isinstance(
            response.get("projection_file"), str
        ):
            return "invalid_native_protocol_projection_file"
    if response.get("schema_version") == "codira.clang-frontend-native/5":
        for item in cast("list[object]", response["declarations"]):
            row = cast("dict[str, object]", _mapping(item))
            if "has_body" not in row or not isinstance(row.get("has_body"), bool):
                return "invalid_native_protocol_callable_body_fact"
            if not isinstance(row.get("linker_symbol"), str):
                return "invalid_native_protocol_linker_symbol"
            if not isinstance(row.get("linkage_kind"), str):
                return "invalid_native_protocol_linkage_kind"
            if row.get("signature_kind") != "derived_display_only":
                return "invalid_native_protocol_signature_kind"
            if row.get("explicit_linkage_label") is not None and not isinstance(
                row.get("explicit_linkage_label"), str
            ):
                return "invalid_native_protocol_linkage_label"
            if row.get("linkage_label_inherited") is not None and not isinstance(
                row.get("linkage_label_inherited"), bool
            ):
                return "invalid_native_protocol_linkage_label_inheritance"
            if row.get("alias_target_symbol") is not None and not isinstance(
                row.get("alias_target_symbol"), str
            ):
                return "invalid_native_protocol_alias_target_symbol"
            if row.get("alias_target_usr") is not None and not isinstance(
                row.get("alias_target_usr"), str
            ):
                return "invalid_native_protocol_alias_target_identity"
            if row.get("alias_binding_status") not in {
                "not_alias",
                "resolved",
                "unresolved",
                "ambiguous",
            }:
                return "invalid_native_protocol_alias_binding_status"
            alias_status = row["alias_binding_status"]
            alias_symbol = row.get("alias_target_symbol")
            alias_usr = row.get("alias_target_usr")
            if alias_status == "not_alias":
                if alias_symbol is not None or alias_usr is not None:
                    return "inconsistent_native_protocol_alias_facts"
            elif alias_status == "resolved":
                if (
                    not isinstance(alias_symbol, str)
                    or not alias_symbol
                    or not isinstance(alias_usr, str)
                    or not alias_usr
                ):
                    return "inconsistent_native_protocol_alias_facts"
            elif (
                not isinstance(alias_symbol, str)
                or not alias_symbol
                or alias_usr is not None
            ):
                return "inconsistent_native_protocol_alias_facts"
    return None


def _position(value: object) -> SourcePosition | None:
    """Decode a single source coordinate from the helper response.

    Parameters
    ----------
    value : object
        Candidate coordinate mapping.

    Returns
    -------
    codira_clang_frontend.contracts.SourcePosition or None
        Typed source coordinate, or ``None`` when unavailable.
    """
    row = _mapping(value)
    if row is None:
        return None
    path = row.get("path")
    line = row.get("line")
    column = row.get("column")
    offset = row.get("offset")
    return SourcePosition(
        path if isinstance(path, str) else None,
        line if isinstance(line, int) else None,
        column if isinstance(column, int) else None,
        offset if isinstance(offset, int) else None,
    )


def _decode_compilation_context(
    response: dict[str, object], working_directory: Path
) -> CompilationContext:
    """Decode the target and sysroot returned by the native Clang invocation.

    Parameters
    ----------
    response : dict[str, object]
        Validated native protocol response.
    working_directory : pathlib.Path
        Captured command directory for resolving a relative sysroot.

    Returns
    -------
    codira_clang_frontend.contracts.CompilationContext
        Exact triple and sysroot value plus its resolved path.
    """
    triple = cast("str", response["target_triple"])
    sysroot = cast("str", response["sysroot"])
    if not sysroot:
        sysroot_path = None
    else:
        candidate = Path(sysroot)
        if not candidate.is_absolute():
            candidate = working_directory / candidate
        sysroot_path = candidate.resolve()
    return CompilationContext(
        target_triple=triple,
        sysroot=sysroot,
        sysroot_path=sysroot_path,
    )


def _context_record(context: CompilationContext | None) -> dict[str, str | None] | None:
    """Return a canonical JSON record for native compiler context.

    Parameters
    ----------
    context : CompilationContext or None
        Compiler-derived target and sysroot context.

    Returns
    -------
    dict or None
        Canonical primitive fields, or ``None`` for an unbound profile.
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


def _point(value: object) -> SourcePoint | None:
    """Decode spelling and expansion coordinates from the helper response.

    Parameters
    ----------
    value : object
        Candidate source-location mapping.

    Returns
    -------
    codira_clang_frontend.contracts.SourcePoint or None
        Typed source location, or ``None`` when unavailable.
    """
    row = _mapping(value)
    if row is None:
        return None
    return SourcePoint(
        _position(row.get("spelling")),
        _position(row.get("expansion")),
        row.get("is_macro") is True,
    )


def _span(value: object) -> SourceSpan | None:
    """Decode the beginning and end of a source range.

    Parameters
    ----------
    value : object
        Candidate range mapping.

    Returns
    -------
    codira_clang_frontend.contracts.SourceSpan or None
        Typed source range, or ``None`` when unavailable.
    """
    row = _mapping(value)
    if row is None:
        return None
    return SourceSpan(_point(row.get("begin")), _point(row.get("end")))


def _arguments(value: object) -> tuple[tuple[str, str], ...]:
    """Decode named and typed function parameter records.

    Parameters
    ----------
    value : object
        Candidate parameter array.

    Returns
    -------
    tuple[tuple[str, str], ...]
        Ordered parameter name and type pairs.
    """
    if not isinstance(value, list):
        return ()
    output: list[tuple[str, str]] = []
    for item in value:
        row = _mapping(item)
        if row is None:
            continue
        name, type_text = row.get("name"), row.get("type")
        output.append(
            (
                name if isinstance(name, str) else "",
                type_text if isinstance(type_text, str) else "",
            )
        )
    return tuple(output)


def _provenance(value: object) -> EntityProvenance:
    """Normalize helper identity values without inferring missing provenance.

    Parameters
    ----------
    value : object
        Helper identity kind or call origin.

    Returns
    -------
    EntityProvenance
        One supported provenance value. Unrecognized or missing values remain
        ``unknown``.
    """
    if value in {"written", "source_written"}:
        return "source_written"
    if value == "macro_replacement":
        return "macro_replacement"
    if value == "macro_argument":
        return "macro_argument"
    if value == "implicit":
        return "implicit"
    if value in {"template_instantiation", "explicit_template_instantiation"}:
        return "template_instantiation"
    return "unknown"


def _callable_qualifiers(value: object) -> FrontendCallableQualifiers:
    """Decode Clang's C++ method-specific qualifier fields.

    Parameters
    ----------
    value : object
        Native ``method_qualifiers`` object.

    Returns
    -------
    codira_clang_frontend.contracts.FrontendCallableQualifiers
        Typed method and constructor metadata.
    """
    row = _mapping(value) or {}
    ref_qualifier = row.get("ref_qualifier")
    return FrontendCallableQualifiers(
        is_method=row.get("is_method") is True,
        is_const=_optional_bool(row.get("is_const")),
        is_volatile=_optional_bool(row.get("is_volatile")),
        is_static=_optional_bool(row.get("is_static")),
        is_virtual=_optional_bool(row.get("is_virtual")),
        is_pure_virtual=_optional_bool(row.get("is_pure_virtual")),
        ref_qualifier=cast("Literal['none', 'lvalue', 'rvalue']", ref_qualifier)
        if ref_qualifier in {"none", "lvalue", "rvalue"}
        else None,
        constructor_kind=_optional_string(row.get("constructor_kind")),
        is_explicit=_optional_bool(row.get("is_explicit")),
    )


def _declaration_provenance(identity: dict[str, object]) -> EntityProvenance:
    """Classify compiler-generated declarations before lexical spelling.

    Parameters
    ----------
    identity : dict[str, object]
        Native declaration identity, including semantic kind and provenance.

    Returns
    -------
    EntityProvenance
        Template/implicit origin when reported, otherwise the native source
        provenance or ``unknown``.
    """
    semantic_kind = identity.get("kind")
    if semantic_kind == "implicit":
        return "implicit"
    if semantic_kind in {
        "template_instantiation",
        "explicit_template_instantiation",
    }:
        return "template_instantiation"
    return _provenance(identity.get("provenance", semantic_kind))


def _decode_entities(
    response: dict[str, object],
) -> tuple[
    tuple[FrontendDeclaration, ...],
    tuple[FrontendCallable, ...],
    tuple[FrontendCall, ...],
]:
    """Build typed declaration and callable DTOs from native helper records.

    Parameters
    ----------
    response : dict[str, object]
        Decoded compact helper response.

    Returns
    -------
    tuple[tuple[FrontendDeclaration, ...], tuple[FrontendCallable, ...], tuple[FrontendCall, ...]]
        Nonfunction declarations, callables with owned calls, and unowned calls.
    """
    declaration_rows = response.get("declarations")
    nonfunction_rows = response.get("non_function_declarations")
    call_rows = response.get("calls")
    raw_calls = call_rows if isinstance(call_rows, list) else []
    calls_by_usr: dict[str, list[FrontendCall]] = {}
    unowned: list[FrontendCall] = []
    for item in raw_calls:
        row = _mapping(item)
        if row is None:
            continue
        callee = _mapping(row.get("callee"))
        target = callee.get("name") if callee is not None else row.get("target_text")
        qualified = callee.get("qualified_name") if callee is not None else None
        caller_usr = row.get("caller_usr")
        call = FrontendCall(
            target=_optional_string(target) or "",
            qualified_target=_optional_string(qualified),
            target_usr=(
                _optional_string(callee.get("usr")) if callee is not None else None
            ),
            caller_usr=_optional_string(caller_usr),
            caller_name=_optional_string(row.get("caller_name")),
            caller_qualified_name=_optional_string(row.get("caller_qualified_name")),
            origin=_provenance(row.get("origin")),
            location=_point(row.get("location")),
            span=_span(row.get("range")),
        )
        if isinstance(caller_usr, str) and caller_usr:
            calls_by_usr.setdefault(caller_usr, []).append(call)
        else:
            unowned.append(call)
    functions = declaration_rows if isinstance(declaration_rows, list) else []
    callables: list[FrontendCallable] = []
    for item in functions:
        row = _mapping(item)
        if row is None:
            continue
        identity = _mapping(row.get("identity")) or {}
        usr = identity.get("usr")
        qualified = row.get("qualified_name")
        qualified_name = qualified if isinstance(qualified, str) else ""
        owner = qualified_name.rpartition("::")[0] or None
        is_definition = row.get("is_definition") is True
        callables.append(
            FrontendCallable(
                usr=usr if isinstance(usr, str) else None,
                kind=cast("str", row.get("decl_kind", "unknown")),
                name=cast("str", row.get("name", "")),
                qualified_name=qualified_name,
                lexical_owner=_optional_string(row.get("lexical_owner")) or owner,
                decl_kind=cast(
                    "str",
                    row.get("native_decl_kind", row.get("decl_kind", "function")),
                ),
                signature=cast("str", row.get("signature", "")),
                function_type=cast("str", row.get("function_type", "")),
                parameters=_arguments(row.get("parameters")),
                has_prototype=row.get("has_prototype") is True,
                is_definition=is_definition,
                is_public=_optional_bool(row.get("is_public")),
                provenance=_declaration_provenance(identity),
                location=_point(row.get("location")),
                span=_span(row.get("range")),
                calls=(
                    tuple(calls_by_usr.pop(usr, ()))
                    if is_definition and isinstance(usr, str)
                    else ()
                ),
                returns_value=row.get("returns_value") is True,
                is_variadic=row.get("is_variadic") is True,
                owner_usr=_optional_string(row.get("owner_usr")),
                owner_location=_point(row.get("owner_location")),
                documentation=_optional_string(row.get("documentation")),
                documentation_location=_point(row.get("documentation_location")),
                documentation_span=_span(row.get("documentation_range")),
                instantiated_from_usr=_optional_string(
                    identity.get("instantiated_from")
                ),
                qualifiers=_callable_qualifiers(row.get("method_qualifiers")),
                has_body=_optional_bool(row.get("has_body")),
                linker_symbol=_optional_string(row.get("linker_symbol")),
                linkage_kind=cast("str", row.get("linkage_kind", "unknown")),
                signature_kind=_optional_string(row.get("signature_kind")),
                explicit_linkage_label=_optional_string(
                    row.get("explicit_linkage_label")
                ),
                linkage_label_inherited=_optional_bool(
                    row.get("linkage_label_inherited")
                ),
                alias_target_symbol=_optional_string(row.get("alias_target_symbol")),
                alias_target_usr=_optional_string(row.get("alias_target_usr")),
                alias_binding_status=cast(
                    "Literal['not_alias', 'resolved', 'unresolved', 'ambiguous']",
                    row.get("alias_binding_status", "not_alias"),
                ),
            )
        )
    declarations: list[FrontendDeclaration] = []
    rows = nonfunction_rows if isinstance(nonfunction_rows, list) else []
    for item in rows:
        row = _mapping(item)
        if row is None:
            continue
        identity = _mapping(row.get("identity")) or {}
        type_value = row.get("type")
        declarations.append(
            FrontendDeclaration(
                usr=_optional_string(identity.get("usr")),
                kind=cast("str", row.get("entity_kind", "declaration")),
                name=cast("str", row.get("name", "")),
                qualified_name=cast("str", row.get("qualified_name", "")),
                decl_kind=cast("str", row.get("decl_kind", "declaration")),
                signature=None,
                type_text=type_value
                if isinstance(type_value, str) and type_value
                else None,
                parameters=(),
                has_prototype=None,
                is_definition=_optional_bool(row.get("is_definition")),
                provenance=_declaration_provenance(identity),
                location=_point(row.get("location")),
                span=_span(row.get("range")),
                owner_usr=_optional_string(row.get("owner_usr")),
                owner_name=_optional_string(row.get("owner_name")),
                owner_location=_point(row.get("owner_location")),
                owner_kind=_optional_string(row.get("owner_kind")),
                access=(
                    cast("Literal['public', 'protected', 'private']", row["access"])
                    if row.get("access") in {"public", "protected", "private"}
                    else None
                ),
                source_text=_optional_string(row.get("source_text")),
                documentation=_optional_string(row.get("documentation")),
                documentation_location=_point(row.get("documentation_location")),
                documentation_span=_span(row.get("documentation_range")),
                enum_ordinal=(
                    cast("int", row.get("enum_ordinal"))
                    if isinstance(row.get("enum_ordinal"), int)
                    and not isinstance(row.get("enum_ordinal"), bool)
                    else None
                ),
                is_file_scope=row.get("is_file_scope") is True,
            )
        )
    for remaining in calls_by_usr.values():
        unowned.extend(remaining)
    return tuple(declarations), tuple(callables), tuple(unowned)


class ClangFrontend:
    """Run the prebuilt helper and retain reproducible per-attempt evidence.

    Parameters
    ----------
    helper_path : pathlib.Path
        Explicitly built LibTooling helper executable.
    build_receipt_path : pathlib.Path
        Receipt produced by the explicit native build step.
    package_version : str
        Installed shared frontend package version.
    cache_dir : pathlib.Path or None, optional
        Optional root for caller-managed result-cache metadata.

    Notes
    -----
    Construction and analysis never search ``PATH`` or build native code.

    Returns
    -------
    None
        Configured helper executor.
    """

    def __init__(
        self,
        helper_path: Path,
        build_receipt_path: Path,
        *,
        package_version: str,
        cache_dir: Path | None = None,
    ) -> None:
        """Bind explicit helper and build receipt paths.

        Parameters
        ----------
        helper_path : pathlib.Path
            Explicitly built native helper executable.
        build_receipt_path : pathlib.Path
            Immutable receipt from the helper build.
        package_version : str
            Installed optional frontend package version.
        cache_dir : pathlib.Path or None, optional
            Optional caller-managed result-cache root.

        Returns
        -------
        None
            Executor initialized with the supplied package and toolchain paths.
        """
        self.helper_path = helper_path.resolve()
        self.build_receipt_path = build_receipt_path.resolve()
        self.package_version = package_version
        self.cache_dir = cache_dir

    def toolchain_fingerprint(self, profile: CompileProfile) -> str:
        """Compute freshness identity without invoking Clang or the helper.

        Parameters
        ----------
        profile : codira_clang_frontend.contracts.CompileProfile
            Exact profile whose source and dependencies must remain unchanged.

        Returns
        -------
        str
            SHA-256 fingerprint covering the profile, toolchain receipt, and
            package version.

        Raises
        ------
        OSError
            If profile, dependency, or toolchain identity files are unreadable.
        ValueError
            If a declared source or dependency digest no longer matches.

        Notes
        -----
        This function hashes captured dependency bytes and does not re-run the
        frontend. Callers can use it from ``analysis_input_fingerprint``.
        """
        source_digest = _sha256(profile.source_path)
        if source_digest != profile.source_sha256:
            raise ValueError("compile profile source digest changed")
        if profile.evidence_path is not None and profile.evidence_sha256 is not None:
            if _sha256(profile.evidence_path) != profile.evidence_sha256:
                raise ValueError("captured compile profile evidence changed")
        dependency_identities = []
        for dependency in sorted(profile.dependencies, key=lambda item: str(item.path)):
            observed = _sha256(dependency.path)
            if observed != dependency.sha256:
                raise ValueError(f"profile dependency changed: {dependency.path}")
            dependency_identities.append(
                {"path": str(dependency.path.resolve()), "sha256": observed}
            )
        directory_identities = []
        for directory in profile.include_directories:
            observed = directory_membership_sha256(directory.path)
            if observed != directory.membership_sha256:
                raise ValueError(f"include search directory changed: {directory.path}")
            directory_identities.append(
                {
                    "path": str(directory.path.resolve()),
                    "membership_sha256": observed,
                    "order": directory.order,
                    "kind": directory.kind,
                }
            )
        toolchain = self._load_toolchain_identity()
        return _hash_json(
            {
                "profile_identity": profile.identity,
                "source_sha256": source_digest,
                "dependencies": dependency_identities,
                "include_directories": directory_identities,
                "include_search_complete": profile.include_search_complete,
                "environment": profile.environment,
                "environment_mode": profile.environment_mode,
                "compilation_context": _context_record(profile.compilation_context),
                "toolchain": {
                    "compiler_sha256": toolchain.compiler_sha256,
                    "compiler_version": toolchain.compiler_version,
                    "resource_dir": str(toolchain.resource_dir),
                    "resource_probe_sha256": toolchain.resource_probe_sha256,
                    "helper_sha256": toolchain.helper_sha256,
                    "helper_source_sha256": toolchain.helper_source_sha256,
                    "build_receipt_sha256": toolchain.build_receipt_sha256,
                },
                "package_version": self.package_version,
            }
        )

    def analyze(
        self,
        profile: CompileProfile,
        *,
        attempt_dir: Path,
        attempt_id: str | None = None,
        allow_unbound_context: bool = False,
        header_projection: HeaderProjectionRequest | None = None,
    ) -> FrontendResult:
        """Run one isolated Clang translation unit with immutable raw evidence.

        Parameters
        ----------
        profile : codira_clang_frontend.contracts.CompileProfile
            Exact source and compile profile.
        attempt_dir : pathlib.Path
            Durable, unique directory for stdout and stderr evidence.
        attempt_id : str or None, optional
            Stable caller identity; a UUID is used when omitted.
        allow_unbound_context : bool, optional
            Permit an unbound profile only for explicit preparation, which
            captures the native context and writes a new immutable profile.
        header_projection : HeaderProjectionRequest or None, optional
            Header projection request resolved from captured owner dependencies.

        Returns
        -------
        codira_clang_frontend.contracts.FrontendResult
            Typed Clang entities, diagnostics, coverage, and provenance.

        Raises
        ------
        FileExistsError
            If the attempt identity has already been used.
        OSError
            If durable evidence cannot be written or required files are unreadable.

        Notes
        -----
        No fallback is run here. Callers must choose Tree-sitter explicitly when
        the result is held or failed, and preserve that status in analysis data.
        """
        if header_projection is not None and (
            header_projection.owner_profile.identity != profile.identity
            or header_projection.owner_profile.source_path.resolve()
            != profile.source_path.resolve()
        ):
            raise ValueError("header projection owner profile does not match analysis")
        selected_id = attempt_id or uuid.uuid4().hex
        if not selected_id or any(
            char
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in selected_id
        ):
            raise ValueError("attempt_id must contain only letters, digits, '-' or '_'")
        directory = attempt_dir.resolve()
        overlap = _attempt_directory_overlap(directory, profile)
        if overlap is not None:
            try:
                fingerprint = self.toolchain_fingerprint(profile)
            except (OSError, ValueError, json.JSONDecodeError):
                fingerprint = _hash_json(
                    {"profile": profile.identity, "attempt_root_overlap": str(overlap)}
                )
            return self._held(
                profile,
                fingerprint,
                f"attempt_directory_overlaps_include_root:{overlap}",
                stdout_path=None,
                stderr_path=None,
            )
        directory.mkdir(parents=True, exist_ok=True)
        self._reserve_attempt(directory / f"{selected_id}.attempt.json", profile)
        stdout_path = directory / f"{selected_id}.stdout"
        stderr_path = directory / f"{selected_id}.stderr"
        try:
            input_fingerprint = self.toolchain_fingerprint(profile)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return self._held(
                profile,
                _hash_json(
                    {
                        "profile": profile.identity,
                        "package_version": self.package_version,
                        "toolchain_error": type(error).__name__,
                    }
                ),
                f"toolchain_identity_invalid:{type(error).__name__}",
                stdout_path=None,
                stderr_path=None,
            )
        source_digest_before = _sha256(profile.source_path)
        if (
            header_projection is not None
            and _sha256(header_projection.requested_header_path)
            != header_projection.requested_header_sha256
        ):
            return self._held(
                profile,
                input_fingerprint,
                "requested_header_changed_before_frontend",
                stdout_path=None,
                stderr_path=None,
            )
        try:
            toolchain = self._load_toolchain_identity()
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return self._held(
                profile,
                input_fingerprint,
                f"toolchain_identity_invalid:{type(error).__name__}",
                stdout_path=None,
                stderr_path=None,
            )
        if profile.environment_mode == "captured_allowlisted":
            process_environment = {
                "PATH": str(toolchain.compiler_path.parent),
                "LANG": "C",
                "LC_ALL": "C",
                **dict(profile.environment),
            }
        else:
            process_environment = {
                "PATH": str(toolchain.compiler_path.parent),
                "LANG": "C",
                "LC_ALL": "C",
            }
        adapted, unsupported, transformations = _adapt_arguments(
            profile.argv,
            profile.source_path,
            profile.working_directory,
            toolchain.resource_dir,
        )
        if unsupported:
            return self._held(
                profile,
                input_fingerprint,
                "unsupported_compile_arguments",
                stdout_path=None,
                stderr_path=None,
                toolchain=toolchain,
            )
        request: dict[str, object] = {
            "file": str(profile.source_path),
            "directory": str(profile.working_directory),
            "repository_root": str(profile.repository_root),
            "language": profile.language,
            "capture_mode": "source_relevant",
            "argv": adapted,
        }
        if header_projection is not None:
            request["projection_file"] = str(header_projection.requested_header_path)
            input_fingerprint = _hash_json(
                {
                    "profile_fingerprint": input_fingerprint,
                    "header_projection_identity": header_projection.identity,
                }
            )
        result = subprocess.run(
            [str(self.helper_path)],
            input=json.dumps(request, separators=(",", ":")).encode("utf-8"),
            cwd=profile.working_directory,
            env=process_environment,
            capture_output=True,
            check=False,
            shell=False,
        )
        stdout = result.stdout if isinstance(result.stdout, bytes) else b""
        stderr = result.stderr if isinstance(result.stderr, bytes) else b""
        self._write_new(stdout_path, stdout)
        self._write_new(stderr_path, stderr)
        stdout_digest = hashlib.sha256(stdout).hexdigest()
        stderr_digest = hashlib.sha256(stderr).hexdigest()
        if _sha256(profile.source_path) != source_digest_before:
            return self._held(
                profile,
                input_fingerprint,
                "source_changed_during_frontend",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
            )
        if (
            header_projection is not None
            and _sha256(header_projection.requested_header_path)
            != header_projection.requested_header_sha256
        ):
            return self._held(
                profile,
                input_fingerprint,
                "requested_header_changed_during_frontend",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        if result.returncode != 0:
            return self._held(
                profile,
                input_fingerprint,
                "libtooling_helper_failed",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        try:
            payload = json.loads(stdout)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._held(
                profile,
                input_fingerprint,
                "invalid_libtooling_json",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        response = _mapping(payload)
        if response is None:
            return self._held(
                profile,
                input_fingerprint,
                "invalid_libtooling_json_shape",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        protocol_error = _validate_response(response)
        if protocol_error is not None:
            return self._held(
                profile,
                input_fingerprint,
                protocol_error,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        if header_projection is not None:
            if response.get("schema_version") not in {
                "codira.clang-frontend-native/4",
                "codira.clang-frontend-native/5",
            }:
                return self._held(
                    profile,
                    input_fingerprint,
                    "header_projection_requires_native_protocol_v4",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    stdout_sha=stdout_digest,
                    stderr_sha=stderr_digest,
                    toolchain=toolchain,
                    failed=True,
                )
            capture_projection = _mapping(response.get("capture_projection"))
            if (
                not _same_path(
                    response.get("translation_unit_file"), profile.source_path
                )
                or not _same_path(
                    response.get("projection_file"),
                    header_projection.requested_header_path,
                )
                or (
                    capture_projection is None
                    or capture_projection.get("mode") != "header_projection"
                    or not _same_path(
                        capture_projection.get("translation_unit_file"),
                        profile.source_path,
                    )
                    or not _same_path(
                        capture_projection.get("requested_header_file"),
                        header_projection.requested_header_path,
                    )
                )
            ):
                return self._held(
                    profile,
                    input_fingerprint,
                    "header_projection_protocol_paths_mismatch",
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    stdout_sha=stdout_digest,
                    stderr_sha=stderr_digest,
                    toolchain=toolchain,
                    failed=True,
                )
        tool_return_code = cast("int", response["tool_return_code"])
        if tool_return_code != 0:
            return self._held(
                profile,
                input_fingerprint,
                f"clang_tool_return_code:{tool_return_code}",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                failed=True,
            )
        compilation_context = _decode_compilation_context(
            response, profile.working_directory
        )
        if profile.compilation_context is None and not allow_unbound_context:
            return self._held(
                profile,
                input_fingerprint,
                "compile_profile_context_unbound",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                compilation_context=compilation_context,
            )
        if (
            profile.compilation_context is not None
            and profile.compilation_context != compilation_context
        ):
            return self._held(
                profile,
                input_fingerprint,
                "clang_compilation_context_changed",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                stdout_sha=stdout_digest,
                stderr_sha=stderr_digest,
                toolchain=toolchain,
                compilation_context=compilation_context,
            )
        declarations, callables, unowned_calls = _decode_entities(response)
        includes = _decode_includes(response.get("includes"))
        preprocessing = _decode_preprocessing(response.get("preprocessing"))
        documentation_comments = _decode_documentation_comments(
            response.get("documentation_comments")
        )
        diagnostics = _diagnostics(response.get("diagnostics"))
        dependency_closure = _dependency_closure(
            response,
            profile.source_path,
            profile.working_directory,
        )
        reasons: list[str] = []
        if profile.status != "complete":
            reasons.append("partial_compile_profile")
        if any(item.severity.lower() in {"error", "fatal"} for item in diagnostics):
            reasons.append("clang_frontend_reported_errors")
        if dependency_closure.status != "complete":
            reasons.append("dependency_closure_incomplete")
        status: FrontendStatus = "diagnostics" if reasons else "parsed"
        coverage: CoverageState = (
            "complete" if profile.status == "complete" and not reasons else "partial"
        )
        cache_fingerprint = _hash_json(
            {
                "pre_run": input_fingerprint,
                "dependencies": [
                    {"path": str(item.path), "sha256": item.sha256}
                    for item in dependency_closure.files
                ],
                "dependency_closure_sha256": dependency_closure.sha256,
                "package_version": self.package_version,
                "compilation_context": _context_record(compilation_context),
                "header_projection_identity": (
                    header_projection.identity if header_projection else None
                ),
            }
        )
        return FrontendResult(
            status=status,
            coverage_state=coverage,
            reasons=tuple(reasons),
            diagnostics=diagnostics,
            declarations=declarations,
            callables=callables,
            dependency_closure=dependency_closure,
            profile_identity=profile.identity,
            toolchain_identity=toolchain,
            cache_fingerprint=cache_fingerprint,
            stdout_path=stdout_path,
            stdout_sha256=stdout_digest,
            stderr_path=stderr_path,
            stderr_sha256=stderr_digest,
            unowned_calls=unowned_calls,
            adapted_argv=tuple(adapted),
            argument_transformations=tuple(transformations),
            environment_mode=profile.environment_mode,
            compilation_context=compilation_context,
            includes=includes,
            preprocessing=preprocessing,
            documentation_comments=documentation_comments,
            requested_source_path=(
                header_projection.requested_header_path
                if header_projection is not None
                else profile.source_path
            ),
            requested_source_sha256=(
                header_projection.requested_header_sha256
                if header_projection is not None
                else source_digest_before
            ),
            translation_unit_path=profile.source_path,
            header_projection_identity=(
                header_projection.identity if header_projection is not None else None
            ),
        )

    def analyze_header(
        self,
        request: HeaderProjectionRequest,
        *,
        attempt_dir: Path,
        attempt_id: str | None = None,
    ) -> FrontendResult:
        """Project one header with its captured owning translation unit.

        Parameters
        ----------
        request : HeaderProjectionRequest
            Resolved requested header and its captured owner profile.
        attempt_dir : pathlib.Path
            Durable directory for immutable raw helper output.
        attempt_id : str or None, optional
            Stable caller-selected attempt identity.

        Returns
        -------
        FrontendResult
            Header-scoped frontend output with separate physical source paths.
        """
        result = self.analyze(
            request.owner_profile,
            attempt_dir=attempt_dir,
            attempt_id=attempt_id,
            header_projection=request,
        )
        return replace(
            result,
            requested_source_path=request.requested_header_path,
            requested_source_sha256=request.requested_header_sha256,
            translation_unit_path=request.owner_profile.source_path,
            header_projection_identity=request.identity,
        )

    def prepare_profile(
        self,
        profile: CompileProfile,
        *,
        attempt_dir: Path,
        profile_output_path: Path,
        attempt_id: str | None = None,
    ) -> tuple[FrontendResult, CompileProfile]:
        """Capture a reusable dependency manifest before normal indexing.

        Parameters
        ----------
        profile : codira_clang_frontend.contracts.CompileProfile
            Exact source and command profile, commonly loaded from a compile DB.
        attempt_dir : pathlib.Path
            Durable directory for immutable helper stdout and stderr.
        profile_output_path : pathlib.Path
            New immutable generic profile manifest path.
        attempt_id : str or None, optional
            Stable caller attempt identity.

        Returns
        -------
        tuple[FrontendResult, CompileProfile]
            Preparation result and reloaded complete profile for indexing.

        Raises
        ------
        ValueError
            If Clang did not produce a complete dependency closure or the input
            profile evidence cannot be rebound.
        FileExistsError
            If either attempt or output profile identity already exists.
        OSError
            If native evidence cannot be retained.

        Notes
        -----
        This explicit command may run Clang and should be checkpointed. Normal
        `toolchain_fingerprint` calls never invoke the helper or alter profiles.
        A complete prepared profile means its command and dependency inputs are
        bound; it does not mean its source entities are semantically correct.
        """
        result = self.analyze(
            profile,
            attempt_dir=attempt_dir,
            attempt_id=attempt_id,
            allow_unbound_context=True,
        )
        closure = result.dependency_closure
        if (
            closure is None
            or closure.status != "complete"
            or not closure.search_directories_complete
        ):
            raise ValueError(
                "helper did not produce complete dependencies and effective search roots"
            )
        if result.compilation_context is None:
            raise ValueError("helper did not produce native compilation context")
        prepared = write_prepared_profile(
            profile,
            closure.files,
            closure.search_directories,
            profile.environment,
            profile.environment_mode,
            result.compilation_context,
            profile_output_path,
        )
        return result, prepared

    def _load_toolchain_identity(self) -> ToolchainIdentity:
        """Validate helper build receipt and return content-bound identities.

        Parameters
        ----------
        None

        Returns
        -------
        codira_clang_frontend.contracts.ToolchainIdentity
            Validated compiler, resource directory, helper, and receipt identity.

        Raises
        ------
        ValueError
            If receipt paths or hashes differ from current artifacts.
        OSError
            If a required toolchain file cannot be read.
        """
        receipt = json.loads(self.build_receipt_path.read_text(encoding="utf-8"))
        row = _mapping(receipt)
        if row is None:
            raise ValueError("build receipt must be a JSON object")
        compiler = _path_field(row, "compiler_path")
        helper = _path_field(row, "helper_path")
        resource_dir = _path_field(row, "resource_dir")
        resource_probe = _path_field(row, "resource_probe")
        compiler_digest = _string_field(row, "compiler_sha256")
        helper_digest = _string_field(row, "helper_sha256")
        source_digest = _string_field(row, "source_sha256")
        probe_digest = _string_field(row, "resource_probe_sha256")
        version = _string_field(row, "compiler_version")
        source_file = Path(__file__).resolve().parent / "native" / "clang_frontend.cpp"
        if compiler_digest != _sha256(compiler) or helper_digest != _sha256(helper):
            raise ValueError("compiler or helper binary digest changed")
        if source_digest != _sha256(source_file):
            raise ValueError("native helper source digest differs from build receipt")
        if resource_probe_digest(probe_digest, resource_probe) != probe_digest:
            raise ValueError("Clang resource probe digest changed")
        if not resource_probe.resolve().is_relative_to(resource_dir.resolve()):
            raise ValueError("Clang resource probe is outside its recorded directory")
        if (
            helper.resolve() != self.helper_path
            or _sha256(self.helper_path) != helper_digest
        ):
            raise ValueError("configured helper differs from build receipt")
        if self.build_receipt_path.resolve() != self.build_receipt_path:
            raise ValueError("build receipt path is not canonical")
        return ToolchainIdentity(
            compiler,
            compiler_digest,
            version,
            resource_dir,
            probe_digest,
            helper,
            helper_digest,
            source_digest,
            self.build_receipt_path,
            _sha256(self.build_receipt_path),
            self.package_version,
            "not_hashed",
        )

    def _held(
        self,
        profile: CompileProfile,
        fingerprint: str,
        reason: str,
        *,
        stdout_path: Path | None,
        stderr_path: Path | None,
        stdout_sha: str | None = None,
        stderr_sha: str | None = None,
        toolchain: ToolchainIdentity | None = None,
        failed: bool = False,
        compilation_context: CompilationContext | None = None,
    ) -> FrontendResult:
        """Return an explicit non-success result without a fallback claim.

        Parameters
        ----------
        profile : codira_clang_frontend.contracts.CompileProfile
            Selected exact profile.
        fingerprint : str
            Current profile and toolchain identity.
        reason : str
            Stable held or failure cause.
        stdout_path, stderr_path : pathlib.Path or None
            Durable raw evidence paths, when helper execution occurred.
        stdout_sha, stderr_sha : str or None, optional
            Digests for retained raw evidence.
        toolchain : codira_clang_frontend.contracts.ToolchainIdentity or None, optional
            Validated toolchain identity when available.
        failed : bool, optional
            Whether the native helper or protocol failed.

        Returns
        -------
        codira_clang_frontend.contracts.FrontendResult
            Held or failed status with empty entity tuples.
        """
        return FrontendResult(
            status="failed" if failed else "held",
            coverage_state="partial",
            reasons=(reason,),
            diagnostics=(),
            declarations=(),
            callables=(),
            dependency_closure=None,
            profile_identity=profile.identity,
            toolchain_identity=toolchain,
            cache_fingerprint=fingerprint,
            stdout_path=stdout_path,
            stdout_sha256=stdout_sha,
            stderr_path=stderr_path,
            stderr_sha256=stderr_sha,
            compilation_context=compilation_context,
        )

    @staticmethod
    def _reserve_attempt(path: Path, profile: CompileProfile) -> None:
        """Claim a unique attempt identity before any native process starts.

        Parameters
        ----------
        path : pathlib.Path
            New immutable identity claim path.
        profile : codira_clang_frontend.contracts.CompileProfile
            Source-bound compiler profile for the attempt.

        Returns
        -------
        None

        Raises
        ------
        FileExistsError
            If the attempt identity has already been reserved.
        OSError
            If the identity claim cannot be persisted.
        """
        payload = json.dumps(
            {
                "schema_version": "codira.clang-frontend-attempt/1",
                "profile_identity": profile.identity,
                "source_path": str(profile.source_path),
                "source_sha256": profile.source_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _write_new(path: Path, data: bytes) -> None:
        """Create one immutable raw-evidence file.

        Parameters
        ----------
        path : pathlib.Path
            New durable evidence path.
        data : bytes
            Exact captured standard stream bytes.

        Returns
        -------
        None

        Raises
        ------
        FileExistsError
            If the attempt path already exists.
        OSError
            If the evidence cannot be persisted.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def profile_toolchain_fingerprint(
    frontend: ClangFrontend, profile: CompileProfile
) -> str:
    """Compute the frontend input fingerprint without running native code.

    Parameters
    ----------
    frontend : codira_clang_frontend.frontend.ClangFrontend
        Configured optional frontend and verified toolchain receipt.
    profile : codira_clang_frontend.contracts.CompileProfile
        Exact source, command, dependency, include-root, and environment identity.

    Returns
    -------
    str
        Stable SHA-256 fingerprint for index reuse validation.

    Raises
    ------
    OSError
        If source, dependency, include-root, or toolchain files are unreadable.
    ValueError
        If any content identity differs from the captured profile.

    Notes
    -----
    Both indexer pre-analysis and post-analysis checks must return the same
    value. This helper never mutates the profile or learns helper output.
    """
    return frontend.toolchain_fingerprint(profile)


def captured_profile_fingerprint(
    profile_json_path: Path,
    source_path: Path,
    source_sha256: str,
    frontend: ClangFrontend | None = None,
    *,
    helper_path: Path | None = None,
    build_receipt_path: Path | None = None,
) -> str:
    """Fingerprint observed inputs even when strict profile loading is stale.

    Parameters
    ----------
    profile_json_path : pathlib.Path
        Generic captured profile manifest whose selected record may be stale.
    source_path : pathlib.Path
        Translation unit selected by exact path and captured source digest.
    source_sha256 : str
        Expected translation unit SHA-256 used to select one manifest row.
    frontend : ClangFrontend or None
        Configured frontend, if profile construction succeeded.
    helper_path, build_receipt_path : pathlib.Path or None, optional
        Explicit helper and receipt paths for the stale-profile exception path,
        where no frontend instance could be returned by the profile factory.

    Returns
    -------
    str
        SHA-256 input identity including current dependency, search-root, and
        compiler artifacts. Missing or unreadable inputs receive stable error
        markers, so replacing or repairing them changes the identity.

    Raises
    ------
    ValueError
        If ``frontend`` is ``None`` and either ``helper_path`` or
        ``build_receipt_path`` is missing.

    Notes
    -----
    This is the fallback for index freshness when strict profile loading rejects
    changed evidence. It never executes Clang and does not convert stale
    evidence into a complete profile.
    """
    if frontend is None:
        if helper_path is None or build_receipt_path is None:
            raise ValueError(
                "supply a frontend or explicit helper_path and build_receipt_path"
            )
        try:
            package_version = version("codira-clang-frontend")
        except PackageNotFoundError:
            package_version = "0.1.0"
        frontend = ClangFrontend(
            helper_path,
            build_receipt_path,
            package_version=package_version,
        )
    manifest_bytes: bytes | None
    try:
        manifest_bytes = profile_json_path.read_bytes()
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        document = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as error:
        return _hash_json(
            {
                "manifest_path": str(profile_json_path.resolve()),
                "manifest_error": type(error).__name__,
                "manifest_digest": _path_digest(profile_json_path),
                "source_path": str(source_path.resolve()),
                "source_sha256_expected": source_sha256,
                "toolchain": _fallback_toolchain_identity(frontend),
            }
        )
    rows = document.get("profiles") if isinstance(document, dict) else None
    selected: dict[str, object] | None = None
    if isinstance(rows, list):
        source = source_path.resolve()
        for value in rows:
            row = _mapping(value)
            if row is None or not isinstance(row.get("source_path"), str):
                continue
            if (
                Path(cast("str", row["source_path"])).resolve() == source
                and row.get("source_sha256") == source_sha256
            ):
                if selected is not None:
                    selected = None
                    break
                selected = row
    dependencies: list[dict[str, object]] = []
    include_directories: list[dict[str, object]] = []
    profile_error: str | None = None
    if selected is None:
        profile_error = "selected_profile_missing_or_ambiguous"
    else:
        dependency_rows = selected.get("dependencies", [])
        if not isinstance(dependency_rows, list):
            profile_error = "invalid_dependency_rows"
            dependency_rows = []
        for value in dependency_rows:
            row = _mapping(value)
            if row is None or not isinstance(row.get("path"), str):
                dependencies.append({"error": "invalid_dependency_record"})
                continue
            path = Path(cast("str", row["path"]))
            dependencies.append(
                {
                    "path": str(path.resolve()),
                    "expected_sha256": row.get("sha256"),
                    "observed": _path_digest(path),
                }
            )
        directory_rows = selected.get("include_directories", [])
        if not isinstance(directory_rows, list):
            profile_error = profile_error or "invalid_include_directory_rows"
            directory_rows = []
        for value in directory_rows:
            row = _mapping(value)
            if row is None or not isinstance(row.get("path"), str):
                include_directories.append(
                    {"error": "invalid_include_directory_record"}
                )
                continue
            path = Path(cast("str", row["path"]))
            try:
                observed_membership: object = directory_membership_sha256(path)
            except OSError as error:
                observed_membership = {"error": type(error).__name__}
            include_directories.append(
                {
                    "path": str(path.resolve()),
                    "expected_membership_sha256": row.get("membership_sha256"),
                    "observed_membership": observed_membership,
                    "order": row.get("order"),
                    "kind": row.get("kind"),
                }
            )
    return _hash_json(
        {
            "manifest_path": str(profile_json_path.resolve()),
            "manifest_sha256": manifest_digest,
            "profile_error": profile_error,
            "selected_profile": selected,
            "source_path": str(source_path.resolve()),
            "source_sha256_expected": source_sha256,
            "source_observed": _path_digest(source_path),
            "dependencies": dependencies,
            "include_directories": include_directories,
            "toolchain": _fallback_toolchain_identity(frontend),
        }
    )


def _path_digest(path: Path) -> dict[str, str]:
    """Return a stable present/missing/error marker with a file digest.

    Parameters
    ----------
    path : pathlib.Path
        File path whose current content identity is observed.

    Returns
    -------
    dict[str, str]
        Path state, canonical path, and content digest when readable.
    """
    try:
        resolved = path.resolve(strict=True)
        return {"state": "present", "path": str(resolved), "sha256": _sha256(resolved)}
    except OSError as error:
        return {
            "state": type(error).__name__,
            "path": str(path.absolute()),
        }


def _fallback_toolchain_identity(frontend: ClangFrontend) -> dict[str, object]:
    """Observe receipt-named toolchain files without requiring a valid receipt.

    Parameters
    ----------
    frontend : ClangFrontend
        Explicit helper and receipt paths.

    Returns
    -------
    dict[str, object]
        Receipt digest and current identities for its compiler, helper, and
        Clang resource probe where those paths can be read.
    """
    try:
        receipt_bytes = frontend.build_receipt_path.read_bytes()
        receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
        row = _mapping(json.loads(receipt_bytes))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "receipt_path": str(frontend.build_receipt_path),
            "receipt_error": type(error).__name__,
            "receipt_observed": _path_digest(frontend.build_receipt_path),
            "helper_observed": _path_digest(frontend.helper_path),
        }
    identities: dict[str, object] = {
        "receipt_path": str(frontend.build_receipt_path.resolve()),
        "receipt_sha256": receipt_digest,
        "helper_observed": _path_digest(frontend.helper_path),
    }
    if row is None:
        identities["receipt_shape"] = "invalid"
        return identities
    for field in ("compiler_path", "helper_path", "resource_probe"):
        value = row.get(field)
        if isinstance(value, str):
            identities[field] = _path_digest(Path(value))
        else:
            identities[field] = {"state": "missing_receipt_field"}
    identities["package_version"] = frontend.package_version
    return identities


def _string_field(row: dict[str, object], name: str) -> str:
    """Read a required nonempty string from a JSON mapping.

    Parameters
    ----------
    row : dict[str, object]
        JSON object to inspect.
    name : str
        Required field name.

    Returns
    -------
    str
        Nonempty field value.

    Raises
    ------
    ValueError
        If the field is missing or not a nonempty string.
    """
    value = row.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"build receipt requires {name}")
    return value


def _path_field(row: dict[str, object], name: str) -> Path:
    """Read a required absolute path from a JSON mapping.

    Parameters
    ----------
    row : dict[str, object]
        JSON object to inspect.
    name : str
        Required field name.

    Returns
    -------
    pathlib.Path
        Resolved receipt path.

    Raises
    ------
    ValueError
        If the field is missing or relative.
    """
    value = _string_field(row, name)
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"build receipt {name} must be absolute")
    return path.resolve()


def resource_probe_digest(expected: str, path: Path) -> str:
    """Verify and return a resource header digest.

    Parameters
    ----------
    expected : str
        Digest recorded by the native build receipt.
    path : pathlib.Path
        Exact Clang resource header path.

    Returns
    -------
    str
        Observed digest when it matches the receipt, empty otherwise.
    """
    observed = _sha256(path)
    return observed if observed == expected else ""


def _adapt_arguments(
    original: tuple[str, ...], source: Path, directory: Path, resource_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    """Forward ordinary compiler flags using the audited pilot transformations.

    Parameters
    ----------
    original : tuple[str, ...]
        Exact original argv, including driver at index zero.
    source : pathlib.Path
        Translation unit selected by the analyzer.
    directory : pathlib.Path
        Original compile command working directory.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        Adapted Clang argv, denied arguments, and ordered transformation ledger.

    Notes
    -----
    This is deliberately not an allowlist parser. It forwards ordinary options
    so Clang diagnoses unknown compiler flags, and strips only known output or
    link actions from the audited pilot adapter.
    """
    adapted = ["-fsyntax-only"]
    unsupported: list[str] = []
    transformations = ["add -fsyntax-only for LibTooling syntax capture"]
    index = 1
    while index < len(original):
        argument = original[index]
        if argument == "-Xclang" and index + 1 < len(original):
            clang_forwarded_argument = original[index + 1]
            if clang_forwarded_argument == "-ast-dump=json":
                transformations.append(
                    "remove retained -Xclang -ast-dump=json output action"
                )
                index += 2
                continue
        if argument in _DENIED_EXECUTION_FLAGS or argument.startswith(
            (
                *_DENIED_EXECUTION_PREFIXES,
                "@",
                "-specs=",
                "-wrapper=",
                "-B",
                "-Xclang=",
                "-cc1",
                "-load=",
            )
        ):
            unsupported.append(argument)
            index += 1
            continue
        if not argument.startswith("-"):
            candidate = Path(argument)
            resolved = candidate if candidate.is_absolute() else directory / candidate
            if resolved.resolve() != source.resolve():
                unsupported.append(argument)
            index += 1
            continue
        following = original[index + 1] if index + 1 < len(original) else None
        action_consumed = 0
        if argument in _ACTION_FLAGS:
            transformations.append(f"remove non-frontend action {argument}")
            index += 1
            continue
        if argument in _ACTION_FLAGS_WITH_VALUE:
            action_consumed = int(following is not None)
            transformations.append(f"remove non-frontend output action {argument}")
            index += 1 + action_consumed
            continue
        if argument in {"-L", "-l", "-Xlinker", "-Xassembler"}:
            transformations.append(f"remove link-only action {argument}")
            index += 1 + int(following is not None)
            continue
        if (
            argument.startswith(
                (
                    *_ACTION_PREFIXES,
                    "-save-temps",
                    "-ftime-trace",
                    "-fmodule-output=",
                    "-serialize-diagnostics=",
                    "-foptimization-record-file=",
                )
            )
            or argument.startswith(("-Wl,", "-Wa,", "-L", "-l", "-fuse-ld="))
            or argument in {"-shared", "-static", "-pie", "-rdynamic", "-fsyntax-only"}
        ):
            transformations.append(f"remove non-frontend action {argument}")
            index += 1
            continue
        if argument == "-resource-dir" and following is not None:
            if Path(following).resolve() != resource_dir.resolve():
                unsupported.append(argument + " " + following)
            else:
                adapted.extend([argument, following])
                transformations.append("preserve profile resource directory")
            index += 2
            continue
        if argument.startswith("-resource-dir="):
            if Path(argument.partition("=")[2]).resolve() != resource_dir.resolve():
                unsupported.append(argument)
            else:
                adapted.append(argument)
                transformations.append("preserve profile resource directory")
            index += 1
            continue
        if argument == "-fdiagnostics-color":
            adapted.append("-fcolor-diagnostics")
            transformations.append("translate -fdiagnostics-color to Clang spelling")
            index += 1
            continue
        adapted.append(
            "-fcolor-diagnostics" if argument == "-fdiagnostics-color" else argument
        )
        if argument in _VALUE_FLAGS and following is not None:
            adapted.append(following)
            index += 2
        else:
            index += 1
    if not unsupported and not any(
        arg == "-resource-dir" or arg.startswith("-resource-dir=") for arg in adapted
    ):
        adapted.extend(["-resource-dir", str(resource_dir)])
        transformations.append("add receipt-bound Clang resource directory")
    return adapted, unsupported, transformations


def _decode_documentation_comments(
    value: object,
) -> tuple[FrontendDocumentationComment, ...]:
    """Decode Doxygen comments and their original source coordinates.

    Parameters
    ----------
    value : object
        Native helper documentation-comment array.

    Returns
    -------
    tuple[codira_clang_frontend.contracts.FrontendDocumentationComment, ...]
        Source-ordered Doxygen comment records.
    """
    if not isinstance(value, list):
        return ()
    comments: list[FrontendDocumentationComment] = []
    for item in value:
        row = _mapping(item)
        if row is None:
            continue
        comments.append(
            FrontendDocumentationComment(
                text=cast("str", row.get("text", "")),
                location=_point(row.get("location")),
                span=_span(row.get("range")),
            )
        )
    return tuple(comments)


def _decode_includes(value: object) -> tuple[FrontendInclude, ...]:
    """Decode include events without normalizing compiler path evidence.

    Parameters
    ----------
    value : object
        Native helper include array.

    Returns
    -------
    tuple[codira_clang_frontend.contracts.FrontendInclude, ...]
        Source-ordered include records.
    """
    if not isinstance(value, list):
        return ()
    includes: list[FrontendInclude] = []
    for item in value:
        row = _mapping(item)
        if row is None:
            continue
        includes.append(
            FrontendInclude(
                spelled_path=cast("str", row.get("spelled_path", "")),
                resolved_path=_optional_string(row.get("resolved_path")),
                angled=row.get("angled") is True,
                search_path=cast("str", row.get("search_path", "")),
                relative_path=cast("str", row.get("relative_path", "")),
                module_imported=row.get("module_imported") is True,
                location=_point(row.get("location")),
            )
        )
    return tuple(includes)


def _decode_preprocessing(value: object) -> tuple[FrontendPreprocessorEvent, ...]:
    """Decode captured macro and conditional events from Clang callbacks.

    Parameters
    ----------
    value : object
        Native helper preprocessing array.

    Returns
    -------
    tuple[codira_clang_frontend.contracts.FrontendPreprocessorEvent, ...]
        Ordered typed preprocessor events.
    """
    if not isinstance(value, list):
        return ()
    events: list[FrontendPreprocessorEvent] = []
    for item in value:
        row = _mapping(item)
        if row is None:
            continue
        replacement = row.get("replacement")
        tokens = (
            tuple(token for token in replacement if isinstance(token, str))
            if isinstance(replacement, list)
            else ()
        )
        kind = cast("PreprocessorEventKind", row.get("kind", "endif"))
        result = row.get("result")
        events.append(
            FrontendPreprocessorEvent(
                kind=kind,
                name=_optional_string(row.get("name")),
                replacement=tokens,
                replacement_truncated=row.get("replacement_truncated") is True,
                function_like=_optional_bool(row.get("function_like")),
                parameters=tuple(
                    name
                    for name in cast("list[object]", row.get("parameters", []))
                    if isinstance(name, str)
                ),
                source_text=_optional_string(row.get("source_text")),
                condition=_optional_string(row.get("condition")),
                result=(
                    cast("Literal['true', 'false', 'not_evaluated', 'unknown']", result)
                    if isinstance(result, str)
                    else None
                ),
                macro_defined=_optional_bool(row.get("macro_defined")),
                invocation=_optional_string(row.get("invocation")),
                location=_point(row.get("location")),
                span=_span(row.get("range")),
            )
        )
    return tuple(events)


def _diagnostics(value: object) -> tuple[FrontendDiagnostic, ...]:
    """Decode diagnostic severity, message, and source location.

    Parameters
    ----------
    value : object
        Native helper diagnostic array.

    Returns
    -------
    tuple[codira_clang_frontend.contracts.FrontendDiagnostic, ...]
        Ordered typed diagnostics.
    """
    if not isinstance(value, list):
        return ()
    diagnostics: list[FrontendDiagnostic] = []
    for item in value:
        row = _mapping(item)
        if row is None:
            continue
        diagnostics.append(
            FrontendDiagnostic(
                cast("str", row.get("severity", "unknown")),
                cast("str", row.get("message", "")),
                _position(row.get("location")),
            )
        )
    return tuple(diagnostics)


def _dependency_closure(
    value: object,
    source_path: Path,
    working_directory: Path,
) -> DependencyClosure:
    """Hash compiler-observed dependencies and actual Clang search roots.

    Parameters
    ----------
    value : object
        Decoded native helper response.
    source_path : pathlib.Path
        Translation unit whose bytes must be part of the closure.
    working_directory : pathlib.Path
        Captured command directory used to resolve relative HeaderSearch names.

    Returns
    -------
    codira_clang_frontend.contracts.DependencyClosure
        Sorted content identities, search-root memberships, and closure digest.
    """
    response = _mapping(value) or {}
    paths = response.get("dependency_paths")
    files: list[DependencyInput] = []
    complete = isinstance(paths, list)
    if isinstance(paths, list):
        for item in paths:
            if not isinstance(item, str):
                complete = False
                continue
            path = Path(item)
            if not path.is_absolute():
                path = working_directory / path
            if not path.is_file():
                complete = False
                continue
            path = path.resolve()
            files.append(DependencyInput(path, _sha256(path)))
    source = source_path.resolve()
    if source.is_file() and all(item.path != source for item in files):
        files.append(DependencyInput(source, _sha256(source)))
    elif not source.is_file():
        complete = False
    files.sort(key=lambda item: str(item.path))
    payload = [{"path": str(item.path), "sha256": item.sha256} for item in files]
    search_value = response.get("search_directories")
    search_directories: list[IncludeDirectoryInput] = []
    search_complete = isinstance(search_value, list)
    if isinstance(search_value, list):
        for item in search_value:
            row = _mapping(item)
            if row is None or not isinstance(row.get("path"), str):
                search_complete = False
                continue
            path = Path(cast("str", row["path"]))
            if not path.is_absolute():
                path = working_directory / path
            path = path.resolve()
            try:
                membership = directory_membership_sha256(path)
            except OSError:
                search_complete = False
                continue
            if row.get("is_header_map") is True:
                kind: Literal[
                    "directory", "framework", "header_map", "quoted_include_parent"
                ] = "header_map"
            elif row.get("is_framework") is True:
                kind = "framework"
            else:
                kind = "directory"
            order = row.get("order")
            search_directories.append(
                IncludeDirectoryInput(
                    path, membership, order if isinstance(order, int) else 0, kind
                )
            )
    else:
        search_complete = False
    covered_directories = {item.path.resolve() for item in search_directories}
    next_order = max((item.order for item in search_directories), default=-1) + 1
    for dependency in files:
        quote_parent = dependency.path.parent.resolve()
        if quote_parent in covered_directories or any(
            _is_within(quote_parent, root) for root in covered_directories
        ):
            continue
        try:
            membership = directory_membership_sha256(quote_parent)
        except OSError:
            search_complete = False
            continue
        search_directories.append(
            IncludeDirectoryInput(
                quote_parent,
                membership,
                next_order,
                "quoted_include_parent",
            )
        )
        covered_directories.add(quote_parent)
        next_order += 1
    search_directories.sort(key=lambda item: item.order)
    digest = _hash_json(
        {
            "dependencies": payload,
            "search_directories": [
                {
                    "path": str(item.path),
                    "membership_sha256": item.membership_sha256,
                    "order": item.order,
                    "kind": item.kind,
                }
                for item in search_directories
            ],
        }
    )
    state: CoverageState = "complete" if complete and search_complete else "partial"
    return DependencyClosure(
        state,
        tuple(files),
        digest,
        tuple(search_directories),
        search_complete,
    )


def _is_within(path: Path, root: Path) -> bool:
    """Check whether a resolved path is equal to or beneath a root.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path to test.
    root : pathlib.Path
        Potential containing root.

    Returns
    -------
    bool
        ``True`` when ``path`` is equal to or beneath ``root``.
    """
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _attempt_directory_overlap(directory: Path, profile: CompileProfile) -> Path | None:
    """Find whether mutable attempt output would alter a bound input root.

    Parameters
    ----------
    directory : pathlib.Path
        Durable attempt directory requested for one analysis.
    profile : CompileProfile
        Bound source, dependency, and include-root profile.

    Returns
    -------
    pathlib.Path or None
        First input root containing the attempt directory, if any.

    Notes
    -----
    Creating stdout, stderr, and attempt reservation files beneath a recursively
    fingerprinted include root would change the analyzer input during its own
    run. Such output placement is rejected before it writes any file.
    """
    roots = {item.path.resolve() for item in profile.include_directories}
    roots.add(profile.source_path.parent.resolve())
    roots.update(item.path.resolve().parent for item in profile.dependencies)
    for root in sorted(roots, key=str):
        if _is_within(directory, root):
            return root
    return None
