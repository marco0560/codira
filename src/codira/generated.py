"""Describe generated callable spellings separately from physical source ranges.

Parameters
----------
None

Returns
-------
None
    Immutable backend-neutral provenance for analyzer-generated declarations.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, Never, cast

if TYPE_CHECKING:
    from codira.models import AnalysisResult, FunctionArtifact, OverloadArtifact


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


def generated_provenance_rows(analysis: AnalysisResult) -> tuple[tuple[str, str], ...]:
    """Serialize generated callable and overload provenance by stable identity.

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
        Serialized version-one provenance record.

    Returns
    -------
    dict[str, object]
        Validated payload retaining physical/generated spelling distinctions.

    Raises
    ------
    ValueError
        If structure, bounds, hashes, paths or physical spelling claims fail.
    """
    if len(value.encode()) > 8 * 1024 * 1024:
        _invalid("generated provenance byte limit exceeded")
    raw: object = json.loads(value)
    if not isinstance(raw, dict):
        _invalid("generated provenance must be an object")
    payload = cast("dict[str, object]", raw)
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
