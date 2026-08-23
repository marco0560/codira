"""Deterministic syntax-only JavaScript and JSX analyzer for Codira.

The analyzer deliberately models source syntax only. It does not execute code,
load Node modules, or assign framework-specific meaning to JSX.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from tree_sitter import Language, Node, Parser
from tree_sitter_javascript import language

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    CallableReference,
    CallSite,
    ClassArtifact,
    DeclarationArtifact,
    DocumentationArtifact,
    FunctionArtifact,
    ImportArtifact,
    ModuleArtifact,
)
from codira.plugin_config import (
    AnalyzerPathFilters,
    analyzer_json_schema,
    analyzer_path_allowed,
    analyzer_path_filters_from_config,
    boolean_property,
    plugin_configuration_fingerprint,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

_LANGUAGE = Language(language())
_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs"})
_SPACE = re.compile(r"\s+")
_JSDOC = re.compile(r"/\*\*(?!\*)(.*?)\*/", re.DOTALL)
__all__ = ["JavaScriptAnalyzer", "build_analyzer"]


def _parser() -> Parser:
    """Create a JavaScript grammar parser.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser configured with the JavaScript and JSX grammar.
    """
    return Parser(_LANGUAGE)


def _text(node: Node | None, source: bytes) -> str:
    """Decode one source node.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Node whose bytes are decoded.
    source : bytes
        Complete UTF-8 source buffer.

    Returns
    -------
    str
        Node text, or an empty string when no node is supplied.
    """
    return (
        ""
        if node is None
        else source[node.start_byte : node.end_byte].decode("utf-8", "replace")
    )


def _normalized(node: Node | None, source: bytes) -> str:
    """Render one node on a normalized line.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Node to render.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str
        Whitespace-collapsed source text.
    """
    return _SPACE.sub(" ", _text(node, source)).strip()


def _descendants(node: Node) -> Iterable[Node]:
    """Yield named descendants in source order.

    Parameters
    ----------
    node : tree_sitter.Node
        Tree root to traverse.

    Returns
    -------
    collections.abc.Iterable[tree_sitter.Node]
        Depth-first named nodes.
    """
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _module_name(path: Path, root: Path) -> str:
    """Derive a dotted JavaScript module name.

    Parameters
    ----------
    path : pathlib.Path
        JavaScript source path.
    root : pathlib.Path
        Repository root.

    Returns
    -------
    str
        Dotted repository-relative module name.
    """
    return ".".join(path.relative_to(root).with_suffix("").parts)


def _owner(path: Path, root: Path) -> str:
    """Return the source-relative stable-id owner.

    Parameters
    ----------
    path : pathlib.Path
        JavaScript source path.
    root : pathlib.Path
        Repository root.

    Returns
    -------
    str
        POSIX repository-relative path.
    """
    return path.relative_to(root).as_posix()


def _parameters(node: Node | None, source: bytes) -> tuple[str, ...]:
    """Extract syntactic parameter bindings.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Formal-parameter node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[str, ...]
        Parameter source fragments in declaration order.
    """
    if node is None:
        return ()
    names: list[str] = []
    for child in node.named_children:
        if child.type == "identifier":
            names.append(_normalized(child, source))
            continue
        name = child.child_by_field_name("left") or child.child_by_field_name("name")
        if name is None and child.named_children:
            name = child.named_children[0]
        names.append(_normalized(name or child, source))
    return tuple(names)


def _call_target(
    node: Node, source: bytes
) -> tuple[Literal["name", "attribute", "unresolved"], str, str]:
    """Classify a JavaScript call target without resolution.

    Parameters
    ----------
    node : tree_sitter.Node
        Called expression node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[str, str, str]
        Call kind, terminal target, and optional static receiver.
    """
    text = _normalized(node, source)
    if node.type == "identifier":
        return "name", text, ""
    if node.type in {"member_expression", "subscript_expression", "optional_chain"}:
        object_node = node.child_by_field_name("object")
        property_node = node.child_by_field_name("property")
        if property_node is not None:
            return (
                "attribute",
                _normalized(property_node, source),
                _normalized(object_node, source),
            )
    return "unresolved", text, ""


def _calls(body: Node | None, source: bytes) -> tuple[CallSite, ...]:
    """Extract direct syntactic calls while excluding nested declarations.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Callable body node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Ordered call artifacts.
    """
    if body is None:
        return ()
    calls: list[CallSite] = []

    def visit(current: Node) -> None:
        """Traverse one body node without crossing callable boundaries.

        Parameters
        ----------
        current : tree_sitter.Node
            Current syntax node.

        Returns
        -------
        None
            Call records are appended to the enclosing list.
        """
        if current is not body and current.type in {
            "function_declaration",
            "generator_function_declaration",
            "arrow_function",
            "function_expression",
            "method_definition",
            "class_declaration",
            "class",
        }:
            return
        if current.type == "call_expression":
            function = current.child_by_field_name("function")
            if function is not None:
                kind, target, base = _call_target(function, source)
                calls.append(
                    CallSite(
                        kind=kind,
                        target=target,
                        lineno=function.start_point.row + 1,
                        col_offset=function.start_point.column,
                        base=base,
                        external_target_kind="javascript_expression"
                        if kind == "unresolved"
                        else None,
                        external_target_name=target if kind == "unresolved" else None,
                    )
                )
        for child in current.named_children:
            visit(child)

    visit(body)
    return tuple(calls)


def _callable_refs(body: Node | None, source: bytes) -> tuple[CallableReference, ...]:
    """Extract callable-object references from a JavaScript callable body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Callable body node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[codira.models.CallableReference, ...]
        Ordered syntactic callable references without semantic inference.
    """
    if body is None:
        return ()
    refs: list[CallableReference] = []

    def append(value: Node | None, ref_kind: str) -> None:
        """Append one supported callable-valued expression.

        Parameters
        ----------
        value : tree_sitter.Node | None
            Candidate identifier or member expression.
        ref_kind : str
            Stable owning-expression classifier.

        Returns
        -------
        None
            A normalized reference appends when the expression is supported.
        """
        if value is None or value.type not in {"identifier", "member_expression"}:
            return
        kind, target, base = _call_target(value, source)
        refs.append(
            CallableReference(
                kind=kind,
                target=target,
                lineno=value.start_point.row + 1,
                col_offset=value.start_point.column,
                ref_kind=cast(
                    'Literal["mapping_value", "sequence_item", "assignment_value", "return_value"]',
                    ref_kind,
                ),
                base=base,
                external_target_kind="javascript_expression"
                if kind == "unresolved"
                else None,
                external_target_name=target if kind == "unresolved" else None,
            )
        )

    def visit(current: Node) -> None:
        """Traverse body nodes without entering nested callable declarations.

        Parameters
        ----------
        current : tree_sitter.Node
            Current syntax node.

        Returns
        -------
        None
            Reference artifacts append in source order.
        """
        if current is not body and current.type in {
            "function_declaration",
            "generator_function_declaration",
            "arrow_function",
            "function_expression",
            "method_definition",
            "class_declaration",
            "class",
        }:
            return
        if current.type in {"variable_declarator", "assignment_expression"}:
            append(
                current.child_by_field_name("value")
                or current.child_by_field_name("right"),
                "assignment_value",
            )
        elif current.type == "return_statement":
            argument = current.child_by_field_name("argument")
            if argument is None and current.named_children:
                argument = current.named_children[0]
            append(argument, "return_value")
        elif current.type == "pair":
            append(current.child_by_field_name("value"), "mapping_value")
        elif current.type == "array":
            for child in current.named_children:
                append(child, "sequence_item")
            return
        for child in current.named_children:
            visit(child)

    visit(body)
    return tuple(refs)


def _function(
    node: Node,
    source: bytes,
    *,
    owner: str,
    name: str | None = None,
    owner_name: str | None = None,
) -> FunctionArtifact | None:
    """Build a function, arrow-function, or method artifact.

    Parameters
    ----------
    node : tree_sitter.Node
        Callable syntax node.
    source : bytes
        Complete source buffer.
    owner : str
        Source-relative stable-id owner.
    name : str | None, optional
        Assigned callable name when the grammar node is anonymous.
    owner_name : str | None, optional
        Owning class name for a method.

    Returns
    -------
    codira.models.FunctionArtifact | None
        Normalized callable, or ``None`` for an anonymous expression.
    """
    function_name = name or _normalized(node.child_by_field_name("name"), source)
    if not function_name:
        return None
    parameters = _parameters(node.child_by_field_name("parameters"), source)
    if not parameters and node.type == "arrow_function":
        parameters = tuple(
            _normalized(child, source)
            for child in node.named_children
            if child.type in {"identifier", "object_pattern", "array_pattern"}
        )
    body = node.child_by_field_name("body")
    if body is None and node.named_children:
        body = node.named_children[-1]
    signature_end = body.start_byte if body is not None else node.end_byte
    signature = _SPACE.sub(
        " ", source[node.start_byte : signature_end].decode("utf-8", "replace")
    ).strip()
    kind = "method" if owner_name else "function"
    stable_owner = f":{owner_name}" if owner_name else ""
    return FunctionArtifact(
        name=function_name,
        stable_id=f"javascript:{kind}:{owner}{stable_owner}:{function_name}",
        lineno=node.start_point.row + 1,
        end_lineno=body.end_point.row + 1
        if body is not None
        else node.end_point.row + 1,
        signature=signature,
        docstring=None,
        has_docstring=0,
        is_method=int(owner_name is not None),
        is_public=int(not function_name.startswith("_")),
        parameters=parameters,
        returns_value=int(
            any(item.type == "return_statement" for item in _descendants(body))
            if body is not None
            else 0
        ),
        yields_value=int(
            any(item.type == "yield_expression" for item in _descendants(body))
            if body is not None
            else 0
        ),
        raises=int(
            any(item.type == "throw_statement" for item in _descendants(body))
            if body is not None
            else 0
        ),
        has_asserts=0,
        decorators=(),
        calls=_calls(body, source),
        callable_refs=_callable_refs(body, source),
    )


def _import(node: Node, source: bytes) -> ImportArtifact:
    """Build a module import artifact.

    Parameters
    ----------
    node : tree_sitter.Node
        Import statement node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    codira.models.ImportArtifact
        Source module with no inferred local alias.
    """
    target = _text(node.child_by_field_name("source"), source).strip("'\"")
    return ImportArtifact(name=target, alias=None, lineno=node.start_point.row + 1)


def _jsdoc_blocks(source: bytes) -> tuple[tuple[int, int, str], ...]:
    """Return cleaned explicit JSDoc blocks with byte spans.

    Parameters
    ----------
    source : bytes
        Complete UTF-8 source buffer.

    Returns
    -------
    tuple[tuple[int, int, str], ...]
        Ordered start byte, end byte, and cleaned JSDoc text.
    """
    text = source.decode("utf-8", "replace")
    return tuple(
        (
            len(text[: match.start()].encode()),
            len(text[: match.end()].encode()),
            "\n".join(
                line.strip().removeprefix("*").lstrip()
                for line in match.group(1).splitlines()
            ).strip(),
        )
        for match in _JSDOC.finditer(text)
    )


def _attached_jsdoc(
    node: Node, source: bytes, blocks: tuple[tuple[int, int, str], ...]
) -> tuple[int, int, str] | None:
    """Find the immediately preceding explicit JSDoc block.

    Parameters
    ----------
    node : tree_sitter.Node
        Declared syntax node.
    source : bytes
        Complete source buffer.
    blocks : tuple[tuple[int, int, str], ...]
        Previously located JSDoc blocks.

    Returns
    -------
    tuple[int, int, str] | None
        Attached block, or ``None`` when whitespace adjacency is absent.
    """
    for block in reversed(blocks):
        if block[1] > node.start_byte:
            continue
        if source[block[1] : node.start_byte].strip() == b"":
            return block
        return None
    return None


class JavaScriptAnalyzer:
    """Analyze JavaScript and JSX syntax into immutable Codira artifacts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances retain only configurable path and emission options.
    """

    name = "javascript"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.js", "*.jsx", "*.mjs", "*.cjs")
    default_coverage_roots: tuple[str, ...] = (
        "src",
        "lib",
        "app",
        "pages",
        "test",
        "tests",
        "scripts",
    )

    def __init__(self) -> None:
        """Initialize default JavaScript analysis settings.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Default filters and emission flags are installed.
        """
        self._path_filters = AnalyzerPathFilters()
        self._emit_variables = True
        self._emit_jsdoc_documentation = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """Return the strict JavaScript plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Shared filters and JavaScript emission options.
        """
        return analyzer_json_schema(
            {
                "emit_variables": boolean_property(True),
                "emit_jsdoc_documentation": boolean_property(True),
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply JavaScript analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced plugin configuration.

        Returns
        -------
        None
            Filters, emission flags, and the provenance fingerprint update.
        """
        self._path_filters = analyzer_path_filters_from_config(config)
        self._emit_variables = bool(config.get("emit_variables", True))
        self._emit_jsdoc_documentation = bool(
            config.get("emit_jsdoc_documentation", True)
        )
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """Declare JavaScript ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit syntax-only JavaScript capability mapping.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_javascript:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "variable",
                "namespace",
                "documentation",
            ),
            does_not_support=("constant",),
            mappings={
                "module": "module",
                "class": "type",
                "function": "callable",
                "arrow_function": "callable",
                "method": "callable",
                "import": "import",
                "variable": "variable",
                "export_namespace": "namespace",
                "jsdoc": "documentation",
            },
        )

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """Declare parser reentrancy and worker safety.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Safe process and thread execution declaration.
        """
        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """Return whether the path has a supported JavaScript suffix.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for JavaScript or JSX extensions only.
        """
        return path.suffix.lower() in _SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """Apply shared path filters to a JavaScript path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        bool
            Whether shared plugin filters include the path.
        """
        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """Analyze one JavaScript or JSX file without runtime evaluation.

        Parameters
        ----------
        path : pathlib.Path
            JavaScript or JSX source file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Deterministically ordered syntax artifacts and JSDoc attachments.
        """
        source = path.read_bytes()
        owner = _owner(path, root)
        blocks = _jsdoc_blocks(source)
        classes: list[ClassArtifact] = []
        functions: list[FunctionArtifact] = []
        declarations: list[DeclarationArtifact] = []
        imports: list[ImportArtifact] = []
        documentation: list[DocumentationArtifact] = []

        def attach(
            item: FunctionArtifact | ClassArtifact | DeclarationArtifact,
            node: Node,
            kind: str,
        ) -> FunctionArtifact | ClassArtifact | DeclarationArtifact:
            """Attach adjacent JSDoc and emit its provenance artifact.

            Parameters
            ----------
            item : codira.models.FunctionArtifact | codira.models.ClassArtifact | codira.models.DeclarationArtifact
                Semantic item receiving documentation.
            node : tree_sitter.Node
                Source node used for attachment adjacency.
            kind : str
                Owner classifier recorded in documentation provenance.

            Returns
            -------
            codira.models.FunctionArtifact | codira.models.ClassArtifact | codira.models.DeclarationArtifact
                Original item or an immutable documented replacement.
            """
            block = _attached_jsdoc(node, source, blocks)
            if block is None or not self._emit_jsdoc_documentation:
                return item
            documentation.append(
                DocumentationArtifact(
                    stable_id=f"doc:jsdoc:{item.stable_id}:{block[0]}",
                    kind="declaration",
                    source_format="jsdoc",
                    source_path=path,
                    lineno=source[: block[0]].count(b"\n") + 1,
                    end_lineno=source[: block[1]].count(b"\n") + 1,
                    title=item.name,
                    heading_path=(),
                    text=block[2],
                    owner_stable_id=item.stable_id,
                    owner_kind=kind,
                    attachment_confidence="explicit",
                )
            )
            if isinstance(item, FunctionArtifact):
                return replace(item, docstring=block[2], has_docstring=1)
            if isinstance(item, ClassArtifact):
                return replace(item, docstring=block[2], has_docstring=1)
            return replace(item, docstring=block[2])

        def analyze_statement(node: Node) -> None:
            """Extract one top-level statement, unwrapping exports.

            Parameters
            ----------
            node : tree_sitter.Node
                Top-level program statement.

            Returns
            -------
            None
                Semantic artifacts append in source order.
            """
            current = node
            if current.type == "export_statement":
                if "export * as" in _normalized(current, source):
                    name_node = next(
                        (
                            child
                            for child in _descendants(current)
                            if child.type == "identifier"
                        ),
                        None,
                    )
                    if name_node is not None:
                        name = _normalized(name_node, source)
                        declarations.append(
                            DeclarationArtifact(
                                name=name,
                                stable_id=f"javascript:namespace:{owner}:{name}",
                                kind="namespace",
                                lineno=name_node.start_point.row + 1,
                                signature=_normalized(current, source),
                            )
                        )
                child = next(
                    (
                        child
                        for child in current.named_children
                        if child.type not in {"export_clause", "string"}
                    ),
                    None,
                )
                if child is None:
                    return
                current = child
            if current.type == "import_statement":
                imports.append(_import(current, source))
            elif current.type in {
                "function_declaration",
                "generator_function_declaration",
            }:
                function = _function(current, source, owner=owner)
                if function is not None:
                    functions.append(
                        cast("FunctionArtifact", attach(function, node, "function"))
                    )
            elif current.type == "class_declaration":
                name = _normalized(current.child_by_field_name("name"), source)
                if not name:
                    return
                body = current.child_by_field_name("body")
                methods: list[FunctionArtifact] = []
                for child in body.named_children if body is not None else ():
                    if child.type not in {
                        "method_definition",
                        "generator_method",
                        "method_signature",
                    }:
                        continue
                    method = _function(child, source, owner=owner, owner_name=name)
                    if method is not None:
                        methods.append(
                            cast("FunctionArtifact", attach(method, child, "function"))
                        )
                class_item = ClassArtifact(
                    name=name,
                    stable_id=f"javascript:class:{owner}:{name}",
                    lineno=current.start_point.row + 1,
                    end_lineno=current.end_point.row + 1,
                    docstring=None,
                    has_docstring=0,
                    methods=tuple(methods),
                )
                classes.append(cast("ClassArtifact", attach(class_item, node, "type")))
            elif current.type in {"lexical_declaration", "variable_declaration"}:
                for declarator in (
                    child
                    for child in current.named_children
                    if child.type == "variable_declarator"
                ):
                    name_node = declarator.child_by_field_name("name")
                    value = declarator.child_by_field_name("value")
                    name = _normalized(name_node, source)
                    if not name:
                        continue
                    if value is not None and value.type in {
                        "arrow_function",
                        "function_expression",
                    }:
                        function = _function(value, source, owner=owner, name=name)
                        if function is not None:
                            functions.append(
                                cast(
                                    "FunctionArtifact",
                                    attach(function, node, "function"),
                                )
                            )
                    elif self._emit_variables:
                        declaration = DeclarationArtifact(
                            name=name,
                            stable_id=f"javascript:variable:{owner}:{name}",
                            kind="variable",
                            lineno=declarator.start_point.row + 1,
                            signature=_normalized(declarator, source),
                        )
                        declarations.append(
                            cast(
                                "DeclarationArtifact",
                                attach(declaration, node, "variable"),
                            )
                        )

        for child in _parser().parse(source).root_node.named_children:
            analyze_statement(child)
        return AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=_module_name(path, root),
                stable_id=f"javascript:module:{owner}",
                docstring=None,
                has_docstring=0,
            ),
            classes=tuple(classes),
            functions=tuple(functions),
            declarations=tuple(declarations),
            imports=tuple(imports),
            documentation=tuple(documentation),
        )


def build_analyzer() -> LanguageAnalyzer:
    """Build a fresh JavaScript analyzer plugin.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        New stateless-parser JavaScript analyzer instance.
    """
    return JavaScriptAnalyzer()
