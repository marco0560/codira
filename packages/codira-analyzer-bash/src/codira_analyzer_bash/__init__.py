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

from dataclasses import replace
from collections import Counter
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

from tree_sitter import Language, Node, Parser
from tree_sitter_bash import language

from codira_analyzer_bash.bash_syntax import bash_parse_root

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    FunctionArtifact,
    ModuleArtifact,
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

_BASH_SUFFIXES = {".sh", ".bash"}
_LANGUAGE = Language(language())
_SHELL_BUILTINS = frozenset(
    {
        ".",
        "[",
        ":",
        "alias",
        "bg",
        "break",
        "cd",
        "command",
        "continue",
        "declare",
        "echo",
        "eval",
        "exec",
        "exit",
        "export",
        "fg",
        "getopts",
        "hash",
        "jobs",
        "local",
        "printf",
        "pwd",
        "read",
        "readonly",
        "return",
        "set",
        "shift",
        "source",
        "test",
        "trap",
        "type",
        "ulimit",
        "umask",
        "unalias",
        "unset",
        "wait",
    }
)
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
        ancestor = node.parent
        nested = False
        while ancestor is not None and ancestor != body:
            if ancestor.type == "function_definition":
                nested = True
                break
            if (
                ancestor.type == "command_substitution"
                and source[ancestor.start_byte : ancestor.start_byte + 2] == b"$("
            ):
                before = ancestor.start_byte - 1
                while before >= 0 and source[before] == ord("\\"):
                    before -= 1
                if (ancestor.start_byte - before - 1) % 2:
                    nested = True
                    break
            ancestor = ancestor.parent
        if nested:
            continue
        if node.type == "unset_command":
            calls.append(
                CallSite(
                    kind="name",
                    target="unset",
                    lineno=node.start_point.row + 1,
                    col_offset=node.start_point.column,
                    external_target_kind="Bash:<builtin>",
                    external_target_name="unset",
                )
            )
            continue
        if (
            node.type == "test_command"
            and source[node.start_byte : node.start_byte + 2] != b"[["
        ):
            calls.append(
                CallSite(
                    kind="name",
                    target="[",
                    lineno=node.start_point.row + 1,
                    col_offset=node.start_point.column,
                    external_target_kind="Bash:<builtin>",
                    external_target_name="[",
                )
            )
            continue
        if node.type != "command":
            continue

        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue

        target = _node_text(name_node, source).strip()
        if not target:
            continue
        if (
            re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", target)
            and source[name_node.end_byte : name_node.end_byte + 1] == b"="
        ):
            continue

        external_target_kind = (
            "Bash:<builtin>" if target in _SHELL_BUILTINS else "Bash:<external>"
        )
        calls.append(
            CallSite(
                kind="name",
                target=target,
                lineno=name_node.start_point.row + 1,
                col_offset=name_node.start_point.column,
                external_target_kind=external_target_kind,
                external_target_name=target,
            )
        )

    additional = _heredoc_calls(body, source)
    existing = {(call.target, call.lineno, call.col_offset) for call in calls}
    missing: list[CallSite] = []
    for call in additional:
        key = (call.target, call.lineno, call.col_offset)
        if key not in existing:
            missing.append(call)
            existing.add(key)
    if missing:
        calls.extend(missing)
        calls.sort(key=lambda call: (call.lineno, call.col_offset, call.target))
    return tuple(calls)


