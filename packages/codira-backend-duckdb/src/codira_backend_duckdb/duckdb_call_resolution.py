"""Conservative call-target resolution for DuckDB relationship persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .duckdb_support import CallResolutionRequest


def _qualified_callable_name(name: str, class_name: str | None = None) -> str:
    """
    Build the logical name used for call-graph identity.

    Parameters
    ----------
    name : str
        Unqualified function or method name.
    class_name : str | None, optional
        Owning class name for methods.

    Returns
    -------
    str
        ``Class.method`` for methods and the bare function name otherwise.
    """
    if class_name is None:
        return name
    return f"{class_name}.{name}"


def _import_alias_map(imports: list[dict[str, object]]) -> dict[str, str]:
    """
    Build a deterministic alias map for imported names.

    Parameters
    ----------
    imports : list[dict[str, object]]
        Parsed import rows from a module.

    Returns
    -------
    dict[str, str]
        Mapping from locally bound names to imported dotted targets.
    """
    aliases: dict[str, str] = {}
    for imp in imports:
        imported = str(imp["name"])
        alias = imp["alias"]
        local_name = str(alias) if alias is not None else imported.split(".")[-1]
        if "." in imported and alias is None and "." not in local_name:
            aliases[imported] = imported
        aliases[local_name] = imported
    return aliases


def _resolve_imported_function(
    imported: str,
    module_functions: dict[str, set[str]],
) -> tuple[str, str] | None:
    """
    Resolve a directly imported same-repository function target.

    Parameters
    ----------
    imported : str
        Imported dotted target as recorded by the parser.
    module_functions : dict[str, set[str]]
        Known top-level functions keyed by module name.

    Returns
    -------
    tuple[str, str] | None
        Resolved module and function name, or ``None`` when ambiguous.
    """
    if "." not in imported:
        return None
    module_name, function_name = imported.rsplit(".", 1)
    if function_name in module_functions.get(module_name, set()):
        return (module_name, function_name)
    return None


def _resolve_module_attribute_call(
    base: str,
    target: str,
    import_aliases: dict[str, str],
    module_functions: dict[str, set[str]],
) -> tuple[str, str] | None:
    """
    Resolve a module-qualified same-repository function call.

    Parameters
    ----------
    base : str
        Static base expression of the attribute call.
    target : str
        Attribute name being called.
    import_aliases : dict[str, str]
        Mapping of locally bound names to imported dotted targets.
    module_functions : dict[str, set[str]]
        Known top-level functions keyed by module name.

    Returns
    -------
    tuple[str, str] | None
        Resolved module and function name, or ``None`` when ambiguous.
    """
    imported = import_aliases.get(base)
    if imported is not None and target in module_functions.get(imported, set()):
        return (imported, target)
    return None


def _resolve_call_record(
    request: CallResolutionRequest,
) -> tuple[str | None, str | None, int]:
    """
    Resolve one parsed call-site record into a stored call edge.

    Parameters
    ----------
    request : CallResolutionRequest
        Call resolution request carrying caller context and symbol maps.

    Returns
    -------
    tuple[str | None, str | None, int]
        Callee module, callee name, and resolved flag for the call edge.
    """
    kind = str(request.call.get("kind", "unresolved"))
    target = str(request.call.get("target", ""))
    candidates: set[tuple[str, str]] = set()
    if kind == "name" and target:
        imported = request.import_aliases.get(target)
        if imported is not None:
            resolved_import = _resolve_imported_function(
                imported, request.module_functions
            )
            if resolved_import is not None:
                candidates.add(resolved_import)
        if target in request.module_functions.get(request.caller_module, set()):
            candidates.add((request.caller_module, target))
    elif kind == "attribute" and target:
        base = str(request.call.get("base", ""))
        if request.caller_class is not None and base in {"self", "cls"}:
            methods = request.class_methods.get(
                (request.caller_module, request.caller_class), set()
            )
            if target in methods:
                candidates.add(
                    (
                        request.caller_module,
                        _qualified_callable_name(target, request.caller_class),
                    )
                )
        methods = request.class_methods.get((request.caller_module, base), set())
        if target in methods:
            candidates.add(
                (request.caller_module, _qualified_callable_name(target, base))
            )
        resolved_module_call = _resolve_module_attribute_call(
            base, target, request.import_aliases, request.module_functions
        )
        if resolved_module_call is not None:
            candidates.add(resolved_module_call)
    if len(candidates) == 1:
        callee_module, callee_name = next(iter(candidates))
        return (callee_module, callee_name, 1)
    return (None, None, 0)


def _unresolved_identity(record: Mapping[str, str | int], *, resolved: int) -> str:
    """
    Return the stable unresolved-target identity for one derived edge.

    Parameters
    ----------
    record : collections.abc.Mapping[str, str | int]
        Raw call-style record that produced the derived relation.
    resolved : int
        Stored relation resolution flag.

    Returns
    -------
    str
        Empty for resolved relations, otherwise a deterministic raw target.
    """
    if resolved:
        return ""
    return json.dumps(
        (
            str(record.get("kind", "")),
            str(record.get("base", "")),
            str(record.get("target", "")),
        ),
        separators=(",", ":"),
    )
