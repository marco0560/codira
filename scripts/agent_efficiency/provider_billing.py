"""Read exact OpenRouter charges from retained terminal response evidence.

Parameters
----------
None

Returns
-------
None
    Parsing never substitutes estimated prices for missing billing evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation


def reported_cost(value: object) -> Decimal | None:
    """Validate a nonnegative finite reported monetary value.

    Parameters
    ----------
    value : object
        JSON number or persisted decimal string, excluding booleans.

    Returns
    -------
    decimal.Decimal or None
        Exact USD charge, including zero, or absent/invalid evidence.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        cost = Decimal(str(value))
    except InvalidOperation:
        return None
    return cost if cost.is_finite() and cost >= 0 else None


def response_cost(body: bytes) -> Decimal | None:
    """Extract cost from a completed Responses JSON object or SSE terminal event.

    Parameters
    ----------
    body : bytes
        Exact retained provider response body.

    Returns
    -------
    decimal.Decimal or None
        Terminal usage.cost; missing, malformed or incomplete bodies return None.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    documents: list[object] = []
    try:
        documents.append(json.loads(text, parse_float=Decimal))
    except json.JSONDecodeError:
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                document = json.loads(line[5:].strip(), parse_float=Decimal)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(document, Mapping)
                and document.get("type") == "response.completed"
            ):
                documents.append(document.get("response"))
    for document in reversed(documents):
        if not isinstance(document, Mapping):
            continue
        if document.get("type") == "response.completed":
            document = document.get("response")
        if not isinstance(document, Mapping) or document.get("status") != "completed":
            continue
        usage = document.get("usage")
        if isinstance(usage, Mapping):
            value = usage.get("cost")
            # Provider JSON must contain a monetary number, never a string.
            return reported_cost(value) if isinstance(value, (int, Decimal)) else None
    return None
