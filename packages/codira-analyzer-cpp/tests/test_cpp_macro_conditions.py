"""Check explicit preprocessing states, conservative holds and arithmetic.

Parameters
----------
None

Returns
-------
None
    Conditions are independent of production indexing and compiler execution.
"""

from __future__ import annotations

import pytest

from codira_analyzer_cpp.cpp_macro_conditions import condition_value
from codira_analyzer_cpp.cpp_macro_expansion import _MacroDefinition


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (b"0", False),
        (b"1", True),
        (b"!0", True),
        (b"!1", False),
        (b"1 + 2 * 3 == 7", True),
        (b"(1 + 2) * 3 == 7", False),
        (b"8 / 3 == 2", True),
        (b"-8 / 3 == -2", True),
        (b"-8 % 3 == -2", True),
        (b"8 % -3 == 2", True),
        (b"1 << 3 == 8", True),
        (b"8 >> 2 == 2", True),
        (b"3 & 1", True),
        (b"1 | 2 ^ 3", True),
        (b"3 <= 3 && 4 >= 3 && 2 != 3", True),
        (b"3 < 2 || 4 > 5", False),
        (b"0x10 + 010 == 24", True),
        (b"0b11 == 3LL", True),
        (b"0x0000'000F == 15", True),
        (b"1'000L == 1000", True),
        (b"+2 - 2", False),
        (b"1 \\\n && /* evidence */ 2", True),
    ],
)
def test_known_condition_arithmetic(expression: bytes, expected: bool) -> None:
    """Match bounded signed preprocessing arithmetic and operator precedence.

    Parameters
    ----------
    expression : bytes
        Original conditional expression.
    expected : bool
        Required truth value.

    Returns
    -------
    None
        Asserts exact truth without compiler or platform defaults.
    """
    assert condition_value(expression, {}) is expected


@pytest.mark.parametrize(
    "expression",
    [
        b"",
        b"UNDECLARED",
        b"0 && UNDECLARED",
        b"UNDECLARED && 0",
        b"defined(UNKNOWN)",
        b"defined()",
        b"defined(1)",
        b"defined(A + B)",
        b"1 +",
        b"(1",
        b"1)",
        b"1 2",
        b"1 ? 2 : 3",
        b"1U",
        b"1lL",
        b"1Ll",
        b"0x'1",
        b"0b'1",
        b"1''2",
        b"1'",
        b"'a'",
        b"1.0",
        b"09",
        b"9223372036854775808",
        b"9223372036854775807 + 1",
        b"-(-9223372036854775807 - 1)",
        b"1 << 63",
        b"1 >> -1",
        b"-1 >> 1",
        b"-1 & 1",
        b"~1",
        b"1 / 0",
        b"0 && (1 / 0)",
        b"1 || (1 / 0)",
        b"(1 / 0) && 0",
        b"~1 && 0",
        b"(9223372036854775807 + 1) && 0",
        b"(defined(MISSING) / 0) && 0",
        b"(defined(MISSING) + 1) && 0",
        b"__has_attribute(weak)",
        b"(" * 66 + b"1" + b")" * 66,
        b"1 " * 5000,
    ],
)
def test_unproven_conditions_remain_unknown(expression: bytes) -> None:
    """Hold missing settings, invalid syntax and target-dependent semantics.

    Parameters
    ----------
    expression : bytes
        Unsupported or unresolved condition.

    Returns
    -------
    None
        Asserts a hold rather than an inferred false/true condition.
    """
    assert condition_value(expression, {}) is None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (b"defined(ON)", True),
        (b"defined OFF", False),
        (b"defined(EMPTY)", True),
        (b"OFF", False),
        (b"ON == 3", True),
        (b"ON * 2 == 5", True),
        (b"TWICE(3) == 6", True),
        (b"defined(ON) && !defined(OFF)", True),
        (b"defined(ON) || defined(MISSING)", True),
        (b"defined(OFF) && defined(MISSING)", False),
        (b"defined(MISSING) && defined(OFF)", False),
        (b"defined(MISSING) || defined(ON)", True),
        (b"defined(ON) && defined(MISSING)", None),
        (b"defined(OFF) || defined(MISSING)", None),
        (b"defined(ALIAS)", True),
        (b"ALIAS", None),
        (b"EMPTY", None),
        (b"0 && ON", False),
    ],
)
def test_explicit_definitions_and_undefined_states(
    expression: bytes, expected: bool | None
) -> None:
    """Distinguish defined, empty, explicitly undefined and unknown settings.

    Parameters
    ----------
    expression : bytes
        Condition referring to captured definitions.
    expected : bool | None
        Proven truth value or required hold.

    Returns
    -------
    None
        Asserts macro replacement precedence and explicit-state handling.
    """
    states = {
        b"ON": _MacroDefinition(None, b"1 + 2"),
        b"OFF": None,
        b"EMPTY": _MacroDefinition(None, b""),
        b"ALIAS": _MacroDefinition(None, b"MISSING"),
        b"TWICE": _MacroDefinition((b"x",), b"(2 * (x))"),
        b"UNUSED": _MacroDefinition((), b"__VA_OPT__(unsupported)", True),
    }
    assert condition_value(expression, states) is expected


def test_condition_inputs_remain_unchanged() -> None:
    """Keep each source-reaching environment isolated from condition evaluation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Checks the environment is read without mutation or inferred definitions.
    """
    states = {b"ON": _MacroDefinition(None, b"1"), b"OFF": None}
    before = dict(states)
    assert condition_value(b"defined(ON) && !defined(OFF)", states) is True
    assert states == before


def test_redefined_defined_operator_is_held() -> None:
    """Reject environments redefining the preprocessing defined operator.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Prevents a reserved operator from receiving invented macro semantics.
    """
    states = {
        b"defined": _MacroDefinition(None, b"1"),
        b"ON": _MacroDefinition(None, b"1"),
    }
    assert condition_value(b"defined(ON)", states) is None
