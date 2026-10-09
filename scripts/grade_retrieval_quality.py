"""Prepare, preflight, execute or rescore a small OpenRouter retrieval grader.

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
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import cast, override

from scripts.known_target_quality import canonical_json, digest_bytes, invalid
from scripts.retrieval_grading import (
    RUBRIC,
    Job,
    aggregate_scores,
    json_object,
    prepare_jobs,
    read_object,
    request_body,
    unique_object,
    validate_grades,
)
from scripts.run_known_target_quality import RunProgress, campaign_lock, write_json

API = "https://openrouter.ai/api/v1"
SCHEMA = "retrieval-llm-grading-v2"
LEGACY_SCHEMA = "retrieval-llm-grading-v1"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so authorization remains scoped to the fixed API host."""

    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        """Refuse every redirect without forwarding credentials.

        Parameters
        ----------
        req : urllib.request.Request
            Original request.
        fp : object
            Response stream.
        code : int
            Redirect status.
        msg : str
            Status description.
        headers : object
            Response headers.
        newurl : str
            Proposed redirect target.

        Returns
        -------
        None
        """
        del req, fp, code, msg, headers, newurl


def provider_call(
    endpoint: str,
    key: str,
    body: dict[str, object] | None,
    timeout: float,
) -> tuple[int, bytes]:
    """Make one fixed-host HTTP request with no retry or redirect.

    Parameters
    ----------
    endpoint : str
        Fixed model-catalog or completion path.
    key : str
        Child-scoped credential, never persisted.
    body : dict[str, object] | None
        Completion payload, or None for the authenticated catalog.
    timeout : float
        HTTP timeout in seconds.

    Returns
    -------
    tuple[int, bytes]
        HTTP status and exact body, including provider error bodies.

    Raises
    ------
    OSError
        The transport cannot establish or finish the request.
    """
    if endpoint not in ("/models/user", "/chat/completions"):
        invalid("Unsupported provider endpoint")
    request = urllib.request.Request(
        API + endpoint,
        data=canonical_json(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def decimal_value(value: object) -> Decimal:
    """Require a finite, nonnegative monetary or token-price value.

    Parameters
    ----------
    value : object
        Provider or local numeric boundary.

    Returns
    -------
    decimal.Decimal
        Exact decimal value.

    Raises
    ------
    ValueError
        The value is missing, invalid, infinite or negative.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        invalid("Missing or invalid numeric accounting value")
    try:
        number = Decimal(str(value))
    except ArithmeticError:
        invalid("Invalid numeric accounting value")
    if not number.is_finite() or number < 0:
        invalid("Non-finite or negative accounting value")
    return number


def read_plan(root: Path, *, check_harness: bool = True) -> dict[str, object]:
    """Validate frozen grader controls and each prepared job checksum.

    Parameters
    ----------
    root : pathlib.Path
        Prepared grading directory.
    check_harness : bool, optional
        Enforce implementation identity before contacting the provider.

    Returns
    -------
    dict[str, object]
        Verified manifest.

    Raises
    ------
    ValueError
        A prepared control or job has changed.
    """
    content = (root / "manifest.json").read_bytes()
    if digest_bytes(content) != (root / "manifest.sha256").read_text().strip():
        invalid("Grading manifest checksum differs")
    plan = read_object(root / "manifest.json")
    if plan["schema_version"] not in (SCHEMA, LEGACY_SCHEMA):
        invalid("Unknown grading schema")
    for name, checksum in cast("dict[str, str]", plan["jobs"]).items():
        if (
            Path(name).name != name
            or digest_bytes((root / "jobs" / name).read_bytes()) != checksum
        ):
            invalid("Prepared grading input changed")
    if check_harness:
        for name, checksum in cast("dict[str, str]", plan["harness"]).items():
            if digest_bytes((Path(__file__).parent / name).read_bytes()) != checksum:
                invalid("Grading harness changed; prepare a new identity")
    recovery_cost(root, plan)
    return plan


def recovery_cost(root: Path, plan: dict[str, object]) -> Decimal:
    """Verify preserved failure evidence and return its carried billed cost.

    Parameters
    ----------
    root : pathlib.Path
        Prepared continuation directory.
    plan : dict[str, object]
        Checksummed manifest.

    Returns
    -------
    decimal.Decimal
        Failed-attempt spending retained across explicit recoveries.

    Raises
    ------
    ValueError
        Preserved evidence paths, hashes or accounting differ.
    """
    if "recovery" not in plan:
        return Decimal(0)
    recovery = json_object(plan["recovery"])
    costs = Decimal(0)
    evidence = cast("dict[str, str]", recovery["evidence"])
    for name, checksum in evidence.items():
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[0] != "prior-attempts"
        ):
            invalid("Invalid recovery evidence path")
        raw = (root / path).read_bytes()
        if digest_bytes(raw) != checksum:
            invalid("Recovery evidence changed")
        if path.name == "response.body":
            body = json_object(json.loads(raw, object_pairs_hook=unique_object))
            costs += decimal_value(json_object(body.get("usage")).get("cost"))
    if costs != decimal_value(recovery["carried_cost_usd"]):
        invalid("Recovery accounting changed")
    return costs


def recover(source: Path, output: Path) -> None:
    """Prepare explicit continuation, preserving valid grades and failed costs.

    Parameters
    ----------
    source : pathlib.Path
        Inactive grading run with fully accounted retained responses.
    output : pathlib.Path
        Fresh continuation identity; the source is never modified.

    Returns
    -------
    None

    Raises
    ------
    ValueError
        Evidence, accounting or request controls cannot safely be reused.
    """
    with campaign_lock(source.resolve()):
        plan = read_plan(source, check_harness=False)
        contract = json_object(read_preflight(source)["contract"])
        completed: list[str] = []
        pending: list[str] = []
        failed: list[str] = []
        carried = recovery_cost(source, plan)
        for name in cast("list[str]", plan["job_order"]):
            job = cast("Job", read_object(source / "jobs" / name))
            attempt = source / "attempts" / job["case_id"]
            if not attempt.exists():
                pending.append(name)
                continue
            state = read_object(attempt / "state.json")
            if state.get("source") == "empty_pool":
                if job["candidates"] or state.get("status") != "complete":
                    invalid("Invalid empty-pool checkpoint")
                completed.append(name)
                continue
            request, reserved, input_bound = bounded_request(job, plan, contract)
            if (
                state.get("request_sha256")
                != digest_bytes(canonical_json(request).encode())
                or read_object(attempt / "request.json") != request
            ):
                invalid("Recovery requires unchanged judge requests and rubric")
            raw_path = attempt / "response.body"
            if (
                state.get("status") not in {"complete", "failed"}
                or not raw_path.is_file()
            ):
                invalid("Recovery refuses an ambiguous paid attempt")
            raw = raw_path.read_bytes()
            if (
                state.get("response_sha256") != digest_bytes(raw)
                or state.get("http_status") != 200
            ):
                invalid("Recovery requires intact successful HTTP response evidence")
            _, accounting = validated_response(
                raw,
                job,
                contract,
                require_keyed=plan["schema_version"] == SCHEMA,
                validate_judgments=state["status"] == "complete",
            )
            cost = decimal_value(accounting["cost_usd"])
            if (
                cost > reserved
                or cast("int", accounting["prompt_tokens"]) > input_bound
                or cast("int", accounting["completion_tokens"])
                > cast("int", plan["max_output_tokens"])
            ):
                invalid("Recovery refuses a reservation violation")
            if state["status"] == "complete":
                completed.append(name)
            else:
                failed.append(job["case_id"])
                pending.append(name)
                carried += cost
        output.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source / "jobs", output / "jobs")
        if (source / "prior-attempts").exists():
            shutil.copytree(source / "prior-attempts", output / "prior-attempts")
        for name in completed:
            case_id = Path(name).stem
            shutil.copytree(
                source / "attempts" / case_id, output / "attempts" / case_id
            )
        for case_id in failed:
            target = output / "prior-attempts" / (source.name + "-" + case_id)
            shutil.copytree(source / "attempts" / case_id, target)
        evidence = {
            str(path.relative_to(output)): digest_bytes(path.read_bytes())
            for path in sorted((output / "prior-attempts").rglob("*"))
            if path.is_file()
        }
        plan["harness"] = {
            name: digest_bytes((Path(__file__).parent / name).read_bytes())
            for name in ("grade_retrieval_quality.py", "retrieval_grading.py")
        }
        plan["job_order"] = completed + pending
        plan["recovery"] = {
            "source": str(source.resolve()),
            "source_manifest_sha256": digest_bytes(
                (source / "manifest.json").read_bytes()
            ),
            "contract": contract,
            "carried_cost_usd": str(carried),
            "evidence": evidence,
            "reused_queries": len(completed),
        }
        write_json(output / "manifest.json", plan)
        (output / "manifest.sha256").write_text(
            digest_bytes((output / "manifest.json").read_bytes()) + "\n"
        )
        print(
            f"Recovery prepared: {len(completed)} grades reused, {len(pending)} queries pending; no provider calls."
        )


def load_jobs(root: Path, plan: dict[str, object]) -> list[Job]:
    """Load checksummed typed jobs from a prepared identity.

    Parameters
    ----------
    root : pathlib.Path
        Grading directory.
    plan : dict[str, object]
        Verified manifest.

    Returns
    -------
    list[Job]
        Jobs in their frozen pilot/full-run order.
    """
    return [
        cast("Job", read_object(root / "jobs" / name))
        for name in cast("list[str]", plan["job_order"])
    ]


def prepare(args: argparse.Namespace) -> None:
    """Prepare an offline identity without credentials or provider calls.

    Parameters
    ----------
    args : argparse.Namespace
        Explicit source, judge, budget and excerpt controls.

    Returns
    -------
    None
    """
    budget = decimal_value(args.budget_usd)
    if (
        budget <= 0
        or not args.judge_model
        or "/" not in args.judge_model
        or args.max_output_tokens < 1
        or not 100 <= args.snippet_chars <= 4000
        or not math.isfinite(args.timeout)
        or args.timeout <= 0
        or (args.case_limit is not None and args.case_limit < 1)
    ):
        invalid("Invalid judge, budget, token, excerpt, timeout or pilot controls")
    jobs, fingerprints = prepare_jobs(
        args.run.resolve(),
        include_private=args.include_private,
        case_limit=args.case_limit,
        snippet_chars=args.snippet_chars,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "jobs").mkdir()
    checksums = {}
    order = []
    for job in jobs:
        name = job["case_id"] + ".json"
        content = (canonical_json(job) + "\n").encode()
        (args.output / "jobs" / name).write_bytes(content)
        checksums[name] = digest_bytes(content)
        order.append(name)
    plan: dict[str, object] = {
        "schema_version": SCHEMA,
        "source_run": str(args.run.resolve()),
        "source_evidence": fingerprints,
        "judge_model": args.judge_model,
        "budget_usd": str(budget),
        "max_output_tokens": args.max_output_tokens,
        "snippet_chars": args.snippet_chars,
        "timeout": args.timeout,
        "include_private": args.include_private,
        "case_limit": args.case_limit,
        "rubric": RUBRIC,
        "jobs": checksums,
        "job_order": order,
        "harness": {
            name: digest_bytes((Path(__file__).parent / name).read_bytes())
            for name in ("grade_retrieval_quality.py", "retrieval_grading.py")
        },
    }
    write_json(args.output / "manifest.json", plan)
    (args.output / "manifest.sha256").write_text(
        digest_bytes((args.output / "manifest.json").read_bytes()) + "\n"
    )
    print(f"Prepared {len(jobs)} blinded query pools; no provider calls.")


def model_contract(catalog: bytes, model: str) -> dict[str, object]:
    """Qualify the exact key-visible model and text-only price contract.

    Parameters
    ----------
    catalog : bytes
        Authenticated models/user response.
    model : str
        Exact requested model identifier.

    Returns
    -------
    dict[str, object]
        Required capabilities, accepted response IDs and price bounds.

    Raises
    ------
    ValueError
        The selected model or required accounting contract is unavailable.
    """
    body = json_object(json.loads(catalog))
    rows = body.get("data")
    if not isinstance(rows, list):
        invalid("Invalid authenticated model catalog")
    found = [json_object(row) for row in rows if json_object(row).get("id") == model]
    if len(found) != 1:
        invalid("Judge model is not uniquely available to this key")
    selected = found[0]
    supported = selected.get("supported_parameters")
    if (
        not isinstance(supported, list)
        or not all(isinstance(item, str) for item in supported)
        or not {
            "structured_outputs",
            "max_tokens",
        }.issubset(supported)
    ):
        invalid("Judge must support structured outputs and max_tokens")
    architecture = json_object(selected.get("architecture"))
    modalities = architecture.get("input_modalities")
    if not isinstance(modalities, list) or "text" not in modalities:
        invalid("Judge does not accept text")
    pricing = json_object(selected.get("pricing"))
    prices = {
        name: str(
            decimal_value(
                pricing.get(name, "0") if name == "request" else pricing.get(name)
            )
        )
        for name in ("prompt", "completion", "request")
    }
    # Reserve the highest published rate across conditional price tiers.
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list):
        invalid("Invalid conditional pricing contract")
    for entry in overrides:
        tier = json_object(entry)
        for name in prices:
            if name in tier:
                prices[name] = str(
                    max(Decimal(prices[name]), decimal_value(tier[name]))
                )
    if any(
        not math.isfinite(float(Decimal(price) * 1_000_000))
        for price in prices.values()
    ):
        invalid("Routing price exceeds supported numeric limits")
    context = selected.get("context_length")
    if type(context) is not int or context <= 0:
        invalid("Judge context bound is missing")
    accepted = {model}
    if isinstance(selected.get("canonical_slug"), str):
        accepted.add(cast("str", selected["canonical_slug"]))
    return {
        "model": model,
        "accepted_response_models": sorted(accepted),
        "pricing": prices,
        "pricing_overrides": overrides,
        "context_length": context,
        "reasoning": selected.get("reasoning"),
        "max_completion_tokens": json_object(selected.get("top_provider")).get(
            "max_completion_tokens"
        ),
    }


def bounded_request(
    job: Job,
    plan: dict[str, object],
    contract: dict[str, object],
) -> tuple[dict[str, object], Decimal, int]:
    """Freeze price-limited routing and a conservative per-request reservation.

    Parameters
    ----------
    job : Job
        Frozen query pool.
    plan : dict[str, object]
        Judge and completion controls.
    contract : dict[str, object]
        Authenticated model capabilities and prices.

    Returns
    -------
    tuple[dict[str, object], decimal.Decimal, int]
        Request, reserved USD and conservative input-token allowance.

    Raises
    ------
    ValueError
        Conservative input plus output does not fit the model's limits.
    """
    output_tokens = int(cast("int", plan["max_output_tokens"]))
    payload = request_body(job, str(plan["judge_model"]), output_tokens)
    prices = cast("dict[str, str]", contract["pricing"])
    payload["provider"] = {
        "require_parameters": True,
        "allow_fallbacks": False,
        "max_price": {
            "prompt": float(Decimal(prices["prompt"]) * 1_000_000),
            "completion": float(Decimal(prices["completion"]) * 1_000_000),
            "request": float(Decimal(prices["request"])),
        },
    }
    # Bytes are a conservative estimate, with extra framing/schema allowance.
    input_bound = len(canonical_json(payload).encode()) + 4096
    completion_limit = contract["max_completion_tokens"]
    if input_bound + output_tokens > cast("int", contract["context_length"]) or (
        isinstance(completion_limit, int) and output_tokens > completion_limit
    ):
        invalid(
            "Conservative request size exceeds judge limits; reduce excerpts or output tokens"
        )
    reserved = (
        Decimal(prices["prompt"]) * input_bound
        + Decimal(prices["completion"]) * output_tokens
        + Decimal(prices["request"])
    )
    return payload, reserved, input_bound


def authenticated_contract(plan: dict[str, object], key: str) -> dict[str, object]:
    """Read the key-visible catalog without making a completion.

    Parameters
    ----------
    plan : dict[str, object]
        Exact judge identity and timeout.
    key : str
        Child-scoped credential.

    Returns
    -------
    dict[str, object]
        Qualified selected model contract.
    """
    status, content = provider_call(
        "/models/user", key, None, float(cast("float", plan["timeout"]))
    )
    if status != 200:
        invalid("Authenticated model lookup failed")
    return model_contract(content, str(plan["judge_model"]))


def preflight(root: Path, key: str) -> None:
    """Save authenticated price/capability admission without paid requests.

    Parameters
    ----------
    root : pathlib.Path
        Prepared grading directory.
    key : str
        Scoped OpenRouter credential.

    Returns
    -------
    None
    """
    plan = read_plan(root)
    contract = authenticated_contract(plan, key)
    if "recovery" in plan and json_object(plan["recovery"])["contract"] != contract:
        invalid("Recovery judge capabilities or prices changed")
    reserved = recovery_cost(root, plan)
    for job in load_jobs(root, plan):
        if not job["candidates"]:
            continue
        attempt = root / "attempts" / job["case_id"]
        if "recovery" in plan and attempt.exists():
            state = read_object(attempt / "state.json")
            raw = (attempt / "response.body").read_bytes()
            if state.get("status") != "complete" or digest_bytes(raw) != state.get(
                "response_sha256"
            ):
                invalid("Recovery checkpoint changed")
            _, accounting = validated_response(
                raw, job, contract, require_keyed=plan["schema_version"] == SCHEMA
            )
            reserved += decimal_value(accounting["cost_usd"])
        else:
            reserved += bounded_request(job, plan, contract)[1]
    if reserved > Decimal(str(plan["budget_usd"])):
        invalid("Conservative full-run reservation exceeds the declared budget")
    receipt = {
        "manifest_sha256": digest_bytes((root / "manifest.json").read_bytes()),
        "contract": contract,
        "full_run_reservation_usd": str(reserved),
    }
    path = root / "preflight.json"
    if path.exists() and read_object(path) != receipt:
        invalid("Preflight controls changed; prepare a new grading identity")
    write_json(path, receipt)
    (root / "preflight.sha256").write_text(digest_bytes(path.read_bytes()) + "\n")
    print(
        f"Preflight passed; conservative reservation USD {reserved}; no paid requests."
    )


def validated_response(
    raw: bytes,
    job: Job,
    contract: dict[str, object],
    *,
    require_keyed: bool = False,
    validate_judgments: bool = True,
) -> tuple[dict[str, int], dict[str, object]]:
    """Validate model identity, terminal completion, usage and candidate grades.

    Parameters
    ----------
    raw : bytes
        Already retained exact provider response.
    job : Job
        Expected pool.
    contract : dict[str, object]
        Accepted model identities.
    require_keyed : bool, optional
        Require the new response shape; allow legacy arrays for old replay.
    validate_judgments : bool, optional
        Disable only to account for a retained failed response during explicit
        recovery. Its scores are never reused.

    Returns
    -------
    tuple[dict[str, int], dict[str, object]]
        Candidate grades and complete provider accounting.

    Raises
    ------
    ValueError
        Model, completion, accounting or semantic-output format is invalid.
    """
    body = json_object(json.loads(raw, object_pairs_hook=unique_object))
    if body.get("model") not in cast("list[str]", contract["accepted_response_models"]):
        invalid("Unexpected response model")
    usage = json_object(body.get("usage"))
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if type(usage.get(name)) is not int or cast("int", usage[name]) < 0:
            invalid("Missing terminal token accounting")
    if usage["total_tokens"] != cast("int", usage["prompt_tokens"]) + cast(
        "int", usage["completion_tokens"]
    ):
        invalid("Inconsistent terminal token accounting")
    cost = decimal_value(usage.get("cost"))
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        invalid("Expected one terminal judge choice")
    choice = json_object(choices[0])
    if choice.get("finish_reason") != "stop":
        invalid("Judge completion did not finish normally")
    content = json_object(choice.get("message")).get("content")
    if not isinstance(content, str):
        invalid("Missing judge JSON content")
    grades = (
        validate_grades(
            json.loads(content, object_pairs_hook=unique_object),
            job,
            require_keyed=require_keyed,
        )
        if validate_judgments
        else {}
    )
    return grades, {
        "cost_usd": str(cost),
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "provider": body.get("provider"),
        "generation_id": body.get("id"),
        "response_model": body.get("model"),
    }


def complete_empty_pool(attempt: Path) -> bool:
    """Checkpoint an empty result pool locally without a paid request.

    Parameters
    ----------
    attempt : pathlib.Path
        Local job checkpoint directory.

    Returns
    -------
    bool
        Whether an existing local checkpoint was reused.

    Raises
    ------
    ValueError
        Existing evidence does not represent an empty pool.
    """
    if attempt.exists():
        if read_object(attempt / "state.json").get("source") != "empty_pool":
            invalid("Empty-pool checkpoint changed")
        return True
    attempt.mkdir(parents=True)
    write_json(attempt / "state.json", {"status": "complete", "source": "empty_pool"})
    return False


def read_preflight(root: Path) -> dict[str, object]:
    """Verify the authenticated receipt against its prepared identity.

    Parameters
    ----------
    root : pathlib.Path
        Prepared grading directory.

    Returns
    -------
    dict[str, object]
        Verified receipt.

    Raises
    ------
    ValueError
        Receipt bytes or the bound manifest changed.
    """
    path = root / "preflight.json"
    if (
        digest_bytes(path.read_bytes())
        != (root / "preflight.sha256").read_text().strip()
    ):
        invalid("Preflight receipt changed")
    receipt = read_object(path)
    if receipt.get("manifest_sha256") != digest_bytes(
        (root / "manifest.json").read_bytes()
    ):
        invalid("Preflight manifest changed")
    return receipt


def execute(root: Path, key: str, *, resume: bool) -> int:
    """Run sequential paid judgments once, retaining ambiguous attempts on failure.

    Parameters
    ----------
    root : pathlib.Path
        Prepared and preflighted grading directory.
    key : str
        Scoped credential.
    resume : bool
        Reuse validated completed jobs; never retry an ambiguous paid attempt.

    Returns
    -------
    int
        Zero only when every selected query is completely graded.

    Raises
    ------
    ValueError
        Controls changed or a previous attempt cannot safely be reused.
    """
    plan = read_plan(root)
    receipt = read_preflight(root)
    contract = json_object(receipt["contract"])
    if (
        receipt["manifest_sha256"]
        != digest_bytes((root / "manifest.json").read_bytes())
        or authenticated_contract(plan, key) != contract
    ):
        invalid("Judge capabilities or prices changed; prepare a new identity")
    jobs = load_jobs(root, plan)
    if not resume and (root / "attempts").exists():
        invalid("Grading already started; use --resume for completed checkpoints")
    progress = RunProgress(len(jobs))
    spent = recovery_cost(root, plan)
    for job in jobs:
        attempt = root / "attempts" / job["case_id"]
        progress.active = f"grading query {progress.completed + 1}/{len(jobs)}"
        progress.render(force=True)
        if not job["candidates"]:
            progress.advance(reused=complete_empty_pool(attempt))
            continue
        request, reserved, input_bound = bounded_request(job, plan, contract)
        if attempt.exists():
            state = read_object(attempt / "state.json")
            if state.get("request_sha256") != digest_bytes(
                canonical_json(request).encode()
            ):
                invalid("Retained grading request changed")
            raw_path = attempt / "response.body"
            if state.get("status") != "complete" or not raw_path.is_file():
                invalid(
                    "Unresolved paid attempt: inspect retained evidence; no automatic retry"
                )
            if digest_bytes(raw_path.read_bytes()) != state.get("response_sha256"):
                invalid("Retained provider evidence changed")
            _, accounting = validated_response(
                raw_path.read_bytes(),
                job,
                contract,
                require_keyed=plan["schema_version"] == SCHEMA,
            )
            spent += Decimal(str(accounting["cost_usd"]))
            progress.advance(reused=True)
            continue
        if spent + reserved > Decimal(str(plan["budget_usd"])):
            invalid("Budget admission stops before the next request")
        attempt.mkdir(parents=True)
        write_json(attempt / "request.json", request)
        state = {
            "status": "in_progress",
            "request_sha256": digest_bytes(canonical_json(request).encode()),
            "reserved_usd": str(reserved),
            "input_token_bound": input_bound,
        }
        write_json(attempt / "state.json", state)
        started = time.monotonic()
        try:
            status, raw = provider_call(
                "/chat/completions", key, request, float(cast("float", plan["timeout"]))
            )
            # Persist the exact response before parsing, accounting or grading.
            (attempt / "response.body").write_bytes(raw)
            state.update(
                {
                    "http_status": status,
                    "response_sha256": digest_bytes(raw),
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            write_json(attempt / "state.json", state)
            if status != 200:
                invalid("Provider completion returned an error")
            grades, accounting = validated_response(
                raw, job, contract, require_keyed=plan["schema_version"] == SCHEMA
            )
            actual = Decimal(str(accounting["cost_usd"]))
            if (
                actual > reserved
                or cast("int", accounting["prompt_tokens"]) > input_bound
                or cast("int", accounting["completion_tokens"])
                > cast("int", plan["max_output_tokens"])
            ):
                invalid("Observed usage exceeds the frozen reservation contract")
            spent += actual
            state.update(
                {"status": "complete", "accounting": accounting, "grades": grades}
            )
            write_json(attempt / "state.json", state)
            progress.advance()
        except (OSError, ValueError) as exc:
            state["status"] = "failed"
            state["failure_type"] = type(exc).__name__
            # Local validators use fixed diagnostics, never provider content.
            detail = (
                str(exc)
                if isinstance(exc, ValueError)
                else "Transport failed; the paid request outcome may be unknown"
            )
            state["failure_detail"] = detail
            write_json(attempt / "state.json", state)
            progress.active = "stopped; inspect private attempt evidence"
            progress.render(force=True)
            print(
                f"\nGrading stopped: {detail}. Evidence: {attempt}",
                file=sys.stderr,
                flush=True,
            )
            report(root)
            return 1
    progress.active = "finished"
    progress.render(force=True)
    if sys.stderr.isatty():
        print(file=sys.stderr, flush=True)
    return report(root)


def report(root: Path) -> int:
    """Rescore saved raw judgments offline and retain incomplete denominators.

    Parameters
    ----------
    root : pathlib.Path
        Prepared grading directory.

    Returns
    -------
    int
        Nonzero if any query remains ungraded or its evidence is invalid.
    """
    plan = read_plan(root, check_harness=False)
    jobs = load_jobs(root, plan)
    preflight_path = root / "preflight.json"
    contract = (
        json_object(read_preflight(root)["contract"]) if preflight_path.exists() else {}
    )
    verdicts: dict[str, dict[str, int]] = {}
    costs = recovery_cost(root, plan)
    unknown_cost_attempts = 0
    for job in jobs:
        state_path = root / "attempts" / job["case_id"] / "state.json"
        if not state_path.exists():
            continue
        state = read_object(state_path)
        if state.get("source") == "empty_pool":
            if job["candidates"] or state.get("status") != "complete":
                invalid("Empty-pool checkpoint differs from prepared input")
            verdicts[job["case_id"]] = {}
            continue
        saved_request = read_object(state_path.parent / "request.json")
        if state.get("request_sha256") != digest_bytes(
            canonical_json(saved_request).encode()
        ):
            invalid("Retained grading request changed")
        if (
            saved_request.get("model") != plan["judge_model"]
            or saved_request.get("max_tokens") != plan["max_output_tokens"]
        ):
            invalid("Retained grading request differs from prepared controls")
        raw_path = state_path.parent / "response.body"
        if not raw_path.exists():
            unknown_cost_attempts += 1
            continue
        raw = raw_path.read_bytes()
        if digest_bytes(raw) != state.get("response_sha256"):
            invalid("Retained provider evidence changed")
        try:
            body = json_object(json.loads(raw, object_pairs_hook=unique_object))
            costs += decimal_value(json_object(body.get("usage")).get("cost"))
        except ValueError:
            unknown_cost_attempts += 1
        if state.get("status") == "complete":
            grades, _accounting = validated_response(
                raw, job, contract, require_keyed=plan["schema_version"] == SCHEMA
            )
            verdicts[job["case_id"]] = grades
    summary = {
        "schema_version": plan["schema_version"],
        "judge_model": plan["judge_model"],
        "planned_queries": len(jobs),
        "graded_queries": len(verdicts),
        "observed_cost_usd": str(costs),
        "carried_failed_cost_usd": str(recovery_cost(root, plan)),
        "unknown_cost_attempts": unknown_cost_attempts,
        "uncertain_judgments": sum(
            score < 0 for grades in verdicts.values() for score in grades.values()
        ),
        "metrics": aggregate_scores(jobs, verdicts),
        "interpretation": "LLM judgments of bounded snippets; pooled relevance is non-exhaustive. Unknown grades score zero in lower-bound metrics. No model is promoted.",
    }
    write_json(root / "grading-summary.json", summary)
    lines = [
        "# Optional LLM retrieval relevance",
        "",
        str(summary["interpretation"]),
        "",
        f"Graded queries: {len(verdicts)}/{len(jobs)}. Observed cost: USD {costs}.",
        f"Attempts with unknown cost: {unknown_cost_attempts}. Uncertain judgments: {summary['uncertain_judgments']}.",
        "",
        "| Model | K | Micro precision lower bound | Micro pooled nDCG |",
        "| --- | ---: | ---: | ---: |",
    ]
    for model, cutoffs in cast(
        "dict[str, dict[str, dict[str, object]]]", summary["metrics"]
    ).items():
        for k, values in cutoffs.items():
            micro = cast("dict[str, float]", values["micro"])
            lines.append(
                f"| {model} | {k} | {micro['judged_precision_lower_bound']:.4f} | {micro['pool_ndcg']:.4f} |"
            )
    (root / "grading-summary.md").write_text("\n".join(lines) + "\n")
    return int(len(verdicts) != len(jobs))


def main(argv: list[str] | None = None) -> int:
    """Dispatch offline preparation, authenticated preflight, execution or rescore.

    Parameters
    ----------
    argv : list[str] | None, optional
        CLI argument vector.

    Returns
    -------
    int
        Command exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--run", type=Path, required=True)
    build.add_argument("--judge-model", required=True)
    build.add_argument("--budget-usd", required=True)
    build.add_argument("--max-output-tokens", type=int, default=4096)
    build.add_argument("--snippet-chars", type=int, default=1600)
    build.add_argument("--timeout", type=float, default=180)
    build.add_argument("--case-limit", type=int)
    build.add_argument("--include-private", action="store_true")
    recovery = commands.add_parser("recover")
    recovery.add_argument("--source", type=Path, required=True)
    for command in (
        build,
        recovery,
        commands.add_parser("preflight"),
        commands.add_parser("run"),
        commands.add_parser("rescore"),
    ):
        command.add_argument("--output", type=Path, required=True)
        if command.prog.endswith(" run"):
            command.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        with campaign_lock(args.output.resolve()):
            if args.command == "prepare":
                prepare(args)
                return 0
            if args.command == "recover":
                recover(args.source, args.output)
                return 0
            if args.command == "rescore":
                return report(args.output)
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                invalid(
                    "OPENROUTER_API_KEY is required through the scoped SOPS environment"
                )
            if args.command == "preflight":
                preflight(args.output, key)
                return 0
            return execute(args.output, key, resume=args.resume)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Grading stopped: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
