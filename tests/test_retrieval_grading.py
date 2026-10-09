"""Offline contracts for blinded, budgeted and resumable retrieval grading.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest
from test_known_target_quality import fake_codira, fixture_controls

from scripts import (
    grade_retrieval_quality as grader,
    retrieval_grading as grading,
    run_known_target_quality as runner,
)
from scripts.known_target_quality import canonical_json, digest_bytes


def completed_comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Execute a synthetic protocol fixture, not a model-quality evaluation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Substituted host executable.

    Returns
    -------
    pathlib.Path
        Completed five-case comparison directory.
    """
    manifest, cases, models = fixture_controls(tmp_path)
    monkeypatch.setattr(runner, "resolve_codira", lambda: str(fake_codira(tmp_path)))
    output = tmp_path / "comparison"
    assert (
        runner.main(
            [
                "--dataset",
                str(cases),
                "--repo-manifest",
                str(manifest),
                "--model-manifest",
                str(models),
                "--output",
                str(output),
                "--quiet-progress",
            ]
        )
        == 0
    )
    return output


def prepared_grader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Prepare explicitly admitted synthetic inputs without network activity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Protocol executable replacement.

    Returns
    -------
    pathlib.Path
        Prepared grader identity.
    """
    source = completed_comparison(tmp_path, monkeypatch)
    output = tmp_path / "grading"
    grader.prepare(
        argparse.Namespace(
            run=source,
            output=output,
            judge_model="fixture/judge",
            budget_usd="1",
            max_output_tokens=4096,
            snippet_chars=1600,
            timeout=10.0,
            case_limit=None,
            include_private=True,
        )
    )
    return output


def catalog() -> bytes:
    """Return a mocked authenticated model contract with mandatory reasoning.

    Parameters
    ----------
    None

    Returns
    -------
    bytes
        Credential-free fixture catalog.
    """
    return canonical_json(
        {
            "data": [
                {
                    "id": "fixture/judge",
                    "canonical_slug": "fixture/judge",
                    "supported_parameters": ["structured_outputs", "max_tokens"],
                    "architecture": {"input_modalities": ["text"]},
                    "context_length": 128000,
                    "top_provider": {"max_completion_tokens": 8192},
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000002",
                        "request": "0",
                    },
                    "reasoning": {"required": True},
                }
            ]
        }
    ).encode()


def response(job: grading.Job, *, finish: str = "stop", cost: object = 0.001) -> bytes:
    """Build a mocked terminal judge response with explicit token accounting.

    Parameters
    ----------
    job : scripts.retrieval_grading.Job
        Expected candidates.
    finish : str, optional
        Terminal completion reason.
    cost : object, optional
        Deliberately configurable accounting boundary.

    Returns
    -------
    bytes
        Exact mocked provider payload.
    """
    return canonical_json(
        {
            "id": "fixture-generation",
            "model": "fixture/judge",
            "provider": "fixture",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 100,
                "total_tokens": 200,
                "cost": cost,
            },
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {
                        "content": canonical_json(
                            {
                                "grades": {
                                    candidate["id"]: {
                                        "score": 2,
                                        "reason": "Fixture judgment.",
                                    }
                                    for candidate in job["candidates"]
                                }
                            }
                        ),
                    },
                }
            ],
        }
    ).encode()


def test_preparation_blinds_models_and_excludes_unattested_private_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep consent explicit and send only the deduplicated shuffled pool.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Protocol substitution.

    Returns
    -------
    None
    """
    source = completed_comparison(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="private sources"):
        grading.prepare_jobs(
            source, include_private=False, case_limit=None, snippet_chars=1600
        )
    jobs, _fingerprints = grading.prepare_jobs(
        source,
        include_private=True,
        case_limit=3,
        snippet_chars=1600,
    )
    assert len(jobs) == 3
    body = grading.request_body(jobs[0], "fixture/judge", 4096)
    visible = canonical_json(body)
    assert (
        "demo-model" not in visible
        and "rankings" not in visible
        and "targets" not in visible
    )
    assert "reasoning" not in body
    assert len(jobs[0]["candidates"]) == 1
    second, _ = grading.prepare_jobs(
        source, include_private=True, case_limit=3, snippet_chars=1600
    )
    assert jobs == second


