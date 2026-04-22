"""AST parsing helpers for extracting repository symbols.

Responsibilities
----------------
- Normalize AST nodes into element-level metadata such as signatures, parameter names, and visibility.
- Detect returns, yields, and generator semantics needed by docstring validation.
- Supply portable utilities consumed by normalization and analyzer implementations.

Design principles
-----------------
Helpers focus on deterministic AST inspection without building heavy classes or carrying storage state.

Architectural role
------------------
This module belongs to the **scanner/indexing layer** and keeps AST-specific heuristics isolated from downstream stages.
"""

from __future__ import annotations

import ast
import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def _is_public(name: str) -> int:
    """
    Encode public visibility as an integer flag.

    Parameters
    ----------
    name : str
        Symbol name to classify.

    Returns
    -------
    int
        ``1`` when the name does not start with an underscore, otherwise ``0``.
    """
    return int(not name.startswith("_"))


def _signature_text(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """
    Render a simplified textual signature for a function node.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to render.

    Returns
    -------
    str
        Function name with positional, variadic, and keyword variadic
        parameters.
    """
    arg_names = [arg.arg for arg in node.args.args]
    if node.args.vararg is not None:
        arg_names.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg is not None:
        arg_names.append(f"**{node.args.kwarg.arg}")
    return f"{node.name}({', '.join(arg_names)})"


def _collapsed_source_text(source: str, node: ast.AST) -> str:
    """
    Return one node's source text collapsed to stable single-space formatting.

    Parameters
    ----------
    source : str
        Full source text containing the node.
    node : ast.AST
        Syntax node whose source text should be rendered.

    Returns
    -------
    str
        Source segment for the node with whitespace collapsed
        deterministically.
    """
    segment = ast.get_source_segment(source, node)
    if segment is None:
        segment = ast.unparse(node)
    return " ".join(segment.split())


def _is_type_alias_annotation(annotation: ast.expr) -> bool:
    """
    Return whether one annotation denotes ``TypeAlias`` explicitly.

    Parameters
    ----------
    annotation : ast.expr
        Annotation expression to classify.

    Returns
    -------
    bool
        ``True`` when the annotation is ``TypeAlias`` or
        ``typing.TypeAlias``.
    """
    return ast.unparse(annotation) in {"TypeAlias", "typing.TypeAlias"}


def _type_alias_entry(
    node: ast.TypeAlias | ast.AnnAssign,
    source: str,
) -> dict[str, str | int | None] | None:
    """
    Convert one explicit top-level Python type alias into parsed metadata.

    Parameters
    ----------
    node : ast.TypeAlias | ast.AnnAssign
        Syntax node representing one explicit type alias.
    source : str
        Full source text containing the alias node.

    Returns
    -------
    dict[str, str | int | None] | None
        Parsed declaration metadata, or ``None`` when the node does not expose
        a deterministic alias name.
    """
    if isinstance(node, ast.TypeAlias):
        if not isinstance(node.name, ast.Name):
            return None
        return {
            "name": node.name.id,
            "kind": "type_alias",
            "lineno": node.lineno,
            "signature": _collapsed_source_text(source, node),
            "docstring": None,
        }

    if (
        isinstance(node.target, ast.Name)
        and node.value is not None
        and _is_type_alias_annotation(node.annotation)
    ):
        return {
            "name": node.target.id,
            "kind": "type_alias",
            "lineno": node.lineno,
            "signature": _collapsed_source_text(source, node),
            "docstring": None,
        }

    return None


def _looks_like_constant_name(name: str) -> bool:
    """
    Return whether one name matches the bounded constant naming rule.

    Parameters
    ----------
    name : str
        Candidate assignment target name.

    Returns
    -------
    bool
        ``True`` when the name is public, contains at least one alphabetic
        character, and all alphabetic characters are uppercase.
    """
    return (
        not name.startswith("_")
        and any(char.isalpha() for char in name)
        and name.isupper()
    )


def _constant_entry(
    node: ast.Assign | ast.AnnAssign,
    source: str,
) -> dict[str, str | int | None] | None:
    """
    Convert one explicit top-level Python constant assignment into metadata.

    Parameters
    ----------
    node : ast.Assign | ast.AnnAssign
        Syntax node representing one constant-like assignment.
    source : str
        Full source text containing the assignment node.

    Returns
    -------
    dict[str, str | int | None] | None
        Parsed declaration metadata, or ``None`` when the assignment falls
        outside the bounded constant rule.
    """
    target: ast.expr | None
    value: ast.expr | None

    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None
        target = node.targets[0]
        value = node.value
    else:
        target = node.target
        value = node.value

    if not isinstance(target, ast.Name) or value is None:
        return None
    if not _looks_like_constant_name(target.id):
        return None

    try:
        ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return None

    return {
        "name": target.id,
        "kind": "constant",
        "lineno": node.lineno,
        "signature": _collapsed_source_text(source, node),
        "docstring": None,
    }


def _append_import_entries(
    result: dict[str, Any],
    node: ast.AST,
) -> bool:
    """
    Append parsed import metadata for one top-level node when applicable.

    Parameters
    ----------
    result : dict[str, typing.Any]
        Mutable parser result under construction.
    node : ast.AST
        Top-level syntax node to inspect.

    Returns
    -------
    bool
        ``True`` when the node was recognized as an import statement.
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            result["imports"].append(
                {
                    "name": alias.name,
                    "alias": alias.asname,
                    "lineno": node.lineno,
                }
            )
        return True

    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            dotted = f"{module}.{alias.name}" if module else alias.name
            result["imports"].append(
                {
                    "name": dotted,
                    "alias": alias.asname,
                    "lineno": node.lineno,
                }
            )
        return True

    return False


def _append_type_alias_declaration(
    result: dict[str, Any],
    node: ast.AST,
    source: str,
) -> bool:
    """
    Append parsed explicit type-alias metadata for one top-level node.

    Parameters
    ----------
    result : dict[str, typing.Any]
        Mutable parser result under construction.
    node : ast.AST
        Top-level syntax node to inspect.
    source : str
        Full source text containing the node.

    Returns
    -------
    bool
        ``True`` when the node was recognized as an explicit type alias.
    """
    if not isinstance(node, (ast.TypeAlias, ast.AnnAssign)):
        return False

    declaration = _type_alias_entry(node, source)
    if declaration is None:
        return False
    result["declarations"].append(declaration)
    return True


def _append_constant_declaration(
    result: dict[str, Any],
    node: ast.AST,
    source: str,
) -> bool:
    """
    Append parsed explicit constant metadata for one top-level node.

    Parameters
    ----------
    result : dict[str, typing.Any]
        Mutable parser result under construction.
    node : ast.AST
        Top-level syntax node to inspect.
    source : str
        Full source text containing the node.

    Returns
    -------
    bool
        ``True`` when the node was recognized as a bounded constant
        declaration.
    """
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return False

    declaration = _constant_entry(node, source)
    if declaration is None:
        return False
    result["declarations"].append(declaration)
    return True


def _parameter_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """
    Collect logical parameter names from a function node.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    list[str]
        Parameter names in declaration order, excluding conventional
        ``self`` and ``cls`` method receivers.
    """
    names: list[str] = []

    for arg in node.args.posonlyargs:
        if arg.arg not in {"self", "cls"}:
            names.append(arg.arg)

    for arg in node.args.args:
        if arg.arg not in {"self", "cls"}:
            names.append(arg.arg)

    if node.args.vararg is not None:
        names.append(node.args.vararg.arg)

    for arg in node.args.kwonlyargs:
        if arg.arg not in {"self", "cls"}:
            names.append(arg.arg)

    if node.args.kwarg is not None:
        names.append(node.args.kwarg.arg)

    return names


def _returns_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Check whether a function explicitly returns a value.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    bool
        ``True`` when the function contains a ``return`` with a non-``None``
        value.
    """
    return any(
        isinstance(child, ast.Return) and child.value is not None
        for child in _walk_local_function_body(node)
    )


def _yields_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Check whether a function yields values.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    bool
        ``True`` when the function contains ``yield`` or ``yield from``.
    """
    return any(
        isinstance(child, (ast.Yield, ast.YieldFrom))
        for child in _walk_local_function_body(node)
    )


def _raises_exception(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Check whether a function explicitly raises an exception.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    bool
        ``True`` when the function contains an explicit ``raise`` statement.
    """
    return any(
        isinstance(child, ast.Raise) for child in _walk_local_function_body(node)
    )


def _walk_local_function_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.AST]:
    """
    Collect AST nodes belonging to the callable's own execution body.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    list[ast.AST]
        Descendant nodes excluding nested function, lambda, and class scopes.
    """
    local_nodes: list[ast.AST] = []

    def visit(current: ast.AST) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(
                child,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.Lambda,
                    ast.ClassDef,
                ),
            ):
                continue
            local_nodes.append(child)
            visit(child)

    visit(node)
    return local_nodes


