#!/usr/bin/env python3
"""Request an independent, non-executing review of the Phase 6 pilot diff."""
# ruff: noqa: EM101, S607, TRY003, TRY301

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "x-ai/grok-build-0.1"
TOKEN_ENVIRONMENT_KEY = "OPENROUTER_API_KEY"


class ReviewError(ValueError):
    """Report one public-safe independent-review failure.

    Parameters
    ----------
    detail : str
        Stable validation or transport failure detail.

    Returns
    -------
    None
        The exception retains no credential or request-body content.
    """


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


def request_review(prompt: str, token: str) -> dict[str, object]:
    """Submit one review request without logging its credential or body.

    Parameters
    ----------
    prompt : str
        Complete independent-review prompt.
    token : str
        SOPS-injected OpenRouter credential.

    Returns
    -------
    dict[str, object]
        Sanitized model response and provider-reported usage.

    Raises
    ------
    ReviewError
        If the provider response is unavailable or malformed.
    """

    body = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
    ).encode("utf-8")
    request = Request(
        OPENROUTER_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:  # noqa: S310
            payload = json.loads(response.read())
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise ReviewError("independent review request failed") from error
    try:
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
    except (KeyError, IndexError, TypeError) as error:
        raise ReviewError("independent review response is malformed") from error
    if not isinstance(content, str) or not isinstance(usage, dict):
        raise ReviewError("independent review response is malformed")
    verdict = "PASS" if content.startswith("VERDICT: PASS") else "NEEDS_FIXES"
    return {"model": MODEL, "verdict": verdict, "review": content, "usage": usage}


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
    parser.add_argument("--output", type=Path)
    return parser


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
    """

    args = build_parser().parse_args(arguments)
    try:
        token = os.environ.get(TOKEN_ENVIRONMENT_KEY, "")
        if not token:
            raise ReviewError("independent review credential is unavailable")
        result = request_review(build_prompt(collect_diff(args.base_ref)), token)
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
