"""Normalization helpers for converting parser output into ADR-004 models.

Responsibilities
----------------
- Transform parsed AST metadata into `AnalysisResult`, `ModuleArtifact`, `FunctionArtifact`, and `CallSite` records.
- Apply deterministic rules for docstring detection, return/yield inference, and signature normalization.
- Provide utilities for normalized parameter names and stable identity generation.

Design principles
-----------------
Normalization stays isolated from scanners, simply translating parser output into storage-friendly models without side effects.

Architectural role
------------------
This module belongs to the **normalization layer** that bridges AST parsing and persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

from codira.models import (
    AnalysisResult,
    CallableReference,
    CallableReferenceKind,
    CallKind,
    CallSite,
    ClassArtifact,
    FunctionArtifact,
    ImportArtifact,
    ImportKind,
    ModuleArtifact,
    OverloadArtifact,
)


def _python_module_stable_id(module_name: str) -> str:
    """
    Build the stable module identity for one Python module.

    Parameters
    ----------
    module_name : str
        Dotted Python module name.

    Returns
    -------
    str
        Durable Python module identity.
    """
    return f"python:module:{module_name}"


def _python_class_stable_id(module_name: str, class_name: str) -> str:
    """
    Build the stable identity for one Python class.

    Parameters
    ----------
    module_name : str
        Dotted Python module name.
    class_name : str
        Class name within the module.

    Returns
    -------
    str
        Durable Python class identity.
    """
    return f"python:class:{module_name}:{class_name}"


def _python_function_stable_id(
    module_name: str,
    function_name: str,
    *,
    class_name: str | None = None,
    decorators: Sequence[object] = (),
) -> str:
    """
    Build the stable identity for one Python callable.

    Parameters
    ----------
    module_name : str
        Dotted Python module name.
    function_name : str
        Unqualified callable name.
    class_name : str | None, optional
        Owning class name for a method.
    decorators : collections.abc.Sequence[object], optional
        Callable decorators used to disambiguate accessor helpers.

    Returns
    -------
    str
        Durable Python function or method identity.
    """
    if class_name is None:
        return f"python:function:{module_name}:{function_name}"
    stable_id = f"python:method:{module_name}:{class_name}.{function_name}"
    decorator_names = tuple(str(value) for value in decorators)
    if any(name.endswith(".setter") for name in decorator_names):
        return f"{stable_id}:setter"
    if any(name.endswith(".deleter") for name in decorator_names):
        return f"{stable_id}:deleter"
    return stable_id


def _python_overload_stable_id(
    module_name: str,
    function_name: str,
    ordinal: int,
    *,
    class_name: str | None = None,
) -> str:
    """
    Build the stable identity for one Python overload declaration.

    Parameters
    ----------
    module_name : str
        Dotted Python module name.
    function_name : str
        Unqualified callable name.
    ordinal : int
        Deterministic declaration order among overloads for the callable.
    class_name : str | None, optional
        Owning class name for method overloads.

    Returns
    -------
    str
        Durable Python overload identity.
    """
    qualified_name = (
        function_name if class_name is None else f"{class_name}.{function_name}"
    )
    return f"python:overload:{module_name}:{qualified_name}:{ordinal}"


def _int_value(value: object, *, default: int = 0) -> int:
    """
    Coerce one parser value into an integer.

    Parameters
    ----------
    value : object
        Raw parsed value.
    default : int, optional
        Integer returned when the value is ``None``.

    Returns
    -------
    int
        Coerced integer value.
    """
    if value is None:
        return default
    return int(cast("int | str", value))


def _optional_int_value(value: object) -> int | None:
    """
    Coerce one parser value into an optional integer.

    Parameters
    ----------
    value : object
        Raw parsed value.

    Returns
    -------
    int | None
        Coerced integer value, or ``None`` when the parsed value is absent.
    """
    if value is None:
        return None
    return int(cast("int | str", value))


def _call_kind(value: object) -> CallKind:
    """
    Validate one normalized call-kind value.

    Parameters
    ----------
    value : object
        Raw parsed value.

    Returns
    -------
    {"name", "attribute", "unresolved"}
        Normalized call kind.

    Raises
    ------
    ValueError
        If the parsed value is not a supported call kind.
    """
    kind = str(value)
    if kind not in {"name", "attribute", "unresolved"}:
        msg = f"Unsupported call kind: {kind}"
        raise ValueError(msg)
    return cast("CallKind", kind)


def _reference_kind(value: object) -> CallableReferenceKind:
    """
    Validate one normalized callable-reference kind.

    Parameters
    ----------
    value : object
        Raw parsed value.

    Returns
    -------
    {"mapping_value", "sequence_item", "assignment_value", "return_value"}
        Normalized callable-reference kind.

    Raises
    ------
    ValueError
        If the parsed value is not a supported reference kind.
    """
    kind = str(value)
    if kind not in {
        "mapping_value",
        "sequence_item",
        "assignment_value",
        "return_value",
    }:
        msg = f"Unsupported callable reference kind: {kind}"
        raise ValueError(msg)
    return cast("CallableReferenceKind", kind)


def _import_kind(value: object) -> ImportKind:
    """
    Validate one normalized import-kind value.

    Parameters
    ----------
    value : object
        Raw parsed value.

    Returns
    -------
    {"import", "include_local", "include_system"}
        Normalized import kind.

    Raises
    ------
    ValueError
        If the parsed value is not a supported import kind.
    """
    kind = str(value)
    if kind not in {"import", "include_local", "include_system"}:
        msg = f"Unsupported import kind: {kind}"
        raise ValueError(msg)
    return cast("ImportKind", kind)


def _call_site_from_mapping(raw: Mapping[str, object]) -> CallSite:
    """
    Convert one parsed call record into a normalized model.

    Parameters
    ----------
    raw : collections.abc.Mapping[str, object]
        Parsed call record.

    Returns
    -------
    codira.models.CallSite
        Normalized call-site model.
    """
    return CallSite(
        kind=_call_kind(raw.get("kind", "unresolved")),
        target=str(raw.get("target", "")),
        lineno=_int_value(raw.get("lineno", 0)),
        col_offset=_int_value(raw.get("col_offset", 0)),
        base=str(raw.get("base", "")),
    )


def _callable_reference_from_mapping(raw: Mapping[str, object]) -> CallableReference:
    """
    Convert one parsed callable-reference record into a normalized model.

    Parameters
    ----------
    raw : collections.abc.Mapping[str, object]
        Parsed callable-reference record.

    Returns
    -------
    codira.models.CallableReference
        Normalized callable-reference model.
    """
    return CallableReference(
        kind=_call_kind(raw.get("kind", "unresolved")),
        target=str(raw.get("target", "")),
        lineno=_int_value(raw.get("lineno", 0)),
        col_offset=_int_value(raw.get("col_offset", 0)),
        ref_kind=_reference_kind(raw.get("ref_kind", "return_value")),
        base=str(raw.get("base", "")),
    )


def _function_from_mapping(
    raw: Mapping[str, object],
    *,
    module_name: str,
    class_name: str | None = None,
) -> FunctionArtifact:
    """
    Convert one parsed function-like mapping into a normalized model.

    Parameters
    ----------
    raw : collections.abc.Mapping[str, object]
        Parsed function or method entry.
    module_name : str
        Dotted Python module name.
    class_name : str | None, optional
        Owning class name for method artifacts.

    Returns
    -------
    codira.models.FunctionArtifact
        Normalized function artifact.
    """
    call_rows = cast("Sequence[Mapping[str, object]]", raw.get("calls", ()))
    ref_rows = cast("Sequence[Mapping[str, object]]", raw.get("callable_refs", ()))
    overload_rows = cast("Sequence[Mapping[str, object]]", raw.get("overloads", ()))
    parameters = cast("Sequence[object]", raw.get("parameters", ()))
    function_name = str(raw["name"])
    function_stable_id = _python_function_stable_id(
        module_name,
        function_name,
        class_name=class_name,
        decorators=cast("Sequence[object]", raw.get("decorators", ())),
    )

    return FunctionArtifact(
        name=function_name,
        stable_id=function_stable_id,
        lineno=_int_value(raw["lineno"]),
        end_lineno=_optional_int_value(raw.get("end_lineno")),
        signature=str(raw["signature"]),
        docstring=cast("str | None", raw.get("docstring")),
        has_docstring=_int_value(raw.get("has_docstring", 0)),
        is_method=_int_value(raw.get("is_method", 0)),
        is_public=_int_value(raw.get("is_public", 0)),
        parameters=tuple(str(value) for value in parameters),
        returns_value=_int_value(raw.get("returns_value", 0)),
        yields_value=_int_value(raw.get("yields_value", 0)),
        raises=_int_value(raw.get("raises", 0)),
        has_asserts=_int_value(raw.get("has_asserts", 0)),
        decorators=tuple(
            str(value) for value in cast("Sequence[object]", raw.get("decorators", ()))
        ),
        calls=tuple(_call_site_from_mapping(row) for row in call_rows),
        callable_refs=tuple(_callable_reference_from_mapping(row) for row in ref_rows),
        overloads=tuple(
            OverloadArtifact(
                stable_id=_python_overload_stable_id(
                    module_name,
                    function_name,
                    ordinal,
                    class_name=class_name,
                ),
                parent_stable_id=function_stable_id,
                ordinal=ordinal,
                signature=str(overload_row["signature"]),
                lineno=_int_value(overload_row["lineno"]),
                end_lineno=_optional_int_value(overload_row.get("end_lineno")),
                docstring=cast("str | None", overload_row.get("docstring")),
            )
            for ordinal, overload_row in enumerate(overload_rows, start=1)
        ),
    )


def analysis_result_from_parsed(
    source_path: Path,
    parsed: Mapping[str, object],
) -> AnalysisResult:
    """
    Convert parser output into the normalized ADR-004 artifact model.

    Parameters
    ----------
    source_path : pathlib.Path
        Source file path that produced the parser output.
    parsed : collections.abc.Mapping[str, object]
        Parser output from the current Python-specific analysis path.

    Returns
    -------
    codira.models.AnalysisResult
        Normalized analyzer output for one file.
    """
    module = cast("Mapping[str, object]", parsed["module"])
    classes = cast("Sequence[Mapping[str, object]]", parsed.get("classes", ()))
    functions = cast("Sequence[Mapping[str, object]]", parsed.get("functions", ()))
    imports = cast("Sequence[Mapping[str, object]]", parsed.get("imports", ()))

    module_name = str(module["name"])

    return AnalysisResult(
        source_path=source_path,
        module=ModuleArtifact(
            name=module_name,
            stable_id=_python_module_stable_id(module_name),
            docstring=cast("str | None", module.get("docstring")),
            has_docstring=_int_value(module.get("has_docstring", 0)),
        ),
        classes=tuple(
            ClassArtifact(
                name=str(class_row["name"]),
                stable_id=_python_class_stable_id(
                    module_name,
                    str(class_row["name"]),
                ),
                lineno=_int_value(class_row["lineno"]),
                end_lineno=_optional_int_value(class_row.get("end_lineno")),
                docstring=cast("str | None", class_row.get("docstring")),
                has_docstring=_int_value(class_row.get("has_docstring", 0)),
                methods=tuple(
                    _function_from_mapping(
                        method_row,
                        module_name=module_name,
                        class_name=str(class_row["name"]),
                    )
                    for method_row in cast(
                        "Sequence[Mapping[str, object]]",
                        class_row.get("methods", ()),
                    )
                ),
            )
            for class_row in classes
        ),
        functions=tuple(
            _function_from_mapping(row, module_name=module_name) for row in functions
        ),
        declarations=(),
        imports=tuple(
            ImportArtifact(
                name=str(import_row["name"]),
                alias=cast("str | None", import_row.get("alias")),
                lineno=_int_value(import_row["lineno"]),
                kind=_import_kind(import_row.get("kind", "import")),
            )
            for import_row in imports
        ),
    )
