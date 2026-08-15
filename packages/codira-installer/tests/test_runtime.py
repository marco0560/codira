"""Tests for managed-runtime receipts and launchers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from codira_installer.runtime import RuntimeReceipt, write_launchers, write_receipt

if TYPE_CHECKING:
    from pathlib import Path


def test_receipt_and_launchers_are_deterministic(tmp_path: Path) -> None:
    """Persist immutable installation choices and all standalone launchers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary managed runtime root.

    Returns
    -------
    None
        The test asserts receipt payload and launcher identity are stable.
    """
    runtime = tmp_path / "runtime"
    receipt = RuntimeReceipt(
        source="pypi",
        profile="recommended",
        version="1.55.0",
        packages=("codira-backend-sqlite",),
    )

    path = write_receipt(runtime, receipt)
    launchers = write_launchers(runtime)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "packages": ["codira-backend-sqlite"],
        "profile": "recommended",
        "source": "pypi",
        "version": "1.55.0",
    }
    assert tuple(path.name for path in launchers) == (
        "codira",
        "codira-mcp",
        "codira-installer",
    )
    assert all(path.stat().st_mode & 0o111 for path in launchers)
