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