def test_prepare_refuses_a_live_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid reading an actively measured retrieval run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Protocol substitution.

    Returns
    -------
    None
    """
    source = completed_comparison(tmp_path, monkeypatch)
    with runner.campaign_lock(source), pytest.raises(BlockingIOError):
        grading.prepare_jobs(
            source, include_private=True, case_limit=None, snippet_chars=1600
        )


@pytest.mark.parametrize(
    "malformation", ["duplicate", "missing", "unknown", "boolean", "range", "reason"]
)
def test_grade_contract_rejects_malformed_judgments(malformation: str) -> None:
    """Reject incomplete or ambiguous grades instead of converting them to scores.

    Parameters
    ----------
    malformation : str
        Output-contract fault.

    Returns
    -------
    None
    """
    job: grading.Job = {
        "case_id": "case",
        "repo": "demo",
        "intent": "symbol_lookup",
        "query": "demo",
        "rankings": {"a": ["one"]},
        "candidates": [
            {
                "id": "one",
                "path": "a.py",
                "line": 1,
                "kind": "symbol",
                "snippet": "def demo(): pass",
                "source_sha256": "a" * 64,
                "truncated": False,
            }
        ],
    }
    row: dict[str, object] = {"id": "one", "score": 2, "reason": "Definition."}
    rows = [row]
    if malformation == "duplicate":
        rows.append(dict(row))
    elif malformation == "missing":
        rows = []
    elif malformation == "unknown":
        row["id"] = "unknown"
    elif malformation == "boolean":
        row["score"] = True
    elif malformation == "range":
        row["score"] = 3
    else:
        row["reason"] = ""
    with pytest.raises(ValueError):
        grading.validate_grades({"grades": rows}, job)


def test_resume_and_rescore_reuse_raw_judgments_without_paid_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise preparation, authenticated contract mocks and provider replay.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked network boundary.

    Returns
    -------
    None
        Mock responses validate mechanics, not actual semantic grading.
    """
    output = prepared_grader(tmp_path, monkeypatch)
    plan = grader.read_plan(output)
    jobs = grader.load_jobs(output, plan)
    calls: list[dict[str, object]] = []

    def transport(
        endpoint: str,
        key: str,
        body: dict[str, object] | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        """Return retained fixture responses at the actual transport boundary.

        Parameters
        ----------
        endpoint : str
            Requested API path.
        key : str
            Synthetic credential.
        body : dict[str, object] | None
            Payload without authorization.
        timeout : float
            Frozen timeout.

        Returns
        -------
        tuple[int, bytes]
            HTTP status and mocked response bytes.
        """
        assert key == "fixture-key" and timeout == 10.0
        if endpoint == "/models/user":
            return 200, catalog()
        assert body is not None
        assert json.loads(canonical_json(body))["provider"]["allow_fallbacks"] is False
        calls.append(body)
        return 200, response(jobs[len(calls) - 1])

    monkeypatch.setattr(grader, "provider_call", transport)
    grader.preflight(output, "fixture-key")
    assert calls == []
    assert grader.execute(output, "fixture-key", resume=False) == 0
    assert len(calls) == 5
    first = (output / "grading-summary.json").read_bytes()
    assert grader.execute(output, "fixture-key", resume=True) == 0
    assert len(calls) == 5
    with monkeypatch.context() as replay:
        replay.setattr(
            grader,
            "bounded_request",
            lambda *_args: pytest.fail(
                "Offline replay rebuilt an old request using current code"
            ),
        )
        assert grader.report(output) == 0
    assert first == (output / "grading-summary.json").read_bytes()
    assert json.loads(first)["observed_cost_usd"] == "0.005"
    assert "fixture-key" not in "".join(
        p.read_text() for p in output.rglob("*") if p.is_file()
    )
    raw = next(output.glob("attempts/*/response.body"))
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="evidence changed"):
        grader.report(output)


