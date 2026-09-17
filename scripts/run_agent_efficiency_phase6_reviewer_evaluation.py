#!/usr/bin/env python3
"""Run a bounded, reproducible Grok and DeepSeek reviewer comparison."""
# ruff: noqa: EM101, S310, S607, TRY003

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_agent_efficiency_phase6_review import (
    TOKEN_ENVIRONMENT_KEY,
    ReviewError,
    build_prompt,
    request_review,
)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_USER_MODELS_URL = "https://openrouter.ai/api/v1/models/user"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
DEFAULT_MANIFEST = Path(
    "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
)
DEFAULT_OUTPUT_DIRECTORY = Path(
    ".artifacts/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash-r4-diagnostic-20260917"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_OUTPUT_ROOT = REPOSITORY_ROOT / DEFAULT_OUTPUT_DIRECTORY
_SHA40 = frozenset("0123456789abcdef")


class EvaluationError(ValueError):
    """Report a public-safe reviewer-evaluation preflight or run failure.

    Parameters
    ----------
    detail : str
        Deterministic failure explanation without a credential or review body.
    """


@dataclass(frozen=True)
class ModelContract:
    """Describe one provider-verified model and its maximum token pricing.

    Parameters
    ----------
    identifier : str
        Exact OpenRouter model ID.
    prompt_usd_per_million : float
        Highest published prompt-token price.
    completion_usd_per_million : float
        Highest published completion-token price.
    """

    identifier: str
    prompt_usd_per_million: float
    completion_usd_per_million: float


@dataclass(frozen=True)
class EvaluationCase:
    """Define one immutable historical change submitted for review.

    Parameters
    ----------
    identifier : str
        Stable corpus-case identifier.
    base : str
        Full immutable Git revision before the reviewed change.
    head : str
        Full immutable Git revision after the reviewed change.
    paths : tuple[str, ...]
        Repository-relative paths included in the review diff.
    expected_verdict : str
        Expected ``NEEDS_FIXES`` or ``PASS`` state from the frozen corpus.
    finding_terms : tuple[tuple[str, ...], ...]
        Alternative all-of term groups for the known defect, empty for repairs.
    diff_sha256 : str
        SHA-256 of the generated binary diff.
    """

    identifier: str
    base: str
    head: str
    paths: tuple[str, ...]
    expected_verdict: str
    finding_terms: tuple[tuple[str, ...], ...]
    diff_sha256: str


def _error(detail: str) -> EvaluationError:
    """Build one stable evaluation failure.

    Parameters
    ----------
    detail : str
        Public-safe failure explanation.

    Returns
    -------
    EvaluationError
        Failure instance carrying the supplied detail.
    """

    return EvaluationError(detail)


def _is_sha40(value: object) -> bool:
    """Return whether a value is a lowercase immutable Git object ID.

    Parameters
    ----------
    value : object
        Candidate object ID.

    Returns
    -------
    bool
        ``True`` only for a 40-character lowercase hexadecimal string.
    """

    return isinstance(value, str) and len(value) == 40 and set(value) <= _SHA40


def _safe_path(value: object) -> bool:
    """Return whether a corpus path is repository-relative and non-escaping.

    Parameters
    ----------
    value : object
        Candidate repository-relative path.

    Returns
    -------
    bool
        ``True`` only for a safe non-empty POSIX path.
    """

    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and "." not in path.parts and ".." not in path.parts


def _load_json(path: Path) -> dict[str, object]:
    """Load one evaluator manifest as a JSON object.

    Parameters
    ----------
    path : pathlib.Path
        Manifest path supplied by the operator.

    Returns
    -------
    dict[str, object]
        Parsed manifest object.

    Raises
    ------
    EvaluationError
        If the manifest cannot be read or is not an object.
    """

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise _error("cannot load reviewer evaluation manifest") from error
    if not isinstance(document, dict):
        raise _error("reviewer evaluation manifest must be an object")
    return document


def _required_int(document: Mapping[str, object], field: str) -> int:
    """Return one manifest integer whose prior validation establishes its type.

    Parameters
    ----------
    document : collections.abc.Mapping[str, object]
        Validated reviewer-evaluation manifest.
    field : str
        Required positive integer field name.

    Returns
    -------
    int
        Validated integer value.

    Raises
    ------
    EvaluationError
        If an internal caller bypasses the manifest validation boundary.
    """

    value = document.get(field)
    if not isinstance(value, int):
        raise _error("reviewer evaluation manifest has invalid bounded controls")
    return value


def _required_number(document: Mapping[str, object], field: str) -> float:
    """Return one manifest numeric value validated at the load boundary.

    Parameters
    ----------
    document : collections.abc.Mapping[str, object]
        Validated reviewer-evaluation manifest.
    field : str
        Required positive numeric field name.

    Returns
    -------
    float
        Validated numeric value.

    Raises
    ------
    EvaluationError
        If an internal caller bypasses the manifest validation boundary.
    """

    value = document.get(field)
    if not isinstance(value, int | float):
        raise _error("reviewer evaluation manifest has invalid bounded controls")
    return float(value)


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Return the stable SHA-256 fingerprint of one JSON-safe document.

    Parameters
    ----------
    document : collections.abc.Mapping[str, object]
        JSON-safe data whose field ordering must not affect the fingerprint.

    Returns
    -------
    str
        Hexadecimal SHA-256 fingerprint.
    """

    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _load_models(document: Mapping[str, object]) -> tuple[ModelContract, ...]:
    """Validate the two fixed model identities and their price ceilings.

    Parameters
    ----------
    document : collections.abc.Mapping[str, object]
        Parsed public evaluation manifest.

    Returns
    -------
    tuple[ModelContract, ...]
        Two exact model contracts in the manifest order.

    Raises
    ------
    EvaluationError
        If model records or identities are invalid.
    """

    raw_models = document.get("models")
    if not isinstance(raw_models, list) or len(raw_models) != 2:
        raise _error("reviewer evaluation manifest must define exactly two models")
    models: list[ModelContract] = []
    for raw_model in raw_models:
        if not isinstance(raw_model, Mapping):
            raise _error("reviewer evaluation model is invalid")
        identifier = raw_model.get("id")
        prompt_price = raw_model.get("max_prompt_usd_per_million")
        completion_price = raw_model.get("max_completion_usd_per_million")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(prompt_price, (int, float))
            or prompt_price <= 0
            or not isinstance(completion_price, (int, float))
            or completion_price <= 0
        ):
            raise _error("reviewer evaluation model is invalid")
        models.append(
            ModelContract(identifier, float(prompt_price), float(completion_price))
        )
    if {model.identifier for model in models} != {
        "x-ai/grok-build-0.1",
        "deepseek/deepseek-v4.1-flash",
    }:
        raise _error("reviewer evaluation model identities are invalid")
    return tuple(models)


def _load_case(raw_case: object) -> EvaluationCase:
    """Validate one immutable historical reviewer corpus case.

    Parameters
    ----------
    raw_case : object
        Candidate JSON case object from the tracked manifest.

    Returns
    -------
    EvaluationCase
        Validated immutable historical source selection.

    Raises
    ------
    EvaluationError
        If any case field is invalid or internally contradictory.
    """

    if not isinstance(raw_case, Mapping):
        raise _error("reviewer evaluation case is invalid")
    identifier = raw_case.get("id")
    base, head = raw_case.get("base"), raw_case.get("head")
    paths = raw_case.get("paths")
    expected = raw_case.get("expected_verdict")
    raw_terms = raw_case.get("finding_terms", [])
    fingerprint = raw_case.get("diff_sha256")
    if (
        not isinstance(identifier, str)
        or not identifier
        or not _is_sha40(base)
        or not _is_sha40(head)
        or not isinstance(paths, list)
        or not paths
        or not all(_safe_path(item) for item in paths)
        or expected not in {"PASS", "NEEDS_FIXES"}
        or not isinstance(raw_terms, list)
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
    ):
        raise _error("reviewer evaluation case is invalid")
    terms: list[tuple[str, ...]] = []
    for group in raw_terms:
        if (
            not isinstance(group, list)
            or not group
            or not all(isinstance(term, str) and term for term in group)
        ):
            raise _error("reviewer evaluation finding terms are invalid")
        terms.append(tuple(group))
    if (expected == "PASS") != (not terms):
        raise _error("reviewer evaluation finding terms contradict expected verdict")
    assert isinstance(base, str)
    assert isinstance(head, str)
    return EvaluationCase(
        identifier,
        base,
        head,
        tuple(paths),
        expected,
        tuple(terms),
        fingerprint,
    )


def load_manifest(
    path: Path,
) -> tuple[dict[str, object], tuple[ModelContract, ...], tuple[EvaluationCase, ...]]:
    """Load and validate the bounded reviewer-evaluation manifest.

    Parameters
    ----------
    path : pathlib.Path
        Tracked JSON manifest defining models, corpus, and ceilings.

    Returns
    -------
    tuple[dict[str, object], tuple[ModelContract, ...], tuple[EvaluationCase, ...]]
        Parsed public manifest and validated model and corpus records.

    Raises
    ------
    EvaluationError
        If any immutable identity, budget, or corpus field is invalid.
    """

    document = _load_json(path)
    if document.get("schema_version") != "1.0":
        raise _error("reviewer evaluation manifest schema_version is invalid")
    evaluation_id = document.get("evaluation_id")
    if not isinstance(evaluation_id, str) or not evaluation_id:
        raise _error("reviewer evaluation manifest evaluation_id is invalid")
    repetitions = document.get("repetitions")
    maximum_requests = document.get("max_requests")
    output_tokens = document.get("max_output_tokens")
    timeout_seconds = document.get("timeout_seconds")
    spend_limit = document.get("max_total_estimated_usd")
    if (
        not isinstance(repetitions, int)
        or repetitions != 2
        or not isinstance(maximum_requests, int)
        or maximum_requests != 24
        or not isinstance(output_tokens, int)
        or output_tokens < 1
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or not isinstance(spend_limit, (int, float))
        or spend_limit <= 0
    ):
        raise _error("reviewer evaluation manifest has invalid bounded controls")
    models = _load_models(document)
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 6:
        raise _error("reviewer evaluation manifest must define six frozen diffs")
    cases = [_load_case(raw_case) for raw_case in raw_cases]
    if len({case.identifier for case in cases}) != len(cases):
        raise _error("reviewer evaluation case identities must be unique")
    return document, models, tuple(cases)


def collect_historical_diff(case: EvaluationCase) -> str:
    """Collect and fingerprint one frozen historical diff.

    Parameters
    ----------
    case : EvaluationCase
        Immutable source revisions and included paths.

    Returns
    -------
    str
        Complete binary diff whose digest matches the tracked corpus record.

    Raises
    ------
    EvaluationError
        If Git cannot reproduce the committed diff or its digest has changed.
    """

    completed = subprocess.run(
        (
            "git",
            "diff",
            "--binary",
            "--full-index",
            case.base,
            case.head,
            "--",
            *case.paths,
        ),
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise _error("cannot reproduce frozen reviewer evaluation diff")
    fingerprint = hashlib.sha256(completed.stdout.encode("utf-8")).hexdigest()
    if fingerprint != case.diff_sha256:
        raise _error("frozen reviewer evaluation diff fingerprint does not match")
    return completed.stdout


def _maximum_price(pricing: Mapping[str, object], field: str) -> float:
    """Return the highest current OpenRouter price for one token category.

    Parameters
    ----------
    pricing : collections.abc.Mapping[str, object]
        OpenRouter model pricing object.
    field : str
        Pricing field, such as ``prompt`` or ``completion``.

    Returns
    -------
    float
        Highest published USD price per token across ordinary and override rates.

    Raises
    ------
    EvaluationError
        If the provider catalog omits a valid price.
    """

    values: list[float] = []
    base = pricing.get(field)
    if isinstance(base, str | int | float):
        try:
            values.append(float(base))
        except ValueError as error:
            raise _error("provider catalog price is invalid") from error
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list):
        raise _error("provider catalog price overrides are invalid")
    for override in overrides:
        if not isinstance(override, Mapping):
            raise _error("provider catalog price overrides are invalid")
        value = override.get(field)
        if isinstance(value, str | int | float):
            try:
                values.append(float(value))
            except ValueError as error:
                raise _error("provider catalog price is invalid") from error
    if not values or any(value <= 0 for value in values):
        raise _error("provider catalog price is unavailable")
    return max(values)


def fetch_provider_contracts(
    models: Sequence[ModelContract],
) -> dict[str, dict[str, object]]:
    """Fetch public OpenRouter metadata and fail closed on contract drift.

    Parameters
    ----------
    models : collections.abc.Sequence[ModelContract]
        Exact model identities and admitted maximum prices.

    Returns
    -------
    dict[str, dict[str, object]]
        Sanitized model identity, capabilities, and price observations.

    Raises
    ------
    EvaluationError
        If a required model is unavailable, lacks ``max_tokens``, or exceeds a
        tracked maximum price.
    """

    request = Request(OPENROUTER_MODELS_URL, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise _error("cannot fetch provider model catalog") from error
    raw_models = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(raw_models, list):
        raise _error("provider model catalog is malformed")
    catalog = {
        item.get("id"): item
        for item in raw_models
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    observed: dict[str, dict[str, object]] = {}
    for expected in models:
        item = catalog.get(expected.identifier)
        if not isinstance(item, Mapping):
            raise _error("required reviewer model is unavailable")
        pricing = item.get("pricing")
        parameters = item.get("supported_parameters")
        top_provider = item.get("top_provider")
        if (
            not isinstance(pricing, Mapping)
            or not isinstance(parameters, list)
            or "max_tokens" not in parameters
            or "reasoning" not in parameters
            or not isinstance(top_provider, Mapping)
        ):
            raise _error("required reviewer model contract is incomplete")
        context_length = item.get("context_length")
        max_completion_tokens = top_provider.get("max_completion_tokens")
        if (
            not isinstance(context_length, int)
            or context_length < 1
            or not isinstance(max_completion_tokens, int)
            or max_completion_tokens < 1
        ):
            raise _error("required reviewer model contract is incomplete")
        prompt_price = _maximum_price(pricing, "prompt") * 1_000_000
        completion_price = _maximum_price(pricing, "completion") * 1_000_000
        if (
            prompt_price > expected.prompt_usd_per_million
            or completion_price > expected.completion_usd_per_million
        ):
            raise _error("required reviewer model price exceeds the frozen ceiling")
        observed[expected.identifier] = {
            "id": expected.identifier,
            "context_length": context_length,
            "max_completion_tokens": max_completion_tokens,
            "supported_parameters": sorted(str(item) for item in parameters),
            "max_prompt_usd_per_million": prompt_price,
            "max_completion_usd_per_million": completion_price,
        }
    return observed


def fetch_authenticated_model_contracts(
    models: Sequence[ModelContract], token: str
) -> dict[str, dict[str, object]]:
    """Verify exact reviewer models against the scoped key's visible catalog.

    Parameters
    ----------
    models : collections.abc.Sequence[ModelContract]
        Exact model identities selected by the frozen evaluation manifest.
    token : str
        SOPS-injected OpenRouter key used only for the authenticated catalog.

    Returns
    -------
    dict[str, dict[str, object]]
        Sanitized selected-model capabilities after key-specific filtering.

    Raises
    ------
    EvaluationError
        If the key cannot access either exact model or its required parameters.
    """

    request = Request(
        OPENROUTER_USER_MODELS_URL,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except HTTPError as error:
        detail = f"cannot fetch authenticated reviewer model catalog: HTTP {error.code}"
        raise _error(detail) from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise _error("cannot fetch authenticated reviewer model catalog") from error
    raw_models = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(raw_models, list):
        raise _error("authenticated reviewer model catalog is malformed")
    catalog = {
        item.get("id"): item
        for item in raw_models
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }
    observed: dict[str, dict[str, object]] = {}
    for expected in models:
        item = catalog.get(expected.identifier)
        if not isinstance(item, Mapping):
            raise _error("scoped key cannot access required reviewer model")
        parameters = item.get("supported_parameters")
        if (
            not isinstance(parameters, list)
            or "max_tokens" not in parameters
            or "reasoning" not in parameters
        ):
            raise _error("scoped key reviewer model contract is incomplete")
        reasoning = item.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, Mapping):
            raise _error("scoped key reviewer model contract is incomplete")
        observed[expected.identifier] = {
            "id": expected.identifier,
            "supported_parameters": sorted(str(value) for value in parameters),
            "reasoning": {
                key: reasoning[key]
                for key in ("mandatory", "default_enabled", "supports_max_tokens")
                if isinstance(reasoning, Mapping)
                and isinstance(reasoning.get(key), bool)
            },
        }
    return observed


def estimate_total_cost(
    cases: Sequence[EvaluationCase],
    diffs: Mapping[str, str],
    models: Sequence[ModelContract],
    *,
    repetitions: int,
    max_output_tokens: int,
) -> float:
    """Estimate a worst-case evaluation cost from frozen source sizes.

    Parameters
    ----------
    cases : collections.abc.Sequence[EvaluationCase]
        Frozen corpus cases.
    diffs : collections.abc.Mapping[str, str]
        Reproduced diff text keyed by case ID.
    models : collections.abc.Sequence[ModelContract]
        Maximum admitted per-token prices.
    repetitions : int
        Number of runs per case and model.
    max_output_tokens : int
        Completion-token ceiling per request.

    Returns
    -------
    float
        Conservative USD estimate using one token per prompt character.
    """

    prompt_tokens = sum(len(build_prompt(diffs[case.identifier])) for case in cases)
    prompt_usd = sum(
        prompt_tokens * model.prompt_usd_per_million / 1_000_000 for model in models
    )
    completion_usd = sum(
        len(cases) * max_output_tokens * model.completion_usd_per_million / 1_000_000
        for model in models
    )
    return (prompt_usd + completion_usd) * repetitions


def validate_execution_limits(
    cases: Sequence[EvaluationCase],
    diffs: Mapping[str, str],
    provider_contracts: Mapping[str, Mapping[str, object]],
    *,
    max_output_tokens: int,
) -> None:
    """Reject an output or prompt size that exceeds a verified model limit.

    Parameters
    ----------
    cases : collections.abc.Sequence[EvaluationCase]
        Frozen cases whose prompts will be submitted.
    diffs : collections.abc.Mapping[str, str]
        Reproduced diff text keyed by case identifier.
    provider_contracts : collections.abc.Mapping[str, collections.abc.Mapping[str, object]]
        Sanitized public model limits.
    max_output_tokens : int
        Requested completion-token cap.

    Raises
    ------
    EvaluationError
        If a requested review could exceed a provider's verified context or
        completion limit.
    """

    for contract in provider_contracts.values():
        context_length = contract.get("context_length")
        completion_limit = contract.get("max_completion_tokens")
        if not isinstance(context_length, int) or not isinstance(completion_limit, int):
            raise _error("required reviewer model contract is incomplete")
        if max_output_tokens > completion_limit:
            raise _error("reviewer evaluation output limit exceeds provider contract")
        for case in cases:
            prompt_tokens = len(build_prompt(diffs[case.identifier]))
            if prompt_tokens + max_output_tokens > context_length:
                raise _error("reviewer evaluation prompt exceeds provider contract")


def _matching_terms(review: str, groups: Sequence[tuple[str, ...]]) -> bool:
    """Return whether a review contains all terms from one expected group.

    Parameters
    ----------
    review : str
        Reviewer text.
    groups : collections.abc.Sequence[tuple[str, ...]]
        Alternative groups of required lowercase term fragments.

    Returns
    -------
    bool
        ``True`` if any group is wholly present in the review.
    """

    normalized = review.lower()
    return any(all(term.lower() in normalized for term in group) for group in groups)


def _safe_model_name(identifier: str) -> str:
    """Return a filesystem-safe stable name for one model identifier.

    Parameters
    ----------
    identifier : str
        OpenRouter model ID.

    Returns
    -------
    str
        Slash-free identifier used below the ignored artifact directory.
    """

    return identifier.replace("/", "--")


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    """Atomically write one ignored evaluation artifact.

    Parameters
    ----------
    path : pathlib.Path
        Destination below the ignored artifact directory.
    document : collections.abc.Mapping[str, object]
        JSON-safe report or raw response document.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _create_json(path: Path, document: Mapping[str, object]) -> None:
    """Create a state file exactly once without replacing an existing claim.

    Parameters
    ----------
    path : pathlib.Path
        New state-file destination below the ignored artifact root.
    document : collections.abc.Mapping[str, object]
        JSON-safe initial state that claims the evaluation identity.

    Raises
    ------
    EvaluationError
        If another process has already claimed the evaluation state.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise _error(
            "reviewer evaluation has unfinished or completed attempt state"
        ) from error


def fetch_key_budget(token: str, required_usd: float) -> dict[str, object]:
    """Verify that the scoped key can fund the complete bounded trial.

    Parameters
    ----------
    token : str
        SOPS-injected OpenRouter inference key.
    required_usd : float
        Conservative whole-trial amount that must remain on the key.

    Returns
    -------
    dict[str, object]
        Public-safe credit-limit and current-usage fields, excluding key labels.

    Raises
    ------
    EvaluationError
        If the key limit is unavailable, malformed, or below the frozen trial
        estimate. This occurs before any model request.
    """

    request = Request(
        OPENROUTER_KEY_URL,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise _error("cannot verify reviewer evaluation key budget") from error
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        raise _error("reviewer evaluation key budget is malformed")
    limit = data.get("limit")
    remaining = data.get("limit_remaining")
    reset = data.get("limit_reset")
    daily_usage = data.get("usage_daily")
    if (
        not isinstance(limit, int | float)
        or not isinstance(remaining, int | float)
        or not isinstance(daily_usage, int | float)
        or limit < required_usd
        or remaining < required_usd
        or (reset is not None and not isinstance(reset, str))
    ):
        raise _error("reviewer evaluation key budget is insufficient")
    return {
        "limit_usd": float(limit),
        "limit_remaining_usd": float(remaining),
        "limit_reset": reset,
        "usage_daily_usd": float(daily_usage),
    }


def key_budget_summary(manifest_path: Path) -> dict[str, object]:
    """Return one non-billing scoped-key budget check for a frozen manifest.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Tracked reviewer-evaluation manifest defining the bounded trial.

    Returns
    -------
    dict[str, object]
        Public-safe evaluation identity, conservative estimate, and key budget.

    Raises
    ------
    EvaluationError
        If the frozen manifest, inputs, credential, or key budget is invalid.
    """

    manifest, models, cases = load_manifest(manifest_path)
    diffs = {case.identifier: collect_historical_diff(case) for case in cases}
    estimate = estimate_total_cost(
        cases,
        diffs,
        models,
        repetitions=_required_int(manifest, "repetitions"),
        max_output_tokens=_required_int(manifest, "max_output_tokens"),
    )
    if estimate > _required_number(manifest, "max_total_estimated_usd"):
        raise _error("reviewer evaluation estimate exceeds the frozen budget")
    token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
    if not token:
        raise _error("independent review credential is unavailable")
    return {
        "evaluation_id": manifest["evaluation_id"],
        "estimated_total_usd": estimate,
        "key_budget": fetch_key_budget(token, estimate),
    }


def authenticated_model_contract_summary(manifest_path: Path) -> dict[str, object]:
    """Return a non-billing, key-specific model admission check.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Tracked reviewer evaluation manifest defining the exact model IDs.

    Returns
    -------
    dict[str, object]
        Sanitized key-visible contracts for the selected reviewer models.

    Raises
    ------
    EvaluationError
        If the credential is absent or cannot admit either selected model.
    """

    manifest, models, _cases = load_manifest(manifest_path)
    token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
    if not token:
        raise _error("independent review credential is unavailable")
    return {
        "evaluation_id": manifest["evaluation_id"],
        "authenticated_model_contracts": fetch_authenticated_model_contracts(
            models, token
        ),
    }


def _validate_output_directory(output_directory: Path) -> Path:
    """Return a resolved ignored-artifact directory or reject a tracked path.

    Parameters
    ----------
    output_directory : pathlib.Path
        Requested root for raw provider evidence.

    Returns
    -------
    pathlib.Path
        Resolved path beneath the repository's ignored artifact root.

    Raises
    ------
    EvaluationError
        If raw evidence could be written to a tracked repository path.
    """

    resolved = output_directory.resolve()
    artifact_root = ARTIFACT_OUTPUT_ROOT.resolve()
    try:
        resolved.relative_to(artifact_root)
    except ValueError as error:
        raise _error(
            "reviewer evaluation output must be under ignored artifacts"
        ) from error
    return resolved


def _total_actual_cost(attempts: Sequence[Mapping[str, object]]) -> float:
    """Return the provider-reported cost of completed safe attempt summaries.

    Parameters
    ----------
    attempts : collections.abc.Sequence[collections.abc.Mapping[str, object]]
        Completed-attempt records whose review bodies are stored separately.

    Returns
    -------
    float
        Aggregate reported USD cost.

    Raises
    ------
    EvaluationError
        If an internal record has no numeric provider-reported cost.
    """

    total = 0.0
    for attempt in attempts:
        usage = attempt.get("usage")
        if not isinstance(usage, Mapping):
            raise _error("reviewer evaluation attempt usage is malformed")
        cost = usage.get("cost")
        if not isinstance(cost, int | float):
            raise _error("reviewer evaluation attempt usage is malformed")
        total += float(cost)
    return total


def run_evaluation(
    manifest: Mapping[str, object],
    models: Sequence[ModelContract],
    cases: Sequence[EvaluationCase],
    diffs: Mapping[str, str],
    output_directory: Path,
) -> dict[str, object]:
    """Submit the frozen corpus and write raw evidence outside Git.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Validated tracked evaluation controls.
    models : collections.abc.Sequence[ModelContract]
        Provider-verified model identities.
    cases : collections.abc.Sequence[EvaluationCase]
        Frozen historical source cases.
    diffs : collections.abc.Mapping[str, str]
        Reproduced source evidence keyed by case ID.
    output_directory : pathlib.Path
        Ignored root for raw responses and safe summary data.

    Returns
    -------
    dict[str, object]
        Safe summary retaining no review body.

    Raises
    ------
    EvaluationError
        If credentials are unavailable or an attempt cannot produce complete
        model-identified evidence. An incomplete prior run is rejected before
        any provider request is retried.
    """

    output_directory = _validate_output_directory(output_directory)
    state_path = output_directory / "execution-state.json"
    if state_path.exists():
        raise _error("reviewer evaluation has unfinished or completed attempt state")
    token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
    if not token:
        raise _error("independent review credential is unavailable")
    authenticated_contracts = fetch_authenticated_model_contracts(models, token)
    repetitions = _required_int(manifest, "repetitions")
    max_output_tokens = _required_int(manifest, "max_output_tokens")
    timeout_seconds = _required_int(manifest, "timeout_seconds")
    planned_attempt_count = len(cases) * len(models) * repetitions
    if planned_attempt_count != _required_int(manifest, "max_requests"):
        raise _error("reviewer evaluation attempt count contradicts the manifest")
    maximum_budget = _required_number(manifest, "max_total_estimated_usd")
    estimated_total_usd = estimate_total_cost(
        cases,
        diffs,
        models,
        repetitions=repetitions,
        max_output_tokens=max_output_tokens,
    )
    if estimated_total_usd > maximum_budget:
        raise _error("reviewer evaluation estimate exceeds the frozen budget")
    key_budget = fetch_key_budget(token, estimated_total_usd)
    immutable_inputs = {
        case.identifier: {"diff_sha256": case.diff_sha256} for case in cases
    }
    controls = {
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout_seconds,
        "max_total_estimated_usd": maximum_budget,
        "estimated_total_usd": estimated_total_usd,
        "max_requests": planned_attempt_count,
    }
    attempts: list[dict[str, object]] = []
    state: dict[str, object] = {
        "schema_version": "1.0",
        "status": "prepared",
        "evaluation_id": manifest["evaluation_id"],
        "manifest_sha256": _canonical_sha256(manifest),
        "artifact_root": str(output_directory),
        "immutable_inputs": immutable_inputs,
        "controls": controls,
        "key_budget": key_budget,
        "authenticated_model_contracts": authenticated_contracts,
        "current_attempt": None,
        "completed_attempts": attempts,
    }
    _create_json(state_path, state)
    for case in cases:
        prompt = build_prompt(diffs[case.identifier])
        for model in models:
            for repetition in range(1, repetitions + 1):
                attempt_identity = {
                    "case_id": case.identifier,
                    "diff_sha256": case.diff_sha256,
                    "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    "requested_model": model.identifier,
                    "repeat": repetition,
                    "max_output_tokens": max_output_tokens,
                    "timeout_seconds": timeout_seconds,
                }
                state.update(
                    {
                        "status": "in_progress",
                        "current_attempt": attempt_identity,
                        "completed_attempts": attempts,
                    }
                )
                _write_json(state_path, state)
                try:
                    result = request_review(
                        prompt,
                        token,
                        model=model.identifier,
                        max_output_tokens=max_output_tokens,
                        timeout_seconds=timeout_seconds,
                    )
                except ReviewError as error:
                    state.update(
                        {
                            "status": "failed",
                            "failure": str(error),
                        }
                    )
                    _write_json(state_path, state)
                    raise _error("reviewer evaluation attempt failed") from error
                review = str(result["review"])
                raw_path = (
                    output_directory
                    / "raw"
                    / case.identifier
                    / _safe_model_name(model.identifier)
                    / f"repeat-{repetition}.json"
                )
                _write_json(raw_path, result)
                expected_terms_found = _matching_terms(review, case.finding_terms)
                attempts.append(
                    {
                        "case_id": case.identifier,
                        "model": model.identifier,
                        "repeat": repetition,
                        "expected_verdict": case.expected_verdict,
                        "verdict": result["verdict"],
                        "provider": result["provider"],
                        "expected_terms_found": expected_terms_found,
                        "review_sha256": hashlib.sha256(
                            review.encode("utf-8")
                        ).hexdigest(),
                        "raw_response_path": str(raw_path),
                        "usage": result["usage"],
                        "elapsed_seconds": result["elapsed_seconds"],
                    }
                )
                state.update(
                    {
                        "current_attempt": None,
                        "completed_attempts": attempts,
                    }
                )
                _write_json(state_path, state)
                total_actual_cost = _total_actual_cost(attempts)
                if total_actual_cost > maximum_budget:
                    state.update(
                        {
                            "status": "failed",
                            "failure": "reviewer evaluation actual cost exceeded budget",
                        }
                    )
                    _write_json(state_path, state)
                    raise _error("reviewer evaluation actual cost exceeded budget")
    _write_json(
        state_path,
        {
            **state,
            "status": "complete",
            "current_attempt": None,
            "completed_attempts": attempts,
        },
    )
    return {"attempts": attempts}


def run_diagnostic_once(
    manifest: Mapping[str, object],
    models: Sequence[ModelContract],
    cases: Sequence[EvaluationCase],
    diffs: Mapping[str, str],
    output_directory: Path,
) -> dict[str, object]:
    """Submit exactly one bounded diagnostic request without a comparison result.

    Parameters
    ----------
    manifest : collections.abc.Mapping[str, object]
        Validated tracked comparison manifest carrying immutable controls.
    models : collections.abc.Sequence[ModelContract]
        Ordered fixed model identities; the Grok control model is first.
    cases : collections.abc.Sequence[EvaluationCase]
        Ordered frozen comparison corpus; the known-defect case is first.
    diffs : collections.abc.Mapping[str, str]
        Reproduced frozen diff text keyed by case identifier.
    output_directory : pathlib.Path
        Distinct ignored artifact root for this diagnostic identity.

    Returns
    -------
    dict[str, object]
        One safe diagnostic attempt, never a comparative evaluation result.

    Raises
    ------
    EvaluationError
        If state, key budget, or response-admission requirements fail. A failed
        diagnostic remains terminal and cannot be resumed.
    """

    output_directory = _validate_output_directory(output_directory)
    state_path = output_directory / "execution-state.json"
    if state_path.exists():
        raise _error("reviewer evaluation has unfinished or completed attempt state")
    token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
    if not token:
        raise _error("independent review credential is unavailable")
    authenticated_contracts = fetch_authenticated_model_contracts(models, token)
    case, model = cases[0], models[0]
    max_output_tokens = _required_int(manifest, "max_output_tokens")
    timeout_seconds = _required_int(manifest, "timeout_seconds")
    prompt = build_prompt(diffs[case.identifier])
    estimate = estimate_total_cost(
        (case,),
        {case.identifier: diffs[case.identifier]},
        (model,),
        repetitions=1,
        max_output_tokens=max_output_tokens,
    )
    maximum_budget = _required_number(manifest, "max_total_estimated_usd")
    if estimate > maximum_budget:
        raise _error("reviewer evaluation estimate exceeds the frozen budget")
    key_budget = fetch_key_budget(token, estimate)
    attempt_identity = {
        "case_id": case.identifier,
        "diff_sha256": case.diff_sha256,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "requested_model": model.identifier,
        "repeat": 1,
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout_seconds,
    }
    state: dict[str, object] = {
        "schema_version": "1.0",
        "status": "in_progress",
        "mode": "diagnostic_once",
        "evaluation_id": manifest["evaluation_id"],
        "manifest_sha256": _canonical_sha256(manifest),
        "artifact_root": str(output_directory),
        "controls": {
            "maximum_requests": 1,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "estimated_total_usd": estimate,
            "max_total_estimated_usd": maximum_budget,
        },
        "key_budget": key_budget,
        "authenticated_model_contracts": authenticated_contracts,
        "current_attempt": attempt_identity,
        "completed_attempts": [],
    }
    _create_json(state_path, state)
    try:
        result = request_review(
            prompt,
            token,
            model=model.identifier,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    except ReviewError as error:
        state.update({"status": "failed", "failure": str(error)})
        _write_json(state_path, state)
        raise _error("reviewer diagnostic attempt failed") from error
    review = str(result["review"])
    raw_path = output_directory / "raw" / "diagnostic-once.json"
    _write_json(raw_path, result)
    attempt = {
        "case_id": case.identifier,
        "model": model.identifier,
        "provider": result["provider"],
        "verdict": result["verdict"],
        "review_sha256": hashlib.sha256(review.encode("utf-8")).hexdigest(),
        "raw_response_path": str(raw_path),
        "usage": result["usage"],
        "elapsed_seconds": result["elapsed_seconds"],
    }
    state.update(
        {
            "status": "complete",
            "current_attempt": None,
            "completed_attempts": [attempt],
        }
    )
    _write_json(state_path, state)
    return {"diagnostic": attempt}


def build_parser() -> argparse.ArgumentParser:
    """Build the bounded reviewer-evaluation command-line interface.

    Returns
    -------
    argparse.ArgumentParser
        Parser requiring explicit execution before any credentialed request.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--key-budget", action="store_true")
    parser.add_argument("--authenticated-model-contract", action="store_true")
    parser.add_argument("--diagnostic-once", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Preflight or execute the tracked reviewer comparison.

    Parameters
    ----------
    arguments : collections.abc.Sequence[str] or None, optional
        Command-line arguments without the executable name.

    Returns
    -------
    int
        Zero for a successful preflight or completed evaluation, two for a safe
        refusal before a credentialed request.
    """

    args = build_parser().parse_args(arguments)
    try:
        if (
            sum(
                (
                    args.key_budget,
                    args.authenticated_model_contract,
                    args.execute,
                    args.diagnostic_once,
                )
            )
            > 1
        ):
            raise _error("reviewer evaluation modes are mutually exclusive")
        if args.key_budget:
            budget_summary = key_budget_summary(args.manifest)
            _write_json(args.output_dir / "key-budget.json", budget_summary)
            print(json.dumps(budget_summary, sort_keys=True))
            return 0
        if args.authenticated_model_contract:
            contract_summary = authenticated_model_contract_summary(args.manifest)
            _write_json(
                args.output_dir / "authenticated-model-contract.json", contract_summary
            )
            print(json.dumps(contract_summary, sort_keys=True))
            return 0
        manifest, models, cases = load_manifest(args.manifest)
        diffs = {case.identifier: collect_historical_diff(case) for case in cases}
        provider_contracts = fetch_provider_contracts(models)
        validate_execution_limits(
            cases,
            diffs,
            provider_contracts,
            max_output_tokens=_required_int(manifest, "max_output_tokens"),
        )
        estimate = estimate_total_cost(
            cases,
            diffs,
            models,
            repetitions=_required_int(manifest, "repetitions"),
            max_output_tokens=_required_int(manifest, "max_output_tokens"),
        )
        if estimate > _required_number(manifest, "max_total_estimated_usd"):
            raise _error("reviewer evaluation estimate exceeds the frozen budget")
        summary: dict[str, object] = {
            "evaluation_id": manifest.get("evaluation_id"),
            "provider_contracts": provider_contracts,
            "frozen_case_count": len(cases),
            "maximum_requests": manifest["max_requests"],
            "estimated_total_usd": estimate,
            "executed": args.execute,
        }
        if args.execute:
            summary.update(
                run_evaluation(manifest, models, cases, diffs, args.output_dir)
            )
        elif args.diagnostic_once:
            summary.update(
                run_diagnostic_once(manifest, models, cases, diffs, args.output_dir)
            )
        _write_json(args.output_dir / "summary.json", summary)
    except (EvaluationError, OSError) as error:
        print(f"reviewer evaluation error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
