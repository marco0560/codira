"""Syntax-only TypeScript and TSX analyzer for Codira."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from tree_sitter import Language, Node, Parser
from tree_sitter_typescript import language_tsx, language_typescript

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    ClassArtifact,
    DeclarationArtifact,
    DocumentationArtifact,
    EnumMemberArtifact,
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

_TYPESCRIPT = Language(language_typescript())
_TSX = Language(language_tsx())
_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts"})
_SPACE = re.compile(r"\s+")
_TSDOC = re.compile(r"/\*\*(?!\*)(.*?)\*/", re.DOTALL)
__all__ = ["TypeScriptAnalyzer", "build_analyzer"]


def _parser(path: Path) -> Parser:
    """Create a parser selected by the TypeScript source suffix.

    Parameters
    ----------
    path : pathlib.Path
        TypeScript source path.

    Returns
    -------
    tree_sitter.Parser
        TypeScript parser, or the TSX parser for ``.tsx`` files.
    """
    return Parser(_TSX if path.suffix.lower() == ".tsx" else _TYPESCRIPT)


def _text(node: Node | None, source: bytes) -> str:
    """Decode one syntax node.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Optional source node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str
        Decoded source text or an empty string.
    """
    return (
        ""
        if node is None
        else source[node.start_byte : node.end_byte].decode("utf-8", "replace")
    )


def _normalized(node: Node | None, source: bytes) -> str:
    """Render node text on one normalized line.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Node to render.
    source : bytes
        Full source buffer.

    Returns
    -------
    str
        Whitespace-collapsed source text.
    """
    return _SPACE.sub(" ", _text(node, source)).strip()


def _descendants(node: Node) -> Iterable[Node]:
    """Yield named descendant nodes in source order.

    Parameters
    ----------
    node : tree_sitter.Node
        Traversal root.

    Returns
    -------
    collections.abc.Iterable[tree_sitter.Node]
        Depth-first named descendants.
    """
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _parameters(node: Node | None, source: bytes) -> tuple[str, ...]:
    """Extract callable parameter binding names.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Formal-parameters node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, ...]
        Parameter names in declaration order.
    """
    if node is None:
        return ()
    names: list[str] = []
    for child in node.named_children:
        pattern = child.child_by_field_name("pattern") or child.child_by_field_name(
            "name"
        )
        if pattern is None:
            pattern = (
                child
                if child.type == "identifier"
                else child.named_children[0]
                if child.named_children
                else child
            )
        names.append(_normalized(pattern, source))
    return tuple(names)


def _call_target(
    node: Node, source: bytes
) -> tuple[Literal["name", "attribute", "unresolved"], str, str]:
    """Classify a TypeScript call target syntactically.

    Parameters
    ----------
    node : tree_sitter.Node
        Called expression.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, str, str]
        Relation kind, terminal target, and optional receiver.
    """
    if node.type == "identifier":
        return "name", _normalized(node, source), ""
    if node.type == "member_expression":
        property_node = node.child_by_field_name("property")
        if property_node is not None:
            return (
                "attribute",
                _normalized(property_node, source),
                _normalized(node.child_by_field_name("object"), source),
            )
    return "unresolved", _normalized(node, source), ""


def _calls(body: Node | None, source: bytes) -> tuple[CallSite, ...]:
    """Extract calls owned directly by a TypeScript callable.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Callable body node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Ordered call-site records.
    """
    if body is None:
        return ()
    records: list[CallSite] = []
    for item in _descendants(body):
        if item.type != "call_expression":
            continue
        function = item.child_by_field_name("function")
        if function is None:
            continue
        kind, target, base = _call_target(function, source)
        records.append(
            CallSite(
                kind=kind,
                target=target,
                lineno=function.start_point.row + 1,
                col_offset=function.start_point.column,
                base=base,
                external_target_kind="typescript_expression"
                if kind == "unresolved"
                else None,
                external_target_name=target if kind == "unresolved" else None,
            )
        )
    return tuple(records)


def _tsdoc_blocks(source: bytes) -> tuple[tuple[int, int, str], ...]:
    """Return cleaned TSDoc blocks with their byte spans.

    Parameters
    ----------
    source : bytes
        Complete UTF-8 source buffer.

    Returns
    -------
    tuple[tuple[int, int, str], ...]
        Ordered start byte, end byte, and cleaned documentation text.
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
        for match in _TSDOC.finditer(text)
    )


