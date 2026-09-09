"""Verify strict Phase 1 benchmark contracts and the offline runner adapter."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from scripts.agent_efficiency.contracts import (
    CONTRACT_VERSION,
    ContractError,
    OfflineRunnerAdapter,
    OfflineRunRequest,
    canonical_fingerprint,
    load_document,
    serialize_public,
    validate_document,
)


def fixture() -> dict[str, object]:
    """Build a valid public fixture document.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Fixture contract fixture.
    """

    return {
        "schema_version": CONTRACT_VERSION,
        "fixture_id": "click-public",
        "revision": "a" * 40,
        "source_url": "https://github.com/pallets/click",
        "license": "BSD-3-Clause",
        "visibility": "public",
    }


def campaign() -> dict[str, object]:
    """Build a valid campaign document.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Campaign contract fixture.
    """

    return {
        "schema_version": CONTRACT_VERSION,
        "campaign_id": "pilot-001",
        "fixture_fingerprint": "a" * 64,
        "task_fingerprints": ["b" * 64],
        "budgets": {
            "max_total_tokens": 100,
            "max_output_tokens": 20,
            "timeout_seconds": 30,
        },
        "visibility": "public",
    }


def test_fixture_rejects_moving_revision_and_private_public_serialization() -> None:
    """Reject moving fixture revisions and private-data publication.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover fixture identity and serialization boundaries.
    """

    document = fixture()
    validate_document("fixture", document)
    assert serialize_public("fixture", document)[
        "fingerprint"
    ] == canonical_fingerprint(document)
    moving = deepcopy(document)
    moving["revision"] = "main"
    with pytest.raises(ContractError, match="does not match"):
        validate_document("fixture", moving)
    private = deepcopy(document)
    private["visibility"] = "private"
    private["private_locator"] = "host-only"
    with pytest.raises(ContractError, match="private"):
        serialize_public("fixture", private)


def test_task_rejects_unsafe_path_and_campaign_rejects_contradictory_budget() -> None:
    """Reject fixture escapes and budgets that cannot be honored.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover schema and cross-field invariants.
    """

    task = {
        "schema_version": CONTRACT_VERSION,
        "task_id": "symbols-001",
        "fixture_id": "codira-public",
        "prompt": "Find a symbol.",
        "result_path": "../oracle.json",
        "oracle_id": "symbols",
        "visibility": "public",
    }
    with pytest.raises(ContractError):
        validate_document("task", task)
    invalid_campaign = campaign()
    invalid_campaign["budgets"] = {
        "max_total_tokens": 10,
        "max_output_tokens": 20,
        "timeout_seconds": 30,
    }
    with pytest.raises(ContractError, match="max_total_tokens"):
        validate_document("campaign", invalid_campaign)


def test_offline_adapter_preserves_attempt_identity_and_complete_usage() -> None:
    """Produce a deterministic schema-valid offline result.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Assertions cover runner-neutral identity and accounting fields.
    """

    result = OfflineRunnerAdapter().run(
        OfflineRunRequest("pilot-001", "symbols-001", "attempt-001", "baseline")
    )
    validate_document("run-result", result)
    assert result["attempt_id"] == "attempt-001"
    assert result["usage_complete"] is True


def test_all_contract_kinds_reject_malformed_and_incompatible_input(
    tmp_path: Path,
) -> None:
    """Validate every document kind and reject malformed or drifted records.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary location used for a malformed JSON fixture.

    Returns
    -------
    None
        Assertions cover every Phase 1 schema and loader failure.
    """

    task = {
        "schema_version": CONTRACT_VERSION,
        "task_id": "symbols-001",
        "fixture_id": "codira-public",
        "prompt": "Find a symbol.",
        "result_path": ".benchmark/result.json",
        "oracle_id": "symbols",
        "visibility": "public",
    }
    oracle = {
        "schema_version": CONTRACT_VERSION,
        "oracle_id": "symbols",
        "task_id": "symbols-001",
        "definition": {"contains_symbols": ["context_for_task"]},
        "visibility": "public",
    }
    result = OfflineRunnerAdapter().run(
        OfflineRunRequest("pilot-001", "symbols-001", "attempt-001", "baseline")
    )
    documents = (
        ("fixture", fixture()),
        ("task", task),
        ("campaign", campaign()),
        (
            "usage",
            {
                "schema_version": CONTRACT_VERSION,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
        ),
        ("run-result", result),
        ("oracle", oracle),
    )
    for kind, document in documents:
        validate_document(kind, document)
    incompatible = fixture()
    incompatible["schema_version"] = "2.0"
    with pytest.raises(ContractError, match="1.0"):
        validate_document("fixture", incompatible)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(ContractError, match="JSON object"):
        load_document(malformed, "fixture")
