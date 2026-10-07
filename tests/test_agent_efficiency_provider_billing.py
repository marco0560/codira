"""Check exact provider charges and budget enforcement without paid requests.

Parameters
----------
None

Returns
-------
None
    Recorded and synthetic response bodies exercise accounting boundaries.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts.agent_efficiency.provider_billing import reported_cost, response_cost
from scripts.agent_efficiency.provider_proxy import ProxySettings
from scripts.run_agent_efficiency_phase6_pilot import _local_proxy_failure_class


@pytest.mark.parametrize("value", [None, True, False, -1, "NaN", "Infinity", "bad", {}])
def test_invalid_charge_is_not_zero(value: object) -> None:
    """Reject unknown charges rather than silently recording free usage.

    Parameters
    ----------
    value : object
        Invalid provider charge.

    Returns
    -------
    None
        Missing, negative and nonfinite values fail billing admission.
    """
    assert reported_cost(value) is None


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("charge", ["0", "0.000000000123", "0.846592325"])
def test_terminal_cost_keeps_precision(stream: bool, charge: str) -> None:
    """Retain zero and precise charges from completed JSON and SSE responses.

    Parameters
    ----------
    stream : bool
        Whether transport uses SSE.
    charge : str
        Exact JSON decimal charge.

    Returns
    -------
    None
        Intermediate events are not substituted for terminal billing.
    """
    body = '{"status":"completed","usage":{"cost":' + charge + "}}"
    if stream:
        body = (
            'data: {"type":"response.created","response":{"usage":{"cost":99}}}\n\n'
            + 'data: {"type":"response.completed","response":'
            + body
            + "}\n\n"
        )
    assert response_cost(body.encode()) == Decimal(charge)


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"\xff",
        b'{"status":"failed","usage":{"cost":1}}',
        b'{"status":"completed","usage":{"cost":true}}',
        b'{"status":"completed","usage":{"cost":"0"}}',
        b'data: {"type":"response.created","response":{"status":"in_progress","usage":{"cost":1}}}',
    ],
)
def test_incomplete_cost_is_not_admitted(body: bytes) -> None:
    """Require a completed response and numeric provider cost.

    Parameters
    ----------
    body : bytes
        Malformed or nonterminal response.

    Returns
    -------
    None
        Unknown billing remains unavailable.
    """
    assert response_cost(body) is None


def test_proxy_enforces_actual_spending_and_preserves_estimate(tmp_path: Path) -> None:
    """Ignore large ceiling estimates and stop exactly at observed charges.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated response evidence root.

    Returns
    -------
    None
        Free responses do not consume USD; exact decimal charges do.
    """
    settings = ProxySettings(
        "client",
        "upstream",
        0,
        max_prompt_usd_per_million=1,
        max_completion_usd_per_million=1,
        max_campaign_spend_usd=0.3,
        response_artifact_root=tmp_path / "responses",
        spend_basis="provider-reported",
    )
    for charge in [0, 0.1, 0.2]:
        assert settings.local_token_cap_reason() is None
        body = json.dumps(
            {
                "status": "completed",
                "usage": {
                    "input_tokens": 1000000,
                    "output_tokens": 0,
                    "total_tokens": 1000000,
                    "cost": charge,
                },
            }
        ).encode()
        settings.record_response(200, [], body=body)
    assert settings.provider_estimated_cost_usd == 3
    assert settings.provider_reported_cost_usd == Decimal("0.3")
    assert settings.local_token_cap_reason() == "campaign_spend_limit_reached"
    assert settings.response_observations[-1]["provider_cost_usd"] == "0.2"


@pytest.mark.parametrize("charge", [None, -1, True, "0"])
def test_proxy_stops_on_invalid_billing(tmp_path: Path, charge: object) -> None:
    """Retain the raw response and block the next call when cost is unknown.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated response evidence root.
    charge : object
        Missing or malformed provider cost.

    Returns
    -------
    None
        Complete token usage alone does not authorize another paid request.
    """
    settings = ProxySettings(
        "client",
        "upstream",
        0,
        response_artifact_root=tmp_path / "responses",
        spend_basis="provider-reported",
    )
    settings.record_response(
        200,
        [],
        body=json.dumps(
            {
                "status": "completed",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "total_tokens": 2,
                    "cost": charge,
                },
            }
        ).encode(),
    )
    assert (tmp_path / "responses/response-001.body").exists()
    assert settings.local_token_cap_reason() == "provider_billing_unavailable"


def test_billing_failure_precedes_retry_noise() -> None:
    """Report unknown billing rather than a later local retry refusal.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The accounting cause remains visible after client retries.
    """
    observations = [
        {"source": "local", "reason": "provider_billing_unavailable"},
        {"source": "local", "reason": "local_request_cap_exceeded"},
    ]
    assert _local_proxy_failure_class(observations) == "provider_billing_unavailable"