def test_failed_paid_attempt_retains_response_and_blocks_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep malformed provider content and refuse another completion on resume.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked network boundary.

    Returns
    -------
    None
    """
    output = prepared_grader(tmp_path, monkeypatch)
    calls = []

    def transport(
        endpoint: str,
        key: str,
        body: dict[str, object] | None,
        timeout: float,
    ) -> tuple[int, bytes]:
        """Return an invalid exact response while recording completion attempts.

        Parameters
        ----------
        endpoint : str
            API path.
        key : str
            Synthetic credential.
        body : dict[str, object] | None
            Request body.
        timeout : float
            Timeout.

        Returns
        -------
        tuple[int, bytes]
            Mocked catalog or malformed completion.
        """
        del key, timeout
        if endpoint == "/models/user":
            return 200, catalog()
        calls.append(body)
        return 200, b"invalid provider payload"

    monkeypatch.setattr(grader, "provider_call", transport)
    grader.preflight(output, "fixture-key")
    assert grader.execute(output, "fixture-key", resume=False) == 1
    raw = next(output.glob("attempts/*/response.body"))
    assert raw.read_bytes() == b"invalid provider payload"
    assert (
        grading.read_object(output / "grading-summary.json")["unknown_cost_attempts"]
        == 1
    )
    with pytest.raises(ValueError, match="Unresolved paid attempt"):
        grader.execute(output, "fixture-key", resume=True)
    assert len(calls) == 1


def test_explicit_recovery_reuses_grades_and_counts_failed_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover only missing queries, keeping original evidence and total spending.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated synthetic evidence workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked provider boundary.

    Returns
    -------
    None
    """
    source = prepared_grader(tmp_path, monkeypatch)
    jobs = grader.load_jobs(source, grader.read_plan(source))
    calls: list[dict[str, object]] = []

    def transport(
        endpoint: str, key: str, body: dict[str, object] | None, timeout: float
    ) -> tuple[int, bytes]:
        """Fail the third query with a billed empty explanation.

        Parameters
        ----------
        endpoint : str
            Mocked API path.
        key : str
            Synthetic credential.
        body : dict[str, object] | None
            Grading request.
        timeout : float
            Frozen timeout.

        Returns
        -------
        tuple[int, bytes]
            Synthetic exact provider response.
        """
        del key, timeout
        if endpoint == "/models/user":
            return 200, catalog()
        assert body is not None
        calls.append(body)
        value = json.loads(response(jobs[len(calls) - 1]))
        if len(calls) == 3:
            content = json.loads(value["choices"][0]["message"]["content"])
            for grade in content["grades"].values():
                grade["reason"] = ""
            value["choices"][0]["message"]["content"] = canonical_json(content)
        return 200, canonical_json(value).encode()

    monkeypatch.setattr(grader, "provider_call", transport)
    grader.preflight(source, "fixture-key")
    assert grader.execute(source, "fixture-key", resume=False) == 1
    before = {
        str(p.relative_to(source)): p.read_bytes()
        for p in source.rglob("*")
        if p.is_file()
    }
    output = tmp_path / "continuation"
    grader.recover(source, output)
    assert len(calls) == 3  # Offline preparation makes no provider request.
    assert before == {
        str(p.relative_to(source)): p.read_bytes()
        for p in source.rglob("*")
        if p.is_file()
    }
    plan = grader.read_plan(output)
    assert grader.recovery_cost(output, plan) == Decimal("0.001")
    assert len(list((output / "attempts").iterdir())) == 2
    assert not (output / "preflight.json").exists()
    expected = Decimal("0.003") + sum(
        (
            grader.bounded_request(
                job, plan, grader.model_contract(catalog(), "fixture/judge")
            )[1]
            for job in jobs[2:]
        ),
        Decimal(0),
    )
    grader.preflight(output, "fixture-key")
    assert (
        Decimal(str(grader.read_preflight(output)["full_run_reservation_usd"]))
        == expected
    )
    calls.clear()

    def remaining(
        endpoint: str, key: str, body: dict[str, object] | None, timeout: float
    ) -> tuple[int, bytes]:
        """Return fresh grades for the three pending pools only.

        Parameters
        ----------
        endpoint : str
            Mocked API path.
        key : str
            Synthetic credential.
        body : dict[str, object] | None
            Query payload.
        timeout : float
            Frozen timeout.

        Returns
        -------
        tuple[int, bytes]
            Mocked catalog or valid judgment.
        """
        del key, timeout
        if endpoint == "/models/user":
            return 200, catalog()
        assert body is not None
        calls.append(body)
        return 200, response(jobs[1 + len(calls)])

    monkeypatch.setattr(grader, "provider_call", remaining)
    assert grader.execute(output, "fixture-key", resume=True) == 0
    assert len(calls) == 3
    summary = grading.read_object(output / "grading-summary.json")
    assert summary["graded_queries"] == 5
    assert summary["observed_cost_usd"] == "0.006"
    assert summary["carried_failed_cost_usd"] == "0.001"
    assert grader.execute(output, "fixture-key", resume=True) == 0
    assert len(calls) == 3
    chained = tmp_path / "second-continuation"
    grader.recover(output, chained)
    grader.preflight(chained, "fixture-key")
    assert grader.report(chained) == 0
    assert (
        grading.read_object(chained / "grading-summary.json")["observed_cost_usd"]
        == "0.006"
    )
    raw = next((output / "prior-attempts").glob("*/response.body"))
    raw.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Recovery evidence changed"):
        grader.read_plan(output)


