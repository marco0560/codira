"""Test bounded, model-identified Phase 6 independent-review evaluation."""

from __future__ import annotations

import importlib.util
import json
import sys
from email.message import Message
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError

import pytest

if TYPE_CHECKING:
    from types import ModuleType
    from urllib.request import Request

    from _pytest.monkeypatch import MonkeyPatch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY_ROOT / "scripts"


def _load_script(module_name: str, filename: str) -> ModuleType:
    """Load one standalone script with sibling imports available.

    Parameters
    ----------
    module_name : str
        Unique temporary import name.
    filename : str
        Script filename beneath the repository scripts directory.

    Returns
    -------
    types.ModuleType
        Loaded script module.
    """

    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def _response(payload: dict[str, object]) -> object:
    """Return a context-managed response with one JSON body.

    Parameters
    ----------
    payload : dict[str, object]
        Fake OpenRouter response object.

    Returns
    -------
    object
        Minimal context manager accepted by ``urlopen`` callers.
    """

    class Response:
        """Expose the fake response body through the urllib context protocol."""

        def __enter__(self) -> Response:
            """Return this fake response."""

            return self

        def __exit__(self, *_arguments: object) -> None:
            """Release no external resource for the fake response."""

        def read(self) -> bytes:
            """Render the configured JSON response."""

            return json.dumps(payload).encode("utf-8")

    return Response()


def _review_payload(model: str, content: str = "VERDICT: PASS\n") -> dict[str, object]:
    """Return one complete model-identified reviewer response.

    Parameters
    ----------
    model : str
        Exact requested OpenRouter model ID.
    content : str, optional
        Reviewer content with the required verdict prefix.

    Returns
    -------
    dict[str, object]
        Complete synthetic Chat Completions response.
    """

    return {
        "model": model,
        "provider": "example-provider",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content},
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
            "cost": 0.01,
        },
    }


def test_request_review_binds_model_budget_and_complete_identity(
    monkeypatch: MonkeyPatch,
) -> None:
    """Send bounded no-fallback requests and retain complete provider evidence.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the network call with a complete model response.

    Returns
    -------
    None
        The request payload and sanitized result are asserted.
    """

    helper = _load_script(
        "phase6_review_request", "run_agent_efficiency_phase6_review.py"
    )
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: int) -> object:
        """Capture a request and return one complete response."""

        body = request.data
        assert isinstance(body, bytes)
        captured["body"] = json.loads(body)
        captured["timeout"] = timeout
        return _response(_review_payload("deepseek/deepseek-v4.1-flash"))

    monkeypatch.setattr(helper, "urlopen", fake_urlopen)
    result = helper.request_review(
        "review this",
        "secret",
        model="deepseek/deepseek-v4.1-flash",
        max_output_tokens=321,
        timeout_seconds=17,
    )
    assert captured == {
        "body": {
            "model": "deepseek/deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "review this"}],
            "temperature": 0,
            "max_tokens": 321,
            "provider": {"allow_fallbacks": False},
        },
        "timeout": 17,
    }
    assert result["requested_model"] == "deepseek/deepseek-v4.1-flash"
    assert result["response_model"] == "deepseek/deepseek-v4.1-flash"
    assert result["provider"] == "example-provider"
    assert result["verdict"] == "PASS"
    assert result["request_settings"]["reasoning_enabled"] is None


def test_request_review_uses_opted_in_router_metadata_for_provider_identity(
    monkeypatch: MonkeyPatch,
) -> None:
    """Accept the documented metadata provider identity when top-level is absent.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the network response with metadata-only provider identity.

    Returns
    -------
    None
        The metadata-derived provider is retained in the safe result.
    """

    helper = _load_script(
        "phase6_review_provider_metadata", "run_agent_efficiency_phase6_review.py"
    )
    payload = _review_payload("expected")
    payload.pop("provider")
    payload["openrouter_metadata"] = {
        "attempts": [{"provider": "Example", "status": 200}]
    }
    monkeypatch.setattr(
        helper, "urlopen", lambda *_arguments, **_kwargs: _response(payload)
    )
    result = helper.request_review("review", "secret", model="expected")
    assert result["provider"] == "Example"


