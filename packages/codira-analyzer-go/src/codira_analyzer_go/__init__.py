"""Syntax-only Go analyzer backed by Tree-sitter.

The analyzer extracts deterministic source facts without evaluating build tags,
resolving modules, or invoking the Go compiler.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from tree_sitter import Language, Node, Parser
from tree_sitter_go import language

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    CallableReference,
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
_SPACE = re.compile(r"\s+")
__all__ = ["GoAnalyzer", "build_analyzer"]


def _text(node: Node | None, source: bytes) -> str:
    """Decode one source node.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Optional syntax node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str
        Decoded node text, or an empty string.
    """
    return (
        ""
        if node is None
        else source[node.start_byte : node.end_byte].decode("utf-8", "replace")
    )


def _normalized(node: Node | None, source: bytes) -> str:
    """Collapse node whitespace.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Optional syntax node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str
        One-line source rendering.
    """
    return _SPACE.sub(" ", _text(node, source)).strip()


def _descendants(node: Node) -> Iterable[Node]:
    """Yield named descendants in source order.

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
    """Extract Go parameter bindings.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Parameter list node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[str, ...]
        Named parameter bindings in declaration order.
    """
    if node is None:
        return ()
    return tuple(
        _normalized(child.child_by_field_name("name"), source)
        for child in node.named_children
        if child.type in {"parameter_declaration", "variadic_parameter_declaration"}
        and child.child_by_field_name("name") is not None
    )


def _target(
    node: Node, source: bytes
) -> tuple[Literal["name", "attribute", "unresolved"], str, str]:
    """Classify a Go call or reference target syntactically.

    Parameters
    ----------
    node : tree_sitter.Node
        Target expression.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[Literal["name", "attribute", "unresolved"], str, str]
        Relation kind, terminal target, and optional receiver.
    """
    if node.type == "identifier":
        return "name", _normalized(node, source), ""
    if node.type == "selector_expression":
        field = node.child_by_field_name("field")
        return (
            "attribute",
            _normalized(field, source),
            _normalized(node.child_by_field_name("operand"), source),
        )
    return "unresolved", _normalized(node, source), ""


def _relations(
    body: Node | None, source: bytes
) -> tuple[tuple[CallSite, ...], tuple[CallableReference, ...]]:
    """Extract calls and value-position callable references.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Callable body.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[tuple[codira.models.CallSite, ...], tuple[codira.models.CallableReference, ...]]
        Ordered call and callable-reference records.
    """
    if body is None:
        return (), ()
    calls: list[CallSite] = []
    refs: list[CallableReference] = []
    for item in _descendants(body):
        if item.type == "call_expression":
            target = item.child_by_field_name("function")
            if target is None:
                continue
            kind, name, base = _target(target, source)
            calls.append(
                CallSite(
                    kind=kind,
                    target=name,
                    base=base,
                    lineno=target.start_point.row + 1,
                    col_offset=target.start_point.column,
                    external_target_kind="go_expression"
                    if kind == "unresolved"
                    else None,
                    external_target_name=name if kind == "unresolved" else None,
                )
            )
        elif (
            item.type == "identifier"
            and item.parent is not None
            and item.parent.type in {"return_statement", "assignment_statement"}
        ):
            kind, name, base = _target(item, source)
            refs.append(
                CallableReference(
                    kind=kind,
                    target=name,
                    base=base,
                    lineno=item.start_point.row + 1,
                    col_offset=item.start_point.column,
                    ref_kind="return_value"
                    if item.parent.type == "return_statement"
                    else "assignment_value",
                    external_target_kind=None,
                    external_target_name=None,
                )
            )
    return tuple(calls), tuple(refs)


def _function(
    node: Node, source: bytes, *, owner: str, receiver: str | None = None
) -> FunctionArtifact | None:
    """Build one Go function or method artifact.

    Parameters
    ----------
    node : tree_sitter.Node
        Function or method declaration.
    source : bytes
        Complete source buffer.
    owner : str
        Repository-relative source owner.
    receiver : str | None
        Receiver type identity for methods.

    Returns
    -------
    codira.models.FunctionArtifact | None
        Normalized callable, or ``None`` if unnamed.
    """
    name = _normalized(node.child_by_field_name("name"), source)
    if not name:
        return None
    body = node.child_by_field_name("body")
    signature_end = body.start_byte if body is not None else node.end_byte
    calls, refs = _relations(body, source)
    return FunctionArtifact(
        name=name,
        stable_id=f"go:{'method' if receiver else 'function'}:{owner}{':' + receiver if receiver else ''}:{name}",
        lineno=node.start_point.row + 1,
        end_lineno=body.end_point.row + 1 if body is not None else None,
        signature=_SPACE.sub(
            " ", source[node.start_byte : signature_end].decode("utf-8", "replace")
        ).strip(),
        docstring=None,
        has_docstring=0,
        is_method=int(receiver is not None),
        is_public=int(name[:1].isupper()),
        parameters=_parameters(node.child_by_field_name("parameters"), source),
        returns_value=int(node.child_by_field_name("result") is not None),
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=calls,
        callable_refs=refs,
    )


