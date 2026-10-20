"""Evaluate bounded preprocessing conditions without inventing initial macros.

Parameters
----------
None

Returns
-------
None
    Supplies three-valued conditions for explicitly configured macro selection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .cpp_macro_expansion import (
    _MacroDefinition,
    _MacroExpander,
    _MacroToken,
    _macro_tokens,
)

_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
_INTEGER = re.compile(
    rb"(0[xX][0-9a-fA-F](?:'?[0-9a-fA-F])*|0[bB][01](?:'?[01])*|[0-9](?:'?[0-9])*)"
    rb"(?:[lL]|ll|LL)?\Z"
)
_UNKNOWN = b"\x00"
_MAX_VALUE = (1 << 63) - 1
_MIN_VALUE = -(1 << 63)
_PRECEDENCE = {
    b"||": 1,
    b"&&": 2,
    b"|": 3,
    b"^": 4,
    b"&": 5,
    b"==": 6,
    b"!=": 6,
    b"<": 7,
    b"<=": 7,
    b">": 7,
    b">=": 7,
    b"<<": 8,
    b">>": 8,
    b"+": 9,
    b"-": 9,
    b"*": 10,
    b"/": 10,
    b"%": 10,
}


def _checked_integer(value: int) -> int | None:
    """Retain values representable in the minimum signed intmax range.

    Parameters
    ----------
    value : int
        Exact intermediate integer.

    Returns
    -------
    int | None
        Unchanged value, or unknown for target-width-dependent arithmetic.
    """
    return value if _MIN_VALUE <= value <= _MAX_VALUE else None


def _integer_literal(spelling: bytes) -> int | None:
    """Read supported signed integer literals, holding unsigned semantics.

    Parameters
    ----------
    spelling : bytes
        One preprocessing number token.

    Returns
    -------
    int | None
        Signed value, or unknown for unsupported, invalid or oversized literals.
    """
    match = _INTEGER.fullmatch(spelling)
    if match is None:
        return None
    value = match[1].replace(b"'", b"")
    base = (
        16
        if value.lower().startswith(b"0x")
        else (
            2
            if value.lower().startswith(b"0b")
            else 8
            if value.startswith(b"0")
            else 10
        )
    )
    try:
        return _checked_integer(int(value, base))
    except ValueError:
        return None


def _binary_value(operator: bytes, left: int | None, right: int | None) -> int | None:
    """Combine known operands conservatively, including logical short circuits.

    Parameters
    ----------
    operator : bytes
        Supported binary preprocessing operator.
    left : int | None
        Left value, or unknown.
    right : int | None
        Right value, or unknown.

    Returns
    -------
    int | None
        Exact bounded value, or unknown for missing or target-dependent evidence.
    """
    if operator == b"&&" and (left == 0 or right == 0):
        return 0
    if operator == b"||" and (
        left is not None and left != 0 or right is not None and right != 0
    ):
        return 1
    if left is None or right is None:
        return None
    if operator == b"&&":
        return int(bool(left) and bool(right))
    if operator == b"||":
        return int(bool(left) or bool(right))
    if operator == b"==":
        return int(left == right)
    if operator == b"!=":
        return int(left != right)
    if operator == b"<":
        return int(left < right)
    if operator == b"<=":
        return int(left <= right)
    if operator == b">":
        return int(left > right)
    if operator == b">=":
        return int(left >= right)
    if operator == b"+":
        return _checked_integer(left + right)
    if operator == b"-":
        return _checked_integer(left - right)
    if operator == b"*":
        return _checked_integer(left * right)
    if operator in {b"/", b"%"}:
        if right == 0:
            return None
        quotient = abs(left) // abs(right)
        if (left < 0) != (right < 0):
            quotient = -quotient
        return _checked_integer(
            quotient if operator == b"/" else left - quotient * right
        )
    if left < 0 or right < 0:
        return None
    if operator in {b"<<", b">>"}:
        if right >= 63:
            return None
        return _checked_integer(left << right if operator == b"<<" else left >> right)
    if operator == b"&":
        return left & right
    if operator == b"|":
        return left | right
    if operator == b"^":
        return left ^ right
    return None


class _ConditionExpression:
    """Parse bounded expressions with preprocessing operator precedence.

    Parameters
    ----------
    spellings : tuple[bytes, ...]
        Macro-expanded condition tokens, with unknowns preserved.
    states : Mapping[bytes, _MacroDefinition | None]
        Known initial/source states; explicit None means undefined.

    Returns
    -------
    None
        Independent parser state for one condition.
    """

    def __init__(
        self,
        spellings: tuple[bytes, ...],
        states: Mapping[bytes, _MacroDefinition | None],
    ) -> None:
        """Store the bounded tokens and known macro states.

        Parameters
        ----------
        spellings : tuple[bytes, ...]
            Expanded preprocessing tokens.
        states : Mapping[bytes, _MacroDefinition | None]
            Explicit definition/undefined states.

        Returns
        -------
        None
            Initializes one expression cursor.
        """
        self.spellings = spellings
        self.states = states
        self.cursor = 0

    def expression(self, minimum: int = 1, depth: int = 0) -> int | None:
        """Parse a left-associative binary expression and its unary operands.

        Parameters
        ----------
        minimum : int, optional
            Lowest operator precedence accepted in this recursive call.
        depth : int, optional
            Parenthesis/unary/operator nesting depth.

        Returns
        -------
        int | None
            Bounded value, retaining unknown operands.

        Raises
        ------
        ValueError
            If nesting, operands or punctuation are invalid or unsupported.
        """
        if depth > 64 or self.cursor >= len(self.spellings):
            raise ValueError("invalid or excessive preprocessing expression")
        token = self.spellings[self.cursor]
        self.cursor += 1
        if token == b"(":
            left = self.expression(depth=depth + 1)
            if (
                self.cursor >= len(self.spellings)
                or self.spellings[self.cursor] != b")"
            ):
                raise ValueError("unbalanced preprocessing condition")
            self.cursor += 1
        elif token in {b"!", b"~", b"+", b"-"}:
            if token == b"~":
                raise ValueError("signed complement requires target representation")
            value = self.expression(11, depth + 1)
            left = (
                None
                if value is None
                else (
                    int(not value)
                    if token == b"!"
                    else _checked_integer(-value if token == b"-" else value)
                )
            )
            if value is not None and left is None:
                raise ValueError("target-dependent unary arithmetic")
        elif token == _UNKNOWN:
            left = None
        elif _IDENTIFIER.fullmatch(token):
            left = 0 if token in self.states and self.states[token] is None else None
        else:
            left = _integer_literal(token)
            if left is None:
                raise ValueError("unsupported preprocessing operand")
        while self.cursor < len(self.spellings):
            operator = self.spellings[self.cursor]
            precedence = _PRECEDENCE.get(operator, 0)
            if precedence < minimum:
                break
            self.cursor += 1
            right = self.expression(precedence + 1, depth + 1)
            left = _binary_value(operator, left, right)
            if left is None and operator not in {b"&&", b"||"}:
                raise ValueError("unresolved or target-dependent binary arithmetic")
        return left


def _defined_tokens(
    tokens: tuple[_MacroToken, ...], states: Mapping[bytes, _MacroDefinition | None]
) -> tuple[_MacroToken, ...]:
    """Resolve original defined operators before ordinary macro replacement.

    Parameters
    ----------
    tokens : tuple[_MacroToken, ...]
        Original condition tokens.
    states : Mapping[bytes, _MacroDefinition | None]
        Explicit known definitions and undefined states.

    Returns
    -------
    tuple[_MacroToken, ...]
        Tokens containing numeric defined results or an unexpandable unknown.

    Raises
    ------
    ValueError
        If a defined operand has invalid syntax.
    """
    result: list[_MacroToken] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.spelling != b"defined":
            result.append(token)
            index += 1
            continue
        start = index
        index += 1
        parenthesized = index < len(tokens) and tokens[index].spelling == b"("
        index += int(parenthesized)
        if index >= len(tokens) or not _IDENTIFIER.fullmatch(tokens[index].spelling):
            raise ValueError("defined requires a macro identifier")
        name = tokens[index].spelling
        index += 1
        if parenthesized:
            if index >= len(tokens) or tokens[index].spelling != b")":
                raise ValueError("defined requires one parenthesized identifier")
            index += 1
        spelling = (
            _UNKNOWN if name not in states else (b"0" if states[name] is None else b"1")
        )
        result.append(_MacroToken(spelling, tokens[start].start, tokens[index - 1].end))
    return tuple(result)


def condition_value(
    source: bytes, states: Mapping[bytes, _MacroDefinition | None]
) -> bool | None:
    """Evaluate a condition from explicit states, preserving unknown settings.

    Parameters
    ----------
    source : bytes
        Condition expression without the directive keyword.
    states : Mapping[bytes, _MacroDefinition | None]
        Captured active definitions and explicitly undefined names. Missing
        names remain unknown; they are not inferred compiler/platform defaults.

    Returns
    -------
    bool | None
        Known truth value, or None for unresolved/unsupported/width-dependent
        expressions. Unsupported subexpressions are held even in otherwise
        decidable branches. Unsigned/character literals, ternary operators and
        signed representation-dependent operations receive no guessed semantics.
    """
    if len(source) > 8192 or len(states) > 4096 or states.get(b"defined") is not None:
        return None
    try:
        tokens = _defined_tokens(_macro_tokens(source), states)
        if len(tokens) > 1024:
            return None
        definitions: dict[bytes, _MacroDefinition] = {}
        pending = [token.spelling for token in tokens]
        seen: set[bytes] = set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            definition = states.get(name)
            if definition is not None:
                definitions[name] = definition
                if not definition.opaque:
                    pending.extend(
                        t.spelling for t in _macro_tokens(definition.replacement)
                    )
        expanded = _MacroExpander(definitions).expand(tokens)
        if len(expanded) > 1024:
            return None
        if any(
            _IDENTIFIER.fullmatch(token.spelling)
            and not (token.spelling in states and states[token.spelling] is None)
            for token in expanded
        ):
            return None
        parser = _ConditionExpression(tuple(t.spelling for t in expanded), states)
        value = parser.expression()
        return None if value is None or parser.cursor != len(expanded) else bool(value)
    except ValueError:
        return None