def test_recovery_refuses_ambiguous_paid_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not make a fresh identity hide missing response or billing evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated mocked workspace.
    monkeypatch : pytest.MonkeyPatch
        Synthetic catalog transport.

    Returns
    -------
    None
    """
    source = prepared_grader(tmp_path, monkeypatch)
    monkeypatch.setattr(
        grader,
        "authenticated_contract",
        lambda *_args: grader.model_contract(catalog(), "fixture/judge"),
    )
    grader.preflight(source, "fixture-key")
    plan = grader.read_plan(source)
    job = grader.load_jobs(source, plan)[0]
    request, _, _ = grader.bounded_request(
        job, plan, grader.model_contract(catalog(), "fixture/judge")
    )
    attempt = source / "attempts" / job["case_id"]
    attempt.mkdir(parents=True)
    runner.write_json(attempt / "request.json", request)
    runner.write_json(
        attempt / "state.json",
        {
            "status": "in_progress",
            "request_sha256": digest_bytes(canonical_json(request).encode()),
        },
    )
    with pytest.raises(ValueError, match="ambiguous paid attempt"):
        grader.recover(source, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_budget_and_terminal_contract_fail_closed() -> None:
    """Require finite prices, sufficient limits and terminal usage.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    for value in ("NaN", "Infinity", "-1", None, True):
        with pytest.raises(ValueError):
            grader.decimal_value(value)
    contract = grader.model_contract(catalog(), "fixture/judge")
    job: grading.Job = {
        "case_id": "case",
        "repo": "demo",
        "intent": "symbol_lookup",
        "query": "demo",
        "candidates": [],
        "rankings": {"a": []},
    }
    with pytest.raises(ValueError, match="finish normally"):
        grader.validated_response(response(job, finish="length"), job, contract)
    with pytest.raises(ValueError):
        grader.validated_response(response(job, cost=None), job, contract)
    plan: dict[str, object] = {
        "judge_model": "fixture/judge",
        "max_output_tokens": 4096,
    }
    _, reservation, allowance = grader.bounded_request(job, plan, contract)
    assert reservation > Decimal(0) and allowance > 4096
    contract["context_length"] = 100
    with pytest.raises(ValueError, match="exceeds judge limits"):
        grader.bounded_request(job, plan, contract)


def test_pooled_ndcg_preserves_rank_and_uncertainty_denominators() -> None:
    """Use a common ideal and keep missing judgments in planned denominators.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    job: grading.Job = {
        "case_id": "case",
        "repo": "demo",
        "intent": "symbol_lookup",
        "query": "demo",
        "candidates": [],
        "rankings": {"a": ["good", "bad"], "b": ["bad", "good"]},
    }
    grades = {"good": 2, "bad": -1}
    scores = grading.score_job(job, grades, 5)
    assert scores["a"]["pool_ndcg"] == 1.0
    assert scores["b"]["pool_ndcg"] < 1.0
    assert scores["a"]["judged_precision_lower_bound"] == 0.2
    assert scores["a"]["uncertain_or_ungraded"] == 1.0
    scores = grading.score_job(job, {}, 5)
    assert scores["a"]["pool_ndcg"] == 0
    assert scores["a"]["judged_precision_lower_bound"] == 0


def test_empty_pools_complete_without_completions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint empty rankings locally and retain zero-score denominators.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked prepared inputs and transport.

    Returns
    -------
    None
    """
    output = prepared_grader(tmp_path, monkeypatch)
    jobs = grader.load_jobs(output, grader.read_plan(output))
    for job in jobs:
        job["candidates"] = []
        job["rankings"] = {model: [] for model in job["rankings"]}
    monkeypatch.setattr(grader, "load_jobs", lambda _root, _plan: jobs)
    monkeypatch.setattr(
        grader,
        "provider_call",
        lambda endpoint, *_args: (
            (200, catalog())
            if endpoint == "/models/user"
            else pytest.fail("Empty pool made a paid call")
        ),
    )
    grader.preflight(output, "fixture-key")
    assert grader.execute(output, "fixture-key", resume=False) == 0
    assert grader.execute(output, "fixture-key", resume=True) == 0
    summary = grading.read_object(output / "grading-summary.json")
    assert summary["graded_queries"] == 5
    assert summary["observed_cost_usd"] == "0"
    assert not list(output.glob("attempts/*/response.body"))


