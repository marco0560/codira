"""Tests for the commit-message validator script.

Responsibilities
----------------
- Load `scripts/check_commit_messages.py` as a module and emulate commit headers with various scopes.
- Assert invalid scope formats are rejected and release-safe scopes are accepted.

Design principles
-----------------
Validation tests keep the commit guardrails deterministic and focused on scope syntax rules.

Architectural role
------------------
This module belongs to the **tooling verification layer** and protects commit validator behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _load_module() -> ModuleType:
    """
    Load the validator script as a module.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Imported module object for ``scripts/check_commit_messages.py``.
    """
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_commit_messages.py"
    )
    spec = importlib.util.spec_from_file_location("check_commit_messages", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_commit_msg_hook() -> ModuleType:
    """
    Load the local commit-msg hook validator as a module.

    Parameters
    ----------
    None

    Returns
    -------
    types.ModuleType
        Imported module object for ``.githooks/commit-msg.py``.
    """
    script_path = Path(__file__).resolve().parents[1] / ".githooks" / "commit-msg.py"
    spec = importlib.util.spec_from_file_location("commit_msg_hook", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_header_rejects_comma_in_scope() -> None:
    """
    Ensure comma-separated scopes are rejected.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that comma-separated scopes are rejected.
    """
    module = _load_module()
    commit = module.CommitHeader(
        sha="4423ab5668861c1710781b06c97421c888706ddd",
        header="feat(context,json-schema): introduce schema v1.1 validation",
        scope="context,json-schema",
    )

    error = module.validate_header(commit)

    assert error is not None
    assert "invalid scope" in error


def test_validate_header_accepts_release_safe_scope() -> None:
    """
    Ensure release-safe scope characters are accepted.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that release-safe scopes are accepted.
    """
    module = _load_module()
    commit = module.CommitHeader(
        sha="4d38c4df70b2e20860fd581f93ded50c570bad75",
        header="feat(context/json-schema): introduce schema v1.1 validation",
        scope="context/json-schema",
    )

    assert module.validate_header(commit) is None


def test_commit_msg_hook_accepts_codira_scope() -> None:
    """
    Accept a Conventional Commit header with a codira-specific scope.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the local Git hook accepts documented codira scopes.
    """
    module = _load_commit_msg_hook()

    assert module.validate_header("fix(indexer): ignore typed coverage marker") is None


def test_commit_msg_hook_rejects_unknown_scope() -> None:
    """
    Reject a Conventional Commit header with a foreign scope.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the local Git hook rejects scopes outside the codira
        scope list.
    """
    module = _load_commit_msg_hook()

    assert module.validate_header("fix(catalog): update font inventory") == (
        "scope 'catalog' not admitted"
    )