def _with_go_doc_comments(analysis: AnalysisResult, source: bytes) -> AnalysisResult:
    """Attach explicit adjacent Go comment blocks to semantic artifacts.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Parsed Go artifacts without documentation provenance.
    source : bytes
        Complete source buffer.

    Returns
    -------
    codira.models.AnalysisResult
        Result with documentation artifacts and owner docstrings.
    """
    package_line = next(
        (
            index + 1
            for index, line in enumerate(source.decode("utf-8", "replace").splitlines())
            if line.lstrip().startswith("package ")
        ),
        1,
    )
    owners = [(analysis.module.stable_id, "module", analysis.module.name, package_line)]
    owners.extend(
        (item.stable_id, item.kind, item.name, item.lineno)
        for item in analysis.declarations
    )
    owners.extend(
        (item.stable_id, "function", item.name, item.lineno)
        for item in analysis.functions
    )
    owners.extend(
        (method.stable_id, "function", method.name, method.lineno)
        for cls in analysis.classes
        for method in cls.methods
    )
    artifacts: list[DocumentationArtifact] = []
    lines = source.decode("utf-8", "replace").splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("//"):
            index += 1
            continue
        start = index
        text: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith("//"):
            text.append(lines[index].lstrip()[2:].removeprefix(" "))
            index += 1
        owner = next((item for item in owners if item[3] == index + 1), None)
        if owner is None:
            continue
        owner_id, owner_kind, title, _ = owner
        artifacts.append(
            DocumentationArtifact(
                stable_id=f"doc:go:{owner_id}:{start + 1}",
                kind="module" if owner_kind == "module" else "declaration",
                source_format="go_doc_comment",
                source_path=analysis.source_path,
                lineno=start + 1,
                end_lineno=index,
                title=title,
                heading_path=(),
                text="\n".join(text).strip(),
                owner_stable_id=owner_id,
                owner_kind=owner_kind,
                attachment_confidence="explicit",
            )
        )
    docs = {
        item.owner_stable_id: item.text
        for item in artifacts
        if item.owner_stable_id is not None
    }

    def function(item: FunctionArtifact) -> FunctionArtifact:
        """Attach one matching explicit Go documentation comment."""
        doc = docs.get(item.stable_id)
        return replace(item, docstring=doc, has_docstring=int(doc is not None))

    return replace(
        analysis,
        module=replace(
            analysis.module,
            docstring=docs.get(analysis.module.stable_id),
            has_docstring=int(analysis.module.stable_id in docs),
        ),
        declarations=tuple(
            replace(item, docstring=docs.get(item.stable_id))
            for item in analysis.declarations
        ),
        functions=tuple(function(item) for item in analysis.functions),
        classes=tuple(
            replace(cls, methods=tuple(function(method) for method in cls.methods))
            for cls in analysis.classes
        ),
        documentation=tuple(artifacts),
    )


