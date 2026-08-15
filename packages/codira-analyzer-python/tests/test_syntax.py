"""Tests for the Python analyzer's normalized Tree-sitter syntax contract."""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json

from codira_analyzer_python.syntax import (
    SyntaxDiagnosticKind,
    SyntaxKind,
    SyntaxNode,
    parse_python_source,
)


def _walk(node: SyntaxNode) -> tuple[SyntaxNode, ...]:
    """Return one normalized tree's nodes in deterministic preorder.

    Parameters
    ----------
    node : SyntaxNode
        Root node to traverse.

    Returns
    -------
    tuple[SyntaxNode, ...]
        Root and all named descendants in source order.
    """
    return (node,) + tuple(
        descendant for child in node.children for descendant in _walk(child)
    )


def test_normalized_syntax_maps_golden_fixture_constructs() -> None:
    """Map characterization-fixture constructs without provider node names.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts normalized kinds cover the characterization constructs.
    """
    source = (
        "import os.path as paths\n"
        "MAXIMUM = 3\n"
        "Alias: type = dict[str, int]\n"
        "\n"
        "def helper(item: int) -> str:\n"
        "    if item:\n"
        "        raise ValueError(item)\n"
        "    return paths.join(str(item))\n"
        "\n"
        "class Worker:\n"
        "    def run(self) -> str:\n"
        "        return helper(1)\n"
    )

    parsed = parse_python_source(source)
    kinds = {node.kind for node in _walk(parsed.root)}
    serialized = json.dumps(asdict(parsed.root), default=str)

    assert parsed.diagnostics == ()
    assert {
        SyntaxKind.MODULE,
        SyntaxKind.IMPORT,
        SyntaxKind.ASSIGNMENT,
        SyntaxKind.FUNCTION,
        SyntaxKind.CLASS,
        SyntaxKind.IF,
        SyntaxKind.RAISE,
        SyntaxKind.RETURN,
        SyntaxKind.CALL,
    } <= kinds
    assert "function_definition" not in serialized
    assert "class_definition" not in serialized


def test_normalized_syntax_preserves_utf8_byte_and_line_spans() -> None:
    """Keep source locations in UTF-8 bytes, including Unicode identifiers.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts byte offsets and line locations remain deterministic.
    """
    source = "α = call('é')\n"

    parsed = parse_python_source(source)
    nodes = _walk(parsed.root)
    identifier = next(node for node in nodes if node.kind is SyntaxKind.IDENTIFIER)
    call = next(node for node in nodes if node.kind is SyntaxKind.CALL)

    assert parse_python_source(source.encode("utf-8")) == parsed
    assert parsed.root.start_byte == 0
    assert parsed.root.end_byte == len(source.encode("utf-8"))
    assert identifier.start_byte == 0
    assert identifier.end_byte == 2
    assert identifier.start_line == identifier.end_line == 1
    assert identifier.start_column == 0
    assert identifier.end_column == 2
    assert call.start_byte == 5
    assert call.start_column == 5


def test_normalized_syntax_reports_error_recovery_deterministically() -> None:
    """Expose deterministic normalized diagnostics for malformed source.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts error recovery diagnostics have stable locations.
    """
    source = "x = (\n"

    first = parse_python_source(source)
    second = parse_python_source(source)

    assert first == second
    assert first.diagnostics == (first.diagnostics[0],)
    assert first.diagnostics[0].kind is SyntaxDiagnosticKind.ERROR
    assert first.diagnostics[0].start_byte == 0
    assert first.diagnostics[0].end_byte == 5
    assert first.diagnostics[0].start_line == first.diagnostics[0].end_line == 1


def test_normalized_syntax_reports_missing_nodes_deterministically() -> None:
    """Expose inserted missing nodes as location-stable diagnostics.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts missing-node diagnostics have stable locations.
    """
    source = "match value:\n    case:\n"

    first = parse_python_source(source)
    second = parse_python_source(source)

    assert first == second
    assert first.diagnostics == (first.diagnostics[0],)
    assert first.diagnostics[0].kind is SyntaxDiagnosticKind.MISSING
    assert first.diagnostics[0].start_byte == first.diagnostics[0].end_byte == 21
    assert first.diagnostics[0].start_line == first.diagnostics[0].end_line == 2
    assert first.diagnostics[0].start_column == first.diagnostics[0].end_column == 8


def test_normalized_syntax_matches_host_ast_only_in_characterization_test() -> None:
    """Characterize key constructs against host AST without using it in production.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts equivalent key construct counts for valid source.
    """
    source = (
        "import package\n"
        "VALUE = 3\n"
        "def run(value):\n"
        "    return helper(value)\n"
        "class Worker:\n"
        "    pass\n"
    )
    host_tree = ast.parse(source)
    parsed = parse_python_source(source)
    kinds = [node.kind for node in _walk(parsed.root)]

    assert sum(
        isinstance(node, ast.Import) for node in ast.walk(host_tree)
    ) == kinds.count(SyntaxKind.IMPORT)
    assert sum(
        isinstance(node, ast.Assign) for node in ast.walk(host_tree)
    ) == kinds.count(SyntaxKind.ASSIGNMENT)
    assert sum(
        isinstance(node, ast.FunctionDef) for node in ast.walk(host_tree)
    ) == kinds.count(SyntaxKind.FUNCTION)
    assert sum(
        isinstance(node, ast.ClassDef) for node in ast.walk(host_tree)
    ) == kinds.count(SyntaxKind.CLASS)
    assert sum(
        isinstance(node, ast.Call) for node in ast.walk(host_tree)
    ) == kinds.count(SyntaxKind.CALL)


def test_normalized_syntax_is_reentrant_for_threaded_analysis() -> None:
    """Create isolated parsers so concurrent analysis yields equal results.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts concurrent parses return equivalent syntax trees.
    """
    source = "def run(value: int) -> int:\n    return value + 1\n"

    with ThreadPoolExecutor(max_workers=8) as executor:
        parsed = tuple(executor.map(parse_python_source, (source,) * 32))

    assert parsed == (parsed[0],) * len(parsed)


def test_core_does_not_depend_on_python_tree_sitter_binding() -> None:
    """Keep the grammar binding confined to the Python analyzer distribution.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts core source omits the Python grammar dependency.
    """
    from pathlib import Path

    core_root = Path(__file__).resolve().parents[4] / "src" / "codira"
    core_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(core_root.rglob("*.py"))
    )

    assert "tree_sitter_python" not in core_source
    assert "tree-sitter-python" not in core_source
