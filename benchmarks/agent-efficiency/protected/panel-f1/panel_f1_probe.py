"""Protected behavioral checks for panel-f1."""

# ruff: noqa: E402, I001
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from codira.cli_parser import build_parser
from codira.query.context import ContextRequest

parser = build_parser()
assert parser.parse_args(["ctx", "probe"]).max_results == 10
for value in ("1", "100"):
    assert parser.parse_args(
        ["ctx", "probe", "--max-results", value]
    ).max_results == int(value)
for value in ("0", "101", "wrong"):
    try:
        parser.parse_args(["ctx", "probe", "--max-results", value])
    except SystemExit as e:
        assert e.code != 0
    else:
        detail = "invalid limit accepted"
        raise AssertionError(detail)
from codira.cli_queries import _run_context_command

assert "max_results" in inspect.getsource(_run_context_command)
assert ContextRequest(root=Path(), query="probe").result_limit == 10

# Exercise actual CLI-to-core forwarding; a variable name alone is not evidence.
from types import SimpleNamespace
from unittest.mock import patch
from codira import cli_queries

for count in (1, 10, 100):
    args = parser.parse_args(["ctx", "probe", "--max-results", str(count)])
    with (
        patch.object(cli_queries, "_ensure_index"),
        patch.object(
            cli_queries,
            "_route_eligible_cli_read",
            return_value=SimpleNamespace(stdout=None),
        ),
        patch.object(cli_queries, "emit_execution_mode"),
        patch.object(
            cli_queries,
            "load_effective_config",
            return_value=SimpleNamespace(
                embeddings=SimpleNamespace(
                    indexing=SimpleNamespace(max_source_file_bytes=100000)
                )
            ),
        ),
        patch.object(cli_queries, "context_for", return_value="qualified") as query,
    ):
        assert _run_context_command(args, Path(), prefix="src") == 0
    query.assert_called_once()
    request = query.call_args.args[0]
    assert request.result_limit == count
    assert request.complete_context_items is True