def _heredoc_calls(body: Node, source: bytes) -> tuple[CallSite, ...]:
    """Recover complete command substitutions from expanding heredoc content.

    Parameters
    ----------
    body : tree_sitter.Node
        Lexical function body with provider-recognized heredoc content.
    source : bytes
        Original bytes used for every command name and physical coordinate.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Complete substitution calls, deduplicated by the caller.

    Notes
    -----
    Quoted delimiters and escaped dollar signs remain literal. A fragment is
    eligible only when its first substitution is complete and error-free.
    Parsing never executes shell code.
    """
    calls: list[CallSite] = []
    for node in _named_descendants(body):
        if node.type != "heredoc_body":
            continue
        ancestor = node.parent
        redirect: Node | None = None
        nested_function = False
        while ancestor is not None and ancestor != body:
            if ancestor.type == "function_definition":
                nested_function = True
                break
            if ancestor.type == "heredoc_redirect":
                redirect = ancestor
            ancestor = ancestor.parent
        if nested_function or redirect is None:
            continue
        delimiter = next(
            (n for n in redirect.named_children if n.type == "heredoc_start"), None
        )
        if delimiter is None or any(
            byte in _node_text(delimiter, source) for byte in "'\"\\"
        ):
            continue
        content = source[node.start_byte : node.end_byte]
        heredoc = next(
            (n for n in redirect.named_children if n.type == "heredoc_body"), None
        )
        if heredoc is None:
            continue
        for match in re.finditer(rb"\$\(", content):
            start = node.start_byte + match.start()
            before = start - 1
            while before >= node.start_byte and source[before] == ord("\\"):
                before -= 1
            if (start - before - 1) % 2:
                continue
            probe = b"echo " + source[start : heredoc.end_byte]
            tree = _new_parser().parse(probe).root_node
            substitution = next(
                (
                    n
                    for n in _named_descendants(tree)
                    if n.type == "command_substitution"
                    and n.start_byte == 5
                    and not n.has_error
                ),
                None,
            )
            if substitution is None:
                continue
            line_starts = [0]
            for index, byte in enumerate(probe):
                if byte == ord("\n"):
                    line_starts.append(index + 1)
            for call in _extract_calls(substitution, probe):
                offset = start + line_starts[call.lineno - 1] + call.col_offset - 5
                line = source.count(b"\n", 0, offset) + 1
                column = offset - source.rfind(b"\n", 0, offset) - 1
                calls.append(replace(call, lineno=line, col_offset=column))
    return tuple(calls)


def _extract_functions(
    root: Node,
    source: bytes,
    *,
    module_name: str,
) -> tuple[FunctionArtifact, ...]:
    """
    Extract lexical functions with the established direct-definition policy.

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

    Notes
    -----
    Direct program definitions keep the last occurrence of each name, matching
    the existing analyzer contract. Conditional and nested definitions remain
    explicit variants; no execution branch is selected.
    """
    functions: list[FunctionArtifact] = []
    last_direct: dict[str, Node] = {}
    for child in root.named_children:
        name_node = child.child_by_field_name("name")
        if child.type == "function_definition" and name_node is not None:
            last_direct[_node_text(name_node, source).strip()] = child

    for child in _named_descendants(root):
        if child.type != "function_definition":
            continue

        name_node = child.child_by_field_name("name")
        body = child.child_by_field_name("body")
        if name_node is None:
            continue

        name = _node_text(name_node, source).strip()
        if not name:
            continue
        if child.parent == root and last_direct.get(name) != child:
            continue

        signature_end = body.start_byte if body is not None else child.end_byte
        signature = source[child.start_byte : signature_end].decode("utf-8").strip()

        functions.append(
            FunctionArtifact(
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
        )

    counts = Counter(function.stable_id for function in functions)
    occurrences: Counter[str] = Counter()
    distinct: list[FunctionArtifact] = []
    for function in functions:
        if counts[function.stable_id] > 1:
            occurrences[function.stable_id] += 1
            function = replace(
                function,
                stable_id=f"{function.stable_id}:definition:{function.lineno}:{occurrences[function.stable_id]}",
            )
        distinct.append(function)
    return tuple(
        sorted(
            distinct,
            key=lambda artifact: artifact.lineno,
        )
    )


class BashAnalyzer:
    """
    Concrete Bash analyzer for repository indexing.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances provide syntax-only shell extraction.

    Notes
    -----
    Isolated Tree-sitter parses and source-owned views retain written functions
    and lexical command sites without executing shell code.
    """

    name = "bash"
    version = "3"
    discovery_globs: tuple[str, ...] = ("*.sh", "*.bash")
    default_coverage_roots: tuple[str, ...] = ("scripts",)

    def __init__(self) -> None:
        self._path_filters = AnalyzerPathFilters()
        self._emit_functions = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the Bash analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for Bash analyzer options.
        """

        return analyzer_json_schema({"emit_functions": boolean_property(True)})

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply Bash analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.
        """

        self._path_filters = analyzer_path_filters_from_config(config)
        self._emit_functions = bool(config.get("emit_functions", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

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
                "documentation",
            ),
            mappings={
                "module": "module",
                "function": "callable",
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

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported shell path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the path is allowed by include/exclude filters.
        """

        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

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
        root_node = bash_parse_root(_new_parser(), source)
        module_name = _module_name_for_path(path, root)
        return replace(
            AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=module_name,
                    stable_id=_module_stable_id(path, root),
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(
                    _extract_functions(root_node, source, module_name=module_name)
                    if self._emit_functions
                    else ()
                ),
                declarations=(),
                imports=(),
            ),
            index_symbols=not root_node.has_error,
            status=tree_sitter_recovery_status(
                language="bash", has_error=root_node.has_error
            ),
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
