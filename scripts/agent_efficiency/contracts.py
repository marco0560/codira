"""Define strict, versioned contracts for the agent-efficiency benchmark.

The contracts deliberately separate public, serializable benchmark definitions
from runtime evidence.  JSON Schema validates individual documents while the
functions here enforce relationships that span fields and documents.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol, cast

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

CONTRACT_VERSION = "1.0"
SCHEMA_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "benchmarks" / "agent-efficiency" / "schemas"
)
DOCUMENT_KINDS = frozenset(
    {"fixture", "task", "campaign", "run-result", "usage", "oracle"}
)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ContractError(ValueError):
    """Report one deterministic benchmark-contract validation failure.

    Parameters
    ----------
    detail : str
        Human-readable failure without private fixture contents.

    Returns
    -------
    None
        The exception carries the deterministic validation detail.
    """


@dataclass(frozen=True)
class OfflineRunRequest:
    """Describe one runner-neutral request used by the offline adapter.

    Parameters
    ----------
    campaign_id : str
        Immutable campaign identity.
    task_id : str
        Registered task identity.
    attempt_id : str
        Stable attempt identity.
    assistance_mode : str
        Either ``baseline`` or ``codira-mcp``.

    Returns
    -------
    None
        Instances are immutable runner inputs.
    """

    campaign_id: str
    task_id: str
    attempt_id: str
    assistance_mode: str


class RunnerAdapter(Protocol):
    """Specify a runner-neutral adapter boundary.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Implementations return a schema-valid run-result mapping.
    """

    def run(self, request: OfflineRunRequest) -> Mapping[str, object]:
        """Execute one request without selecting a provider implementation.

        Parameters
        ----------
        request : OfflineRunRequest
            Immutable run request.

        Returns
        -------
        Mapping[str, object]
            Schema-valid run-result mapping.
        """


@dataclass(frozen=True)
class OfflineRunnerAdapter:
    """Return deterministic results for harness tests without a provider.

    Parameters
    ----------
    outcome : str, optional
        Recorded deterministic terminal outcome.

    Returns
    -------
    None
        Instances implement the runner-neutral adapter contract.
    """

    outcome: str = "infrastructure_failure"

    def run(self, request: OfflineRunRequest) -> Mapping[str, object]:
        """Return a zero-usage result for one offline request.

        Parameters
        ----------
        request : OfflineRunRequest
            Request whose identity is preserved in the result.

        Returns
        -------
        Mapping[str, object]
            Deterministic, schema-valid offline run-result document.
        """

        return {
            "schema_version": CONTRACT_VERSION,
            "campaign_id": request.campaign_id,
            "task_id": request.task_id,
            "attempt_id": request.attempt_id,
            "assistance_mode": request.assistance_mode,
            "outcome": self.outcome,
            "failure_class": "offline" if self.outcome != "success" else None,
            "usage_complete": True,
            "usage": {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
            },
            "provenance": {"runner": "offline", "runner_version": CONTRACT_VERSION},
        }


def canonical_fingerprint(document: Mapping[str, object]) -> str:
    """Return a SHA-256 fingerprint of canonical public JSON.

    Parameters
    ----------
    document : Mapping[str, object]
        JSON-compatible document without private runtime material.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """

    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_relative_path(value: object) -> bool:
    """Return whether a value is a safe non-empty POSIX-relative path.

    Parameters
    ----------
    value : object
        Candidate path value.

    Returns
    -------
    bool
        ``True`` only for paths that cannot escape a fixture root.
    """

    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _validator(kind: str) -> Draft202012Validator:
    """Load the strict validator for one versioned benchmark document kind.

    Parameters
    ----------
    kind : str
        One value from ``DOCUMENT_KINDS``.

    Returns
    -------
    jsonschema.Draft202012Validator
        Validator with the benchmark safe-path format registered.

    Raises
    ------
    ContractError
        If the requested document kind is unsupported.
    """

    if kind not in DOCUMENT_KINDS:
        raise ContractError(f"unsupported benchmark document kind: {kind}")  # noqa: TRY003, EM102
    schema_path = SCHEMA_DIRECTORY / f"{kind}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    checker = FormatChecker()
    checker.checks("safe-relative-path")(_safe_relative_path)
    return Draft202012Validator(schema, format_checker=checker)


def validate_document(kind: str, document: Mapping[str, object]) -> None:
    """Validate one document and its non-schema local invariants.

    Parameters
    ----------
    kind : str
        Versioned benchmark document kind.
    document : Mapping[str, object]
        Parsed JSON object to validate.

    Returns
    -------
    None
        Invalid documents raise ``ContractError``.
    """

    errors = sorted(
        _validator(kind).iter_errors(document), key=lambda item: list(item.path)
    )
    if errors:
        raise ContractError(errors[0].message)
    if document.get("schema_version") != CONTRACT_VERSION:
        raise ContractError("incompatible schema_version")  # noqa: TRY003, EM101
    if kind == "fixture" and not _SHA40.fullmatch(cast("str", document["revision"])):
        raise ContractError("fixture revision must be an immutable 40-character SHA")  # noqa: TRY003, EM101
    if kind == "campaign":
        budgets = cast("Mapping[str, object]", document["budgets"])
        if cast("int", budgets["max_total_tokens"]) < cast(
            "int", budgets["max_output_tokens"]
        ):
            raise ContractError("max_total_tokens cannot be below max_output_tokens")  # noqa: TRY003, EM101


def load_document(path: Path, kind: str) -> dict[str, object]:
    """Load and validate a JSON document from a safe expected filename.

    Parameters
    ----------
    path : pathlib.Path
        Document path beneath a caller-controlled approved root.
    kind : str
        Expected document kind.

    Returns
    -------
    dict[str, object]
        Validated JSON object.

    Raises
    ------
    ContractError
        If JSON is malformed, is not an object, or violates the contract.
    """

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load {kind} document: {error}") from error  # noqa: TRY003, EM102
    if not isinstance(parsed, dict):
        raise ContractError(f"{kind} document must be a JSON object")  # noqa: TRY003, EM102
    document = cast("dict[str, object]", parsed)
    validate_document(kind, document)
    return document


def serialize_public(kind: str, document: Mapping[str, object]) -> dict[str, object]:
    """Return a public serialization or reject a private document.

    Parameters
    ----------
    kind : str
        Benchmark document kind.
    document : Mapping[str, object]
        Already parsed benchmark document.

    Returns
    -------
    dict[str, object]
        Deep-copied JSON-safe public document with its fingerprint.

    Raises
    ------
    ContractError
        If a private document or private-named field would be serialized.
    """

    validate_document(kind, document)
    if document.get("visibility") == "private" or any(
        key.startswith("private_") for key in document
    ):
        raise ContractError("private benchmark material cannot be publicly serialized")  # noqa: TRY003, EM101
    public = cast("dict[str, object]", json.loads(json.dumps(document)))
    public["fingerprint"] = canonical_fingerprint(public)
    return public
