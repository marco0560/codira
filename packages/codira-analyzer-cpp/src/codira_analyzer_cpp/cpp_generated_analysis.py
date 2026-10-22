"""Integrate explicit captured declaration macros with normalized C++ analysis.

Parameters
----------
None

Returns
-------
None
    Bounded in-process selection, projection and generated callable provenance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING

from tree_sitter import Node

from codira.generated import (
    GeneratedCallableProvenance,
    GeneratedTokenProvenance,
    MacroInputProvenance,
)
from codira.models import AnalysisResult, CallSite, OverloadArtifact

from .cpp_include_context import IncludeContext
from .cpp_active_source import project_root_activity
from .cpp_macro_context import (
    MacroSelection,
    _ContextWalk,
    _MAX_CAPTURE_FILES,
    _directives,
)
from .cpp_macro_expansion import (
    _MacroDefinition,
    _MacroExpander,
    _MacroToken,
    _macro_tokens,
)
from .cpp_macro_projection import (
    MacroProjection,
    MacroReplacement,
    project_macro_replacements,
)
from .cpp_namespace_bindings import _parse_with_namespace_bindings
from .cpp_projection import SyntaxNode, _ProjectedNode
from .cpp_preprocessing import _conditional_else_source, _original_declaration_start
from .cpp_syntax import (
    _function_stable_id,
    _node_text,
    _normalize_signature,
    _symbol_owner_id,
    _new_parser,
)
from .cpp_statement_macros import (
    declaration_invocations,
    has_lexical_calls,
    is_declaration_statement,
    statement_invocations,
)
from .cpp_preprocessor_queries import QueryResolver

if TYPE_CHECKING:
    from . import CppAnalyzer

_NAME = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")


def preprocessor_definitions(value: object) -> dict[bytes, _MacroDefinition | None]:
    """Validate explicit replacement, undefined and opaque-defined profile states.

    Parameters
    ----------
    value : object
        Configuration mapping; true means 1, false means undefined, and
        {'defined': true} preserves definedness without inventing a replacement.

    Returns
    -------
    dict[bytes, _MacroDefinition | None]
        Explicit bounded initial states; missing names remain unknown.

    Raises
    ------
    ValueError
        If names, state shapes or replacement token syntax are unsupported.
    """
    if not isinstance(value, Mapping) or len(value) > 4096:
        raise ValueError("preprocessor_definitions must be a bounded mapping")
    result: dict[bytes, _MacroDefinition | None] = {}
    for name, replacement in value.items():
        if (
            not isinstance(name, str)
            or not name.isascii()
            or _NAME.fullmatch(name.encode()) is None
            or name == "defined"
        ):
            raise ValueError("invalid preprocessor definition name")
        key = name.encode()
        if replacement is False:
            result[key] = None
        elif replacement is True:
            result[key] = _MacroDefinition(None, b"1")
        elif isinstance(replacement, str):
            raw = replacement.encode()
            if b"\n" in raw or b"\r" in raw:
                raise ValueError("profile replacement must be a single logical line")
            _macro_tokens(raw)
            result[key] = _MacroDefinition(None, raw)
        elif (
            isinstance(replacement, Mapping)
            and set(replacement) == {"defined"}
            and replacement["defined"] is True
        ):
            result[key] = _MacroDefinition(None, b"", opaque=True)
        else:
            raise ValueError(
                "profile values must be replacements, booleans or {'defined': true}"
            )
    _MacroExpander({name: item for name, item in result.items() if item is not None})
    return result


def captured_identity(context: IncludeContext, configuration: str) -> str:
    """Bind one frozen source/include manifest to its explicit configuration.

    Parameters
    ----------
    context : IncludeContext
        Frozen source bytes and ordered resolution observations.
    configuration : str
        Analyzer configuration fingerprint.

    Returns
    -------
    str
        Opaque canonical input identity also used by incremental reuse.
    """
    payload = json.loads(context.identity)
    payload["configuration_fingerprint"] = configuration
    payload["generated_provenance_version"] = 1
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


@dataclass(frozen=True)
class _Expansion:
    """Retain one selected invocation and its exact generated parser interval.

    Parameters
    ----------
    span : tuple[int, int]
        Original invocation range.
    tokens : tuple[_MacroToken, ...]
        Rescanned replacement tokens.
    selection : MacroSelection
        Reaching explicit/captured states at the invocation.
    used : frozenset[bytes]
        Definitions actually substituted, including argument prescan.
    projected_span : tuple[int, int]
        Rendered token interval in the parser projection.
    namespace : bool, optional
        Whether this replacement supplies a namespace declaration name.
    statement : bool, optional
        Whether this replacement supplies one source-owned static assertion.
    declaration_statement : bool, optional
        Whether this replacement forwards one bounded declaration statement.
    arguments : tree_sitter.Node or None, optional
        Original argument syntax when a replacement completely erases operands.

    Returns
    -------
    None
        Immutable evidence for normalization.
    """

    span: tuple[int, int]
    tokens: tuple[_MacroToken, ...]
    selection: MacroSelection
    used: frozenset[bytes]
    projected_span: tuple[int, int]
    namespace: bool = False
    statement: bool = False
    arguments: Node | None = None
    declaration_statement: bool = False


def _invocations(source: bytes) -> tuple[tuple[int, int, bytes, bool], ...]:
    """Locate bounded complete declaration headers and namespace identifiers.

    Parameters
    ----------
    source : bytes
        Original source, including untouched physical function bodies.

    Returns
    -------
    tuple[tuple[int, int, bytes, bool], ...]
        Ordered candidate spans, macro names and namespace-name flags.

    Raises
    ------
    ValueError
        If lexical syntax or invocation bounds are unsupported.
    """
    directives = _directives(source)
    tokens = _macro_tokens(source)
    result: list[tuple[int, int, bytes, bool]] = []
    for index, token in enumerate(tokens):
        if _NAME.fullmatch(token.spelling) is None or any(
            first <= token.start < last for first, last, _, _ in directives
        ):
            continue
        if (
            index
            and tokens[index - 1].spelling == b"namespace"
            and index + 1 < len(tokens)
            and tokens[index + 1].spelling == b"{"
        ):
            result.append((token.start, token.end, token.spelling, True))
        elif index + 1 < len(tokens) and tokens[index + 1].spelling == b"(":
            depth = 0
            for closing in range(index + 1, len(tokens)):
                spelling = tokens[closing].spelling
                depth += int(spelling == b"(") - int(spelling == b")")
                if depth == 0:
                    if (
                        closing + 1 < len(tokens)
                        and tokens[closing + 1].spelling == b"{"
                    ):
                        result.append(
                            (token.start, tokens[closing].end, token.spelling, False)
                        )
                    break
    if len(result) > 256:
        raise ValueError("declaration macro candidate limit exceeded")
    return tuple(result)


def _nodes(root: SyntaxNode) -> tuple[SyntaxNode, ...]:
    """Visit named parser nodes without filesystem or compiler access.

    Parameters
    ----------
    root : SyntaxNode
        Root whose coordinate buffer is held by the caller.

    Returns
    -------
    tuple[SyntaxNode, ...]
        Deterministic preorder of named nodes.
    """
    pending = [root]
    result = []
    while pending:
        node = pending.pop()
        result.append(node)
        pending.extend(reversed(node.named_children))
    return tuple(result)


def _parameter_types(node: SyntaxNode, source: bytes) -> tuple[str, ...]:
    """Retain written parameter types while removing only proven name tokens.

    Parameters
    ----------
    node : SyntaxNode
        Function declaration or definition.
    source : bytes
        Coordinate-aligned parser bytes.

    Returns
    -------
    tuple[str, ...]
        Source-spelled types; no compiler equivalence is inferred.

    Raises
    ------
    ValueError
        If the declaration is not a supported nonvariadic callable.
    """
    from . import _find_function_declarator, _parameter_name_node

    declarator = _find_function_declarator(node)
    parameters = (
        None if declarator is None else declarator.child_by_field_name("parameters")
    )
    if parameters is None:
        raise ValueError("generated callable lacks parameter syntax")
    types = []
    for parameter in parameters.named_children:
        if parameter.type == "comment":
            continue
        if parameter.type != "parameter_declaration":
            raise ValueError("unsupported generated parameter syntax")
        raw = source[parameter.start_byte : parameter.end_byte]
        name_node = parameter.child_by_field_name("declarator")
        name_node = None if name_node is None else _parameter_name_node(name_node)
        if name_node is not None:
            first = name_node.start_byte - parameter.start_byte
            last = name_node.end_byte - parameter.start_byte
            raw = raw[:first] + raw[last:]
        value = _normalize_signature(raw.decode())
        if value != "void":
            types.append(value)
    return tuple(types)


def _namespace_at(node: SyntaxNode, source: bytes, selection: MacroSelection) -> str:
    """Resolve enclosing namespace names at a proven active declaration query.

    Parameters
    ----------
    node : SyntaxNode
        Declaration node in its original captured file.
    source : bytes
        Coordinate-aligned captured bytes.
    selection : MacroSelection
        States reaching this declaration during its include visit.

    Returns
    -------
    str
        Qualified source namespace; unavailable replacements remain failures.

    Raises
    ------
    ValueError
        If namespace expansion is ambiguous or unsupported.
    """
    from .cpp_macro_projection import _render_macro_tokens
    from .cpp_syntax import _new_parser

    definitions = {
        name: binding.definition
        for name, binding in selection.bindings
        if binding.definition is not None
    }
    scopes = []
    parent = node.parent
    while parent is not None:
        if parent.type == "namespace_definition":
            name = parent.child_by_field_name("name")
            if name is None:
                raise ValueError("anonymous namespace callable type is unsupported")
            tokens = _MacroExpander(definitions).expand(
                _macro_tokens(_node_text(name, source).encode())
            )
            rendered, _ = _render_macro_tokens(tokens)
            trial = b"namespace " + rendered + b" {}"
            tree = _new_parser().parse(trial).root_node
            namespace = next(
                (
                    child
                    for child in tree.named_children
                    if child.type == "namespace_definition"
                ),
                None,
            )
            resolved = (
                None if namespace is None else namespace.child_by_field_name("name")
            )
            if tree.has_error or resolved is None:
                raise ValueError("unresolved generated callable namespace")
            scopes.append(trial[resolved.start_byte : resolved.end_byte].decode())
        parent = parent.parent
    return "::".join(reversed(scopes))


def analyze_generated_file(
    analyzer: CppAnalyzer, path: Path, root: Path, context: IncludeContext
) -> AnalysisResult:
    """Analyze explicitly configured macros from the same captured input snapshot.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Configured owner with an explicit preprocessing profile.
    path, root : pathlib.Path
        Original file and trusted repository boundary.
    context : IncludeContext
        Frozen original source/header bytes and resolution observations.

    Returns
    -------
    AnalysisResult
        Generated-aware normalized metadata with physical body coordinates.

    Raises
    ------
    ValueError
        If required context, declaration semantics or mapping is unsupported.
    """
    source = context.source
    key = path.resolve().relative_to(root.resolve()).as_posix()
    captures = {
        key: source,
        **{
            h.path.relative_to(root.resolve()).as_posix(): h.source
            for h in context.headers
        },
    }
    if len(captures) > _MAX_CAPTURE_FILES:
        raise ValueError("macro context capture limit exceeded")
    identity = json.loads(context.identity)
    resolutions = {
        (owner, spelling, quoted): target if status == "resolved" else None
        for owner, spelling, quoted, status, target in identity["lookups"]
        if quoted is not None
    }
    initial = analyzer._preprocessor_definitions
    assert initial is not None
    statements = statement_invocations(source, captures)
    statement_spans = {(first, last) for first, last, _ in statements}
    declarations = declaration_invocations(source, captures)
    declaration_spans = {(first, last) for first, last, _ in declarations}
    candidates = tuple(
        sorted(
            {
                *_invocations(source),
                *((first, last, name, False) for first, last, name in statements),
                *((first, last, name, False) for first, last, name in declarations),
            }
        )
    )
    if any(left[1] > right[0] for left, right in zip(candidates, candidates[1:])):
        raise ValueError("overlapping declaration and statement macro invocations")
    from . import (
        _initializer_header_value_bindings_from_walk,
        _initializer_header_value_query_plan,
    )

    initializer_root = _parse_with_namespace_bindings(
        source,
        bindings=analyzer._namespace_macro_definitions,
        included_sources=tuple((h.source, h.available_after) for h in context.headers),
    )
    initializer_plan = _initializer_header_value_query_plan(
        analyzer, initializer_root, source, context, root
    )
    query_answers = _query_resolver(analyzer, key, context, captures)
    walk = _ContextWalk(
        captures,
        resolutions,
        initial,
        query_offsets=initializer_plan.header_query_offsets,
        query_resolver=None if query_answers is None else query_answers.resolve,
        feature_resolver=None
        if query_answers is None
        else query_answers.expand_feature,
        track_root_activity=True,
    )
    walk.walk(
        key,
        offsets=tuple(
            sorted(
                {item[0] for item in candidates} | set(initializer_plan.root_offsets)
            )
        ),
    )
    initializer_value_bindings = _initializer_header_value_bindings_from_walk(
        analyzer,
        initializer_root,
        source,
        context,
        root,
        captures,
        walk,
        initializer_plan,
    )
    replacements = []
    records = []
    for first, last, name, namespace in candidates:
        selection = walk.results[first]
        binding = dict(selection.bindings).get(name)
        statement_candidate = (first, last) in statement_spans
        declaration_candidate = (first, last) in declaration_spans
        declaration_statement = declaration_candidate
        if (
            (statement_candidate or declaration_statement)
            and binding is not None
            and binding.definition is None
        ):
            continue
        if (
            (statement_candidate or declaration_statement)
            and selection.active is not False
            and (
                selection.active is not True
                or binding is None
                or binding.definition is None
            )
        ):
            raise ValueError("statement macro has uncertain reaching definition")
        if (
            selection.active is not True
            or binding is None
            or binding.definition is None
        ):
            continue
        definitions = {
            name: binding.definition
            for name, binding in selection.bindings
            if binding.definition is not None
        }
        expander = _MacroExpander(definitions)
        tokens = expander.expand(_macro_tokens(source[first:last], offset=first))
        if not expander.used:
            continue
        if declaration_statement and not is_declaration_statement(tokens):
            declaration_statement = False
        statement = statement_candidate and not declaration_statement
        if declaration_candidate and not declaration_statement and not statement:
            continue
        if declaration_statement and not tokens:
            # An empty replacement may erase a declaration containing written
            # calls. Keep parseable expression wrappers intact, and leave any
            # unsupported/invalid operand syntax to the normal error path.
            if has_lexical_calls(source, first, last) is not False:
                continue
        argument_tree = None
        if statement:
            if not tokens or tokens[0].spelling != b"static_assert":
                continue
            trial = b" ".join(t.spelling for t in tokens)
            if not trial.rstrip().endswith(b";"):
                trial += b";"
            assertion = _new_parser().parse(trial).root_node
            if (
                assertion.has_error
                or len(assertion.named_children) != 1
                or assertion.named_children[0].type != "static_assert_declaration"
            ):
                raise ValueError("statement macro is not one static assertion")
            arguments = _macro_tokens(source[first:last], offset=first)[2:-1]
            preserved = {
                (t.start, t.end) for t in tokens if t.argument and not t.synthetic
            }
            if any(t.spelling == b"(" for t in arguments) and any(
                t.spelling != b"," and (t.start, t.end) not in preserved
                for t in arguments
            ):
                if any(
                    t.argument or t.operation in {"paste", "stringify"} for t in tokens
                ):
                    raise ValueError(
                        "statement macro erases or transforms call-shaped argument spelling"
                    )
                argument_tree = _statement_argument_tree(source, first, last)
        replacements.append(MacroReplacement((first, last), tokens))
        records.append(
            (
                len(replacements) - 1,
                (first, last),
                tokens,
                selection,
                frozenset(expander.used),
                namespace,
                statement,
                argument_tree,
                declaration_statement,
            )
        )
    if not replacements and not any(
        active is False or directive in {b"if", b"ifdef", b"ifndef"}
        for _, _, active, directive in walk.root_activity
    ):
        return analyzer._analyze_captured_file(
            path,
            root,
            context,
            initializer_value_bindings=initializer_value_bindings,
        )
    retained_regions: list[tuple[int, int]] = []
    if b"else" in source:
        parser = _new_parser()
        _conditional_else_source(
            source,
            parser.parse(source).root_node,
            parser,
            tuple((h.source, h.available_after) for h in context.headers),
            retained_regions=retained_regions,
        )
    unmasked = project_macro_replacements(source, tuple(replacements))
    projection = project_root_activity(
        unmasked,
        walk.root_activity,
        retained_regions=retained_regions,
    )
    if not replacements:
        if not projection.masked_spans:
            return analyzer._analyze_captured_file(
                path,
                root,
                context,
                initializer_value_bindings=initializer_value_bindings,
            )
        return _analyze_statements(
            analyzer,
            path,
            root,
            context,
            projection,
            (),
            initializer_value_bindings=initializer_value_bindings,
        )
    expansions = []
    token_index = 0
    for (
        replacement_index,
        span,
        tokens,
        selection,
        used,
        namespace,
        statement,
        argument_tree,
        declaration_statement,
    ) in records:
        rendered = projection.generated_tokens[token_index : token_index + len(tokens)]
        if tokens and not rendered:
            raise ValueError("declaration expansion produced no syntax")
        projected_span = (
            (rendered[0].projected_span[0], rendered[-1].projected_span[1])
            if rendered
            else projection.replacement_spans[replacement_index]
        )
        expansions.append(
            _Expansion(
                span,
                tokens,
                selection,
                used,
                projected_span,
                namespace,
                statement,
                argument_tree,
                declaration_statement,
            )
        )
        token_index += len(tokens)
    projected_context = _projected_context(context, projection)
    projected_initializer_bindings = _project_initializer_value_bindings(
        initializer_value_bindings, initializer_plan.root_spans, projection
    )
    if expansions and all(expansion.statement for expansion in expansions):
        return _analyze_statements(
            analyzer,
            path,
            root,
            context,
            projection,
            tuple(expansions),
            initializer_value_bindings=initializer_value_bindings,
        )
    result = analyzer._analyze_captured_file(
        path,
        root,
        projected_context,
        comment_source=unmasked.source if projection.masked_spans else None,
        initializer_value_bindings=projected_initializer_bindings,
    )
    return _finalize(
        analyzer,
        path,
        root,
        context,
        projection,
        tuple(expansions),
        captures,
        resolutions,
        result,
        initializer_value_bindings=initializer_value_bindings,
    )


def _query_resolver(
    analyzer: CppAnalyzer,
    key: str,
    context: IncludeContext,
    captures: Mapping[str, bytes],
) -> QueryResolver | None:
    """License header facts only against this full input graph and prefix profile.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Explicitly configured profile owner.
    key : str
        Contained original translation-unit path.
    context : IncludeContext
        Unmodified physical input identity, including dependency hashes.
    captures : Mapping[str, bytes]
        Exact source buffers consumed by the context walk.

    Returns
    -------
    QueryResolver or None
        Offline operator resolution; stale or absent facts remain unknown.
    """
    initial = analyzer._preprocessor_definitions
    assert initial is not None
    supplied = analyzer._preprocessor_header_queries.get(key)
    headers = (
        supplied.queries
        if supplied is not None
        and supplied.profile_fingerprint
        == analyzer._preprocessor_query_profile_fingerprint
        and supplied.context_sha256
        == hashlib.sha256(context.identity.encode()).hexdigest()
        else ()
    )
    if not analyzer._preprocessor_features and not headers:
        return None
    return QueryResolver(captures, initial, analyzer._preprocessor_features, headers)


def _statement_argument_tree(source: bytes, first: int, last: int) -> Node:
    """Parse erased written operands separately without adding declaration syntax.

    Parameters
    ----------
    source : bytes
        Immutable physical translation unit.
    first, last : int
        Complete selected macro invocation boundaries.

    Returns
    -------
    tree_sitter.Node
        Argument list with unchanged physical byte and line coordinates.

    Raises
    ------
    ValueError
        If the invocation cannot be parsed as exactly one ordinary call.
    """
    prefix = re.sub(rb"[^\r\n]", b" ", source[:first])
    root = _new_parser().parse(prefix + source[first:last] + b";").root_node
    expression = (
        root.named_children[0]
        if not root.has_error and len(root.named_children) == 1
        else None
    )
    call = (
        expression.named_children[0]
        if expression is not None
        and expression.type == "expression_statement"
        and len(expression.named_children) == 1
        else None
    )
    arguments = (
        call.child_by_field_name("arguments")
        if call is not None
        and call.type == "call_expression"
        and (call.start_byte, call.end_byte) == (first, last)
        else None
    )
    if arguments is None:
        raise ValueError(
            "erased statement macro arguments lack complete lexical syntax"
        )
    return arguments


def _statement_tree(
    source: bytes,
    projection: MacroProjection,
    tree: SyntaxNode,
    expansions: tuple[_Expansion, ...],
) -> SyntaxNode:
    """Attach source hints and detached lexical operands to projected assertions.

    Parameters
    ----------
    source : bytes
        Original physical source.
    projection : MacroProjection
        Selected replacement tokens and physical origin mapping.
    tree : SyntaxNode
        Parsed replacement syntax.
    expansions : tuple[_Expansion, ...]
        Statement expansions whose reaching definitions are known.

    Returns
    -------
    SyntaxNode
        Physical syntax with separately owned original call operands.

    Raises
    ------
    ValueError
        If a selected assertion has no unique mapped syntax owner.
    """
    physical_tree = projection.syntax_tree(tree)
    owners = {e.projected_span[0]: e for e in expansions if e.statement}
    found = set()
    for node, physical in zip(_nodes(tree), _nodes(physical_tree), strict=True):
        expansion = owners.get(node.start_byte)
        if node.type != "static_assert_declaration" or expansion is None:
            continue
        if not isinstance(physical, _ProjectedNode):
            raise ValueError("statement macro syntax lacks a physical projection")
        physical.macro_hint = _macro_tokens(
            source[expansion.span[0] : expansion.span[1]]
        )[0].spelling.decode()
        physical.macro_arguments = expansion.arguments
        found.add(node.start_byte)
    if found != owners.keys():
        raise ValueError("statement macro assertion has no mapped syntax owner")
    return physical_tree


def _analyze_statements(
    analyzer: CppAnalyzer,
    path: Path,
    root: Path,
    context: IncludeContext,
    projection: MacroProjection,
    expansions: tuple[_Expansion, ...],
    *,
    initializer_value_bindings: Mapping[str, tuple[int, ...]] | None = None,
) -> AnalysisResult:
    """Extract ordinary metadata from statement syntax mapped to original bytes.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Explicitly configured source owner.
    path, root : pathlib.Path
        Original source and trusted repository boundary.
    context : IncludeContext
        Immutable original include/source snapshot.
    projection : MacroProjection
        Selected assertion tokens and separate argument spelling evidence.
    expansions : tuple[_Expansion, ...]
        Statement-only invocations licensed by the ordered context walk.
    initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]] | None, optional
        Qualified header values keyed by original declaration offsets.

    Returns
    -------
    AnalysisResult
        Ordinary ownership and physical metadata, including source macro hints.

    Raises
    ------
    ValueError
        If generated calls lack physical source ownership or assertions are lost.
    """
    from . import _call_site_from_expression

    projected = _projected_context(context, projection)
    tree = _parse_with_namespace_bindings(
        projection.source,
        bindings=analyzer._namespace_macro_definitions,
        included_sources=tuple(
            (h.source, h.available_after) for h in projected.headers
        ),
    )
    nodes = _nodes(tree)
    for node in nodes:
        if node.type != "call_expression":
            continue
        call = _call_site_from_expression(node, projection.source)
        if call is None:
            continue
        offset = _offset(projection.source, call.lineno, call.col_offset)
        if projection.physical_span(offset, offset + 1, include_arguments=True) is None:
            raise ValueError(
                f"replacement-introduced call {call.external_target_name or call.target!r} lacks separate generated ownership"
            )
    physical_tree = _statement_tree(context.source, projection, tree, expansions)
    return analyzer._analyze_captured_file(
        path,
        root,
        context,
        syntax_root=physical_tree,
        comment_source=context.source if projection.masked_spans else None,
        initializer_value_bindings=initializer_value_bindings,
    )


def _project_initializer_value_bindings(
    bindings: Mapping[str, tuple[int, ...]],
    declaration_ends: Mapping[int, int],
    projection: MacroProjection,
) -> dict[str, tuple[int, ...]]:
    """Map facts only for complete declarations copied unchanged to a projection.

    Parameters
    ----------
    bindings : collections.abc.Mapping[str, tuple[int, ...]]
        Proven qualified names and original candidate declaration starts.
    declaration_ends : collections.abc.Mapping[int, int]
        Original end offsets for each candidate declaration start.
    projection : MacroProjection
        Selected parser projection with explicit unchanged source segments.

    Returns
    -------
    dict[str, tuple[int, ...]]
        Facts keyed by projected starts when the entire candidate lies in one
        unchanged interval. Generated or partial declarations remain unknown.
    """
    result: dict[str, set[int]] = {}
    for name, offsets in bindings.items():
        for original_start in offsets:
            original_end = declaration_ends.get(original_start)
            if original_end is None:
                continue
            for segment in projection.original_segments:
                segment_start, segment_end = segment.original_span
                if segment_start <= original_start < original_end <= segment_end:
                    projected_start = segment.projected_start + (
                        original_start - segment_start
                    )
                    result.setdefault(name, set()).add(projected_start)
                    break
    return {name: tuple(sorted(offsets)) for name, offsets in result.items()}


def _projected_context(
    context: IncludeContext, projection: MacroProjection
) -> IncludeContext:
    """Translate original include availability boundaries into parser coordinates.

    Parameters
    ----------
    context : IncludeContext
        Frozen original source/header inputs.
    projection : MacroProjection
        Generated parser bytes and unchanged intervals.

    Returns
    -------
    IncludeContext
        Parser context whose header availability preserves actual include order.

    Raises
    ------
    ValueError
        If an include boundary is not in unchanged physical source.
    """
    headers = []
    for header in context.headers:
        boundary = next(
            (
                projected_start + header.available_after - first
                for projected_start, first, last in (
                    projection.coordinate_segments
                    or tuple(
                        (s.projected_start, *s.original_span)
                        for s in projection.original_segments
                    )
                )
                if first <= header.available_after <= last
            ),
            None,
        )
        if boundary is None:
            raise ValueError("include availability boundary lies in generated syntax")
        headers.append(replace(header, available_after=boundary))
    return replace(context, source=projection.source, headers=tuple(headers))


def _line(source: bytes, offset: int) -> int:
    """Convert a physical byte offset to its one-based source line.

    Parameters
    ----------
    source : bytes
        Original source buffer.
    offset : int
        Physical byte position.

    Returns
    -------
    int
        One-based physical line.
    """
    return source.count(b"\n", 0, offset) + 1


def _offset(source: bytes, line: int, column: int = 0) -> int:
    """Locate a parser line and byte column in its coordinate buffer.

    Parameters
    ----------
    source : bytes
        Parser buffer.
    line, column : int
        One-based line and zero-based byte column.

    Returns
    -------
    int
        Byte position, bounded to the source length.
    """
    return min(
        len(source),
        sum(len(part) for part in source.splitlines(keepends=True)[: line - 1])
        + column,
    )


def _physical_position(
    projection: MacroProjection, offset: int, expansions: tuple[_Expansion, ...]
) -> int:
    """Map copied bytes physically and generated positions only to invocation anchors.

    Parameters
    ----------
    projection : MacroProjection
        Original and generated coordinate buffers.
    offset : int
        Projected position.
    expansions : tuple[_Expansion, ...]
        Original invocation anchors for generated intervals.

    Returns
    -------
    int
        Physical byte or explicit invocation anchor, not generated spelling.

    Raises
    ------
    ValueError
        If no proven mapping or invocation anchor exists.
    """
    span = projection.physical_span(offset, offset + 1)
    if span is not None:
        return span[0]
    for expansion in expansions:
        if expansion.projected_span[0] - 1 <= offset <= expansion.projected_span[1] + 1:
            return expansion.span[0]
    if offset == len(projection.source):
        return len(projection.original)
    raise ValueError("unmapped generated source position")


def _inputs(
    selection: MacroSelection,
    used: frozenset[bytes],
    captures: Mapping[str, bytes],
) -> tuple[MacroInputProvenance, ...]:
    """Bind actually used replacement templates to all agreed captured origins.

    Parameters
    ----------
    selection : MacroSelection
        Bindings at the source position supplying replacement tokens.
    used : frozenset[bytes]
        Names actually substituted at that position.
    captures : Mapping[str, bytes]
        Frozen source bytes keyed by contained relative path.

    Returns
    -------
    tuple[MacroInputProvenance, ...]
        Profile or physical directive evidence, with exact definition digests.
    """
    bindings = dict(selection.bindings)
    result = []
    for name in sorted(used):
        binding = bindings[name]
        encoded = (
            json.dumps(
                asdict(binding.definition),
                sort_keys=True,
                default=lambda value: value.hex(),
            ).encode()
            if binding.definition is not None
            else b"null"
        )
        digest = hashlib.sha256(encoded).hexdigest()
        for origin in binding.origins:
            source_digest = (
                None
                if origin.source_path is None
                else hashlib.sha256(captures[origin.source_path]).hexdigest()
            )
            result.append(
                MacroInputProvenance(
                    name.decode(),
                    digest,
                    origin.source_path,
                    source_digest,
                    origin.span,
                )
            )
    return tuple(result)


@dataclass(frozen=True)
class _CallableTypeProof:
    """Retain expanded callable types and the earlier macros proving them.

    Parameters
    ----------
    return_type : str
        Expanded return type spelling.
    parameter_types : tuple[str, ...]
        Expanded parameter type spellings without parameter names.
    inputs : tuple[MacroInputProvenance, ...]
        Contributing definitions at the earlier declaration positions.

    Returns
    -------
    None
        Immutable type evidence independent of later macro redefinitions.
    """

    return_type: str
    parameter_types: tuple[str, ...]
    inputs: tuple[MacroInputProvenance, ...]


def _declaration_type_proof(
    node: SyntaxNode,
    source: bytes,
    selection: MacroSelection,
    captures: Mapping[str, bytes],
) -> _CallableTypeProof:
    """Expand callable type fragments with their declaration-time macro state.

    Parameters
    ----------
    node : SyntaxNode
        Earlier active callable declaration.
    source : bytes
        Coordinate-aligned captured declaration source.
    selection : MacroSelection
        Reaching definitions at this declaration, before later changes.
    captures : Mapping[str, bytes]
        Frozen source bytes for definition provenance.

    Returns
    -------
    _CallableTypeProof
        Exact expanded spellings and contributing macro origins.

    Raises
    ------
    ValueError
        If types are unavailable or depend on uncertain or opaque replacements.
    """
    from .cpp_macro_projection import _render_macro_tokens

    type_node = node.child_by_field_name("type")
    if type_node is None:
        raise ValueError("required callable return type is unavailable")
    definitions = {
        name: binding.definition
        for name, binding in selection.bindings
        if binding.definition is not None
    }
    expander = _MacroExpander(definitions)
    expanded = []
    for fragment in (_node_text(type_node, source), *_parameter_types(node, source)):
        tokens = _macro_tokens(fragment.encode())
        if any(token.spelling in selection.uncertain for token in tokens):
            raise ValueError("required callable type has uncertain macro state")
        tokens = expander.expand(tokens)
        if any(token.spelling in selection.uncertain for token in tokens):
            raise ValueError("expanded callable type has uncertain macro state")
        rendered, _ = _render_macro_tokens(tokens)
        expanded.append(_normalize_signature(rendered.decode()))
    return _CallableTypeProof(
        expanded[0],
        tuple(expanded[1:]),
        _inputs(selection, frozenset(expander.used), captures),
    )


def _header_callable_types(
    analyzer: CppAnalyzer,
    path: Path,
    root: Path,
    context: IncludeContext,
    captures: Mapping[str, bytes],
    resolutions: Mapping[tuple[str, str, bool], str | None],
    expansions: tuple[_Expansion, ...],
    references: frozenset[str],
) -> dict[tuple[int, str], _CallableTypeProof]:
    """Prove unique function types from active declarations reaching each invocation.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Explicitly configured owner.
    path, root : pathlib.Path
        Original file and trusted root.
    context : IncludeContext
        Frozen original inputs.
    captures, resolutions : Mapping
        Captured bytes and ordered literal include outcomes.
    expansions : tuple[_Expansion, ...]
        Invocations whose referenced callable types need proof.
    references : frozenset[str]
        Qualified decltype operands; variable declarations never qualify.

    Returns
    -------
    dict[tuple[int, str], _CallableTypeProof]
        Expanded types and earlier macro origins at each invocation offset.

    Raises
    ------
    ValueError
        If a required declaration is ambiguous, inactive, late or unsupported.
    """
    from . import (
        _find_function_declarator,
        _unwrap_declarator_name,
    )

    key = path.resolve().relative_to(root.resolve()).as_posix()
    queries: dict[str, list[int]] = {}
    declarations = []
    base_names = {ref.rsplit("::", 1)[-1] for ref in references}
    for owner, raw in captures.items():
        if not any(name.encode() in raw for name in base_names):
            continue
        tree = _parse_with_namespace_bindings(
            raw, bindings=analyzer._namespace_macro_definitions
        )
        for node in _nodes(tree):
            if node.type not in {"declaration", "function_definition"}:
                continue
            declarator = _find_function_declarator(node)
            name = (
                None if declarator is None else _unwrap_declarator_name(declarator, raw)
            )
            if name is None or name.rsplit("::", 1)[-1] not in base_names:
                continue
            queries.setdefault(owner, []).append(node.start_byte)
            declarations.append((owner, node, name, raw))
    initial = analyzer._preprocessor_definitions
    assert initial is not None
    root_offsets = sorted({e.span[0] for e in expansions} | set(queries.get(key, ())))
    query_answers = _query_resolver(analyzer, key, context, captures)
    walk = _ContextWalk(
        captures,
        resolutions,
        initial,
        query_offsets={
            owner: tuple(sorted(set(values))) for owner, values in queries.items()
        },
        query_resolver=None if query_answers is None else query_answers.resolve,
        feature_resolver=None
        if query_answers is None
        else query_answers.expand_feature,
    )
    walk.walk(key, offsets=tuple(root_offsets))
    result = {}
    for expansion in expansions:
        before = walk.query_events[key, expansion.span[0]][0]
        for reference in references:
            alternatives = set()
            origins: list[MacroInputProvenance] = []
            for owner, node, name, raw in declarations:
                for selection, event in zip(
                    walk.file_results.get((owner, node.start_byte), ()),
                    walk.query_events.get((owner, node.start_byte), ()),
                    strict=True,
                ):
                    if event >= before or selection.active is False:
                        continue
                    namespace = _namespace_at(node, raw, selection)
                    qualified = (namespace + "::" if namespace else "") + name
                    if qualified != reference:
                        continue
                    if selection.active is not True:
                        raise ValueError(
                            "required callable declaration has unknown activity"
                        )
                    proof = _declaration_type_proof(node, raw, selection, captures)
                    alternatives.add((proof.return_type, proof.parameter_types))
                    origins.extend(proof.inputs)
            if len(alternatives) != 1:
                raise ValueError(
                    "decltype requires a unique reaching function declaration"
                )
            return_type, parameter_types = alternatives.pop()
            result[expansion.span[0], reference] = _CallableTypeProof(
                return_type, parameter_types, tuple(dict.fromkeys(origins))
            )
    return result


def _finalize(
    analyzer: CppAnalyzer,
    path: Path,
    root: Path,
    context: IncludeContext,
    projection: MacroProjection,
    expansions: tuple[_Expansion, ...],
    captures: Mapping[str, bytes],
    resolutions: Mapping[tuple[str, str, bool], str | None],
    result: AnalysisResult,
    *,
    initializer_value_bindings: Mapping[str, tuple[int, ...]] | None = None,
) -> AnalysisResult:
    """Normalize generated declarations, relationships and original body coordinates.

    Parameters
    ----------
    analyzer : CppAnalyzer
        Explicitly configured source owner.
    path, root : pathlib.Path
        Original file and trusted repository boundary.
    context : IncludeContext
        Frozen original dependency graph.
    projection : MacroProjection
        Generated parser bytes and separate physical mappings.
    expansions : tuple[_Expansion, ...]
        Selected invocations and provenance.
    captures, resolutions : Mapping
        Exact captured bytes and ordered resolution observations.
    result : AnalysisResult
        Ordinary extraction from the projected buffer, before coordinate repair.
    initializer_value_bindings : collections.abc.Mapping[str, tuple[int, ...]] | None, optional
        Qualified header values keyed by original declaration offsets.

    Returns
    -------
    AnalysisResult
        Physical source positions and explicit generated callable/prototype/alias data.

    Raises
    ------
    ValueError
        If required identity, decltype type proof or source mapping is unsupported.
    """
    from . import (
        _extract_calls,
        _find_function_declarator,
        _parameter_name_node,
        _unwrap_declarator_name,
    )

    source = projection.source
    original = context.source
    tree = _parse_with_namespace_bindings(
        source,
        bindings=analyzer._namespace_macro_definitions,
        included_sources=tuple(
            (h.source, h.available_after)
            for h in _projected_context(context, projection).headers
        ),
    )
    nodes = _nodes(tree)
    statements = tuple(e for e in expansions if e.statement or e.declaration_statement)
    physical_nodes = (
        {
            (node.type, node.start_byte, node.end_byte): physical
            for node, physical in zip(
                nodes,
                _nodes(_statement_tree(original, projection, tree, statements)),
                strict=True,
            )
        }
        if statements
        else {}
    )

    def signature_line(node: SyntaxNode) -> int:
        """Find the extraction header boundary, including enclosing templates.

        Parameters
        ----------
        node : SyntaxNode
            Projected callable definition.

        Returns
        -------
        int
            Same one-based header line used by ordinary artifact extraction.
        """
        signature = node
        while signature.parent is not None and (
            signature.parent.type == "template_declaration"
            or signature.parent.type == "linkage_specification"
            and signature.parent.child_by_field_name("body") == signature
        ):
            signature = signature.parent
        return _line(source, _original_declaration_start(signature, source))

    def mapped_calls(
        calls: tuple[CallSite, ...],
        definition: SyntaxNode | None,
        parameters: tuple[str, ...],
    ) -> tuple[CallSite, ...]:
        """Preserve argument calls and retain the original statement macro hint.

        Parameters
        ----------
        calls : tuple[CallSite, ...]
            Calls extracted from projected syntax.
        definition : SyntaxNode or None
            Owning projected function definition, when uniquely identified.
        parameters : tuple[str, ...]
            Value parameters licensing initializer argument recovery.

        Returns
        -------
        tuple[CallSite, ...]
            Physical lexical sites, with repeated expansion copies deduplicated.

        Raises
        ------
        ValueError
            If a replacement-introduced call lacks physical argument ownership.
        """
        mapped = []
        for call in calls:
            position = _offset(source, call.lineno, call.col_offset)
            physical = projection.physical_span(
                position,
                position + 1,
                include_arguments=bool(statements),
            )
            if physical is None:
                raise ValueError(
                    f"replacement-introduced call {call.external_target_name or call.target!r} lacks separate generated ownership"
                )
            mapped.append(
                replace(
                    call,
                    lineno=_line(original, physical[0]),
                    col_offset=physical[0]
                    - (original.rfind(b"\n", 0, physical[0]) + 1),
                )
            )
        body = None if definition is None else definition.child_by_field_name("body")
        owned = tuple(
            e
            for e in statements
            if body is not None
            and body.start_byte <= e.projected_span[0] < body.end_byte
            and (
                e.projected_span[0] == e.projected_span[1]
                or e.projected_span[1] <= body.end_byte
            )
        )
        if not owned or body is None:
            return tuple(mapped)
        physical_body = physical_nodes[body.type, body.start_byte, body.end_byte]
        original_calls = _extract_calls(
            physical_body,
            original,
            parameter_names=parameters,
            initializer_value_bindings=initializer_value_bindings,
        )
        hints = []
        for expansion in owned:
            name = _macro_tokens(original[expansion.span[0] : expansion.span[1]])[
                0
            ].spelling.decode()
            hints.append(
                CallSite(
                    kind="name",
                    target=name,
                    lineno=_line(original, expansion.span[0]),
                    col_offset=expansion.span[0]
                    - (original.rfind(b"\n", 0, expansion.span[0]) + 1),
                    external_target_kind="C++:<macro>",
                    external_target_name=name,
                )
            )
        return tuple(
            sorted(
                dict.fromkeys((*original_calls, *hints)),
                key=lambda c: (c.lineno, c.col_offset),
            )
        )

    declarations = []
    for expansion in expansions:
        if (
            expansion.namespace
            or expansion.statement
            or expansion.declaration_statement
        ):
            continue
        for node in nodes:
            type_node = (
                node.child_by_field_name("type") if node.type == "declaration" else None
            )
            if (
                type_node is not None
                and type_node.type == "decltype"
                and expansion.projected_span[0]
                <= node.start_byte
                < expansion.projected_span[1]
            ):
                spelling = tuple(
                    t.spelling
                    for t in _macro_tokens(
                        source[type_node.start_byte : type_node.end_byte]
                    )
                )
                if (
                    len(spelling) < 4
                    or spelling[:2] != (b"decltype", b"(")
                    or spelling[-1] != b")"
                    or any(
                        token != b"::" and _NAME.fullmatch(token) is None
                        for token in spelling[2:-1]
                    )
                ):
                    raise ValueError("unsupported generated decltype operand")
                declarations.append(
                    (expansion, node, b"".join(spelling[2:-1]).decode())
                )
    references = frozenset(ref for _, _, ref in declarations)
    types = (
        _header_callable_types(
            analyzer,
            path,
            root,
            context,
            captures,
            resolutions,
            tuple(
                e
                for e in expansions
                if not e.namespace and not e.statement and not e.declaration_statement
            ),
            references,
        )
        if references
        else {}
    )
    input_identity = captured_identity(context, analyzer.configuration_fingerprint)
    source_digest = hashlib.sha256(original).hexdigest()
    type_inputs: dict[int, list[MacroInputProvenance]] = {}
    for (offset, _), proof in types.items():
        type_inputs.setdefault(offset, []).extend(proof.inputs)

    def provenance(
        expansion: _Expansion,
        node: SyntaxNode,
        role: str,
        names: tuple[str | None, ...],
        parameter_types: tuple[str, ...],
    ) -> GeneratedCallableProvenance:
        """Build role-specific generated evidence without physical spelling fiction.

        Parameters
        ----------
        expansion : _Expansion
            Original invocation and selected replacements.
        node : SyntaxNode
            Generated declaration or implementation node.
        role : str
            Definition, prototype or alias role.
        names : tuple[str | None, ...]
            Actual parameter names, including unnamed parameters.
        parameter_types : tuple[str, ...]
            Proven source-spelled parameter types.

        Returns
        -------
        GeneratedCallableProvenance
            Immutable declaration evidence.
        """
        from typing import cast, Literal

        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        tokens = tuple(
            GeneratedTokenProvenance(
                t.token.spelling.decode(),
                (t.token.start, t.token.end),
                t.physical_spelling_span,
                t.token.operation,
            )
            for t in projection.generated_tokens
            if node.start_byte <= t.projected_span[0] < end
        )
        related = [expansion]
        parent = node.parent
        while parent is not None:
            if parent.type == "namespace_definition":
                body_node = parent.child_by_field_name("body")
                if body_node is not None:
                    related.extend(
                        item
                        for item in expansions
                        if item.namespace
                        and parent.start_byte
                        <= item.projected_span[0]
                        < body_node.start_byte
                    )
            parent = parent.parent
        inputs = tuple(
            dict.fromkeys(
                [
                    origin
                    for item in related
                    for origin in _inputs(item.selection, item.used, captures)
                ]
                + type_inputs.get(expansion.span[0], [])
            )
        )
        return GeneratedCallableProvenance(
            cast('Literal["definition", "prototype", "alias"]', role),
            expansion.span,
            source_digest,
            input_identity,
            tokens,
            inputs,
            names,
            parameter_types,
        )

    def physical_line(line: int) -> int:
        """Map an artifact line to original bytes or its explicit invocation anchor.

        Parameters
        ----------
        line : int
            Projected one-based line.

        Returns
        -------
        int
            Original one-based line.
        """
        return _line(
            original, _physical_position(projection, _offset(source, line), expansions)
        )

    functions = []
    generated_nodes: dict[str, SyntaxNode] = {}
    generated_expansions: dict[str, _Expansion] = {}
    for function in result.functions:
        matches = [
            n
            for n in nodes
            if n.type == "function_definition"
            and signature_line(n) == function.lineno
            and (d := _find_function_declarator(n)) is not None
            and _unwrap_declarator_name(d, source) == function.name.rsplit("::", 1)[-1]
        ]
        definition_node = matches[0] if len(matches) == 1 else None
        if definition_node is None and any(
            function.lineno
            <= _line(source, e.projected_span[0])
            <= (function.end_lineno or function.lineno)
            for e in statements
        ):
            raise ValueError("statement macro callable ownership is not unique")
        owned_expansion = next(
            (
                e
                for e in expansions
                if not e.namespace
                and definition_node is not None
                and e.projected_span[0]
                <= definition_node.start_byte
                < e.projected_span[1]
            ),
            None,
        )
        calls = mapped_calls(function.calls, definition_node, function.parameters)
        mapped = replace(
            function,
            lineno=physical_line(function.lineno),
            end_lineno=None
            if function.end_lineno is None
            else physical_line(function.end_lineno)
            if definition_node is None
            else _line(
                original,
                _physical_position(
                    projection, definition_node.end_byte - 1, expansions
                ),
            ),
            calls=tuple(calls),
            overloads=tuple(
                replace(
                    o,
                    lineno=physical_line(o.lineno),
                    end_lineno=None
                    if o.end_lineno is None
                    else physical_line(o.end_lineno),
                )
                for o in function.overloads
            ),
        )
        if owned_expansion is not None and definition_node is not None:
            body = definition_node.child_by_field_name("body")
            assert body is not None
            ending = projection.physical_span(body.end_byte - 1, body.end_byte)
            if ending is None:
                raise ValueError("generated implementation body is not original source")
            declarator = _find_function_declarator(definition_node)
            parameters = (
                None
                if declarator is None
                else declarator.child_by_field_name("parameters")
            )
            names = []
            for parameter in () if parameters is None else parameters.named_children:
                if parameter.type != "parameter_declaration":
                    continue
                name = parameter.child_by_field_name("declarator")
                name = None if name is None else _parameter_name_node(name)
                if _normalize_signature(_node_text(parameter, source)) != "void":
                    names.append(None if name is None else _node_text(name, source))
            mapped = replace(
                mapped,
                lineno=_line(original, owned_expansion.span[0]),
                end_lineno=_line(original, ending[0]),
                generated=provenance(
                    owned_expansion,
                    definition_node,
                    "definition",
                    tuple(names),
                    _parameter_types(definition_node, source),
                ),
            )
            generated_nodes[mapped.name] = definition_node
            generated_expansions[mapped.name] = owned_expansion
        functions.append(mapped)
    labels: dict[str, str] = {}
    aliases = []
    for expansion, node, reference in declarations:
        declarator = node.child_by_field_name("declarator")
        if declarator is None or declarator.type not in {
            "identifier",
            "attributed_declarator",
        }:
            raise ValueError("unsupported generated decltype declarator")
        declared_name = _unwrap_declarator_name(declarator, source)
        if declared_name is None or _NAME.fullmatch(declared_name.encode()) is None:
            raise ValueError("unsupported generated declaration name")
        namespace = reference.rpartition("::")[0]
        qualified = (namespace + "::" if namespace else "") + declared_name
        raw = source[node.start_byte : node.end_byte]
        alias = re.search(rb'gnu\s*::\s*alias\s*\(\s*("(?:[^"\\]|\\.)*")\s*\)', raw)
        asm = re.search(rb'\basm\s*\(\s*("(?:[^"\\]|\\.)*")\s*\)', raw)
        proof = types[expansion.span[0], reference]
        return_type, parameter_types = proof.return_type, proof.parameter_types
        if alias is not None:
            aliases.append(
                (expansion, node, qualified, parameter_types, json.loads(alias[1]))
            )
            continue
        matching = [
            i
            for i, fn in enumerate(functions)
            if fn.name == qualified
            and fn.generated is not None
            and generated_expansions[fn.name].span == expansion.span
        ]
        if len(matching) != 1:
            raise ValueError("generated prototype has no unique implementation")
        index = matching[0]
        fn = functions[index]
        definition = generated_nodes[qualified]
        type_node = definition.child_by_field_name("type")
        if (
            type_node is None
            or _normalize_signature(_node_text(type_node, source)) != return_type
            or fn.generated is None
            or fn.generated.parameter_types != parameter_types
        ):
            raise ValueError("decltype and implementation type spellings disagree")
        generated = provenance(
            expansion,
            node,
            "prototype",
            (None,) * len(parameter_types),
            parameter_types,
        )
        label = None if asm is None else json.loads(asm[1])
        generated = replace(generated, linkage_name=label)
        overload = OverloadArtifact(
            fn.stable_id + ":generated-prototype:" + str(len(fn.overloads) + 1),
            fn.stable_id,
            len(fn.overloads) + 1,
            _normalize_signature(raw.decode()),
            _line(original, expansion.span[0]),
            None,
            None,
            generated,
        )
        functions[index] = replace(
            fn,
            overloads=(*fn.overloads, overload),
            generated=replace(fn.generated, linkage_name=label),
        )
        if label is not None:
            if label in labels and labels[label] != qualified:
                raise ValueError("ambiguous generated assembler label")
            labels[label] = qualified
    for expansion, node, qualified, parameter_types, label in aliases:
        target = labels.get(label)
        target_functions = [
            fn
            for fn in functions
            if fn.name == target
            and fn.generated is not None
            and fn.generated.invocation_span == expansion.span
        ]
        if len(target_functions) != 1:
            raise ValueError(
                "generated alias has no proven implementation linker target"
            )
        fn = target_functions[0]
        if fn.generated is None or fn.generated.parameter_types != parameter_types:
            raise ValueError("generated alias and implementation types disagree")
        generated = replace(
            provenance(
                expansion,
                node,
                "alias",
                (None,) * len(parameter_types),
                parameter_types,
            ),
            alias_target=target,
            linkage_name=label,
        )
        functions.append(
            replace(
                fn,
                name=qualified,
                stable_id=_function_stable_id(_symbol_owner_id(path, root), qualified),
                end_lineno=None,
                signature=_normalize_signature(
                    source[node.start_byte : node.end_byte].decode()
                ),
                parameters=(),
                returns_value=0,
                calls=(),
                callable_refs=(),
                overloads=(),
                generated=generated,
            )
        )
    consumed = {item.span for item in generated_expansions.values()}
    if any(
        not item.namespace
        and not item.statement
        and not item.declaration_statement
        and item.span not in consumed
        for item in expansions
    ):
        raise ValueError("declaration expansion has unsupported callable ownership")
    classes = []
    for cls in result.classes:
        methods = []
        for method in cls.methods:
            matches = [
                n
                for n in nodes
                if n.type == "function_definition"
                and signature_line(n) == method.lineno
                and (d := _find_function_declarator(n)) is not None
                and _unwrap_declarator_name(d, source)
                == method.name.rsplit("::", 1)[-1]
            ]
            method_definition = matches[0] if len(matches) == 1 else None
            if method_definition is None and any(
                method.lineno
                <= _line(source, e.projected_span[0])
                <= (method.end_lineno or method.lineno)
                for e in statements
            ):
                raise ValueError("statement macro method ownership is not unique")
            calls = mapped_calls(method.calls, method_definition, method.parameters)
            methods.append(
                replace(
                    method,
                    lineno=physical_line(method.lineno),
                    end_lineno=None
                    if method.end_lineno is None
                    else physical_line(method.end_lineno),
                    calls=tuple(calls),
                    overloads=tuple(
                        replace(
                            o,
                            lineno=physical_line(o.lineno),
                            end_lineno=None
                            if o.end_lineno is None
                            else physical_line(o.end_lineno),
                        )
                        for o in method.overloads
                    ),
                )
            )
        classes.append(
            replace(
                cls,
                lineno=physical_line(cls.lineno),
                end_lineno=None
                if cls.end_lineno is None
                else physical_line(cls.end_lineno),
                methods=tuple(methods),
            )
        )
    return replace(
        result,
        functions=tuple(functions),
        classes=tuple(classes),
        imports=tuple(
            replace(item, lineno=physical_line(item.lineno)) for item in result.imports
        ),
        declarations=tuple(
            replace(
                item,
                lineno=physical_line(item.lineno),
                enum_members=tuple(
                    replace(member, lineno=physical_line(member.lineno))
                    for member in item.enum_members
                ),
            )
            for item in result.declarations
        ),
        documentation=tuple(
            replace(
                item,
                lineno=physical_line(item.lineno),
                end_lineno=None
                if item.end_lineno is None
                else physical_line(item.end_lineno),
            )
            for item in result.documentation
        ),
    )