class GoAnalyzer:
    """Analyze Go source syntax without module or compiler evaluation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances retain shared plugin configuration only.
    """

    name = "go"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.go",)
    default_coverage_roots: tuple[str, ...] = (
        "cmd",
        "internal",
        "pkg",
        "src",
        "tests",
    )

    def __init__(self) -> None:
        """Initialize Go analyzer configuration.

        Returns
        -------
        None
            Default path filters and emission settings are installed.
        """
        self._filters = AnalyzerPathFilters()
        self._emit_variables = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """Return strict Go analyzer configuration.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Shared filters plus variable emission control.
        """
        return analyzer_json_schema({"emit_variables": boolean_property(True)})

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply namespaced configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Go analyzer configuration.

        Returns
        -------
        None
            Configuration state and fingerprint update.
        """
        self._filters = analyzer_path_filters_from_config(config)
        self._emit_variables = bool(config.get("emit_variables", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """Declare syntax-only Go coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit Go ontology mappings.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_go:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "variable",
                "documentation",
            ),
            does_not_support=("namespace",),
            mappings={
                "package": "module",
                "struct": "type",
                "interface": "type",
                "function": "callable",
                "method": "callable",
                "import": "import",
                "const": "constant",
                "var": "variable",
                "go_doc_comment": "documentation",
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
            Reentrant process and thread worker support.
        """
        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """Return whether a path is Go source.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for ``.go`` files.
        """
        return path.suffix == ".go"

    def allows_path(self, path: Path, root: Path) -> bool:
        """Apply shared path filters.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        bool
            Whether the path is configured for analysis.
        """
        return analyzer_path_allowed(path=path, root=root, filters=self._filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """Analyze one Go file into deterministic artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Go source file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Package, import, declaration, callable, call, and reference facts.
        """
        source = path.read_bytes()
        owner = path.relative_to(root).as_posix()
        declarations: list[DeclarationArtifact] = []
        functions: list[FunctionArtifact] = []
        classes: dict[str, list[FunctionArtifact]] = {}
        imports: list[ImportArtifact] = []
        package = path.parent.name
        for node in Parser(_LANGUAGE).parse(source).root_node.named_children:
            if node.type == "package_clause":
                package = _normalized(next(iter(node.named_children), None), source)
            elif node.type == "import_declaration":
                for spec in _descendants(node):
                    if spec.type == "import_spec":
                        target = _text(spec.child_by_field_name("path"), source).strip(
                            '"'
                        )
                        alias = (
                            _normalized(spec.child_by_field_name("name"), source)
                            or None
                        )
                        imports.append(
                            ImportArtifact(
                                name=target,
                                alias=alias,
                                lineno=spec.start_point.row + 1,
                            )
                        )
            elif node.type in {"const_declaration", "var_declaration"}:
                for spec in _descendants(node):
                    if spec.type not in {"const_spec", "var_spec"}:
                        continue
                    for name_node in spec.children_by_field_name("name"):
                        name = _normalized(name_node, source)
                        if name and (
                            node.type == "const_declaration" or self._emit_variables
                        ):
                            kind = (
                                "constant"
                                if node.type == "const_declaration"
                                else "variable"
                            )
                            declarations.append(
                                DeclarationArtifact(
                                    name=name,
                                    stable_id=f"go:{kind}:{owner}:{name}",
                                    kind=cast("Literal['constant', 'variable']", kind),
                                    lineno=name_node.start_point.row + 1,
                                    signature=_normalized(spec, source),
                                )
                            )
            elif node.type == "type_declaration":
                for spec in (
                    child for child in node.named_children if child.type == "type_spec"
                ):
                    name = _normalized(spec.child_by_field_name("name"), source)
                    type_node = spec.child_by_field_name("type")
                    if (
                        name
                        and type_node is not None
                        and type_node.type in {"struct_type", "interface_type"}
                    ):
                        declarations.append(
                            DeclarationArtifact(
                                name=name,
                                stable_id=f"go:struct:{owner}:{name}",
                                kind="struct",
                                lineno=spec.start_point.row + 1,
                                signature=_normalized(spec, source),
                            )
                        )
            elif node.type == "function_declaration":
                if (item := _function(node, source, owner=owner)) is not None:
                    functions.append(item)
            elif node.type == "method_declaration":
                receiver_node = node.child_by_field_name("receiver")
                receiver = _normalized(receiver_node, source)
                if (
                    item := _function(node, source, owner=owner, receiver=receiver)
                ) is not None:
                    classes.setdefault(receiver, []).append(item)
        return _with_go_doc_comments(
            AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=package,
                    stable_id=f"go:module:{owner}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=tuple(
                    ClassArtifact(
                        name=name,
                        stable_id=f"go:receiver:{owner}:{name}",
                        lineno=items[0].lineno,
                        end_lineno=items[-1].end_lineno,
                        docstring=None,
                        has_docstring=0,
                        methods=tuple(items),
                    )
                    for name, items in classes.items()
                ),
                functions=tuple(functions),
                declarations=tuple(declarations),
                imports=tuple(imports),
            ),
            source,
        )


def build_analyzer() -> LanguageAnalyzer:
    """Build a fresh Go analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Autonomous Go analyzer instance.
    """
    return GoAnalyzer()
