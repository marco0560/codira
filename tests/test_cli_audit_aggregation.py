"""Tests for CLI docstring-audit aggregation output."""

from pathlib import Path
from typing import Any

import pytest

from codira.cli import _run_audit_docstrings


def test_missing_parameter_aggregation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Group missing-parameter rows for the same function and location.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to replace the docstring issue provider.
    capsys : pytest.CaptureFixture[str]
        Pytest fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the plain audit output aggregates parameter names.
    """
    rows = [
        (
            "missing_parameter",
            "Parameter not documented: family",
            "id1",
            "function",
            "mod",
            "run_saved_query",
            "/tmp/file.py",
            10,
            None,
        ),
        (
            "missing_parameter",
            "Parameter not documented: font_path",
            "id2",
            "function",
            "mod",
            "run_saved_query",
            "/tmp/file.py",
            10,
            None,
        ),
    ]

    def fake_docstring_issues(root: Path, prefix: str | None = None) -> list[Any]:
        return rows

    monkeypatch.setattr("codira.cli.docstring_issues", fake_docstring_issues)

    # Act
    exit_code = _run_audit_docstrings(Path())

    # Assert
    captured = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 0
    assert len(captured) == 1
    assert (
        captured[0]
        == "missing_parameter: Function run_saved_query: Parameters not documented: family, font_path [/tmp/file.py:10]"
    )
