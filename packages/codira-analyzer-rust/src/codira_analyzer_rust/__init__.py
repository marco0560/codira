"""Rust language analyzer backed by tree-sitter.

The plugin performs deterministic syntax-only extraction.  It intentionally
does not expand macros, invoke Cargo, or infer compiler and borrow-checker
semantics.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

from tree_sitter import Language, Node, Parser
from tree_sitter_rust import language

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    CallSite,
    ClassArtifact,
    DeclarationKind,
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

_LANGUAGE = Language(language())
_RUST_SUFFIXES = {".rs"}
_SPACE = re.compile(r"\s+")
__all__ = ["RustAnalyzer", "build_analyzer"]


def _parser() -> Parser:
    """Create a Rust parser.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser configured with the Rust grammar.
    """
    return Parser(_LANGUAGE)


def _text(node: Node | None, source: bytes) -> str:
    """Return UTF-8 source text for a syntax node.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Node whose source span is requested.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str
        Decoded node text, or an empty string when no node is supplied.
    """
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _normalized(node: Node, source: bytes) -> str:
    """Normalize a node's source text to one line.

    Parameters
    ----------
    node : tree_sitter.Node
        Node to render.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str
        Whitespace-collapsed node text.
    """
    return _SPACE.sub(" ", _text(node, source)).strip()


def _module_name(path: Path, root: Path) -> str:
    """Derive a dotted module name from a Rust path.

    Parameters
    ----------
    path : pathlib.Path
        Rust source path.
    root : pathlib.Path
        Repository root.

    Returns
    -------
    str
        Dotted repository-relative module name.
    """
    return ".".join(path.relative_to(root).with_suffix("").parts)


def _owner(path: Path, root: Path) -> str:
    """Return the repository-relative owner identity.

    Parameters
    ----------
    path : pathlib.Path
        Rust source path.
    root : pathlib.Path
        Repository root.

    Returns
    -------
    str
        POSIX repository-relative source path.
    """
    return path.relative_to(root).as_posix()


def _identifier(node: Node, source: bytes) -> str | None:
    """Extract the first declaration identifier from a node.

    Parameters
    ----------
    node : tree_sitter.Node
        Rust declaration node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    str | None
        Declared identifier, if the grammar exposes one.
    """
    if node.type in {"identifier", "type_identifier"}:
        return _text(node, source)
    for child in node.named_children:
        if child.type in {"identifier", "type_identifier"}:
            return _text(child, source)
    return None


def _descendants(node: Node) -> Iterable[Node]:
    """Yield named descendants in source order.

    Parameters
    ----------
    node : tree_sitter.Node
        Root node to traverse.

    Returns
    -------
    collections.abc.Iterable[tree_sitter.Node]
        Depth-first named descendants.
    """
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _parameters(node: Node | None, source: bytes) -> tuple[str, ...]:
    """Extract declaration parameter bindings in source order.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Function parameter-list node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[str, ...]
        Parameter binding names, excluding type annotations.
    """
    if node is None:
        return ()
    names: list[str] = []
    for child in node.named_children:
        if child.type == "self_parameter":
            names.append(_normalized(child, source))
        elif child.type == "parameter":
            pattern = child.child_by_field_name("pattern")
            name = _identifier(pattern, source) if pattern is not None else None
            if name is not None:
                names.append(name)
    return tuple(names)


def _call_target(
    node: Node, source: bytes
) -> tuple[Literal["name", "attribute", "unresolved"], str, str]:
    """Classify a Rust call target without semantic resolution.

    Parameters
    ----------
    node : tree_sitter.Node
        Call-expression function node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[str, str, str]
        Call kind, terminal target, and optional receiver/base path.
    """
    text = _normalized(node, source)
    if node.type == "identifier":
        return "name", text, ""
    if node.type in {"field_expression", "scoped_identifier"}:
        parts = text.split("::") if "::" in text else text.split(".")
        if len(parts) > 1:
            return "attribute", parts[-1], "::".join(parts[:-1])
    return "unresolved", text, ""


def _calls(body: Node | None, source: bytes) -> tuple[CallSite, ...]:
    """Extract syntactically evident calls from a function body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Function body node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Ordered call-site artifacts.
    """
    if body is None:
        return ()
    calls: list[CallSite] = []
    for node in _descendants(body):
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            if function is None:
                continue
            kind, target, base = _call_target(function, source)
            calls.append(
                CallSite(
                    kind=kind,
                    target=target,
                    lineno=function.start_point.row + 1,
                    col_offset=function.start_point.column,
                    base=base,
                    external_target_kind="rust_expression"
                    if kind == "unresolved"
                    else None,
                    external_target_name=target if kind == "unresolved" else None,
                )
            )
        elif node.type == "macro_invocation":
            macro = node.child_by_field_name("macro")
            if macro is None:
                continue
            target = _normalized(macro, source)
            calls.append(
                CallSite(
                    kind="unresolved",
                    target=target,
                    lineno=macro.start_point.row + 1,
                    col_offset=macro.start_point.column,
                    external_target_kind="rust_macro",
                    external_target_name=target,
                )
            )
    return tuple(calls)


def _function(
    node: Node,
    source: bytes,
    *,
    owner: str,
    owner_name: str | None,
) -> FunctionArtifact | None:
    """Build one function or method artifact.

    Parameters
    ----------
    node : tree_sitter.Node
        Rust function declaration or signature node.
    source : bytes
        Complete source buffer.
    owner : str
        File-scoped stable identity prefix.
    owner_name : str | None
        Trait or implementation owner for methods.

    Returns
    -------
    codira.models.FunctionArtifact | None
        Normalized callable, or ``None`` when unnamed.
    """
    name = _identifier(node, source)
    if name is None:
        return None
    body = node.child_by_field_name("body")
    parameters = _parameters(node.child_by_field_name("parameters"), source)
    signature_end = body.start_byte if body is not None else node.end_byte
    signature = _SPACE.sub(
        " ", source[node.start_byte : signature_end].decode("utf-8", "replace")
    ).strip()
    stable_owner = f":{owner_name}" if owner_name is not None else ""
    return FunctionArtifact(
        name=name,
        stable_id=f"rust:function:{owner}{stable_owner}:{name}",
        lineno=node.start_point.row + 1,
        end_lineno=body.end_point.row + 1 if body is not None else None,
        signature=signature,
        docstring=None,
        has_docstring=0,
        is_method=int(owner_name is not None),
        is_public=int(_normalized(node, source).startswith("pub ")),
        parameters=parameters,
        returns_value=int("->" in signature),
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=_calls(body, source),
        callable_refs=(),
    )


def _enum_members(
    node: Node, source: bytes, *, owner: str, parent_id: str
) -> tuple[EnumMemberArtifact, ...]:
    """Extract enum variants in declaration order.

    Parameters
    ----------
    node : tree_sitter.Node
        Rust enum declaration node.
    source : bytes
        Complete source buffer.
    owner : str
        File-scoped stable identity prefix.
    parent_id : str
        Owning enum stable identifier.

    Returns
    -------
    tuple[codira.models.EnumMemberArtifact, ...]
        Enum variants with durable ordinal identities.
    """
    members: list[EnumMemberArtifact] = []
    for child in _descendants(node):
        if child.type != "enum_variant":
            continue
        name = _identifier(child, source)
        if name is None:
            continue
        ordinal = len(members) + 1
        members.append(
            EnumMemberArtifact(
                stable_id=f"rust:enum_member:{owner}:{parent_id}:{ordinal}",
                parent_stable_id=parent_id,
                ordinal=ordinal,
                name=name,
                signature=_normalized(child, source),
                lineno=child.start_point.row + 1,
            )
        )
    return tuple(members)


def _import(node: Node, source: bytes) -> ImportArtifact:
    """Build an import artifact from a Rust use declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        Rust use-declaration node.
    source : bytes
        Complete source buffer.

    Returns
    -------
    codira.models.ImportArtifact
        Syntactic import target and optional alias.
    """
    text = _normalized(node, source).removeprefix("use ").removesuffix(";")
    target, separator, alias = text.partition(" as ")
    return ImportArtifact(
        name=target,
        alias=alias if separator else None,
        lineno=node.start_point.row + 1,
    )


def _macro_declaration(
    node: Node, source: bytes, *, owner: str
) -> DeclarationArtifact | None:
    """Build one declarative Rust macro artifact without expanding it.

    Parameters
    ----------
    node : tree_sitter.Node
        ``macro_definition`` syntax node.
    source : bytes
        Complete UTF-8 source buffer.
    owner : str
        File-scoped stable identity prefix.

    Returns
    -------
    codira.models.DeclarationArtifact | None
        Named macro declaration, or ``None`` when the grammar has no name.

    Notes
    -----
    The macro rule body remains signature text. Expansion may depend on Cargo,
    imports, conditional compilation, and arbitrary token trees.
    """
    name_node = node.child_by_field_name("name")
    name = _identifier(name_node, source) if name_node is not None else None
    if name is None:
        return None
    return DeclarationArtifact(
        name=name,
        stable_id=f"rust:macro:{owner}:{name}",
        kind="macro",
        lineno=node.start_point.row + 1,
        signature=_normalized(node, source),
    )


def _rustdoc_artifacts(
    *, path: Path, analysis: AnalysisResult, source: bytes
) -> tuple[DocumentationArtifact, ...]:
    """Extract explicitly attached line-style Rustdoc comment blocks.

    Parameters
    ----------
    path : pathlib.Path
        Rust source file owning the comments.
    analysis : codira.models.AnalysisResult
        Completed syntax artifacts used for deterministic ownership attachment.
    source : bytes
        Complete UTF-8 source buffer.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        Crate-level and item-level Rustdoc artifacts in source order.

    Notes
    -----
    Only ``//!`` and ``///`` line comments are recognized. Block comments and
    macro-expanded documentation remain deliberately outside this boundary.
    """
    owners = [(analysis.module.stable_id, "module", analysis.module.name, 1)]
    owners.extend(
        (item.stable_id, item.kind, item.name, item.lineno)
        for item in analysis.declarations
    )
    owners.extend(
        (item.stable_id, "type", item.name, item.lineno) for item in analysis.classes
    )
    owners.extend(
        (item.stable_id, "function", item.name, item.lineno)
        for item in (
            *analysis.functions,
            *(method for cls in analysis.classes for method in cls.methods),
        )
    )
    ordered_owners = sorted(owners, key=lambda item: item[3])
    artifacts: list[DocumentationArtifact] = []
    lines = source.decode("utf-8", "replace").splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip()
        marker = (
            "//!"
            if stripped.startswith("//!")
            else "///"
            if stripped.startswith("///")
            else None
        )
        if marker is None:
            index += 1
            continue
        start = index
        text_lines: list[str] = []
        while index < len(lines) and lines[index].lstrip().startswith(marker):
            text_lines.append(lines[index].lstrip()[3:].removeprefix(" "))
            index += 1
        end = index
        if marker == "//!":
            owner_id, owner_kind, title = (
                analysis.module.stable_id,
                "module",
                analysis.module.name,
            )
        else:
            match = next((item for item in ordered_owners if item[3] >= end + 1), None)
            if match is None:
                continue
            owner_id, owner_kind, title, _ = match
        artifacts.append(
            DocumentationArtifact(
                stable_id=f"doc:rustdoc:{owner_id}:{start + 1}",
                kind="module" if owner_kind == "module" else "declaration",
                source_format="rustdoc",
                source_path=path,
                lineno=start + 1,
                end_lineno=end,
                title=title,
                heading_path=(),
                text="\n".join(text_lines).strip(),
                owner_stable_id=owner_id,
                owner_kind=owner_kind,
                attachment_confidence="explicit",
            )
        )
    return tuple(artifacts)


def _with_rustdoc(analysis: AnalysisResult, source: bytes) -> AnalysisResult:
    """Attach extracted Rustdoc text to the matching semantic artifacts.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Parsed Rust artifacts without documentation attachments.
    source : bytes
        Complete UTF-8 source buffer.

    Returns
    -------
    codira.models.AnalysisResult
        Analysis result with Rustdoc artifacts and matching docstring fields.
    """
    documentation = _rustdoc_artifacts(
        path=analysis.source_path,
        analysis=analysis,
        source=source,
    )
    doc_by_owner = {
        item.owner_stable_id: item.text
        for item in documentation
        if item.owner_stable_id is not None
    }

    def documented_function(item: FunctionArtifact) -> FunctionArtifact:
        """Return one callable with its explicit Rustdoc attachment."""
        doc = doc_by_owner.get(item.stable_id)
        return replace(item, docstring=doc, has_docstring=int(doc is not None))

    return replace(
        analysis,
        module=replace(
            analysis.module,
            docstring=doc_by_owner.get(analysis.module.stable_id),
            has_docstring=int(analysis.module.stable_id in doc_by_owner),
        ),
        declarations=tuple(
            replace(item, docstring=doc_by_owner.get(item.stable_id))
            for item in analysis.declarations
        ),
        classes=tuple(
            replace(
                item,
                docstring=doc_by_owner.get(item.stable_id),
                has_docstring=int(item.stable_id in doc_by_owner),
                methods=tuple(documented_function(method) for method in item.methods),
            )
            for item in analysis.classes
        ),
        functions=tuple(documented_function(item) for item in analysis.functions),
        documentation=documentation,
    )


class RustAnalyzer:
    """Analyze Rust syntax into Codira's stable language-neutral artifacts.

    Parameters
    ----------
    None

    Notes
    -----
    Extraction is intentionally syntax-only: macro expansion and compiler
    semantics are outside this plugin's contract.
    """

    name = "rust"
    version = "2"
    discovery_globs: tuple[str, ...] = ("*.rs",)
    default_coverage_roots: tuple[str, ...] = ("src", "tests", "benches", "examples")

    def __init__(self) -> None:
        """Initialize default path-filter configuration.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Instance configuration is initialized.
        """
        self._path_filters = AnalyzerPathFilters()
        self._emit_macros = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """Return the Rust analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict schema containing the shared path-filter options.
        """
        return analyzer_json_schema({"emit_macros": boolean_property(True)})

    def configure(self, config: Mapping[str, object]) -> None:
        """Apply Rust analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration.

        Returns
        -------
        None
            Shared path filters and the configuration fingerprint are updated.
        """
        self._path_filters = analyzer_path_filters_from_config(config)
        self._emit_macros = bool(config.get("emit_macros", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """Declare Rust ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping for syntax-only Rust extraction.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_rust:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "namespace",
                "documentation",
            ),
            does_not_support=("variable",),
            mappings={
                "module": "module",
                "rust_module": "namespace",
                "struct": "type",
                "enum": "type",
                "trait": "type",
                "impl": "type",
                "function": "callable",
                "method": "callable",
                "use": "import",
                "const": "constant",
                "macro_rules": "constant",
                "rustdoc": "documentation",
            },
        )

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """Declare Rust parser execution safety.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Safe process and thread worker support.
        """
        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """Return whether a path has a Rust suffix.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` only for ``.rs`` paths.
        """
        return path.suffix in _RUST_SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """Return whether configured filters allow a Rust path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        bool
            ``True`` when shared analyzer path filters allow the path.
        """
        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """Analyze a Rust file without macro expansion or compiler emulation.

        Parameters
        ----------
        path : pathlib.Path
            Rust source file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Deterministically ordered Rust artifacts.
        """
        source = path.read_bytes()
        owner = _owner(path, root)
        declarations: list[DeclarationArtifact] = []
        classes: list[ClassArtifact] = []
        functions: list[FunctionArtifact] = []
        imports: list[ImportArtifact] = []

        for node in _parser().parse(source).root_node.named_children:
            name = _identifier(node, source)
            if node.type == "use_declaration":
                imports.append(_import(node, source))
            elif node.type == "macro_definition":
                macro = _macro_declaration(node, source, owner=owner)
                if macro is not None:
                    declarations.append(macro)
            elif (
                node.type in {"struct_item", "enum_item", "const_item", "mod_item"}
                and name
            ):
                declaration_kind = cast(
                    "DeclarationKind",
                    {
                        "struct_item": "struct",
                        "enum_item": "enum",
                        "const_item": "constant",
                        "mod_item": "namespace",
                    }[node.type],
                )
                stable_id = f"rust:{declaration_kind}:{owner}:{name}"
                declarations.append(
                    DeclarationArtifact(
                        name=name,
                        stable_id=stable_id,
                        kind=declaration_kind,
                        lineno=node.start_point.row + 1,
                        signature=_normalized(node, source),
                        enum_members=(
                            _enum_members(
                                node, source, owner=owner, parent_id=stable_id
                            )
                            if node.type == "enum_item"
                            else ()
                        ),
                    )
                )
            elif node.type == "function_item":
                function = _function(node, source, owner=owner, owner_name=None)
                if function is not None:
                    functions.append(function)
            elif node.type in {"trait_item", "impl_item"}:
                owner_name = (
                    name or _normalized(node, source).split("{", 1)[0].strip()
                    if node.type == "trait_item"
                    else _normalized(node, source).split("{", 1)[0].strip()
                )
                methods = tuple(
                    function
                    for child in _descendants(node)
                    if child.type in {"function_item", "function_signature_item"}
                    if (
                        function := _function(
                            child, source, owner=owner, owner_name=owner_name
                        )
                    )
                    is not None
                )
                owner_kind = "trait" if node.type == "trait_item" else "impl"
                classes.append(
                    ClassArtifact(
                        name=owner_name,
                        stable_id=f"rust:{owner_kind}:{owner}:{owner_name}",
                        lineno=node.start_point.row + 1,
                        end_lineno=node.end_point.row + 1,
                        docstring=None,
                        has_docstring=0,
                        methods=methods,
                    )
                )

        result = AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=_module_name(path, root),
                stable_id=f"rust:module:{owner}",
                docstring=None,
                has_docstring=0,
            ),
            classes=tuple(classes),
            functions=tuple(functions),
            declarations=tuple(declarations),
            imports=tuple(imports),
        )
        if not self._emit_macros:
            result = replace(
                result,
                declarations=tuple(
                    item for item in result.declarations if item.kind != "macro"
                ),
            )
        return _with_rustdoc(result, source)


def build_analyzer() -> LanguageAnalyzer:
    """Build the first-party Rust analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh Rust analyzer instance.
    """
    return RustAnalyzer()
