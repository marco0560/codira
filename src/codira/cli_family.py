"""Explicit family CLI selection and independent member indexing.

Parameters
----------
None

Returns
-------
None
    CLI orchestration without changing single-repository commands.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.cli_index import _run_index
from codira.cli_requests import IndexCommandRequest
from codira.contracts import BackendError
from codira.family import FamilyDefinition, load_family
from codira.family_runtime import FamilyRuntime, member_scope, member_state

if TYPE_CHECKING:
    import argparse

    from codira.family_runtime import FamilyOperation


def add_family_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register local family operations with an explicit manifest argument.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        Top-level CLI subcommand collection.

    Returns
    -------
    None
        Parsers are registered in place.
    """
    parser = subparsers.add_parser(
        "family", help="Index and query an explicit local repository family"
    )
    actions = parser.add_subparsers(dest="family_action", required=True)
    for action in ("index", "status", "validate", "ctx", "sym", "refs", "evidence"):
        command = actions.add_parser(action)
        command.add_argument(
            "manifest", type=Path, help="Versioned TOML family definition"
        )
        command.add_argument(
            "--json",
            action="store_true",
            help="Print the complete family contract envelope",
        )
        if action in {"ctx", "sym", "refs", "evidence"}:
            command.add_argument(
                "query", help="Query, exact name, or returned family symbol identity"
            )
            command.add_argument("--limit", type=int, default=10)
        if action in {"ctx", "sym", "refs"}:
            command.add_argument(
                "--member",
                action="append",
                default=[],
                help="Restrict to a declared workspace; repeat to select several",
            )
            command.add_argument(
                "--cursor", help="Exact returned global continuation cursor"
            )
            command.add_argument(
                "--allow-partial",
                action="store_true",
                help="Explicitly return incomplete results with exclusion reasons",
            )
        if action == "refs":
            command.add_argument(
                "--direction", choices=("incoming", "outgoing"), default="outgoing"
            )
        if action == "index":
            command.add_argument("--full", action="store_true")
            command.add_argument("--defer-embeddings", action="store_true")
            command.add_argument("--require-full-coverage", action="store_true")


def _index_family(
    family: FamilyDefinition, args: argparse.Namespace
) -> tuple[dict[str, object], int]:
    """Attempt every independent index and preserve each member's outcome.

    Parameters
    ----------
    family : FamilyDefinition
        Startup-pinned member routing.
    args : argparse.Namespace
        Family index options.

    Returns
    -------
    tuple[dict[str, object], int]
        Structured per-member results and nonzero status for any failure.
    """
    members: list[dict[str, object]] = []
    failed = False
    for member in family.members:
        output = io.StringIO()
        result: dict[str, object] = {"repository": member.member.workspace}
        try:
            with member_scope(member), redirect_stdout(output):
                assert member.workspace is not None
                status = _run_index(
                    IndexCommandRequest(
                        root=member.workspace.repository_root,
                        full=args.full,
                        explain=False,
                        require_full_coverage=args.require_full_coverage,
                        defer_embeddings=args.defer_embeddings,
                        embeddings_only=False,
                        as_json=True,
                    )
                )
                result["index"] = json.loads(output.getvalue())
                if status == 0:
                    result["freshness"] = member_state(member)
                if cast("dict[str, object]", result["index"])["failures"]:
                    status = 2
                result["exit_status"] = status
                failed = failed or status != 0
        except (BackendError, OSError, RuntimeError, ValueError) as error:
            result.update({"exit_status": 2, "reason": str(error)})
            if output.getvalue():
                result["index_output"] = output.getvalue()
            failed = True
        members.append(result)
    return {
        "contract_version": "1.0.0",
        "family": family.name,
        "status": "failed" if failed else "ok",
        "members": members,
    }, 2 if failed else 0


def run_family_command(args: argparse.Namespace) -> int:
    """Dispatch explicit family operations and render repository provenance.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed family command arguments.

    Returns
    -------
    int
        Zero on successful queries or indexing, two on validation failure.
    """
    family = load_family(args.manifest)
    runtime = FamilyRuntime(family)
    action = args.family_action
    status = 0
    if action == "index":
        response, status = _index_family(family, args)
    elif action in {"status", "validate"}:
        response = runtime.status()
        if action == "validate":
            for link in family.links:
                runtime.query(
                    "references",
                    link.source.name,
                    repositories=(link.source.workspace,),
                )
            status = (
                2 if cast("dict[str, object]", response["result"])["excluded"] else 0
            )
    elif action == "evidence":
        response = runtime.evidence(args.query, limit=args.limit)
    else:
        operation = {"ctx": "context", "sym": "symbol", "refs": "references"}[action]
        response = runtime.query(
            cast("FamilyOperation", operation),
            args.query,
            repositories=tuple(args.member),
            cursor=args.cursor,
            limit=args.limit,
            allow_partial=args.allow_partial,
            direction=getattr(args, "direction", "outgoing"),
        )
    # JSON is also the readable default: it retains complete evidence and origin.
    print(json.dumps(response, indent=2, sort_keys=True))
    return status
