"""Describe generated artifact provenance separately from physical source ranges.

Parameters
----------
None

Returns
-------
None
    Immutable backend-neutral provenance for generated callables and declarations.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, Never, cast

if TYPE_CHECKING:
    from codira.models import (
        AnalysisResult,
        FunctionArtifact,
        OverloadArtifact,
        SemanticIdentity,
    )


@dataclass(frozen=True)
class GeneratedTokenProvenance:
    """Retain generated spelling, derivation and a distinct original anchor.

    Parameters
    ----------
    spelling : str
        Preprocessing token spelling in the generated declaration.
    anchor : tuple[int, int]
        Original invocation or argument range; not a claim of literal spelling.
    physical_spelling_span : tuple[int, int] | None
        Original unmodified argument spelling, when independently established.
    operation : {'source', 'replacement', 'paste', 'stringify'}
        Final token derivation operation.

    Returns
    -------
    None
        Immutable token evidence without invented physical positions.
    """

    spelling: str
    anchor: tuple[int, int]
    physical_spelling_span: tuple[int, int] | None
    operation: Literal["source", "replacement", "paste", "stringify"]


@dataclass(frozen=True)
class MacroInputProvenance:
    """Bind one used macro replacement to a physical directive or profile key.

    Parameters
    ----------
    name : str
        Selected macro name; also identifies an explicit profile input.
    replacement_sha256 : str
        Digest of the exact selected definition shape and replacement bytes.
    source_path : str | None
        Repository-relative captured source; None identifies the profile key.
    source_sha256 : str | None
        Exact captured dependency digest, absent for a profile binding.
    span : tuple[int, int] | None
        Original directive range, absent for a profile binding.

    Returns
    -------
    None
        Explicit replacement origin independent of physical generated spelling.
    """

    name: str
    replacement_sha256: str
    source_path: str | None
    source_sha256: str | None
    span: tuple[int, int] | None


@dataclass(frozen=True)
class GeneratedCallableProvenance:
    """Describe one generated callable without changing its physical invocation.

    Parameters
    ----------
    role : {'definition', 'prototype', 'alias'}
        Declaration role; an alias owns no implementation body.
    invocation_span : tuple[int, int]
        Original complete macro invocation, excluding its unchanged body.
    source_sha256 : str
        Original translation-unit digest.
    context_identity : str
        Opaque analyzer input identity binding configuration and dependencies.
    tokens : tuple[GeneratedTokenProvenance, ...]
        Generated header tokens with separate physical spelling evidence.
    inputs : tuple[MacroInputProvenance, ...]
        Used selected definitions and their captured or explicit profile origins.
    parameter_names : tuple[str | None, ...]
        Parameter names, retaining unnamed prototype or alias parameters.
    parameter_types : tuple[str, ...]
        Proven source-spelled parameter types; not compiler type equivalence.
    alias_target : str | None, optional
        Qualified implementation identity when proven within the expansion.
    linkage_name : str | None, optional
        Explicit assembler label or alias linker target, when present.
    format_version : int, optional
        Version of this normalized generated provenance representation.

    Returns
    -------
    None
        Immutable provenance, separate from signature and decorators.
    """

    role: Literal["definition", "prototype", "alias"]
    invocation_span: tuple[int, int]
    source_sha256: str
    context_identity: str
    tokens: tuple[GeneratedTokenProvenance, ...]
    inputs: tuple[MacroInputProvenance, ...]
    parameter_names: tuple[str | None, ...]
    parameter_types: tuple[str, ...]
    alias_target: str | None = None
    linkage_name: str | None = None
    format_version: int = 1


@dataclass(frozen=True)
class CompilerObservedSourceCoordinate:
    """Retain one compiler-reported source coordinate without reconstruction.

    Parameters
    ----------
    path : str
        Repository-relative source path reported by the producing frontend.
    byte_offset : int
        Zero-based byte offset reported by the producer.

    Returns
    -------
    None
        Immutable observed coordinate.
    """

    path: str
    byte_offset: int


@dataclass(frozen=True)
class CompilerObservedMacroInvocation:
    """Retain a separate observed preprocessor invocation event.

    Parameters
    ----------
    name : str
        Observed macro name.
    path : str
        Repository-relative path containing the invocation.
    byte_range : tuple[int, int]
        Zero-based half-open byte range of the observed invocation.
    text : str
        Invocation text captured by the preprocessor observer.

    Returns
    -------
    None
        Immutable preprocessor observation, not token derivation evidence.
    """

    name: str
    path: str
    byte_range: tuple[int, int]
    text: str


@dataclass(frozen=True)
class CompilerObservedCallableProvenance:
    """Describe compiler-observed callable origin without token reconstruction.

    Parameters
    ----------
    origin : {'macro_argument', 'macro_replacement', 'implicit', 'template_instantiation', 'unknown'}
        Normalized compiler-reported origin classification.
    role : {'definition', 'prototype'}
        Callable declaration role reported by the frontend.
    source_sha256 : str
        Digest of the indexed source translation unit.
    context_identity : str
        Analysis input fingerprint binding the compiler result.
    spelling_location, expansion_location : CompilerObservedSourceCoordinate | None
        Optional source coordinates reported by the compiler.
    invocation : CompilerObservedMacroInvocation | None
        Separate preprocessor event correlated with the compiler expansion
        position, when observed.
    receipt_namespace : str
        Opaque namespace for the producer's canonical JSON receipt.
    receipt_json : str
        Bounded canonical compiler evidence, interpreted only by its producer.
    variant : {'compiler_observed'}, optional
        Discriminant for this representation variant.
    format_version : {2}, optional
        Version of this normalized compiler-observed representation.

    Returns
    -------
    None
        Immutable compiler evidence without fabricated tokens or source types.
    """

    origin: Literal[
        "macro_argument",
        "macro_replacement",
        "implicit",
        "template_instantiation",
        "unknown",
    ]
    role: Literal["definition", "prototype"]
    source_sha256: str
    context_identity: str
    receipt_namespace: str
    receipt_json: str
    spelling_location: CompilerObservedSourceCoordinate | None = None
    expansion_location: CompilerObservedSourceCoordinate | None = None
    invocation: CompilerObservedMacroInvocation | None = None
    variant: Literal["compiler_observed"] = "compiler_observed"
    format_version: Literal[2] = 2


@dataclass(frozen=True)
class CompilerObservedCallableProvenanceV3:
    """Describe compiler-observed callable evidence with explicit alias facts.

    Parameters
    ----------
    origin : {'macro_argument', 'macro_replacement', 'implicit', 'template_instantiation', 'unknown'}
        Normalized compiler-reported origin classification.
    role : {'definition', 'prototype', 'alias'}
        Declaration role reported by the frontend.
    source_sha256 : str
        Digest of the indexed source translation unit.
    context_identity : str
        Analysis input fingerprint binding the compiler result.
    receipt_namespace : str
        Opaque namespace for the producer's canonical JSON receipt.
    receipt_json : str
        Bounded canonical compiler evidence, interpreted only by its producer.
    alias_target_identity : codira.models.SemanticIdentity | None, optional
        Exact target identity when the compiler directly resolves the alias.
    linkage_name : str | None, optional
        Explicit linker label observed on the callable declaration.
    spelling_location, expansion_location : CompilerObservedSourceCoordinate | None
        Optional source coordinates reported by the compiler.
    invocation : CompilerObservedMacroInvocation | None, optional
        Separate observed preprocessor event, when available.

    Returns
    -------
    None
        Immutable version-three compiler evidence without token reconstruction.

    Notes
    -----
    The target identity is nullable because an observed alias spelling does not
    prove which callable declaration the compiler resolved. Version-two payloads
    retain their original exact field set and validation contract.
    """

    origin: Literal[
        "macro_argument",
        "macro_replacement",
        "implicit",
        "template_instantiation",
        "unknown",
    ]
    role: Literal["definition", "prototype", "alias"]
    source_sha256: str
    context_identity: str
    receipt_namespace: str
    receipt_json: str
    alias_target_identity: SemanticIdentity | None = None
    linkage_name: str | None = None
    spelling_location: CompilerObservedSourceCoordinate | None = None
    expansion_location: CompilerObservedSourceCoordinate | None = None
    invocation: CompilerObservedMacroInvocation | None = None
    variant: Literal["compiler_observed"] = "compiler_observed"
    format_version: Literal[3] = 3


@dataclass(frozen=True)
class CompilerObservedDeclarationProvenance:
    """Describe compiler-observed macro origin for a variable or constant.

    Parameters
    ----------
    origin : {'macro_argument', 'macro_replacement'}
        Compiler-reported origin of the declaration spelling.
    declaration_kind : {'variable', 'constant'}
        Existing logical declaration kind carrying this observation.
    source_sha256 : str
        Digest of the indexed translation unit.
    context_identity : str
        Analysis input fingerprint binding the compiler result.
    receipt_namespace : str
        Fixed namespace identifying the compiler's declaration receipt.
    receipt_json : str
        Bounded canonical compiler evidence, interpreted only by its producer.
    expansion_location : CompilerObservedSourceCoordinate
        Required compiler-reported expansion coordinate.
    invocation : CompilerObservedMacroInvocation
        Required separately observed preprocessor invocation event.
    spelling_location : CompilerObservedSourceCoordinate | None, optional
        Compiler-reported spelling coordinate when present.
    variant : {'compiler_observed_declaration'}, optional
        Discriminant for this declaration evidence representation.
    format_version : {1}, optional
        Version of this normalized declaration provenance representation.

    Returns
    -------
    None
        Immutable declaration evidence without token derivation claims.
    """

    origin: Literal["macro_argument", "macro_replacement"]
    declaration_kind: Literal["variable", "constant"]
    source_sha256: str
    context_identity: str
    receipt_namespace: str
    receipt_json: str
    expansion_location: CompilerObservedSourceCoordinate
    invocation: CompilerObservedMacroInvocation
    spelling_location: CompilerObservedSourceCoordinate | None = None
    variant: Literal["compiler_observed_declaration"] = "compiler_observed_declaration"
    format_version: Literal[1] = 1


type GeneratedCallableEvidence = (
    GeneratedCallableProvenance
    | CompilerObservedCallableProvenance
    | CompilerObservedCallableProvenanceV3
)
type GeneratedDeclarationEvidence = CompilerObservedDeclarationProvenance


def generated_provenance_rows(analysis: AnalysisResult) -> tuple[tuple[str, str], ...]:
    """Serialize generated artifact provenance by stable identity.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized source analysis emitted by an analyzer.

    Returns
    -------
    tuple[tuple[str, str], ...]
        Stable artifact identities and deterministic JSON payloads.
    """
    rows: list[tuple[str, str]] = []
    functions = (*analysis.functions, *(m for c in analysis.classes for m in c.methods))
    for function in functions:
        artifacts: tuple[FunctionArtifact | OverloadArtifact, ...] = (
            function,
            *function.overloads,
        )
        for artifact in artifacts:
            if artifact.generated is not None:
                rows.append(
                    (
                        artifact.stable_id,
                        json.dumps(
                            asdict(artifact.generated),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                )
    for declaration in analysis.declarations:
        if declaration.generated is not None:
            if declaration.kind != declaration.generated.declaration_kind:
                _invalid(
                    "compiler-observed declaration kind does not match its artifact"
                )
            rows.append(
                (
                    declaration.stable_id,
                    json.dumps(
                        asdict(declaration.generated),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
    return tuple(rows)


def _invalid(message: str) -> Never:
    """Reject semantically invalid persisted provenance.

    Parameters
    ----------
    message : str
        Stable validation diagnostic.

    Returns
    -------
    Never
        Always raises a value error.

    Raises
    ------
    ValueError
        The persisted evidence is invalid.
    """
    raise ValueError(message)


def _source_span(value: object) -> tuple[int, int]:
    """Validate a nonempty physical or invocation byte range.

    Parameters
    ----------
    value : object
        Decoded JSON range.

    Returns
    -------
    tuple[int, int]
        Nonnegative ordered integer positions.

    Raises
    ------
    ValueError
        If range shape or values are invalid.
    """
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(position) is not int for position in value)
        or not 0 <= value[0] < value[1]
    ):
        _invalid("invalid generated source span")
    return int(value[0]), int(value[1])


def _valid_digest(value: object) -> bool:
    """Check an exact lower-case SHA-256 digest.

    Parameters
    ----------
    value : object
        Decoded digest value.

    Returns
    -------
    bool
        Whether the value is a complete SHA-256 representation.
    """
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _reject_nonfinite_json(value: str) -> Never:
    """Reject JavaScript-style non-finite JSON constants.

    Parameters
    ----------
    value : str
        Non-standard JSON constant emitted by the decoder.

    Returns
    -------
    Never
        Always rejects the constant.

    Raises
    ------
    ValueError
        The value is not valid strict JSON.
    """
    _invalid(f"non-finite JSON value is unsupported: {value}")


def _valid_repository_path(value: object) -> bool:
    """Check a normalized repository-relative POSIX path.

    Parameters
    ----------
    value : object
        Candidate path from decoded compiler evidence.

    Returns
    -------
    bool
        Whether the path is relative, normalized and traversal-free.
    """
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == value
        and value != "."
    )


def _validate_observed_coordinate(value: object) -> None:
    """Validate one compiler-reported source coordinate.

    Parameters
    ----------
    value : object
        Decoded spelling or expansion coordinate.

    Returns
    -------
    None
        The coordinate has a safe path and nonnegative byte offset.

    Raises
    ------
    ValueError
        If the coordinate shape or range is invalid.
    """
    if not isinstance(value, dict) or set(value) != {"path", "byte_offset"}:
        _invalid("invalid compiler-observed source coordinate")
    if not _valid_repository_path(value["path"]):
        _invalid("invalid compiler-observed source path")
    offset = value["byte_offset"]
    if type(offset) is not int or offset < 0:
        _invalid("invalid compiler-observed byte offset")


def _validate_observed_invocation(value: object, payload: dict[str, object]) -> None:
    """Validate one separately captured macro expansion event.

    Parameters
    ----------
    value : object
        Decoded macro invocation event.
    payload : dict[str, object]
        Parent compiler-observed declaration or callable record.

    Returns
    -------
    None
        The event is structurally valid and anchored to the expansion point.

    Raises
    ------
    ValueError
        If the event is malformed or conflicts with the callable origin.
    """
    if not isinstance(value, dict) or set(value) != {
        "name",
        "path",
        "byte_range",
        "text",
    }:
        _invalid("invalid observed macro invocation fields")
    name, path, byte_range, text = (
        value["name"],
        value["path"],
        value["byte_range"],
        value["text"],
    )
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 256
        or not _valid_repository_path(path)
        or not isinstance(text, str)
    ):
        _invalid("invalid observed macro invocation identity")
    start, end = _source_span(byte_range)
    try:
        text_bytes = text.encode("utf-8")
    except UnicodeEncodeError:
        _invalid("observed macro invocation is not valid UTF-8")
    if len(text_bytes) != end - start or len(text_bytes) > 64 * 1024:
        _invalid("observed macro invocation text does not match its byte range")
    if payload["origin"] not in ("macro_argument", "macro_replacement"):
        _invalid("non-macro callable cannot have a macro invocation")
    expansion = payload["expansion_location"]
    if (
        not isinstance(expansion, dict)
        or expansion["path"] != path
        or not start <= expansion["byte_offset"] < end
    ):
        _invalid("macro invocation does not contain the expansion location")


def _validate_receipt_json(value: object) -> None:
    """Validate bounded canonical JSON without interpreting its contents.

    Parameters
    ----------
    value : object
        Namespaced receipt string from the producing compiler frontend.

    Returns
    -------
    None
        The receipt is canonical strict JSON within the approved bounds.

    Raises
    ------
    ValueError
        If size, JSON shape, depth or canonical form is invalid.
    """
    if not isinstance(value, str) or len(value.encode("utf-8")) > 64 * 1024:
        _invalid("compiler receipt byte limit exceeded")
    try:
        receipt: object = json.loads(
            value,
            parse_constant=_reject_nonfinite_json,
        )
    except (json.JSONDecodeError, RecursionError):
        _invalid("invalid compiler receipt JSON")
    if not isinstance(receipt, dict):
        _invalid("compiler receipt must be a JSON object")
    _validate_json_tree(receipt, depth=0)
    try:
        canonical = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError):
        _invalid("compiler receipt is not canonical JSON")
    if canonical != value:
        _invalid("compiler receipt JSON is not canonical")


def _validate_json_tree(value: object, *, depth: int) -> None:
    """Validate receipt JSON types and bound nested object depth.

    Parameters
    ----------
    value : object
        A decoded JSON value.
    depth : int
        Current nesting depth.

    Returns
    -------
    None
        The tree contains only bounded standard JSON values.

    Raises
    ------
    ValueError
        If nesting exceeds 16 or a non-JSON value is encountered.
    """
    if depth > 16:
        _invalid("compiler receipt nesting limit exceeded")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            _invalid("compiler receipt object keys must be strings")
        for child in value.values():
            _validate_json_tree(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_json_tree(child, depth=depth + 1)
    elif value is None or type(value) in {str, int, float, bool}:
        return
    else:
        _invalid("compiler receipt contains a non-JSON value")


def _validate_compiler_observed_payload(payload: dict[str, object]) -> None:
    """Validate tagged version-two and version-three compiler evidence.

    Parameters
    ----------
    payload : dict[str, object]
        Decoded compiler-observed provenance object.

    Returns
    -------
    None
        The compiler-observed receipt is safe to expose to evidence clients.

    Raises
    ------
    ValueError
        If fields, context, coordinates, invocation or receipt are invalid.
    """
    base_fields = {
        "variant",
        "format_version",
        "origin",
        "role",
        "source_sha256",
        "context_identity",
        "spelling_location",
        "expansion_location",
        "invocation",
        "receipt_namespace",
        "receipt_json",
    }
    version = payload.get("format_version")
    if type(version) is not int:
        _invalid("unsupported compiler-observed provenance fields or version")
    required = (
        base_fields
        if version == 2
        else base_fields | {"alias_target_identity", "linkage_name"}
        if version == 3
        else set()
    )
    if (
        set(payload) != required
        or payload["variant"] != "compiler_observed"
        or payload["origin"]
        not in {
            "macro_argument",
            "macro_replacement",
            "implicit",
            "template_instantiation",
            "unknown",
        }
        or payload["role"]
        not in (
            {"definition", "prototype"}
            if version == 2
            else {"definition", "prototype", "alias"}
        )
    ):
        _invalid("unsupported compiler-observed provenance fields or version")
    if (
        not _valid_digest(payload["source_sha256"])
        or not isinstance(payload["context_identity"], str)
        or not payload["context_identity"]
    ):
        _invalid("invalid compiler-observed input identity")
    namespace = payload["receipt_namespace"]
    if not isinstance(namespace, str) or not namespace or len(namespace) > 256:
        _invalid("invalid compiler receipt namespace")
    for key in ("spelling_location", "expansion_location"):
        location = payload[key]
        if location is not None:
            _validate_observed_coordinate(location)
    invocation = payload["invocation"]
    if invocation is not None:
        _validate_observed_invocation(invocation, payload)
    _validate_receipt_json(payload["receipt_json"])
    if version == 3:
        _validate_compiler_observed_alias_fields(payload)


def _validate_compiler_observed_declaration_payload(
    payload: dict[str, object],
) -> None:
    """Validate the exact version-one compiler-observed declaration contract.

    Parameters
    ----------
    payload : dict[str, object]
        Decoded compiler-observed declaration provenance.

    Returns
    -------
    None
        The macro declaration receipt is bounded and structurally valid.

    Raises
    ------
    ValueError
        If fields, declaration kind, coordinates, invocation or receipt are invalid.
    """
    required = {
        "variant",
        "format_version",
        "origin",
        "declaration_kind",
        "source_sha256",
        "context_identity",
        "spelling_location",
        "expansion_location",
        "invocation",
        "receipt_namespace",
        "receipt_json",
    }
    if (
        set(payload) != required
        or payload["variant"] != "compiler_observed_declaration"
        or type(payload["format_version"]) is not int
        or payload["format_version"] != 1
        or payload["origin"] not in {"macro_argument", "macro_replacement"}
        or payload["declaration_kind"] not in {"variable", "constant"}
    ):
        _invalid("unsupported compiler-observed declaration fields or version")
    if (
        not _valid_digest(payload["source_sha256"])
        or not isinstance(payload["context_identity"], str)
        or not payload["context_identity"]
    ):
        _invalid("invalid compiler-observed declaration input identity")
    if payload["receipt_namespace"] != "clang.frontend.declaration-observation.v1":
        _invalid("invalid compiler-observed declaration receipt namespace")
    spelling = payload["spelling_location"]
    if spelling is not None:
        _validate_observed_coordinate(spelling)
    expansion = payload["expansion_location"]
    _validate_observed_coordinate(expansion)
    invocation = payload["invocation"]
    if invocation is None:
        _invalid("compiler-observed declaration requires a macro invocation")
    _validate_observed_invocation(invocation, payload)
    _validate_receipt_json(payload["receipt_json"])


def _validate_compiler_observed_alias_fields(payload: dict[str, object]) -> None:
    """Validate version-three alias identity and observed linker label.

    Parameters
    ----------
    payload : dict[str, object]
        Decoded version-three compiler-observed provenance.

    Returns
    -------
    None
        Alias facts are either valid and explicit or unresolved.

    Raises
    ------
    ValueError
        If identity fields are malformed or attached to a non-alias role.
    """
    target = payload["alias_target_identity"]
    linkage_name = payload["linkage_name"]
    if payload["role"] != "alias":
        if target is not None or linkage_name is not None:
            _invalid("alias target and linkage facts require alias role")
        return
    if linkage_name is not None and (
        not isinstance(linkage_name, str)
        or not linkage_name
        or len(linkage_name) > 4096
    ):
        _invalid("invalid observed alias linkage name")
    if target is not None:
        if not isinstance(target, dict) or set(target) != {"namespace", "value"}:
            _invalid("invalid observed alias target identity")
        namespace, value = target["namespace"], target["value"]
        if (
            not isinstance(namespace, str)
            or not namespace
            or len(namespace) > 256
            or not isinstance(value, str)
            or not value
            or len(value) > 4096
        ):
            _invalid("invalid observed alias target identity")


def _validate_tokens(tokens: list[object], invocation: tuple[int, int]) -> None:
    """Validate token anchors without accepting invented physical spellings.

    Parameters
    ----------
    tokens : list[object]
        Decoded generated tokens.
    invocation : tuple[int, int]
        Proven containing invocation range.

    Returns
    -------
    None
        Every token preserves the physical/generated distinction.

    Raises
    ------
    ValueError
        If token shape, bounds or physical claims are invalid.
    """
    for item in tokens:
        if not isinstance(item, dict) or set(item) != {
            "spelling",
            "anchor",
            "physical_spelling_span",
            "operation",
        }:
            _invalid("invalid generated token fields")
        record = cast("dict[str, object]", item)
        if (
            not isinstance(record["spelling"], str)
            or not record["spelling"]
            or record["operation"]
            not in ("source", "replacement", "paste", "stringify")
        ):
            _invalid("invalid generated token spelling or derivation")
        anchor = _source_span(record["anchor"])
        if not invocation[0] <= anchor[0] < anchor[1] <= invocation[1]:
            _invalid("generated token anchor escapes invocation")
        physical = record["physical_spelling_span"]
        if physical is not None and (
            record["operation"] != "source" or _source_span(physical) != anchor
        ):
            _invalid("generated spelling cannot claim a physical token range")


def _validate_inputs(inputs: list[object]) -> None:
    """Validate contained directive origins and nonphysical profile bindings.

    Parameters
    ----------
    inputs : list[object]
        Decoded macro definition provenance.

    Returns
    -------
    None
        Every input has a valid profile or captured-source origin.

    Raises
    ------
    ValueError
        If names, hashes, paths or source ranges are invalid.
    """
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {
            "name",
            "replacement_sha256",
            "source_path",
            "source_sha256",
            "span",
        }:
            _invalid("invalid generated macro input fields")
        record = cast("dict[str, object]", item)
        name = record["name"]
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name) is None
            or not _valid_digest(record["replacement_sha256"])
        ):
            _invalid("invalid generated macro name or replacement digest")
        path = record["source_path"]
        if path is None:
            if record["source_sha256"] is not None or record["span"] is not None:
                _invalid("profile input has no physical source range")
        else:
            if (
                not isinstance(path, str)
                or not path
                or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts
                or not _valid_digest(record["source_sha256"])
            ):
                _invalid("invalid generated macro source origin")
            _source_span(record["span"])


def generated_provenance_payload(value: str) -> dict[str, object]:
    """Validate stored provenance before exposing generated source evidence.

    Parameters
    ----------
    value : str
        Serialized generated callable or compiler-observed declaration record.

    Returns
    -------
    dict[str, object]
        Validated payload retaining physical/generated spelling distinctions.

    Raises
    ------
    ValueError
        If structure, bounds, hashes, paths or provenance claims fail.
    """
    if len(value.encode()) > 8 * 1024 * 1024:
        _invalid("generated provenance byte limit exceeded")
    try:
        raw: object = json.loads(value, parse_constant=_reject_nonfinite_json)
    except RecursionError:
        _invalid("generated provenance nesting limit exceeded")
    if not isinstance(raw, dict):
        _invalid("generated provenance must be an object")
    payload = cast("dict[str, object]", raw)
    if payload.get("variant") == "compiler_observed_declaration":
        _validate_compiler_observed_declaration_payload(payload)
        return payload
    if payload.get("variant") == "compiler_observed":
        _validate_compiler_observed_payload(payload)
        return payload
    required = {
        "format_version",
        "role",
        "invocation_span",
        "source_sha256",
        "context_identity",
        "tokens",
        "inputs",
        "parameter_names",
        "parameter_types",
        "alias_target",
        "linkage_name",
    }
    if (
        set(payload) != required
        or type(payload["format_version"]) is not int
        or payload["format_version"] != 1
        or payload["role"] not in ("definition", "prototype", "alias")
    ):
        _invalid("unsupported generated provenance fields, version or role")
    if (
        not _valid_digest(payload["source_sha256"])
        or not isinstance(payload["context_identity"], str)
        or not payload["context_identity"]
    ):
        _invalid("invalid generated input identity")
    tokens, inputs = payload["tokens"], payload["inputs"]
    names, types = payload["parameter_names"], payload["parameter_types"]
    if (
        not isinstance(tokens, list)
        or len(tokens) > 32768
        or not isinstance(inputs, list)
        or len(inputs) > 8192
        or not isinstance(names, list)
        or not isinstance(types, list)
        or len(names) != len(types)
        or any(name is not None and not isinstance(name, str) for name in names)
        or any(not isinstance(item, str) for item in types)
    ):
        _invalid("invalid generated token, input or parameter collection")
    _validate_tokens(tokens, _source_span(payload["invocation_span"]))
    _validate_inputs(inputs)
    if any(
        payload[key] is not None and not isinstance(payload[key], str)
        for key in ("alias_target", "linkage_name")
    ) or (payload["role"] == "alias" and not payload["alias_target"]):
        _invalid("invalid generated alias or linkage identity")
    return payload