def test_preflight_budget_and_receipt_tampering_stop_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject unaffordable controls and altered authenticated evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked authenticated lookup.

    Returns
    -------
    None
    """
    output = prepared_grader(tmp_path, monkeypatch)
    monkeypatch.setattr(grader, "provider_call", lambda *_args: (200, catalog()))
    plan = grader.read_plan(output)
    monkeypatch.setattr(
        grader,
        "read_plan",
        lambda *_args, **_kwargs: {**plan, "budget_usd": "0.0000001"},
    )
    with pytest.raises(ValueError, match="reservation exceeds"):
        grader.preflight(output, "fixture-key")
    assert not (output / "preflight.json").exists()
    monkeypatch.setattr(grader, "read_plan", lambda *_args, **_kwargs: plan)
    grader.preflight(output, "fixture-key")
    (output / "preflight.json").write_text("{}")
    with pytest.raises(ValueError, match="receipt changed"):
        grader.report(output)
    with pytest.raises(ValueError, match="receipt changed"):
        grader.execute(output, "fixture-key", resume=False)


def test_catalog_optional_request_price_and_conditional_rates() -> None:
    """Accept omitted fixed fees and reserve the highest published tier.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    body = json.loads(catalog())
    pricing = body["data"][0]["pricing"]
    del pricing["request"]
    pricing["overrides"] = [
        {"min_prompt_tokens": 100000, "prompt": "0.000005", "completion": "0.00001"}
    ]
    contract = grader.model_contract(canonical_json(body).encode(), "fixture/judge")
    assert contract["pricing"] == {
        "prompt": "0.000005",
        "completion": "0.00001",
        "request": "0",
    }
    pricing["overrides"] = [{"prompt": "NaN"}]
    with pytest.raises(ValueError, match="Non-finite"):
        grader.model_contract(canonical_json(body).encode(), "fixture/judge")


def test_empty_explanation_stops_with_diagnostic_and_retained_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reproduce a normal completion with one invalid blank explanation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked network boundary.
    capsys : pytest.CaptureFixture[str]
        Captured terminal diagnostics.

    Returns
    -------
    None
        Validates failure mechanics, not judge accuracy.
    """
    output = prepared_grader(tmp_path, monkeypatch)
    job = grader.load_jobs(output, grader.read_plan(output))[0]
    body = json.loads(response(job))
    content = json.loads(body["choices"][0]["message"]["content"])
    content["grades"][job["candidates"][0]["id"]]["reason"] = ""
    body["choices"][0]["message"]["content"] = canonical_json(content)
    raw = canonical_json(body).encode()
    calls = []

    def transport(
        endpoint: str, key: str, payload: dict[str, object] | None, timeout: float
    ) -> tuple[int, bytes]:
        """Return a terminal response containing a blank explanation.

        Parameters
        ----------
        endpoint : str
            Requested endpoint.
        key : str
            Fixture credential.
        payload : dict[str, object] | None
            Credential-free request.
        timeout : float
            Frozen timeout.

        Returns
        -------
        tuple[int, bytes]
            Mocked HTTP status and exact body.
        """
        del key, timeout
        if endpoint == "/models/user":
            return 200, catalog()
        calls.append(payload)
        return 200, raw

    monkeypatch.setattr(grader, "provider_call", transport)
    grader.preflight(output, "fixture-key")
    assert grader.execute(output, "fixture-key", resume=False) == 1
    attempt = output / "attempts" / job["case_id"]
    assert (attempt / "response.body").read_bytes() == raw
    state = grading.read_object(attempt / "state.json")
    assert state["status"] == "failed"
    assert (
        state["failure_detail"]
        == "Candidate explanation must contain 1 to 300 nonblank characters"
    )
    summary = grading.read_object(output / "grading-summary.json")
    assert summary["observed_cost_usd"] == "0.001"
    assert summary["graded_queries"] == 0
    assert summary["unknown_cost_attempts"] == 0
    stderr = capsys.readouterr().err
    assert str(state["failure_detail"]) in stderr
    assert "fixture-key" not in stderr
    assert raw.decode() not in stderr
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Unresolved paid attempt"):
        grader.execute(output, "fixture-key", resume=True)
    assert len(calls) == 1


def test_request_describes_provider_unsupported_constraints() -> None:
    """Keep reason and coverage requirements in prompts and local validation.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    job: grading.Job = {
        "case_id": "case",
        "repo": "demo",
        "intent": "symbol_lookup",
        "query": "demo",
        "rankings": {},
        "candidates": [],
    }
    body = grading.request_body(job, "fixture/judge", 4096)
    schema = json.loads(canonical_json(body))["response_format"]["json_schema"][
        "schema"
    ]
    rows = schema["properties"]["grades"]
    assert "minItems" not in rows and "maxItems" not in rows
    reason = schema["$defs"]["candidate_grade"]["properties"]["reason"]
    assert "minLength" not in reason and "maxLength" not in reason
    assert "1 to 300" in reason["description"]
    assert "Never return an empty" in grading.RUBRIC