def _attached_tsdoc(
    node: Node, source: bytes, blocks: tuple[tuple[int, int, str], ...]
) -> tuple[int, int, str] | None:
    """Return the whitespace-adjacent preceding TSDoc block, if any.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration node.
    source : bytes
        Complete source buffer.
    blocks : tuple[tuple[int, int, str], ...]
        Previously discovered TSDoc blocks.
    """
    for block in reversed(blocks):
        if block[1] <= node.start_byte:
            gap = source[block[1] : node.start_byte].strip()
            return (
                block
                if gap
                in {
                    b"",
                    b"export",
                    b"default",
                    b"export default",
                    b"declare",
                    b"export declare",
                }
                else None
            )
        if block[0] == node.start_byte:
            remainder = source[block[1] : node.end_byte]
            if b";" not in remainder and b"}" not in remainder[:-1]:
                return block
    return None


def _function(
    node: Node,
    source: bytes,
    *,
    owner: str,
    name: str | None = None,
    class_name: str | None = None,
    namespace: str | None = None,
) -> FunctionArtifact | None:
    """Build a normalized TypeScript function or method.

    Parameters
    ----------
    node : tree_sitter.Node
        Callable grammar node.
    source : bytes
        Full source buffer.
    owner : str
        Source-relative stable-id owner.
    name : str | None, optional
        Assigned name for anonymous callable expressions.
    class_name : str | None, optional
        Owning class name for methods.
    namespace : str | None, optional
        Owning namespace for callable stable identities.

    Returns
    -------
    codira.models.FunctionArtifact | None
        Callable artifact, or ``None`` without a usable name.
    """
    function_name = name or _normalized(node.child_by_field_name("name"), source)
    if not function_name:
        return None
    body = node.child_by_field_name("body")
    signature_end = body.start_byte if body is not None else node.end_byte
    signature = _SPACE.sub(
        " ", source[node.start_byte : signature_end].decode("utf-8", "replace")
    ).strip()
    kind = "method" if class_name else "function"
    namespace_suffix = f":{namespace}" if namespace else ""
    owner_suffix = (
        f"{namespace_suffix}:{class_name}" if class_name else namespace_suffix
    )
    return FunctionArtifact(
        name=function_name,
        stable_id=f"typescript:{kind}:{owner}{owner_suffix}:{function_name}",
        lineno=node.start_point.row + 1,
        end_lineno=body.end_point.row + 1
        if body is not None
        else node.end_point.row + 1,
        signature=signature,
        docstring=None,
        has_docstring=0,
        is_method=int(class_name is not None),
        is_public=int(not function_name.startswith("_")),
        parameters=_parameters(node.child_by_field_name("parameters"), source),
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
        callable_refs=(),
    )