def test_request_review_retains_only_http_status_for_transport_diagnostics(
    monkeypatch: MonkeyPatch,
) -> None:
    """Expose a safe HTTP category without retaining the provider error body.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the network request with one HTTP status failure.

    Returns
    -------
    None
        The raised error contains only the stable HTTP status.
    """

    helper = _load_script(
        "phase6_review_http_status", "run_agent_efficiency_phase6_review.py"
    )

    def fail_request(*_arguments: object, **_kwargs: object) -> object:
        """Raise one HTTP error with an intentionally unexposed message body."""

        url, message = "https://example.invalid", "private"
        raise HTTPError(url, 400, message, Message(), None)

    monkeypatch.setattr(helper, "urlopen", fail_request)
    with pytest.raises(helper.ReviewError, match="HTTP 400"):
        helper.request_review("review", "secret", model="expected")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_review_payload("other-model"), "model identity"),
        ({**_review_payload("expected"), "provider": None}, "provider identity"),
        (_review_payload("expected", "unstructured response"), "verdict"),
        (_review_payload("expected", "VERDICT: PASS but uncertain"), "verdict"),
        (
            {
                **_review_payload("expected"),
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            "usage is incomplete",
        ),
        (
            {
                **_review_payload("expected"),
                "choices": [
                    {"finish_reason": "length", "message": {"content": "VERDICT: PASS"}}
                ],
            },
            "incomplete",
        ),
    ],
)
def test_request_review_rejects_unverified_or_incomplete_output(
    monkeypatch: MonkeyPatch, payload: dict[str, object], message: str
) -> None:
    """Fail closed when a response cannot prove a complete valid verdict.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the network call with malformed response variants.
    payload : dict[str, object]
        Synthetic malformed provider response.
    message : str
        Required stable error fragment.

    Returns
    -------
    None
        Each malformed response raises the review error.
    """

    helper = _load_script(
        "phase6_review_rejections", "run_agent_efficiency_phase6_review.py"
    )
    monkeypatch.setattr(
        helper, "urlopen", lambda *_arguments, **_kwargs: _response(payload)
    )
    with pytest.raises(helper.ReviewError, match=message):
        helper.request_review("review", "secret", model="expected")


def test_request_review_preserves_invalid_response_body_for_ignored_evidence(
    monkeypatch: MonkeyPatch,
) -> None:
    """Keep a received malformed verdict available to the artifact writer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the network call with a response that violates the verdict contract.

    Returns
    -------
    None
        The received provider body remains available to the artifact writer.
    """

    helper = _load_script(
        "phase6_review_evidence", "run_agent_efficiency_phase6_review.py"
    )
    payload = _review_payload("expected", "I found a defect.")
    monkeypatch.setattr(
        helper, "urlopen", lambda *_arguments, **_kwargs: _response(payload)
    )
    with pytest.raises(helper.ReviewError, match="verdict") as captured:
        helper.request_review("review", "secret", model="expected")
    assert captured.value.response_body == json.dumps(payload)


def test_evaluation_requires_an_explicit_execution_flag() -> None:
    """Reject evaluation selection unless the operator explicitly authorizes it.

    Parameters
    ----------
    None
        The test supplies only fixed command-line arguments.

    Returns
    -------
    None
        The SOPS-approved wrapper refuses before importing the evaluator.
    """

    helper = _load_script(
        "phase6_review_execution_flag", "run_agent_efficiency_phase6_review.py"
    )
    assert helper.main(["--evaluation-manifest", "fixture.json"]) == 2


def test_evaluation_manifest_reproduces_all_six_frozen_diffs() -> None:
    """Keep every tracked historical comparison input content-addressed.

    Parameters
    ----------
    None
        The test reads the fixed tracked manifest.

    Returns
    -------
    None
        Six immutable diffs are reproduced from their recorded revisions.
    """

    helper = _load_script(
        "phase6_reviewer_manifest", "run_agent_efficiency_phase6_reviewer_evaluation.py"
    )
    _, models, cases = helper.load_manifest(
        REPOSITORY_ROOT
        / "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
    )
    assert [model.identifier for model in models] == [
        "x-ai/grok-build-0.1",
        "deepseek/deepseek-v4.1-flash",
    ]
    assert len(cases) == 6
    assert all(helper.collect_historical_diff(case) for case in cases)