def test_keyed_schema_requires_every_candidate() -> None:
    """Express exact pool coverage using required object fields.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    job: grading.Job = {
        "case_id": "case",
        "repo": "demo",
        "intent": "symbol_lookup",
        "query": "demo",
        "rankings": {"a": ["first", "second"]},
        "candidates": [
            {
                "id": candidate,
                "path": "a.py",
                "line": 1,
                "kind": "symbol",
                "snippet": "def demo(): pass",
                "source_sha256": "a" * 64,
                "truncated": False,
            }
            for candidate in ("first", "second")
        ],
    }
    wire = json.loads(canonical_json(grading.request_body(job, "fixture/judge", 4096)))
    schema = wire["response_format"]["json_schema"]["schema"]
    grades_schema = schema["properties"]["grades"]
    assert grades_schema["type"] == "object"
    assert set(grades_schema["required"]) == {"first", "second"}
    assert set(grades_schema["properties"]) == {"first", "second"}
    assert grades_schema["additionalProperties"] is False
    complete = {
        "grades": {
            candidate: {"score": 1, "reason": "Related definition."}
            for candidate in ("first", "second")
        }
    }
    assert grading.validate_grades(complete, job, require_keyed=True) == {
        "first": 1,
        "second": 1,
    }
    del complete["grades"]["second"]
    with pytest.raises(ValueError, match="Missing or unknown"):
        grading.validate_grades(complete, job, require_keyed=True)
    with pytest.raises(ValueError, match="candidate-keyed"):
        grading.validate_grades(
            {"grades": [{"id": "first", "score": 0, "reason": ""}]},
            job,
            require_keyed=True,
        )


def test_duplicate_candidate_keys_are_rejected_before_grading() -> None:
    """Reject ambiguous JSON instead of silently choosing the last value.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    duplicate = (
        '{"grades":{"one":{"score":0,"reason":"A"},"one":{"score":2,"reason":"B"}}}'
    )
    with pytest.raises(ValueError, match="Duplicate JSON"):
        json.loads(duplicate, object_pairs_hook=grading.unique_object)


def test_legacy_array_identity_can_be_rescored_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replay retained v1 evidence without rewriting its format or making calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.
    monkeypatch : pytest.MonkeyPatch
        Mocked transport.

    Returns
    -------
    None
    """
    output = prepared_grader(tmp_path, monkeypatch)
    plan = grader.read_plan(output)
    plan["schema_version"] = grader.LEGACY_SCHEMA
    runner.write_json(output / "manifest.json", plan)
    (output / "manifest.sha256").write_text(
        digest_bytes((output / "manifest.json").read_bytes()) + "\n"
    )
    jobs = grader.load_jobs(output, plan)
    calls: list[str] = []

    def transport(endpoint: str, *_args: object) -> tuple[int, bytes]:
        """Return legacy array judgments with terminal usage.

        Parameters
        ----------
        endpoint : str
            Requested API path.
        *_args : object
            Unused fixture transport controls.

        Returns
        -------
        tuple[int, bytes]
            Legacy mocked response.
        """
        if endpoint == "/models/user":
            return 200, catalog()
        job = jobs[len(calls)]
        calls.append(job["case_id"])
        body = json.loads(response(job))
        body["choices"][0]["message"]["content"] = canonical_json(
            {
                "grades": [
                    {"id": candidate["id"], "score": 2, "reason": "Legacy explanation."}
                    for candidate in job["candidates"]
                ]
            }
        )
        return 200, canonical_json(body).encode()

    monkeypatch.setattr(grader, "provider_call", transport)
    grader.preflight(output, "fixture-key")
    assert grader.execute(output, "fixture-key", resume=False) == 0
    monkeypatch.setattr(
        grader,
        "provider_call",
        lambda *_args: pytest.fail("Offline replay contacted provider"),
    )
    assert grader.report(output) == 0
    assert (
        grading.read_object(output / "grading-summary.json")["schema_version"]
        == grader.LEGACY_SCHEMA
    )
