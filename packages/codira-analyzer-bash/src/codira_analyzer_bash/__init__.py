"""Bash language analyzer backed by tree-sitter.

Responsibilities
----------------
- Initialize the tree-sitter Bash parser and derive module and function stable IDs.
- Walk parse nodes to extract normalized shell function artifacts.
- Translate the collected metadata into `AnalysisResult` objects for persistence.

Design principles
-----------------
The analyzer confines tree-sitter interaction to this module so language-specific
logic stays isolated and deterministic.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the shell
analysis path for Bash and POSIX-style `.sh` scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

from tree_sitter import Language, Node, Parser
from tree_sitter_bash import language

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.models import AnalysisResult, CallSite, FunctionArtifact, ModuleArtifact

_BASH_SUFFIXES = {".sh", ".bash"}
_LANGUAGE = Language(language())
__all__ = ["BashAnalyzer", "build_analyzer"]


def _new_parser() -> Parser:
    """
    Create a parser configured for the Bash grammar.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser configured for ``tree-sitter-bash``.
    """
    return Parser(_LANGUAGE)


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive the logical module name for one shell source path.

    Parameters
    ----------
    path : pathlib.Path
        Source file being analyzed.
    root : pathlib.Path
        Repository root used for relative module naming.

    Returns
    -------
    str
        Dotted module identity derived from the relative file path.
    """
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


def _module_stable_id(path: Path, root: Path) -> str:
    """
    Build the durable identity for one shell module.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable shell module identity.
    """
    return f"bash:module:{path.relative_to(root).as_posix()}"


def _function_stable_id(module_name: str, function_name: str) -> str:
    """
    Build the durable identity for one shell function.

    Parameters
    ----------
    module_name : str
        Dotted owner module name.
    function_name : str
        Unqualified function name.

    Returns
    -------
    str
        Durable shell function identity.
    """
    return f"bash:function:{module_name}:{function_name}"


def _node_text(node: Node, source: bytes) -> str:
    """
    Decode the source text owned by one syntax node.

    Parameters
    ----------
    node : tree_sitter.Node
        Syntax node whose text should be decoded.
    source : bytes
        Full source buffer.

    Returns
    -------
    str
        Decoded UTF-8 node text.
    """
    return source[node.start_byte : node.end_byte].decode("utf-8")


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
    stack = list(reversed(node.named_children))

    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(reversed(current.named_children))

    return descendants


def _extract_calls(body: Node | None, source: bytes) -> tuple[CallSite, ...]:
    """
    Extract normalized command invocations from one shell function body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Node owning the function body.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Call records in deterministic source order.
    """
    if body is None:
        return ()

    calls: list[CallSite] = []

    for node in _named_descendants(body):
        if node.type != "command":
            continue

        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue

        target = _node_text(name_node, source).strip()
        if not target:
            continue

        calls.append(
            CallSite(
                kind="name",
                target=target,
                lineno=name_node.start_point.row + 1,
                col_offset=name_node.start_point.column,
            )
        )

    return tuple(calls)


def _extract_functions(
    root: Node,
    source: bytes,
    *,
    module_name: str,
) -> tuple[FunctionArtifact, ...]:
    """
    Extract top-level shell function definitions from one source file.

    Parameters
    ----------
    root : tree_sitter.Node
        Parse-tree root node.
    source : bytes
        Full source buffer.
    module_name : str
        Dotted owner module name.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Deterministic function artifacts ordered by source position.
    """
    functions_by_name: dict[str, FunctionArtifact] = {}

    for child in root.children:
        if child.type != "function_definition":
            continue

        name_node = child.child_by_field_name("name")
        body = child.child_by_field_name("body")
        if name_node is None:
            continue

        name = _node_text(name_node, source).strip()
        if not name:
            continue

        signature_end = body.start_byte if body is not None else child.end_byte
        signature = source[child.start_byte : signature_end].decode("utf-8").strip()

        functions_by_name[name] = FunctionArtifact(
            name=name,
            stable_id=_function_stable_id(module_name, name),
            lineno=child.start_point.row + 1,
            end_lineno=body.end_point.row + 1 if body is not None else None,
            signature=" ".join(signature.split()),
            docstring=None,
            has_docstring=0,
            is_method=0,
            is_public=1,
            parameters=(),
            returns_value=0,
            yields_value=0,
            raises=0,
            has_asserts=0,
            decorators=(),
            calls=_extract_calls(body, source),
            callable_refs=(),
        )

    return tuple(
        sorted(
            functions_by_name.values(),
            key=lambda artifact: artifact.lineno,
        )
    )


class BashAnalyzer:
    """
    Concrete Bash analyzer for repository indexing.

    Parameters
    ----------
    None

    Notes
    -----
    This analyzer is backed by ``tree-sitter-bash`` so shell extraction work
    can evolve from a real parse tree instead of regex heuristics.
    """

    name = "bash"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.sh", "*.bash")

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return Bash analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from Bash artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_bash:build_analyzer",
            supports=("module", "callable"),
            does_not_support=(
                "type",
                "import",
                "constant",
                "variable",
                "namespace",
            ),
            mappings={
                "module": "module",
                "function": "callable",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a shell source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file is a ``.sh`` or ``.bash`` source file.
        """
        return path.suffix in _BASH_SUFFIXES

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one shell source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Shell source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        source = path.read_bytes()
        root_node = _new_parser().parse(source).root_node
        module_name = _module_name_for_path(path, root)
        return AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=module_name,
                stable_id=_module_stable_id(path, root),
                docstring=None,
                has_docstring=0,
            ),
            classes=(),
            functions=_extract_functions(
                root_node,
                source,
                module_name=module_name,
            ),
            declarations=(),
            imports=(),
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party Bash analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        First-party Bash analyzer instance.
    """
    return BashAnalyzer()
