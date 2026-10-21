"""Select reaching C++ macros from an ordered, already captured include graph.

Parameters
----------
None

Returns
-------
None
    Source-only conditional selection; this module performs no filesystem reads.

Notes
-----
At most 2,048 snapshots and 32,768 directive events are admitted. Active include
traversal retains separate limits of 1,024 visits, 8 MiB and 64 nested includes.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import re

from .cpp_macro_conditions import condition_value
from .cpp_macro_expansion import _LEXEME, _MacroDefinition, _MacroToken, _macro_tokens

_DIRECTIVE = re.compile(rb"(?m)^[ \t]*#[ \t]*([A-Za-z_][A-Za-z_0-9]*)([^\n]*)")
_NAME = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*")
_RAW = re.compile(rb'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(')
_SPLICE = re.compile(rb"\\\r?\n")

_MAX_CAPTURE_FILES = 2048
_MAX_DIRECTIVE_EVENTS = 32768


@dataclass(frozen=True)
class MacroOrigin:
    """Describe a real directive span or an explicit profile input.

    Parameters
    ----------
    source_path : str | None
        Captured repository-relative path; None marks a profile binding.
    span : tuple[int, int] | None
        Physical directive byte range, or None for a profile input.

    Returns
    -------
    None
        Provenance without invented physical locations for profile values.
    """

    source_path: str | None
    span: tuple[int, int] | None


@dataclass(frozen=True)
class MacroBinding:
    """Retain a known definition or undefined state and all possible origins.

    Parameters
    ----------
    definition : _MacroDefinition | None
        Captured replacement, or an explicitly proven undefined state.
    origins : tuple[MacroOrigin, ...]
        Directive/profile inputs supporting the same semantic state.

    Returns
    -------
    None
        Immutable binding; absence from the environment means unknown.
    """

    definition: _MacroDefinition | None
    origins: tuple[MacroOrigin, ...]


@dataclass(frozen=True)
class MacroObservation:
    """Preserve an encountered include or unsupported directive observation.

    Parameters
    ----------
    source_path : str
        Captured owner of the directive.
    span : tuple[int, int]
        Original physical byte range.
    kind : str
        Directive keyword.
    payload : bytes
        Logical directive suffix before expansion.
    status : str
        Selection outcome, including unavailable include context.
    active : bool | None
        Certain or possible activity, preserving mutually exclusive observations.

    Returns
    -------
    None
        Ordered context evidence distinct from parser/native qualification.
    """

    source_path: str
    span: tuple[int, int]
    kind: str
    payload: bytes
    status: str
    active: bool | None


@dataclass(frozen=True)
class MacroSelection:
    """Snapshot the possible preprocessing state at an original source offset.

    Parameters
    ----------
    bindings : tuple[tuple[bytes, MacroBinding], ...]
        Known states, sorted by name.
    uncertain : frozenset[bytes]
        Captured names with unavailable or branch-dependent replacements.
    active : bool | None
        Whether the original position is active, inactive or condition-dependent.
    observations : tuple[MacroObservation, ...]
        Ordered context observations reached before this position.

    Returns
    -------
    None
        Immutable input for a separate bounded expansion/provenance stage.
    """

    bindings: tuple[tuple[bytes, MacroBinding], ...]
    uncertain: frozenset[bytes]
    active: bool | None
    observations: tuple[MacroObservation, ...]


ConditionQueryResolver = Callable[
    [
        str,
        tuple[int, int],
        tuple[tuple[str, int], ...],
        bytes,
        Mapping[bytes, MacroBinding],
    ],
    bytes,
]
FeatureQueryResolver = Callable[
    [tuple[_MacroToken, ...], Mapping[bytes, MacroBinding]],
    tuple[_MacroToken, ...] | None,
]


@dataclass
class _Environment:
    """Maintain local branch bindings and definitely visited pragma-once files.

    Parameters
    ----------
    bindings : dict[bytes, MacroBinding]
        Known states in the current possible branch.
    uncertain : set[bytes], optional
        Ambiguous captured names.
    once : set[str], optional
        Pragma-once files visited on every represented path.
    maybe_once : set[str], optional
        Files visited under pragma once on only some represented paths.

    Returns
    -------
    None
        Mutable state owned by one selection walk.
    """

    bindings: dict[bytes, MacroBinding]
    uncertain: set[bytes] = field(default_factory=set)
    once: set[str] = field(default_factory=set)
    maybe_once: set[str] = field(default_factory=set)

    def clone(self) -> _Environment:
        """Copy branch state before exploring another written alternative.

        Parameters
        ----------
        None

        Returns
        -------
        _Environment
            Independent containers sharing only immutable binding values.
        """
        return _Environment(
            dict(self.bindings),
            set(self.uncertain),
            set(self.once),
            set(self.maybe_once),
        )

    def states(self) -> dict[bytes, _MacroDefinition | None]:
        """Expose only proven states to the three-valued condition evaluator.

        Parameters
        ----------
        None

        Returns
        -------
        dict[bytes, _MacroDefinition | None]
            Known definitions and explicit undefined states.
        """
        return {name: binding.definition for name, binding in self.bindings.items()}


@dataclass
class _Conditional:
    """Collect possible branch outcomes without choosing unknown conditions.

    Parameters
    ----------
    initial : _Environment
        State before this conditional.
    parent : bool | None
        Activity of its enclosing source region.
    remaining : bool | None
        Whether no preceding branch has been taken.
    outcomes : list[_Environment], optional
        Completed possible branch states.
    has_else : bool, optional
        Whether a final else directive has occurred.

    Returns
    -------
    None
        Stack frame scoped to one captured source file.
    """

    initial: _Environment
    parent: bool | None
    remaining: bool | None
    outcomes: list[_Environment] = field(default_factory=list)
    has_else: bool = False


def _both(left: bool | None, right: bool | None) -> bool | None:
    """Conjoin known or unknown Boolean conditions.

    Parameters
    ----------
    left, right : bool | None
        Known truth values or unknowns.

    Returns
    -------
    bool | None
        False if either operand is false, otherwise the proven conjunction.
    """
    if left is False or right is False:
        return False
    return True if left is True and right is True else None


def _merge(outcomes: list[_Environment]) -> _Environment:
    """Retain identical states across every possible branch with their origins.

    Parameters
    ----------
    outcomes : list[_Environment]
        Nonempty possible branch states, including an implicit untaken branch.

    Returns
    -------
    _Environment
        Agreed definitions; conflicting or possibly absent names stay uncertain.
    """
    if len(outcomes) == 1:
        return outcomes[0].clone()
    common = set(outcomes[0].bindings)
    all_names: set[bytes] = set()
    uncertain: set[bytes] = set()
    once = set(outcomes[0].once)
    possible_once: set[str] = set()
    for outcome in outcomes:
        common.intersection_update(outcome.bindings)
        all_names.update(outcome.bindings)
        uncertain.update(outcome.uncertain)
        once.intersection_update(outcome.once)
        possible_once.update(outcome.once | outcome.maybe_once)
    bindings: dict[bytes, MacroBinding] = {}
    for name in common:
        definition = outcomes[0].bindings[name].definition
        if not all(
            outcome.bindings[name].definition == definition for outcome in outcomes
        ):
            continue
        origins = {
            origin for outcome in outcomes for origin in outcome.bindings[name].origins
        }
        bindings[name] = MacroBinding(
            definition,
            tuple(
                sorted(
                    origins,
                    key=lambda item: (item.source_path or "", item.span or (0, 0)),
                )
            ),
        )
    opaque = {
        name
        for name, binding in bindings.items()
        if binding.definition is not None and binding.definition.opaque
    }
    return _Environment(
        bindings,
        ((uncertain | all_names) - set(bindings)) | opaque,
        once,
        possible_once - once,
    )


def _directives(source: bytes) -> tuple[tuple[int, int, bytes, bytes], ...]:
    """Scan logical directives while excluding comments and all source literals.

    Parameters
    ----------
    source : bytes
        Exact physical captured bytes.

    Returns
    -------
    tuple[tuple[int, int, bytes, bytes], ...]
        Original start/end, keyword and logical suffix in physical source order.

    Raises
    ------
    ValueError
        If a comment or literal is unterminated or input exceeds the byte bound.
    """
    if len(source) > 8 * 1024 * 1024:
        raise ValueError("macro context source byte limit exceeded")
    parts: list[bytes] = []
    positions: list[int] = []
    shifts: list[int] = []
    physical_ends: list[int] = []
    cursor = size = removed = 0
    for splice in _SPLICE.finditer(source):
        parts.append(source[cursor : splice.start()])
        size += splice.start() - cursor
        removed += splice.end() - splice.start()
        positions.append(size)
        shifts.append(removed)
        physical_ends.append(splice.end())
        cursor = splice.end()
    parts.append(source[cursor:])
    logical = b"".join(parts)
    opaque: list[tuple[int, int]] = []
    comment_spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(logical):
        raw = _RAW.match(logical, cursor)
        if raw:
            shift_index = bisect_right(positions, raw.end()) - 1
            opening = raw.end() + (shifts[shift_index] if shift_index >= 0 else 0)
            closing = source.find(b")" + raw[1] + b'"', opening)
            if closing < 0:
                raise ValueError("unterminated raw string in macro context")
            physical_end = closing + len(raw[1]) + 2
            splice_index = bisect_right(physical_ends, physical_end) - 1
            end = physical_end - (shifts[splice_index] if splice_index >= 0 else 0)
            opaque.append((cursor, end))
            cursor = end
            continue
        match = _LEXEME.match(logical, cursor)
        if logical[cursor : cursor + 2] == b"/*" and (
            match is None or match.lastgroup != "space"
        ):
            raise ValueError("unterminated source comment")
        if match is None:
            if logical[cursor : cursor + 2] in (b"/*", b"//") or logical[cursor] in (
                34,
                39,
            ):
                raise ValueError("unterminated source literal or comment")
            cursor += 1
            continue
        if match.lastgroup == "literal" or logical[cursor : cursor + 2] in (
            b"/*",
            b"//",
        ):
            opaque.append((cursor, match.end()))
        if logical[cursor : cursor + 2] in (b"/*", b"//"):
            comment_spans.append((cursor, match.end()))
        cursor = match.end()
    starts = [start for start, _ in opaque]
    directive_view = bytearray(logical)
    for start, end in comment_spans:
        directive_view[start:end] = b" " * (end - start)
    result = []
    for match in _DIRECTIVE.finditer(directive_view):
        hash_offset = directive_view.index(b"#", match.start(), match.end())
        protected = bisect_right(starts, hash_offset) - 1
        if protected >= 0 and hash_offset < opaque[protected][1]:
            continue
        first = bisect_right(positions, hash_offset) - 1
        last = bisect_right(positions, match.end()) - 1
        start = hash_offset + (shifts[first] if first >= 0 else 0)
        end = match.end() + (shifts[last] if last >= 0 else 0)
        result.append(
            (start, end, bytes(match[1]), logical[match.start(2) : match.end(2)])
        )
    return tuple(result)


def _skip_space(source: bytes) -> int:
    """Skip preprocessing whitespace and complete comments in a suffix.

    Parameters
    ----------
    source : bytes
        Logical directive suffix.

    Returns
    -------
    int
        Offset of its first non-whitespace preprocessing token.
    """
    cursor = 0
    while cursor < len(source):
        match = _LEXEME.match(source, cursor)
        if match is None or match.lastgroup != "space":
            break
        cursor = match.end()
    return cursor


def _controlling_guard(
    source: bytes, directives: tuple[tuple[int, int, bytes, bytes], ...]
) -> bytes | None:
    """Prove that one balanced ifndef encloses every non-comment source token.

    Parameters
    ----------
    source : bytes
        Frozen physical source bytes already checked by the directive scanner.
    directives : tuple[tuple[int, int, bytes, bytes], ...]
        Scanned physical spans, directive keywords and logical suffixes.

    Returns
    -------
    bytes | None
        Controlling macro name, or None when structural proof is unavailable.
        Malformed alternatives and closing directives cannot qualify for skipping.
    """
    if not directives or directives[0][2] != b"ifndef":
        return None
    prefix = _SPLICE.sub(b"", source[: directives[0][0]])
    suffix = _SPLICE.sub(b"", source[directives[-1][1] :])
    if _skip_space(prefix) != len(prefix) or _skip_space(suffix) != len(suffix):
        return None
    alternatives: list[bool] = []
    guard = None
    try:
        for index, (_, _, kind, payload) in enumerate(directives):
            if kind in {b"if", b"ifdef", b"ifndef"}:
                if len(alternatives) >= 64:
                    return None
                if kind != b"if":
                    tokens = _macro_tokens(payload)
                    if len(tokens) != 1 or _NAME.fullmatch(tokens[0].spelling) is None:
                        return None
                    if index == 0:
                        guard = tokens[0].spelling
                alternatives.append(False)
            elif kind in {b"elif", b"elifdef", b"elifndef", b"else"}:
                if len(alternatives) <= 1 or alternatives[-1]:
                    return None
                if kind == b"else":
                    if _macro_tokens(payload):
                        return None
                    alternatives[-1] = True
            elif kind == b"endif":
                if not alternatives or _macro_tokens(payload):
                    return None
                alternatives.pop()
                if not alternatives and index != len(directives) - 1:
                    return None
        return guard if not alternatives and directives[-1][2] == b"endif" else None
    except ValueError:
        return None


def _definition(payload: bytes) -> tuple[bytes, _MacroDefinition | None]:
    """Parse a definition's name and supported object/function parameter shape.

    Parameters
    ----------
    payload : bytes
        Logical suffix of a define directive.

    Returns
    -------
    tuple[bytes, _MacroDefinition | None]
        Macro name and definition; None marks an unsupported replacement shape.

    Raises
    ------
    ValueError
        If no macro name is present or it uses the defined operator's spelling.
    """
    name = _NAME.match(payload, _skip_space(payload))
    if name is None or name[0] == b"defined":
        raise ValueError("invalid macro definition name")
    tail = payload[name.end() :]
    parameters = None
    variadic = False
    try:
        if tail.startswith(b"("):
            formal_tokens = _macro_tokens(tail)
            closing = next(
                (
                    index
                    for index, token in enumerate(formal_tokens)
                    if token.spelling == b")"
                ),
                None,
            )
            if closing is None:
                return name[0], None
            values: list[tuple[bytes, ...]] = []
            group: list[bytes] = []
            for token in formal_tokens[1:closing]:
                if token.spelling == b",":
                    values.append(tuple(group))
                    group = []
                else:
                    group.append(token.spelling)
            if group or values:
                values.append(tuple(group))
            if values and values[-1] == (b"...",):
                variadic = True
                values.pop()
            if any(
                len(value) != 1 or _NAME.fullmatch(value[0]) is None for value in values
            ):
                return name[0], None
            parameters = tuple(value[0] for value in values)
            if len(set(parameters)) != len(parameters) or b"__VA_ARGS__" in parameters:
                return name[0], None
            tail = tail[formal_tokens[closing].end :]
        _macro_tokens(tail)
        return name[0], _MacroDefinition(parameters, tail.strip(), variadic)
    except ValueError:
        return name[0], None


class _ContextWalk:
    """Walk captured include events with independent possible-branch states.

    Parameters
    ----------
    captures : Mapping[str, bytes]
        Frozen repository-relative source snapshots.
    resolutions : Mapping[tuple[str, str, bool], str | None]
        Captured owner/spelling/quoted lookups; None records unavailable context.
    initial : Mapping[bytes, _MacroDefinition | None]
        Explicit initial definitions and undefined states.
    query_offsets : Mapping[str, tuple[int, ...]] or None, optional
        Additional physical declaration queries in captured headers.
    query_resolver : ConditionQueryResolver or None, optional
        Explicit intrinsic answers bound to source and profile context.
    feature_resolver : FeatureQueryResolver or None, optional
        The same licensed pure intrinsic answers after ordinary macro rescan.

    Returns
    -------
    None
        One bounded traversal with no filesystem or compiler access.
    """

    def __init__(
        self,
        captures: Mapping[str, bytes],
        resolutions: Mapping[tuple[str, str, bool], str | None],
        initial: Mapping[bytes, _MacroDefinition | None],
        *,
        query_offsets: Mapping[str, tuple[int, ...]] | None = None,
        query_resolver: ConditionQueryResolver | None = None,
        feature_resolver: FeatureQueryResolver | None = None,
    ) -> None:
        """Snapshot explicit macro state and initialize traversal bounds.

        Parameters
        ----------
        captures : Mapping[str, bytes]
            Already captured relative sources.
        resolutions : Mapping[tuple[str, str, bool], str | None]
            Already observed include resolutions.
        initial : Mapping[bytes, _MacroDefinition | None]
            Explicit initial macro states.
        query_offsets : Mapping[str, tuple[int, ...]] | None, optional
            Additional physical declaration queries in captured headers.
        query_resolver : ConditionQueryResolver or None, optional
            Explicit source/profile-bound intrinsic answers; never branch values.
        feature_resolver : FeatureQueryResolver or None, optional
            Licensed pure intrinsic answers reached through captured aliases.

        Returns
        -------
        None
            Initializes a traversal-local environment and event cache.
        """
        self.captures = captures
        self.resolutions = resolutions
        self.environment = _Environment(
            {
                name: MacroBinding(definition, (MacroOrigin(None, None),))
                for name, definition in initial.items()
            },
            {
                name
                for name, definition in initial.items()
                if definition is not None and definition.opaque
            },
        )
        self.observations: list[MacroObservation] = []
        self.cache: dict[str, tuple[tuple[int, int, bytes, bytes], ...]] = {}
        self.guards: dict[str, bytes | None] = {}
        self.stack: list[str] = []
        self.include_sites: list[tuple[str, int]] = []
        self.query_resolver = query_resolver
        self.feature_resolver = feature_resolver
        self.visits = self.bytes = self.events = 0
        self.results: dict[int, MacroSelection] = {}
        self.query_offsets = query_offsets or {}
        self.file_results: dict[tuple[str, int], list[MacroSelection]] = {}
        self.query_events: dict[tuple[str, int], list[int]] = {}
        self.query_sequence = 0

    def save_query(self, path: str, offset: int, active: bool | None) -> None:
        """Retain per-visit declaration activity without conflating file offsets.

        Parameters
        ----------
        path : str
            Captured file owning the physical query.
        offset : int
            Original byte offset in that file.
        active : bool | None
            Activity under the current ordered include visit.

        Returns
        -------
        None
            Root queries retain their existing API; headers retain every visit.
        """
        selection = self.snapshot(active)
        self.file_results.setdefault((path, offset), []).append(selection)
        self.query_sequence += 1
        self.query_events.setdefault((path, offset), []).append(self.query_sequence)
        if len(self.stack) == 1:
            self.results[offset] = selection

    def snapshot(self, active: bool | None) -> MacroSelection:
        """Freeze the current environment and ordered observations.

        Parameters
        ----------
        active : bool | None
            Activity of the queried original source interval.

        Returns
        -------
        MacroSelection
            Independent immutable state at this position.
        """
        return MacroSelection(
            tuple(sorted(self.environment.bindings.items())),
            frozenset(self.environment.uncertain),
            active,
            tuple(self.observations),
        )

    def walk(
        self, path: str, parent: bool | None = True, offsets: tuple[int, ...] = ()
    ) -> None:
        """Apply one captured file in source order and snapshot requested offsets.

        Parameters
        ----------
        path : str
            Captured relative path.
        parent : bool | None, optional
            Activity of the including source region.
        offsets : tuple[int, ...], optional
            Sorted query offsets in this file; headers supply no queries.

        Returns
        -------
        None
            Updates only this walk's environment and requested snapshots.

        Raises
        ------
        ValueError
            If bounds, source directives, queries or unguarded cycles are invalid.
        """
        if path in self.environment.once:
            return
        offsets = offsets or self.query_offsets.get(path, ())
        skipped = None
        if path in self.environment.maybe_once:
            skipped = self.environment.clone()
            skipped.maybe_once.discard(path)
            skipped.once.add(path)
            self.environment = self.environment.clone()
            self.environment.maybe_once.discard(path)
        cached_guard = self.guards.get(path)
        cached_binding = (
            self.environment.bindings.get(cached_guard)
            if cached_guard is not None
            else None
        )
        if (
            not offsets
            and cached_binding is not None
            and cached_binding.definition is not None
        ):
            if skipped is not None:
                self.environment = _merge([skipped, self.environment])
            return
        if len(self.stack) >= 64:
            raise ValueError("unguarded include cycle or include depth limit")
        self.visits += 1
        self.bytes += len(self.captures[path])
        if self.visits > 1024 or self.bytes > 8 * 1024 * 1024:
            raise ValueError("macro include traversal limit exceeded")
        self.stack.append(path)
        if path not in self.cache:
            self.cache[path] = _directives(self.captures[path])
            self.guards[path] = _controlling_guard(
                self.captures[path], self.cache[path]
            )
        guard = self.guards[path]
        binding = self.environment.bindings.get(guard) if guard is not None else None
        if not offsets and binding is not None and binding.definition is not None:
            self.stack.pop()
            if skipped is not None:
                self.environment = _merge([skipped, self.environment])
            return
        frames: list[_Conditional] = []
        active = parent
        query = 0
        for start, end, kind, payload in self.cache[path]:
            while query < len(offsets) and offsets[query] < start:
                self.save_query(path, offsets[query], active)
                query += 1
            if query < len(offsets) and start <= offsets[query] < end:
                raise ValueError("macro query lies inside a preprocessing directive")
            self.events += 1
            if (
                self.events > _MAX_DIRECTIVE_EVENTS
                or len(self.environment.bindings) + len(self.environment.uncertain)
                > 4096
            ):
                raise ValueError("macro directive or binding limit exceeded")
            if kind in {b"if", b"ifdef", b"ifndef"}:
                if len(frames) >= 64:
                    raise ValueError("macro conditional depth limit exceeded")
                value = (
                    self.condition(kind, payload, span=(start, end))
                    if active is not False
                    else False
                )
                remaining = None if value is None else not value
                frames.append(_Conditional(self.environment.clone(), active, remaining))
                active = _both(active, value)
            elif kind in {b"elif", b"elifdef", b"elifndef", b"else"}:
                if not frames or frames[-1].has_else:
                    raise ValueError("unmatched or duplicate conditional alternative")
                frame = frames[-1]
                if active is not False:
                    frame.outcomes.append(self.environment)
                self.environment = frame.initial.clone()
                if kind == b"else":
                    if _macro_tokens(payload):
                        raise ValueError("unexpected tokens after else")
                    frame.has_else = True
                    value = True
                else:
                    value = (
                        self.condition(
                            {
                                b"elif": b"if",
                                b"elifdef": b"ifdef",
                                b"elifndef": b"ifndef",
                            }[kind],
                            payload,
                            span=(start, end),
                        )
                        if _both(frame.parent, frame.remaining) is not False
                        else False
                    )
                active = _both(frame.parent, _both(frame.remaining, value))
                frame.remaining = _both(
                    frame.remaining, None if value is None else not value
                )
            elif kind == b"endif":
                if not frames or _macro_tokens(payload):
                    raise ValueError("unmatched or invalid endif")
                frame = frames.pop()
                if active is not False:
                    frame.outcomes.append(self.environment)
                if frame.remaining is not False:
                    frame.outcomes.append(frame.initial)
                self.environment = (
                    _merge(frame.outcomes) if frame.outcomes else frame.initial
                )
                active = frame.parent
            elif active is not False:
                self.directive(path, start, end, kind, payload, active)
        if frames:
            raise ValueError("unterminated preprocessing conditional")
        if len(self.environment.bindings) + len(self.environment.uncertain) > 4096:
            raise ValueError("macro binding limit exceeded")
        while query < len(offsets):
            self.save_query(path, offsets[query], active)
            query += 1
        self.stack.pop()
        if skipped is not None:
            self.environment = _merge([skipped, self.environment])

    def condition(
        self, kind: bytes, payload: bytes, *, span: tuple[int, int] | None = None
    ) -> bool | None:
        """Evaluate a condition using only currently proven reaching states.

        Parameters
        ----------
        kind : bytes
            If, ifdef or ifndef keyword.
        payload : bytes
            Original logical condition suffix.
        span : tuple[int, int] or None, optional
            Physical directive interval licensing source-bound intrinsic queries.

        Returns
        -------
        bool | None
            Known truth value, or unknown for missing/unsupported evidence.

        Raises
        ------
        ValueError
            If an ifdef/ifndef directive does not contain exactly one name.
        """
        if kind == b"if":
            if self.query_resolver is not None and span is not None:
                payload = self.query_resolver(
                    self.stack[-1],
                    span,
                    tuple(self.include_sites),
                    payload,
                    self.environment.bindings,
                )
            feature = self.feature_resolver
            return condition_value(
                payload,
                self.environment.states(),
                opaque_resolver=(
                    None
                    if feature is None
                    else lambda tokens: feature(tokens, self.environment.bindings)
                ),
            )
        tokens = _macro_tokens(payload)
        if len(tokens) != 1 or _NAME.fullmatch(tokens[0].spelling) is None:
            raise ValueError("ifdef/ifndef requires exactly one macro name")
        binding = self.environment.bindings.get(tokens[0].spelling)
        if binding is None:
            return None
        defined = binding.definition is not None
        return defined if kind == b"ifdef" else not defined

    def directive(
        self,
        path: str,
        start: int,
        end: int,
        kind: bytes,
        payload: bytes,
        active: bool | None,
    ) -> None:
        """Apply an active or possible non-conditional directive.

        Parameters
        ----------
        path : str
            Captured owner path.
        start, end : int
            Physical directive span.
        kind : bytes
            Directive keyword.
        payload : bytes
            Logical suffix.
        active : bool | None
            True or possible activity of this branch.

        Returns
        -------
        None
            Records source mutations or explicit unavailable context.

        Raises
        ------
        ValueError
            If a directive is invalid or a possible active error is encountered.
        """
        if kind == b"define":
            name, definition = _definition(payload)
            if definition is None:
                self.environment.bindings[name] = MacroBinding(
                    _MacroDefinition(None, b"", opaque=True),
                    (MacroOrigin(path, (start, end)),),
                )
                self.environment.uncertain.add(name)
            else:
                self.environment.bindings[name] = MacroBinding(
                    definition, (MacroOrigin(path, (start, end)),)
                )
                self.environment.uncertain.discard(name)
            return
        if kind == b"undef":
            tokens = _macro_tokens(payload)
            if (
                len(tokens) != 1
                or _NAME.fullmatch(tokens[0].spelling) is None
                or tokens[0].spelling == b"defined"
            ):
                raise ValueError("invalid undef directive")
            name = tokens[0].spelling
            self.environment.bindings[name] = MacroBinding(
                None, (MacroOrigin(path, (start, end)),)
            )
            self.environment.uncertain.discard(name)
            return
        status = "not-interpreted"
        if kind == b"include":
            match = re.fullmatch(
                rb'\s*(?:"([^"\r\n]*)"|<([^>\r\n]*)>)(.*)',
                payload[_skip_space(payload) :],
                re.DOTALL,
            )
            if match is None or _macro_tokens(match[3]):
                status = "unsupported-include"
            else:
                quoted = match[1] is not None
                spelling = (match[1] if quoted else match[2]).decode(
                    "utf-8", "surrogateescape"
                )
                target = self.resolutions.get((path, spelling, quoted))
                status = "captured" if target in self.captures else "unavailable"
                self.observations.append(
                    MacroObservation(
                        path, (start, end), "include", payload, status, active
                    )
                )
                if target is not None and target in self.captures:
                    self.include_sites.append((path, start))
                    try:
                        self.walk(target, active)
                    finally:
                        self.include_sites.pop()
                return
        elif kind == b"pragma" and tuple(
            token.spelling for token in _macro_tokens(payload)
        ) == (b"once",):
            self.environment.once.add(path)
            self.environment.maybe_once.discard(path)
            status = "once"
        elif kind == b"error":
            raise ValueError("possible active error directive in captured context")
        self.observations.append(
            MacroObservation(path, (start, end), kind.decode(), payload, status, active)
        )


def select_macro_environments(
    path: str,
    offsets: tuple[int, ...],
    captures: Mapping[str, bytes],
    resolutions: Mapping[tuple[str, str, bool], str | None],
    initial: Mapping[bytes, _MacroDefinition | None],
) -> dict[int, MacroSelection]:
    """Select reaching macros at original offsets from frozen input snapshots.

    Parameters
    ----------
    path : str
        Repository-relative original source key in captures.
    offsets : tuple[int, ...]
        Query positions outside preprocessing directives.
    captures : Mapping[str, bytes]
        Exact repository-contained snapshots; no files are read here.
    resolutions : Mapping[tuple[str, str, bool], str | None]
        Captured owner/spelling/quoted include lookup results.
    initial : Mapping[bytes, _MacroDefinition | None]
        Explicit initial definitions and undefined states. Missing settings
        remain unknown in conditions. Unavailable headers supply no definitions
        and remain observations; this does not establish compiler equivalence.

    Returns
    -------
    dict[int, MacroSelection]
        Immutable selections preserving original query offsets and provenance.

    Raises
    ------
    ValueError
        If names, paths, directives, query positions or traversal bounds fail.

    Notes
    -----
    Captured but inactive headers count toward snapshot capacity without
    consuming the independent active traversal budget.
    """
    if (
        path not in captures
        or len(captures) > _MAX_CAPTURE_FILES
        or len(initial) > 4096
    ):
        raise ValueError("invalid or excessive macro context inputs")
    if any(
        not name
        or PurePosixPath(name).is_absolute()
        or ".." in PurePosixPath(name).parts
        for name in captures
    ):
        raise ValueError("macro captures must use contained relative paths")
    if any(_NAME.fullmatch(name) is None or name == b"defined" for name in initial):
        raise ValueError("invalid initial macro name")
    if any(offset < 0 or offset > len(captures[path]) for offset in offsets):
        raise ValueError("macro query offset outside source")
    walk = _ContextWalk(captures, resolutions, initial)
    walk.walk(path, offsets=tuple(sorted(set(offsets))))
    return walk.results
