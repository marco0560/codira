"""C++ include extraction helpers.

Responsibilities
----------------
- Extract local and system include directives from C++ parse trees.
- Return deterministic package-model import artifacts.

Architectural role
------------------
This module owns include syntax translation and has no analyzer lifecycle or
configuration responsibilities.
"""

from __future__ import annotations

from tree_sitter import Node

from codira.models import ImportArtifact, ImportKind

from .cpp_syntax import _node_text


def _extract_imports(root: Node, source: bytes) -> tuple[ImportArtifact, ...]:
    """
    Extract include rows from one translation unit.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[codira.models.ImportArtifact, ...]
        Deterministic include rows ordered by source position.
    """
    imports: list[ImportArtifact] = []
    for child in root.children:
        if child.type != "preproc_include":
            continue
        include_target = None
        include_kind: ImportKind = "include_local"
        for named_child in child.named_children:
            if named_child.type == "string_literal":
                include_target = _node_text(named_child, source).strip('"')
                include_kind = "include_local"
                break
            if named_child.type == "system_lib_string":
                include_target = _node_text(named_child, source).strip("<>")
                include_kind = "include_system"
                break
        if include_target is None:
            continue
        imports.append(
            ImportArtifact(
                name=include_target,
                alias=None,
                lineno=child.start_point.row + 1,
                kind=include_kind,
            )
        )
    return tuple(imports)