def _has_asserts(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Check whether a function contains explicit assert statements.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node to inspect.

    Returns
    -------
    bool
        ``True`` when the function contains at least one ``assert`` statement.
    """
    return any(isinstance(child, ast.Assert) for child in ast.walk(node))


def _decorator_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    """
    Collect statically representable decorator names from a callable node.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node whose decorators should be inspected.

    Returns
    -------
    list[str]
        Deterministic dotted decorator names, preserving declaration order.
    """
    decorators: list[str] = []

    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            name = _attribute_path(decorator.func)
        else:
            name = _attribute_path(decorator)
        if name is not None:
            decorators.append(name)

    return decorators


def _is_overload_stub(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """
    Return whether a callable node is a typing overload stub.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function-like AST node whose decorators should be inspected.

    Returns
    -------
    bool
        ``True`` when the callable is decorated with ``@overload`` or
        ``@typing.overload``.
    """
    return any(
        name in {"overload", "typing.overload"} for name in _decorator_names(node)
    )


def _overload_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str | int | None]:
    """
    Convert one overload stub into a normalized parsed mapping.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Overload-decorated callable AST node.

    Returns
    -------
    dict[str, str | int | None]
        Parsed overload metadata used by normalization.
    """
    overload_doc = ast.get_docstring(node)
    return {
        "lineno": node.lineno,
        "end_lineno": getattr(node, "end_lineno", None),
        "signature": _signature_text(node),
        "docstring": overload_doc,
    }


def _module_name_from_path(path: Path, root: Path) -> str:
    """
    Derive the dotted module name for a source file.

    Parameters
    ----------
    path : pathlib.Path
        Python file path to convert.
    root : pathlib.Path
        Repository root used to compute the relative module path.

    Returns
    -------
    str
        Dotted import-style module name.
    """
    rel = path.with_suffix("").relative_to(root)
    parts = list(rel.parts)

    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]

    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts)


def _attribute_path(node: ast.AST) -> str | None:
    """
    Render a dotted attribute chain when it is statically representable.

    Parameters
    ----------
    node : ast.AST
        Expression node that may encode a dotted attribute path.

    Returns
    -------
    str | None
        Dotted path for ``ast.Name`` and nested ``ast.Attribute`` chains, or
        ``None`` when the expression depends on dynamic evaluation.
    """
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        prefix = _attribute_path(node.value)
        if prefix is None:
            return None
        return f"{prefix}.{node.attr}"

    return None


def _call_site_position(
    func: ast.expr,
    call: ast.Call,
) -> tuple[int, int]:
    """
    Compute a stable source position for a call target.

    Parameters
    ----------
    func : ast.expr
        Callee expression stored on the ``ast.Call`` node.
    call : ast.Call
        Call node that owns the callee expression.

    Returns
    -------
    tuple[int, int]
        ``(lineno, col_offset)`` for the most specific statically known call
        target token.

    Notes
    -----
    Python 3.14 can report the same ``ast.Call.col_offset`` for each step in a
    chained expression such as ``str(value).strip().lower()``. Attribute calls
    therefore anchor their position on the attribute token instead of the outer
    call expression.

    Examples
    --------
    ``str(value).strip().lower()`` yields distinct positions for ``strip`` and
    ``lower`` even though the nested ``ast.Call`` nodes share the same start
    offset.
    """
    if isinstance(func, ast.Name):
        return (
            getattr(func, "lineno", getattr(call, "lineno", 0)),
            getattr(func, "col_offset", getattr(call, "col_offset", 0)),
        )

    if isinstance(func, ast.Attribute):
        lineno = getattr(func, "end_lineno", getattr(call, "lineno", 0))
        end_col_offset = getattr(func, "end_col_offset", None)
        if isinstance(end_col_offset, int):
            return (lineno, end_col_offset - len(func.attr))
        return (
            getattr(func, "lineno", getattr(call, "lineno", 0)),
            getattr(func, "col_offset", getattr(call, "col_offset", 0)),
        )

    return (
        getattr(call, "lineno", 0),
        getattr(call, "col_offset", 0),
    )


def _reference_record_from_expr(
    expr: ast.expr,
    *,
    kind: str,
) -> dict[str, str | int] | None:
    """
    Build a callable-reference record from a direct expression.

    Parameters
    ----------
    expr : ast.expr
        Expression that may name a callable object.
    kind : str
        Stable classifier describing the surrounding expression context.

    Returns
    -------
    dict[str, str | int] | None
        Structured reference record, or ``None`` when the expression does not
        statically encode a supported callable reference.
    """
    lineno = getattr(expr, "lineno", 0)
    col_offset = getattr(expr, "col_offset", 0)

    if isinstance(expr, ast.Name):
        return {
            "kind": "name",
            "target": expr.id,
            "lineno": lineno,
            "col_offset": col_offset,
            "ref_kind": kind,
        }

    if isinstance(expr, ast.Attribute):
        dotted = _attribute_path(expr)
        if dotted is None or "." not in dotted:
            return {
                "kind": "unresolved",
                "target": "",
                "lineno": lineno,
                "col_offset": col_offset,
                "ref_kind": kind,
            }

        base, target = dotted.rsplit(".", 1)
        return {
            "kind": "attribute",
            "base": base,
            "target": target,
            "lineno": lineno,
            "col_offset": col_offset,
            "ref_kind": kind,
        }

    return None


def _extract_call_records(node: ast.AST) -> list[dict[str, str | int]]:
    """
    Collect deterministic call-site records from a subtree.

    Parameters
    ----------
    node : ast.AST
        AST node whose descendants should be inspected.

    Returns
    -------
    list[dict[str, str | int]]
        Ordered call-site records with the static information available for
        later resolution.

    Notes
    -----
    Dynamic attribute receivers keep the known attribute name in the record.
    For example, ``factory().build()`` is stored as an attribute call targeting
    ``build`` with an empty base rather than collapsing to a fully unresolved
    placeholder.
    """
    calls: list[dict[str, str | int]] = []

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        func = child.func
        lineno, col_offset = _call_site_position(func, child)

        if isinstance(func, ast.Name):
            calls.append(
                {
                    "kind": "name",
                    "target": func.id,
                    "lineno": lineno,
                    "col_offset": col_offset,
                }
            )
            continue

        if isinstance(func, ast.Attribute):
            dotted = _attribute_path(func)
            if dotted is None:
                calls.append(
                    {
                        "kind": "attribute",
                        "base": "",
                        "target": func.attr,
                        "lineno": lineno,
                        "col_offset": col_offset,
                    }
                )
                continue

            if "." not in dotted:
                calls.append(
                    {
                        "kind": "attribute",
                        "base": "",
                        "target": func.attr,
                        "lineno": lineno,
                        "col_offset": col_offset,
                    }
                )
                continue

            base, target = dotted.rsplit(".", 1)
            calls.append(
                {
                    "kind": "attribute",
                    "base": base,
                    "target": target,
                    "lineno": lineno,
                    "col_offset": col_offset,
                }
            )
            continue

        calls.append(
            {
                "kind": "unresolved",
                "target": "",
                "lineno": lineno,
                "col_offset": col_offset,
            }
        )

    calls.sort(
        key=lambda call: (
            int(call.get("lineno", 0)),
            int(call.get("col_offset", 0)),
            str(call.get("kind", "")),
            str(call.get("base", "")),
            str(call.get("target", "")),
        )
    )
    return calls


def _reference_records_from_child(child: ast.AST) -> list[dict[str, str | int]]:
    """
    Collect callable-object reference records for one AST child.

    Parameters
    ----------
    child : ast.AST
        AST child node to inspect for direct callable-object values.

    Returns
    -------
    list[dict[str, str | int]]
        Callable-reference records extracted from the child node.
    """
    if isinstance(child, ast.Dict):
        return _reference_records_from_values(child.values, kind="mapping_value")

    if isinstance(child, (ast.List, ast.Tuple, ast.Set)):
        return _reference_records_from_values(child.elts, kind="sequence_item")

    if isinstance(child, ast.Assign):
        return _reference_records_from_optional_value(
            child.value,
            kind="assignment_value",
        )

    if isinstance(child, ast.AnnAssign) and child.value is not None:
        return _reference_records_from_optional_value(
            child.value,
            kind="assignment_value",
        )

    if isinstance(child, ast.Return) and child.value is not None:
        return _reference_records_from_optional_value(
            child.value,
            kind="return_value",
        )

    return []


def _reference_records_from_values(
    values: Sequence[ast.expr | None],
    *,
    kind: str,
) -> list[dict[str, str | int]]:
    """
    Collect callable-reference records from expression values.

    Parameters
    ----------
    values : collections.abc.Sequence[ast.expr | None]
        AST expression values to inspect.
    kind : str
        Reference kind assigned to emitted records.

    Returns
    -------
    list[dict[str, str | int]]
        Callable-reference records for expressions that resolve to callables.
    """
    refs: list[dict[str, str | int]] = []
    for value in values:
        if value is None:
            continue
        ref = _reference_record_from_expr(value, kind=kind)
        if ref is not None:
            refs.append(ref)
    return refs


def _reference_records_from_optional_value(
    value: ast.expr,
    *,
    kind: str,
) -> list[dict[str, str | int]]:
    """
    Collect a callable-reference record from one expression value.

    Parameters
    ----------
    value : ast.expr
        AST expression value to inspect.
    kind : str
        Reference kind assigned to the emitted record.

    Returns
    -------
    list[dict[str, str | int]]
        One callable-reference record when the expression resolves to a
        callable, otherwise an empty list.
    """
    ref = _reference_record_from_expr(value, kind=kind)
    if ref is None:
        return []
    return [ref]


def _extract_callable_refs(node: ast.AST) -> list[dict[str, str | int]]:
    """
    Collect deterministic callable-object reference records from a subtree.

    Parameters
    ----------
    node : ast.AST
        AST node whose descendants should be inspected.

    Returns
    -------
    list[dict[str, str | int]]
        Ordered callable-reference records for direct values such as registry
        entries, assignment values, and return values.
    """
    refs: list[dict[str, str | int]] = []

    for child in ast.walk(node):
        refs.extend(_reference_records_from_child(child))

    refs.sort(
        key=lambda ref: (
            int(ref.get("lineno", 0)),
            int(ref.get("col_offset", 0)),
            str(ref.get("kind", "")),
            str(ref.get("base", "")),
            str(ref.get("target", "")),
            str(ref.get("ref_kind", "")),
        )
    )
    return refs


def parse_file(path: Path, root: Path) -> dict[str, Any]:
    """
    Parse a Python file into indexable metadata.

    Parameters
    ----------
    path : pathlib.Path
        Python source file to parse.
    root : pathlib.Path
        Repository root used for module name derivation.

    Returns
    -------
    dict[str, Any]
        Parsed module, class, function, and import metadata ready for indexing.
    """
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=str(path))

    module_doc = ast.get_docstring(tree)

    result: dict[str, Any] = {
        "module": {
            "name": _module_name_from_path(path, root),
            "docstring": module_doc,
            "has_docstring": int(module_doc is not None),
        },
        "classes": [],
        "functions": [],
        "declarations": [],
        "imports": [],
    }
    pending_functions: dict[str, list[dict[str, str | int | None]]] = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_doc = ast.get_docstring(node)
            class_entry: dict[str, Any] = {
                "name": node.name,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
                "docstring": class_doc,
                "has_docstring": int(class_doc is not None),
                "methods": [],
            }
            pending_overloads: dict[str, list[dict[str, str | int | None]]] = {}

            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    _is_overload_stub(child)
                ):
                    pending_overloads.setdefault(child.name, []).append(
                        _overload_entry(child)
                    )
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = ast.get_docstring(child)
                    class_entry["methods"].append(
                        {
                            "name": child.name,
                            "lineno": child.lineno,
                            "end_lineno": getattr(child, "end_lineno", None),
                            "signature": _signature_text(child),
                            "docstring": method_doc,
                            "has_docstring": int(method_doc is not None),
                            "is_method": 1,
                            "is_public": _is_public(child.name),
                            "parameters": _parameter_names(child),
                            "returns_value": int(_returns_value(child)),
                            "yields_value": int(_yields_value(child)),
                            "raises": int(_raises_exception(child)),
                            "has_asserts": int(_has_asserts(child)),
                            "decorators": _decorator_names(child),
                            "calls": _extract_call_records(child),
                            "callable_refs": _extract_callable_refs(child),
                            "overloads": pending_overloads.pop(child.name, ()),
                        }
                    )

            result["classes"].append(class_entry)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_overload_stub(node):
                pending_functions.setdefault(node.name, []).append(
                    _overload_entry(node)
                )
            else:
                func_doc = ast.get_docstring(node)
                result["functions"].append(
                    {
                        "name": node.name,
                        "lineno": node.lineno,
                        "end_lineno": getattr(node, "end_lineno", None),
                        "signature": _signature_text(node),
                        "docstring": func_doc,
                        "has_docstring": int(func_doc is not None),
                        "is_method": 0,
                        "is_public": _is_public(node.name),
                        "parameters": _parameter_names(node),
                        "returns_value": int(_returns_value(node)),
                        "yields_value": int(_yields_value(node)),
                        "raises": int(_raises_exception(node)),
                        "has_asserts": int(_has_asserts(node)),
                        "decorators": _decorator_names(node),
                        "calls": _extract_call_records(node),
                        "callable_refs": _extract_callable_refs(node),
                        "overloads": pending_functions.pop(node.name, ()),
                    }
                )

        elif (
            _append_import_entries(result, node)
            or _append_type_alias_declaration(
                result,
                node,
                source,
            )
            or _append_constant_declaration(
                result,
                node,
                source,
            )
        ):
            continue

    return result