class TypeScriptAnalyzer:
    """Analyze TypeScript and TSX declarations without compiler emulation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances retain only configuration state.
    """

    name = "typescript"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.ts", "*.tsx", "*.mts", "*.cts")
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
        """Initialize shared path filters and emission switches.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Defaults are installed.
        """
        self._filters = AnalyzerPathFilters()
        self._emit_variables = True
        self._emit_tsdoc_documentation = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """Return the TypeScript plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Shared filters plus variable emission configuration.
        """
        return analyzer_json_schema(
            {
                "emit_variables": boolean_property(True),
                "emit_tsdoc_documentation": boolean_property(True),
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply namespaced analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Plugin configuration values.

        Returns
        -------
        None
            Filters, switches, and provenance update.
        """
        self._filters = analyzer_path_filters_from_config(config)
        self._emit_variables = bool(config.get("emit_variables", True))
        self._emit_tsdoc_documentation = bool(
            config.get("emit_tsdoc_documentation", True)
        )
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """Declare syntax-only TypeScript ontology support.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit TypeScript construct mapping.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_typescript:build_analyzer",
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
                "interface": "type",
                "type_alias": "type",
                "enum": "type",
                "class": "type",
                "function": "callable",
                "method": "callable",
                "import": "import",
                "variable": "variable",
                "namespace": "namespace",
                "tsdoc": "documentation",
            },
        )

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """Declare parser worker safety.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Safe concurrent execution declaration.
        """
        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """Return whether a path has a supported TypeScript suffix.

        Parameters
        ----------
        path : pathlib.Path
            Candidate file.

        Returns
        -------
        bool
            ``True`` only for TypeScript and TSX paths.
        """
        return path.suffix.lower() in _SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """Apply shared filters to a TypeScript source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        bool
            Whether configured filters allow analysis.
        """
        return analyzer_path_allowed(path=path, root=root, filters=self._filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """Analyze one TypeScript or TSX file deterministically.

        Parameters
        ----------
        path : pathlib.Path
            Source file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Ordered normalized TypeScript artifacts.
        """
        source = path.read_bytes()
        owner = path.relative_to(root).as_posix()
        declarations: list[DeclarationArtifact] = []
        functions: list[FunctionArtifact] = []
        classes: list[ClassArtifact] = []
        imports: list[ImportArtifact] = []
        documentation: list[DocumentationArtifact] = []
        blocks = _tsdoc_blocks(source)

        def attach(
            item: FunctionArtifact | ClassArtifact | DeclarationArtifact,
            node: Node,
            kind: str,
        ) -> FunctionArtifact | ClassArtifact | DeclarationArtifact:
            """Attach adjacent TSDoc and emit its explicit provenance artifact.

            Parameters
            ----------
            item : FunctionArtifact | ClassArtifact | DeclarationArtifact
                Semantic artifact receiving documentation.
            node : tree_sitter.Node
                Source declaration node.
            kind : str
                Ontology kind for provenance.
            """
            block = _attached_tsdoc(node, source, blocks)
            if block is None or not self._emit_tsdoc_documentation:
                return item
            documentation.append(
                DocumentationArtifact(
                    stable_id=f"doc:tsdoc:{item.stable_id}:{block[0]}",
                    kind="declaration",
                    source_format="tsdoc",
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
            if isinstance(item, (FunctionArtifact, ClassArtifact)):
                return replace(item, docstring=block[2], has_docstring=1)
            return replace(item, docstring=block[2])

        def visit(node: Node, namespace: str | None = None) -> None:
            """Extract one top-level or namespace declaration.

            Parameters
            ----------
            node : tree_sitter.Node
                Candidate declaration node.
            namespace : str | None, optional
                Namespace owner for nested declarations.

            Returns
            -------
            None
                Artifacts append in deterministic source order.
            """
            current = node
            while current.type in {
                "ambient_declaration",
                "export_statement",
                "expression_statement",
            }:
                declaration = current.child_by_field_name("declaration")
                if declaration is None and current.type == "ambient_declaration":
                    declaration = next(iter(current.named_children), None)
                if declaration is None and current.type == "expression_statement":
                    candidate = next(iter(current.named_children), None)
                    if candidate is not None and candidate.type == "internal_module":
                        declaration = candidate
                if declaration is None:
                    break
                current = declaration
            if (
                node.type == "export_statement"
                and node.child_by_field_name("source") is not None
            ):
                imports.append(
                    ImportArtifact(
                        name=_text(node.child_by_field_name("source"), source).strip(
                            "'\""
                        ),
                        alias=None,
                        lineno=node.start_point.row + 1,
                    )
                )
            if current.type == "import_statement":
                imports.append(
                    ImportArtifact(
                        name=_text(current.child_by_field_name("source"), source).strip(
                            "'\""
                        ),
                        alias=None,
                        lineno=current.start_point.row + 1,
                    )
                )
                return
            name = _normalized(current.child_by_field_name("name"), source)
            prefix = f":{namespace}" if namespace else ""
            if (
                current.type
                in {
                    "interface_declaration",
                    "type_alias_declaration",
                    "enum_declaration",
                }
                and name
            ):
                kind = cast(
                    'Literal["struct", "type_alias", "enum"]',
                    {
                        "interface_declaration": "struct",
                        "type_alias_declaration": "type_alias",
                        "enum_declaration": "enum",
                    }[current.type],
                )
                stable_id = f"typescript:{kind}:{owner}{prefix}:{name}"
                enum_body = current.child_by_field_name("body")
                members = (
                    tuple(
                        EnumMemberArtifact(
                            stable_id=f"typescript:enum_member:{owner}:{name}:{index}",
                            parent_stable_id=stable_id,
                            ordinal=index,
                            name=_normalized(
                                child.child_by_field_name("name") or child, source
                            ),
                            signature=_normalized(child, source),
                            lineno=child.start_point.row + 1,
                        )
                        for index, child in enumerate(
                            enum_body.named_children if enum_body is not None else (), 1
                        )
                    )
                    if current.type == "enum_declaration"
                    else ()
                )
                declarations.append(
                    cast(
                        "DeclarationArtifact",
                        attach(
                            DeclarationArtifact(
                                name=name,
                                stable_id=stable_id,
                                kind=kind,
                                lineno=current.start_point.row + 1,
                                signature=_normalized(current, source),
                                enum_members=members,
                            ),
                            current,
                            "type",
                        ),
                    )
                )
                return
            if current.type == "internal_module" and name:
                declarations.append(
                    cast(
                        "DeclarationArtifact",
                        attach(
                            DeclarationArtifact(
                                name=name,
                                stable_id=f"typescript:namespace:{owner}{prefix}:{name}",
                                kind="namespace",
                                lineno=current.start_point.row + 1,
                                signature=_normalized(current, source),
                            ),
                            current,
                            "namespace",
                        ),
                    )
                )
                body = current.child_by_field_name("body")
                nested_namespace = f"{namespace}.{name}" if namespace else name
                for child in body.named_children if body is not None else ():
                    visit(child, nested_namespace)
                return
            if current.type in {
                "function_declaration",
                "function_signature",
                "generator_function_declaration",
            }:
                function = _function(current, source, owner=owner, namespace=namespace)
                if function is not None:
                    functions.append(
                        cast("FunctionArtifact", attach(function, current, "function"))
                    )
                return
            if (
                current.type in {"abstract_class_declaration", "class_declaration"}
                and name
            ):
                body = current.child_by_field_name("body")
                methods_list: list[FunctionArtifact] = []
                for child in body.named_children if body is not None else ():
                    if child.type not in {
                        "abstract_method_signature",
                        "method_definition",
                        "method_signature",
                    }:
                        continue
                    method = _function(
                        child,
                        source,
                        owner=owner,
                        class_name=name,
                        namespace=namespace,
                    )
                    if method is not None:
                        methods_list.append(
                            cast("FunctionArtifact", attach(method, child, "function"))
                        )
                classes.append(
                    cast(
                        "ClassArtifact",
                        attach(
                            ClassArtifact(
                                name=name,
                                stable_id=f"typescript:class:{owner}{prefix}:{name}",
                                lineno=current.start_point.row + 1,
                                end_lineno=current.end_point.row + 1,
                                docstring=None,
                                has_docstring=0,
                                methods=tuple(methods_list),
                            ),
                            current,
                            "type",
                        ),
                    )
                )
                return
            if current.type in {"lexical_declaration", "variable_declaration"}:
                for item in (
                    child
                    for child in current.named_children
                    if child.type == "variable_declarator"
                ):
                    variable_name = _normalized(
                        item.child_by_field_name("name"), source
                    )
                    value = item.child_by_field_name("value")
                    if value is not None and value.type in {
                        "arrow_function",
                        "function_expression",
                    }:
                        function = _function(
                            value,
                            source,
                            owner=owner,
                            name=variable_name,
                            namespace=namespace,
                        )
                        if function is not None:
                            functions.append(
                                cast(
                                    "FunctionArtifact",
                                    attach(function, current, "function"),
                                )
                            )
                    elif variable_name and self._emit_variables:
                        declarations.append(
                            cast(
                                "DeclarationArtifact",
                                attach(
                                    DeclarationArtifact(
                                        name=variable_name,
                                        stable_id=f"typescript:variable:{owner}{prefix}:{variable_name}",
                                        kind="variable",
                                        lineno=item.start_point.row + 1,
                                        signature=_normalized(item, source),
                                    ),
                                    current,
                                    "variable",
                                ),
                            )
                        )

        for child in _parser(path).parse(source).root_node.named_children:
            visit(child)
        return AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=".".join(path.relative_to(root).with_suffix("").parts),
                stable_id=f"typescript:module:{owner}",
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
    """Build a fresh autonomous TypeScript analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        TypeScript analyzer instance.
    """
    return TypeScriptAnalyzer()