def test_provider_contract_rejects_price_drift_and_requires_output_control(
    monkeypatch: MonkeyPatch,
) -> None:
    """Reject a catalog whose price or request controls exceed the manifest.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies controlled public catalog responses.

    Returns
    -------
    None
        A price increase and absent output control both fail before requests.
    """

    helper = _load_script(
        "phase6_reviewer_contract", "run_agent_efficiency_phase6_reviewer_evaluation.py"
    )
    models = (
        helper.ModelContract("first", 1.0, 1.0),
        helper.ModelContract("second", 1.0, 1.0),
    )

    def catalog(parameters: list[str], prompt: str = "0.000001") -> dict[str, object]:
        """Build a public model catalog for both selected model IDs."""

        return {
            "data": [
                {
                    "id": identifier,
                    "pricing": {"prompt": prompt, "completion": "0.000001"},
                    "supported_parameters": parameters,
                    "top_provider": {"max_completion_tokens": 100},
                    "context_length": 1000,
                }
                for identifier in ("first", "second")
            ]
        }

    monkeypatch.setattr(
        helper, "urlopen", lambda *_args, **_kwargs: _response(catalog([]))
    )
    with pytest.raises(helper.EvaluationError, match="contract is incomplete"):
        helper.fetch_provider_contracts(models)
    monkeypatch.setattr(
        helper,
        "urlopen",
        lambda *_args, **_kwargs: _response(
            catalog(["max_tokens", "reasoning"], prompt="0.000002")
        ),
    )
    with pytest.raises(helper.EvaluationError, match="price exceeds"):
        helper.fetch_provider_contracts(models)


