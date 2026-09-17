#!/usr/bin/env python3
"""Request an independent, non-executing review of the Phase 6 pilot diff."""
# ruff: noqa: EM101, S607, TRY003, TRY301

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "x-ai/grok-build-0.1"
TOKEN_ENVIRONMENT_KEY = "OPENROUTER_API_KEY"
DEFAULT_MAX_OUTPUT_TOKENS = 12000
DEFAULT_TIMEOUT_SECONDS = 300

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ReviewError(ValueError):
    """Report one public-safe independent-review failure.

    Parameters
    ----------
    detail : str
        Stable validation or transport failure detail.

    response_body : str, optional
        Exact provider response body, retained only so the caller can place it
        in its ignored evidence artifact. It never contains the credential or
        request headers and must not be rendered in logs or state files.
    """

    def __init__(self, detail: str, *, response_body: str | None = None) -> None:
        """Initialize a validation failure with optional response evidence.

        Parameters
        ----------
        detail : str
            Stable validation or transport failure detail.
        response_body : str, optional
            Received provider response body, if one was available.
        """

        super().__init__(detail)
        self.response_body = response_body


def _git_output(arguments: tuple[str, ...]) -> str:
    """Return one repository Git command's text output.

    Parameters
    ----------
    arguments : tuple[str, ...]
        Git arguments excluding the executable.

    Returns
    -------
    str
        Captured standard output.

    Raises
    ------
    ReviewError
        If Git cannot produce the requested review evidence.
    """

    completed = subprocess.run(
        ("git", *arguments), check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise ReviewError("cannot collect the review diff")
    return completed.stdout


def collect_diff(base_ref: str) -> str:
    """Collect tracked and untracked Phase 6 review material deterministically.

    Parameters
    ----------
    base_ref : str
        Git revision used as the review base.

    Returns
    -------
    str
        Unified diff including untracked non-ignored files.

    Raises
    ------
    ReviewError
        If no reviewable change exists or Git collection fails.
    """

    parts = [_git_output(("diff", "--binary", base_ref))]
    untracked = _git_output(("ls-files", "--others", "--exclude-standard"))
    for raw_path in sorted(item for item in untracked.splitlines() if item):
        completed = subprocess.run(
            ("git", "diff", "--no-index", "--binary", "/dev/null", raw_path),
            check=False,
            text=True,
            capture_output=True,
        )
        if completed.returncode not in {0, 1}:
            raise ReviewError("cannot collect an untracked review file")
        parts.append(completed.stdout)
    diff = "".join(parts)
    if not diff.strip():
        raise ReviewError("there is no uncommitted review material")
    return diff


def build_prompt(diff: str) -> str:
    """Build the bounded independent-review instruction and evidence.

    Parameters
    ----------
    diff : str
        Complete local Phase 6 candidate diff.

    Returns
    -------
    str
        Review prompt requiring an explicit machine-readable verdict.
    """

    return (
        """You are an independent code reviewer. Review this Phase 6 benchmark-pilot
diff only; do not propose unrelated refactors. Verify: credential separation,
one-response-request enforcement, frozen fixture identity, protected grader
asset provenance/isolation, resumable immutable records, and safe failure
behavior. Report only concrete correctness, security, or test-coverage defects.
Start exactly with `VERDICT: PASS` when no required change remains, otherwise
`VERDICT: NEEDS_FIXES`, followed by concise findings with file and line.

DIFF:
"""
        + diff
    )


def _provider_identity(payload: dict[str, object]) -> str:
    """Extract one provider identity from OpenRouter's opted-in metadata.

    Parameters
    ----------
    payload : dict[str, object]
        Complete non-streaming OpenRouter Chat Completions response.

    Returns
    -------
    str
        Non-empty provider name for the successful routed attempt.

    Raises
    ------
    ReviewError
        If the response cannot prove one selected provider identity.
    """

    provider = payload.get("provider")
    if isinstance(provider, str) and provider:
        return provider
    metadata = payload.get("openrouter_metadata")
    if not isinstance(metadata, dict):
        raise ReviewError("independent review provider identity is unverified")
    raw_attempts = metadata.get("attempts")
    if not isinstance(raw_attempts, list):
        raise ReviewError("independent review provider identity is unverified")
    providers: list[str] = []
    for attempt in raw_attempts:
        if not isinstance(attempt, dict) or attempt.get("status") != 200:
            continue
        candidate = attempt.get("provider")
        if isinstance(candidate, str) and candidate:
            providers.append(candidate)
    if len(providers) != 1:
        raise ReviewError("independent review provider identity is unverified")
    return providers[0]


def request_review(
    prompt: str,
    token: str,
    *,
    model: str = MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Submit one review request without logging its credential or body.

    Parameters
    ----------
    prompt : str
        Complete independent-review prompt.
    token : str
        SOPS-injected OpenRouter credential.
    model : str, optional
        Exact OpenRouter model identifier selected for this review.
    max_output_tokens : int, optional
        Positive completion-token ceiling sent to OpenRouter.
    timeout_seconds : int, optional
        Positive request timeout in seconds.

    Returns
    -------
    dict[str, object]
        Sanitized model response and provider-reported usage.

    Raises
    ------
    ReviewError
        If request settings or the provider response are unavailable, malformed,
        truncated, or do not prove the requested model identity.
    """

    if not model:
        raise ReviewError("independent review model is required")
    if max_output_tokens < 1:
        raise ReviewError("independent review output limit must be positive")
    if timeout_seconds < 1:
        raise ReviewError("independent review timeout must be positive")
    request_payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_output_tokens,
        "provider": {"allow_fallbacks": False},
    }
    body = json.dumps(request_payload).encode("utf-8")
    request = Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-OpenRouter-Metadata": "enabled",
        },
        method="POST",
    )
    started = time.monotonic()
    response_body: str | None = None
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            response_body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = f"independent review request failed with HTTP {error.code}"
        raise ReviewError(detail) from error
    except (OSError, URLError, UnicodeDecodeError) as error:
        raise ReviewError("independent review request failed") from error
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise ReviewError(
            "independent review response is malformed", response_body=response_body
        ) from error
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
        usage = payload.get("usage", {})
        response_model = payload["model"]
    except (KeyError, IndexError, TypeError) as error:
        raise ReviewError(
            "independent review response is malformed", response_body=response_body
        ) from error
    if (
        not isinstance(content, str)
        or not isinstance(usage, dict)
        or not isinstance(response_model, str)
    ):
        raise ReviewError(
            "independent review response is malformed", response_body=response_body
        )
    if response_model != model:
        raise ReviewError(
            "independent review model identity is unverified",
            response_body=response_body,
        )
    if choice.get("finish_reason") != "stop":
        raise ReviewError(
            "independent review response is incomplete", response_body=response_body
        )
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if first_line == "VERDICT: PASS":
        verdict = "PASS"
    elif first_line == "VERDICT: NEEDS_FIXES":
        verdict = "NEEDS_FIXES"
    else:
        raise ReviewError(
            "independent review verdict is malformed", response_body=response_body
        )
    required_usage = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
    if not all(
        isinstance(usage.get(field), int | float) and usage[field] >= 0
        for field in required_usage
    ):
        raise ReviewError(
            "independent review usage is incomplete", response_body=response_body
        )
    elapsed_seconds = time.monotonic() - started
    provider = _provider_identity(payload)
    return {
        "requested_model": model,
        "response_model": response_model,
        "provider": provider,
        "verdict": verdict,
        "review": content,
        "response_body": response_body,
        "usage": usage,
        "elapsed_seconds": elapsed_seconds,
        "request_settings": {
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "allow_fallbacks": False,
            "reasoning_enabled": None,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the independent-review command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for a base revision and optional public output file.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="HEAD")
    parser.add_argument("--diff-file", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument(
        "--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--evaluation-manifest", type=Path)
    parser.add_argument("--evaluation-output-dir", type=Path)
    parser.add_argument("--execute-evaluation", action="store_true")
    parser.add_argument("--evaluation-key-budget", action="store_true")
    parser.add_argument(
        "--evaluation-authenticated-model-contract", action="store_true"
    )
    parser.add_argument("--diagnostic-evaluation", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def _run_evaluation(args: argparse.Namespace) -> int:
    """Delegate one explicitly selected bounded evaluation action.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed wrapper arguments with an evaluation manifest.

    Returns
    -------
    int
        Evaluator exit status, or two for an invalid wrapper invocation.
    """

    if args.output is not None or args.diff_file is not None or args.base_ref != "HEAD":
        print(
            "independent review error: evaluation mode cannot combine with single-review input options",
            file=sys.stderr,
        )
        return 2
    selected_modes = sum(
        (
            args.execute_evaluation,
            args.evaluation_key_budget,
            args.evaluation_authenticated_model_contract,
            args.diagnostic_evaluation,
        )
    )
    if selected_modes > 1:
        print(
            "independent review error: evaluation modes are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    if selected_modes == 0:
        print(
            "independent review error: evaluation mode requires an explicit evaluation action",
            file=sys.stderr,
        )
        return 2
    from scripts.run_agent_efficiency_phase6_reviewer_evaluation import main as evaluate

    evaluation_arguments = ["--manifest", str(args.evaluation_manifest)]
    selected_flag = next(
        flag
        for enabled, flag in (
            (args.execute_evaluation, "--execute"),
            (args.evaluation_key_budget, "--key-budget"),
            (
                args.evaluation_authenticated_model_contract,
                "--authenticated-model-contract",
            ),
            (args.diagnostic_evaluation, "--diagnostic-once"),
        )
        if enabled
    )
    evaluation_arguments.append(selected_flag)
    if args.evaluation_output_dir is not None:
        evaluation_arguments.extend(["--output-dir", str(args.evaluation_output_dir)])
    return evaluate(evaluation_arguments)


def main(arguments: list[str] | None = None) -> int:
    """Request and render one independent review under the SOPS test key.

    Parameters
    ----------
    arguments : list[str] or None, optional
        Command-line arguments excluding the executable name.

    Returns
    -------
    int
        Zero for a completed review and two for safe rejection.

    Raises
    ------
    SystemExit
        If command-line arguments violate the parser contract.
    """

    args = build_parser().parse_args(arguments)
    if args.evaluation_manifest is not None:
        return _run_evaluation(args)
    try:
        if (
            args.execute_evaluation
            or args.evaluation_key_budget
            or args.evaluation_authenticated_model_contract
            or args.diagnostic_evaluation
        ):
            raise ReviewError("evaluation mode requires --evaluation-manifest")
        token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
        if not token:
            raise ReviewError("independent review credential is unavailable")
        if args.diff_file is None:
            diff = collect_diff(args.base_ref)
        else:
            if args.base_ref != "HEAD":
                raise ReviewError("--diff-file cannot be combined with --base-ref")
            diff = args.diff_file.read_text(encoding="utf-8")
            if not diff.strip():
                raise ReviewError("review diff file is empty")
        result = request_review(
            build_prompt(diff),
            token,
            model=args.model,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
        )
        rendered = json.dumps(result, sort_keys=True)
        if args.output is not None:
            args.output.write_text(rendered + "\n", encoding="utf-8")
    except (OSError, ReviewError) as error:
        print(f"independent review error: {error}", file=sys.stderr)
        return 2
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
