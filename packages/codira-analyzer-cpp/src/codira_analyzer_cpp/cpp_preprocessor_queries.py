"""Validate explicit compiler query answers without invoking an external tool.

Parameters
----------
None

Returns
-------
None
    Bounded feature answers and source-bound header-search observations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from .cpp_macro_conditions import _integer_literal
from .cpp_macro_context import MacroBinding
from .cpp_macro_expansion import _MacroDefinition, _MacroToken, _macro_tokens

_FEATURES = frozenset(
    {
        b"__has_builtin",
        b"__has_feature",
        b"__has_extension",
        b"__has_attribute",
        b"__has_cpp_attribute",
        b"__is_identifier",
        b"__has_declspec_attribute",
        b"__has_keyword",
        b"__has_warning",
    }
)
_HEADERS = frozenset({b"__has_include", b"__has_include_next"})
_NAME = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE = re.compile(r"[0-9a-f]{16}\Z")
FeatureAnswers = dict[tuple[bytes, ...], bytes]
IncludeSites = tuple[tuple[str, int], ...]


def _relative_path(value: object) -> str:
    """Require a canonical contained profile path.

    Parameters
    ----------
    value : object
        Untrusted configuration value.

    Returns
    -------
    str
        Canonical relative POSIX spelling.

    Raises
    ------
    ValueError
        If the path is empty, absolute or traverses a parent directory.
    """
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or PurePosixPath(value).as_posix() != value
        or value == "."
    ):
        raise ValueError("preprocessor query paths must be contained relative paths")
    return value


def _expression(value: object) -> tuple[bytes, ...]:
    """Tokenize one bounded complete query invocation.

    Parameters
    ----------
    value : object
        Written query spelling from the profile.

    Returns
    -------
    tuple[bytes, ...]
        Canonical preprocessing tokens.

    Raises
    ------
    ValueError
        If the spelling is not one supported complete invocation.
    """
    if not isinstance(value, str) or not value.isascii() or len(value) > 4096:
        raise ValueError("preprocessor query expression must be bounded ASCII")
    tokens = tuple(t.spelling for t in _macro_tokens(value.encode()))
    if (
        len(tokens) < 4
        or tokens[0] not in _FEATURES | _HEADERS
        or tokens[1] != b"("
        or tokens[-1] != b")"
        or any(t in {b"(", b")"} for t in tokens[2:-1])
    ):
        raise ValueError("preprocessor query must be one supported invocation")
    return tokens


def feature_answers(
    value: object, initial: Mapping[bytes, _MacroDefinition | None] | None
) -> FeatureAnswers:
    """Validate literal answers for explicitly opaque compiler feature operators.

    Parameters
    ----------
    value : object
        Mapping from complete query spellings to exact native integer literals.
    initial : Mapping[bytes, _MacroDefinition or None] or None
        Explicit initial macro states; feature operators must be opaque-defined.

    Returns
    -------
    FeatureAnswers
        Immutable token keys with exact supported numeric spellings.

    Raises
    ------
    ValueError
        If operators, arguments, literals or duplicate answers are invalid.
    """
    if not isinstance(value, Mapping) or len(value) > 4096:
        raise ValueError("preprocessor_features must be a bounded mapping")
    result: FeatureAnswers = {}
    for expression, literal in value.items():
        tokens = _expression(expression)
        definition = None if initial is None else initial.get(tokens[0])
        warning = (
            tokens[0] == b"__has_warning"
            and len(tokens[2:-1]) == 1
            and re.fullmatch(rb'"(?:[^"\\\r\n]|\\.)*"', tokens[2]) is not None
        )
        if (
            tokens[0] not in _FEATURES
            or definition is None
            or not definition.opaque
            or not warning
            and (
                any(
                    _NAME.fullmatch(t) is None if i % 2 == 0 else t != b"::"
                    for i, t in enumerate(tokens[2:-1])
                )
                or len(tokens[2:-1]) % 2 != 1
            )
        ):
            raise ValueError(
                "feature query requires an opaque initial operator and identifier arguments"
            )
        if not isinstance(literal, str) or len(literal) > 32:
            raise ValueError(
                "feature answer must be an exact supported integer literal"
            )
        raw = literal.encode()
        number = _integer_literal(raw)
        if number is None or number < 0 or len(_macro_tokens(raw)) != 1:
            raise ValueError(
                "feature answer must be an exact supported integer literal"
            )
        if tokens in result and result[tokens] != raw:
            raise ValueError("conflicting feature query answers")
        result[tokens] = raw
    return result


@dataclass(frozen=True)
class HeaderQuery:
    """Bind one native header query to its physical include context.

    Parameters
    ----------
    path : str
        Captured owner path.
    span : tuple[int, int]
        Complete physical operator invocation.
    include_stack : IncludeSites
        Root-to-owner include directive sites.
    tokens : tuple[bytes, ...]
        Original query tokens, including its literal header spelling.
    value : bool
        Native existence result at this exact search position.

    Returns
    -------
    None
        Immutable profile observation; it reads no header itself.
    """

    path: str
    span: tuple[int, int]
    include_stack: IncludeSites
    tokens: tuple[bytes, ...]
    value: bool


@dataclass(frozen=True)
class HeaderQuerySet:
    """Bind search observations to a full contained input graph and configuration.

    Parameters
    ----------
    context_sha256 : str
        Exact SHA-256 of the full contained include-context identity.
    profile_fingerprint : str
        Core configuration fingerprint without header queries.
    queries : tuple[HeaderQuery, ...]
        Observed physical queries; absent sites remain unknown.

    Returns
    -------
    None
        Immutable, translation-unit-specific search evidence.
    """

    context_sha256: str
    profile_fingerprint: str
    queries: tuple[HeaderQuery, ...]


def _site(value: object) -> tuple[str, int]:
    """Validate one source-owned include directive site.

    Parameters
    ----------
    value : object
        Two-item path and physical offset array.

    Returns
    -------
    tuple[str, int]
        Contained parent path and nonnegative directive start.

    Raises
    ------
    ValueError
        If the pair or offset is invalid.
    """
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("header query include sites must be path/offset pairs")
    path, offset = value
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("header query include offsets must be nonnegative integers")
    return _relative_path(path), offset


def header_query_sets(value: object) -> dict[str, HeaderQuerySet]:
    """Validate source-specific native search facts without accepting branch results.

    Parameters
    ----------
    value : object
        Translation-unit mapping containing context/profile digests and queries.

    Returns
    -------
    dict[str, HeaderQuerySet]
        Bounded source-bound observations with conflicting duplicates rejected.

    Raises
    ------
    ValueError
        If a path, digest, range, expression, Boolean or work bound is invalid.
    """
    if not isinstance(value, Mapping) or len(value) > 1024:
        raise ValueError("preprocessor_header_queries must be a bounded mapping")
    result = {}
    total = 0
    for unit, data in value.items():
        key = _relative_path(unit)
        if not isinstance(data, Mapping) or set(data) != {
            "context_sha256",
            "profile_fingerprint",
            "queries",
        }:
            raise ValueError(
                "header query set requires context/profile digests and queries"
            )
        context_hash, profile_hash = data["context_sha256"], data["profile_fingerprint"]
        if (
            not isinstance(context_hash, str)
            or _DIGEST.fullmatch(context_hash) is None
            or not isinstance(profile_hash, str)
            or _PROFILE.fullmatch(profile_hash) is None
        ):
            raise ValueError(
                "header query requires an input SHA-256 and core profile fingerprint"
            )
        rows = data["queries"]
        if not isinstance(rows, list) or len(rows) > 8192:
            raise ValueError("header query set exceeds its query bound")
        queries: dict[
            tuple[str, tuple[int, int], IncludeSites, tuple[bytes, ...]], HeaderQuery
        ] = {}
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {
                "path",
                "span",
                "include_stack",
                "expression",
                "value",
            }:
                raise ValueError("invalid header query fields")
            span, stack, answer = row["span"], row["include_stack"], row["value"]
            if (
                not isinstance(span, list)
                or len(span) != 2
                or any(not isinstance(x, int) or isinstance(x, bool) for x in span)
                or not 0 <= span[0] < span[1]
            ):
                raise ValueError("header query span must be a nonempty physical range")
            if (
                not isinstance(stack, list)
                or len(stack) > 64
                or type(answer) is not bool
            ):
                raise ValueError(
                    "header query requires a bounded include stack and Boolean answer"
                )
            tokens = _expression(row["expression"])
            arguments = tokens[2:-1]
            literal = (
                len(arguments) == 1
                and re.fullmatch(rb'"[A-Za-z_0-9./+-]+"', arguments[0]) is not None
            )
            angled = (
                len(arguments) > 2
                and arguments[0] == b"<"
                and arguments[-1] == b">"
                and not any(t in {b"<", b">", b"#", b"##"} for t in arguments[1:-1])
            )
            angled = (
                angled
                and re.fullmatch(rb"[A-Za-z_0-9./+-]+", b"".join(arguments[1:-1]))
                is not None
            )
            if tokens[0] not in _HEADERS or not (literal or angled):
                raise ValueError("header query must contain one literal header name")
            query = HeaderQuery(
                _relative_path(row["path"]),
                (span[0], span[1]),
                tuple(_site(s) for s in stack),
                tokens,
                answer,
            )
            identity = query.path, query.span, query.include_stack, query.tokens
            if identity in queries and queries[identity].value != answer:
                raise ValueError("conflicting native header query observations")
            queries[identity] = query
            total += 1
            if total > 65536:
                raise ValueError("header observations exceed the total query bound")
        result[key] = HeaderQuerySet(
            context_hash, profile_hash, tuple(queries.values())
        )
    return result


class QueryResolver:
    """Apply known operator answers while leaving condition syntax to its parser.

    Parameters
    ----------
    captures : Mapping[str, bytes]
        Immutable contained source snapshots.
    initial : Mapping[bytes, _MacroDefinition or None]
        Explicit prefix states used to reject source overrides.
    features : FeatureAnswers
        Exact native literals for pure compiler feature queries.
    headers : tuple[HeaderQuery, ...]
        Search observations already matched to the full input/profile identity.

    Returns
    -------
    None
        One bounded lookup scoped to an analysis input snapshot.
    """

    def __init__(
        self,
        captures: Mapping[str, bytes],
        initial: Mapping[bytes, _MacroDefinition | None],
        features: FeatureAnswers,
        headers: tuple[HeaderQuery, ...],
    ) -> None:
        """Store validated answers and source inputs.

        Parameters
        ----------
        captures : Mapping[str, bytes]
            Frozen physical input buffers.
        initial : Mapping[bytes, _MacroDefinition or None]
            Original explicit prefix definitions.
        features : FeatureAnswers
            Validated exact compiler literals.
        headers : tuple[HeaderQuery, ...]
            Context-matched search observations.

        Returns
        -------
        None
        """
        self.captures = captures
        self.initial = initial
        self.features = features
        self.headers = {
            (q.path, q.span, q.include_stack, q.tokens): q.value for q in headers
        }

    def expand_feature(
        self,
        tokens: tuple[_MacroToken, ...],
        bindings: Mapping[bytes, MacroBinding],
    ) -> tuple[_MacroToken, ...] | None:
        """Resolve a pure feature call reached after captured argument prescan.

        Parameters
        ----------
        tokens : tuple[_MacroToken, ...]
            Complete intrinsic invocation after ordinary macro substitution.
        bindings : Mapping[bytes, MacroBinding]
            Actual reaching states, including source overrides.

        Returns
        -------
        tuple[_MacroToken, ...] or None
            One licensed scalar, or no answer for changed or unobserved inputs.
            Header-search answers are never treated as global feature values.
        """
        spellings = tuple(t.spelling for t in tokens)
        answer = self.features.get(spellings)
        if answer is None:
            return None
        name = tokens[0].spelling
        binding = bindings.get(name)
        definition = self.initial.get(name)
        if (
            definition is None
            or not definition.opaque
            or binding is None
            or binding.definition != definition
            or any(o.source_path is not None for o in binding.origins)
        ):
            return None
        for argument in tokens[2:-1]:
            if argument.spelling == b"::" or (
                name == b"__has_warning" and argument.spelling.startswith(b'"')
            ):
                continue
            state = bindings.get(argument.spelling)
            if (
                argument.spelling not in self.initial
                or self.initial[argument.spelling] is not None
                or state is None
                or state.definition is not None
                or any(o.source_path is not None for o in state.origins)
            ):
                return None
        return (
            _MacroToken(
                answer,
                tokens[0].start,
                tokens[-1].end,
                synthetic=True,
                operation="replacement",
                unavailable=tokens[0].unavailable | {name},
            ),
        )

    def resolve(
        self,
        path: str,
        span: tuple[int, int],
        include_stack: IncludeSites,
        payload: bytes,
        bindings: Mapping[bytes, MacroBinding],
    ) -> bytes:
        """Replace only witnessed intrinsic calls, preserving unsupported syntax.

        Parameters
        ----------
        path : str
            Current contained owner.
        span : tuple[int, int]
            Physical conditional directive range.
        include_stack : IncludeSites
            Actual traversal's source include directive sites.
        payload : bytes
            Original condition suffix, retained when no answer applies.
        bindings : Mapping[bytes, MacroBinding]
            Current reaching definitions and their physical/profile origins.

        Returns
        -------
        bytes
            Condition tokens with licensed numeric answers; no whole branch
            outcome or unresolved source macro is substituted.
        """
        if len(payload) > 8192:
            return payload
        source = self.captures[path]
        tokens = _macro_tokens(source[span[0] : span[1]], offset=span[0])[2:]
        output: list[bytes] = []
        changed = False
        index = 0
        while index < len(tokens):
            token = tokens[index]
            binding = bindings.get(token.spelling)
            definition = self.initial.get(token.spelling)
            if (
                token.spelling not in _FEATURES | _HEADERS
                or binding is None
                or definition is None
                or not definition.opaque
                or binding.definition != definition
                or any(o.source_path is not None for o in binding.origins)
                or index + 1 >= len(tokens)
                or tokens[index + 1].spelling != b"("
            ):
                output.append(token.spelling)
                index += 1
                continue
            closing = index + 2
            while closing < len(tokens) and tokens[closing].spelling not in {
                b"(",
                b")",
            }:
                closing += 1
            if closing == len(tokens) or tokens[closing].spelling != b")":
                output.append(token.spelling)
                index += 1
                continue
            spellings = tuple(t.spelling for t in tokens[index : closing + 1])
            feature = self.expand_feature(tokens[index : closing + 1], bindings)
            answer = None if feature is None else feature[0].spelling
            if answer is None:
                header_value = self.headers.get(
                    (path, (token.start, tokens[closing].end), include_stack, spellings)
                )
                if header_value is not None:
                    answer = b"1" if header_value else b"0"
            if answer is None:
                output.append(token.spelling)
                index += 1
                continue
            output.append(answer)
            changed = True
            index = closing + 1
        return b" ".join(output) if changed else payload


def header_queries_schema() -> dict[str, object]:
    """Describe strict source-bound header observations in the public schema.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        JSON Schema for bounded translation-unit observation sets.
    """
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    offset = {"type": "integer", "minimum": 0}
    row = {
        "type": "object",
        "properties": {
            "path": path,
            "span": {"type": "array", "minItems": 2, "maxItems": 2, "items": offset},
            "include_stack": {
                "type": "array",
                "maxItems": 64,
                "items": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"anyOf": [path, offset]},
                },
            },
            "expression": {"type": "string", "minLength": 1, "maxLength": 4096},
            "value": {"type": "boolean"},
        },
        "required": ["path", "span", "include_stack", "expression", "value"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "maxProperties": 1024,
        "additionalProperties": {
            "type": "object",
            "properties": {
                "context_sha256": digest,
                "profile_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
                "queries": {"type": "array", "maxItems": 8192, "items": row},
            },
            "required": ["context_sha256", "profile_fingerprint", "queries"],
            "additionalProperties": False,
        },
        "description": "Offline native header-search answers bound to the complete contained input graph, exact prefix configuration, physical invocation and include directive chain. Missing or stale observations remain unknown.",
    }