def test_authenticated_model_contract_rejects_key_filtered_model(
    monkeypatch: MonkeyPatch,
) -> None:
    """Require both exact models in the scoped key's filtered catalog.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies a key-specific catalog without the second selected model.

    Returns
    -------
    None
        A missing key-visible model fails before any completion request.
    """

    helper = _load_script(
        "phase6_reviewer_authenticated_contract",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    models = (
        helper.ModelContract("first", 1.0, 1.0),
        helper.ModelContract("second", 1.0, 1.0),
    )
    monkeypatch.setattr(
        helper,
        "urlopen",
        lambda *_args, **_kwargs: _response(
            {
                "data": [
                    {
                        "id": "first",
                        "supported_parameters": ["max_tokens", "reasoning"],
                        "reasoning": {"mandatory": False, "default_enabled": False},
                    }
                ]
            }
        ),
    )
    with pytest.raises(helper.EvaluationError, match="cannot access"):
        helper.fetch_authenticated_model_contracts(models, "secret")


def test_execution_limits_reject_provider_context_overflow() -> None:
    """Reject a frozen request whose output cap exceeds a public model limit.

    Parameters
    ----------
    None
        The test constructs a fixed minimal model contract.

    Returns
    -------
    None
        The contract boundary raises before credentials or requests are used.
    """

    helper = _load_script(
        "phase6_reviewer_limits", "run_agent_efficiency_phase6_reviewer_evaluation.py"
    )
    case = helper.EvaluationCase(
        "case",
        "0" * 40,
        "1" * 40,
        ("scripts/example.py",),
        "PASS",
        (),
        "2" * 64,
    )
    with pytest.raises(helper.EvaluationError, match="output limit exceeds"):
        helper.validate_execution_limits(
            (case,),
            {"case": "diff"},
            {
                "model": {
                    "context_length": 100,
                    "max_completion_tokens": 10,
                }
            },
            max_output_tokens=11,
        )


def test_key_budget_requires_the_complete_conservative_trial_amount(
    monkeypatch: MonkeyPatch,
) -> None:
    """Reject a scoped key that cannot fund the frozen whole-trial estimate.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces the key-metadata request with deterministic safe fields.

    Returns
    -------
    None
        The admitted metadata is sanitized and an insufficient limit is refused.
    """

    helper = _load_script(
        "phase6_reviewer_key_budget",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    monkeypatch.setattr(
        helper,
        "urlopen",
        lambda *_args, **_kwargs: _response(
            {
                "data": {
                    "label": "private-label-not-retained",
                    "limit": 2.0,
                    "limit_remaining": 1.7,
                    "limit_reset": "daily",
                    "usage_daily": 0.3,
                }
            }
        ),
    )
    assert helper.fetch_key_budget("secret", 1.6) == {
        "limit_usd": 2.0,
        "limit_remaining_usd": 1.7,
        "limit_reset": "daily",
        "usage_daily_usd": 0.3,
    }
    with pytest.raises(helper.EvaluationError, match="key budget is insufficient"):
        helper.fetch_key_budget("secret", 1.8)


def test_atomic_state_creation_rejects_a_concurrent_claim(tmp_path: Path) -> None:
    """Prevent a second evaluator process from replacing the run state.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated state-file parent directory.

    Returns
    -------
    None
        The original immutable claim is preserved.
    """

    helper = _load_script(
        "phase6_reviewer_atomic_state",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    state_path = tmp_path / "execution-state.json"
    helper._create_json(state_path, {"status": "prepared"})
    with pytest.raises(helper.EvaluationError, match="attempt state"):
        helper._create_json(state_path, {"status": "other"})
    assert json.loads(state_path.read_text()) == {"status": "prepared"}


def test_run_evaluation_writes_raw_responses_only_under_ignored_output(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Execute exactly 24 model-identified attempts with ignored raw evidence.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies a credential and deterministic review results.
    tmp_path : pathlib.Path
        Ignored-artifact stand-in used for test output.

    Returns
    -------
    None
        Every bounded attempt is recorded beneath the configured output root.
    """

    helper = _load_script(
        "phase6_reviewer_execution",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    manifest, models, cases = helper.load_manifest(
        REPOSITORY_ROOT
        / "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
    )
    diffs = {case.identifier: "diff" for case in cases}
    monkeypatch.setenv(helper.TOKEN_ENVIRONMENT_KEY, "secret")
    monkeypatch.setattr(
        helper,
        "fetch_key_budget",
        lambda _token, _estimate: {
            "limit_usd": 2.0,
            "limit_remaining_usd": 2.0,
            "limit_reset": "daily",
            "usage_daily_usd": 0.0,
        },
    )
    monkeypatch.setattr(
        helper,
        "fetch_authenticated_model_contracts",
        lambda _models, _token: {"x-ai/grok-build-0.1": {"reasoning": {}}},
    )
    monkeypatch.setattr(
        helper,
        "request_review",
        lambda _prompt, _token, **kwargs: {
            "review": "VERDICT: PASS\n",
            "verdict": "PASS",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
                "cost": 0.01,
            },
            "elapsed_seconds": 0.2,
            "requested_model": kwargs["model"],
            "response_model": kwargs["model"],
            "provider": "example-provider",
        },
    )
    artifact_root = tmp_path / ".artifacts/agent-efficiency/reviewer-evaluation"
    monkeypatch.setattr(helper, "ARTIFACT_OUTPUT_ROOT", artifact_root)
    summary = helper.run_evaluation(
        manifest,
        models,
        cases,
        diffs,
        artifact_root,
    )
    attempts = summary["attempts"]
    assert isinstance(attempts, list)
    assert len(attempts) == 24
    assert all(Path(item["raw_response_path"]).is_file() for item in attempts)
    state = json.loads((artifact_root / "execution-state.json").read_text())
    assert state["status"] == "complete"
    assert state["controls"]["max_requests"] == 24
    assert state["immutable_inputs"] == {
        case.identifier: {"diff_sha256": case.diff_sha256} for case in cases
    }
    assert len(state["completed_attempts"]) == 24
    assert state["key_budget"]["limit_remaining_usd"] == 2.0


def test_run_evaluation_rejects_existing_attempt_state(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Fail closed before a retry can duplicate an unknown provider request.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies the scoped credential marker without calling a provider.
    tmp_path : pathlib.Path
        Artifact root already containing incomplete attempt state.

    Returns
    -------
    None
        Existing state rejects the requested evaluation before network activity.
    """

    helper = _load_script(
        "phase6_reviewer_resume", "run_agent_efficiency_phase6_reviewer_evaluation.py"
    )
    manifest, models, cases = helper.load_manifest(
        REPOSITORY_ROOT
        / "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
    )
    artifact_root = tmp_path / ".artifacts/agent-efficiency/reviewer-evaluation"
    artifact_root.mkdir(parents=True)
    monkeypatch.setattr(helper, "ARTIFACT_OUTPUT_ROOT", artifact_root)
    (artifact_root / "execution-state.json").write_text('{"status":"in_progress"}\n')
    monkeypatch.setenv(helper.TOKEN_ENVIRONMENT_KEY, "secret")
    with pytest.raises(helper.EvaluationError, match="unfinished"):
        helper.run_evaluation(
            manifest,
            models,
            cases,
            {case.identifier: "diff" for case in cases},
            artifact_root,
        )


def test_run_evaluation_persists_the_safe_provider_failure_reason(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Retain the safe admission failure without a review body or credential.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Supplies a scoped credential marker and deterministic review failure.
    tmp_path : pathlib.Path
        Isolated ignored-artifact stand-in.

    Returns
    -------
    None
        The terminal state identifies the safe failure category for diagnosis.
    """

    helper = _load_script(
        "phase6_reviewer_failure_reason",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    manifest, models, cases = helper.load_manifest(
        REPOSITORY_ROOT
        / "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
    )
    artifact_root = tmp_path / ".artifacts/agent-efficiency/reviewer-evaluation"
    monkeypatch.setattr(helper, "ARTIFACT_OUTPUT_ROOT", artifact_root)
    monkeypatch.setenv(helper.TOKEN_ENVIRONMENT_KEY, "secret")
    monkeypatch.setattr(
        helper,
        "fetch_key_budget",
        lambda _token, _estimate: {
            "limit_usd": 2.0,
            "limit_remaining_usd": 2.0,
            "limit_reset": "daily",
            "usage_daily_usd": 0.0,
        },
    )
    monkeypatch.setattr(
        helper,
        "fetch_authenticated_model_contracts",
        lambda _models, _token: {"x-ai/grok-build-0.1": {"reasoning": {}}},
    )

    failure = "independent review model identity is unverified"
    response_body = '{"model":"wrong"}'

    def fail_review(*_arguments: object, **_kwargs: object) -> dict[str, object]:
        """Raise the stable admission failure used by this regression test."""

        raise helper.ReviewError(failure, response_body=response_body)

    monkeypatch.setattr(helper, "request_review", fail_review)
    with pytest.raises(helper.EvaluationError, match="attempt failed"):
        helper.run_evaluation(
            manifest,
            models,
            cases,
            {case.identifier: "diff" for case in cases},
            artifact_root,
        )
    state = json.loads((artifact_root / "execution-state.json").read_text())
    assert state["status"] == "failed"
    assert state["failure"] == failure
    failed_attempt = state["failed_attempt"]
    evidence_path = Path(failed_attempt["raw_response_path"])
    assert json.loads(evidence_path.read_text()) == {
        "response_body": response_body,
        "validation_error": failure,
    }
    assert (
        failed_attempt["raw_response_sha256"]
        == helper.hashlib.sha256(response_body.encode("utf-8")).hexdigest()
    )


def test_diagnostic_once_submits_only_the_first_grok_control_request(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Keep the authorized transport diagnostic to exactly one request.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces credential, budget, and reviewer boundaries.
    tmp_path : pathlib.Path
        Isolated ignored-artifact stand-in.

    Returns
    -------
    None
        The single selected case, model, and terminal-state limit are asserted.
    """

    helper = _load_script(
        "phase6_reviewer_diagnostic",
        "run_agent_efficiency_phase6_reviewer_evaluation.py",
    )
    manifest, models, cases = helper.load_manifest(
        REPOSITORY_ROOT
        / "benchmarks/agent-efficiency/reviewer-evaluation/phase6-deepseek-v4-1-flash.json"
    )
    artifact_root = tmp_path / ".artifacts/agent-efficiency/reviewer-evaluation"
    monkeypatch.setattr(helper, "ARTIFACT_OUTPUT_ROOT", artifact_root)
    monkeypatch.setenv(helper.TOKEN_ENVIRONMENT_KEY, "secret")
    monkeypatch.setattr(
        helper,
        "fetch_key_budget",
        lambda _token, _estimate: {
            "limit_usd": 2.0,
            "limit_remaining_usd": 2.0,
            "limit_reset": "daily",
            "usage_daily_usd": 0.0,
        },
    )
    monkeypatch.setattr(
        helper,
        "fetch_authenticated_model_contracts",
        lambda _models, _token: {"x-ai/grok-build-0.1": {"reasoning": {}}},
    )
    calls: list[dict[str, object]] = []

    def review_once(_prompt: str, _token: str, **kwargs: object) -> dict[str, object]:
        """Record the only admitted reviewer request."""

        calls.append(kwargs)
        return {
            "review": "VERDICT: NEEDS_FIXES\n",
            "verdict": "NEEDS_FIXES",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
                "cost": 0.01,
            },
            "elapsed_seconds": 0.2,
            "provider": "example-provider",
        }

    monkeypatch.setattr(helper, "request_review", review_once)
    summary = helper.run_diagnostic_once(
        manifest,
        models,
        cases,
        {case.identifier: "diff" for case in cases},
        artifact_root,
    )
    assert len(calls) == 1
    assert calls[0]["model"] == "x-ai/grok-build-0.1"
    assert summary["diagnostic"]["case_id"] == "baseline-mcp-defect"
    state = json.loads((artifact_root / "execution-state.json").read_text())
    assert state["mode"] == "diagnostic_once"
    assert state["controls"]["maximum_requests"] == 1
    assert len(state["completed_attempts"]) == 1
