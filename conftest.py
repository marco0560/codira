"""Shared pytest fixtures for repository-wide test isolation.

Responsibilities
----------------
- Neutralize ambient backend-selection environment variables that would
  otherwise leak into unrelated tests.
- Provide an explicit helper for tests that need to select one backend.
- Observe asynchronous descendant termination with a bounded shared assertion.

Design principles
-----------------
Fixtures keep backend selection deterministic per test and reset registry
plugin caches whenever backend-related environment changes occur.

Architectural role
------------------
This module belongs to the **test harness layer** and stabilizes repository
tests across different operator shell environments.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from codira import registry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture(autouse=True)
def _isolate_index_backend_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """
    Remove ambient backend overrides before each test runs.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate process-local environment changes.

    Yields
    ------
    None
        Fixture lifetime surrounding one test execution.
    """
    monkeypatch.delenv(registry.INDEX_BACKEND_ENV_VAR, raising=False)
    registry.reset_plugin_registry_caches()
    yield
    registry.reset_plugin_registry_caches()


@pytest.fixture
def set_index_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str | None], None]:
    """
    Set or clear the active index backend for one test.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate process-local environment changes.

    Returns
    -------
    collections.abc.Callable[[str | None], None]
        Helper that applies the requested backend selection and refreshes
        cached registry state immediately.
    """

    def _set(backend_name: str | None) -> None:
        """
        Apply one backend selection for the current test process.

        Parameters
        ----------
        backend_name : str | None
            Backend name to export, or ``None`` to clear the override.

        Returns
        -------
        None
            The environment and registry caches are updated in place.
        """
        if backend_name is None:
            monkeypatch.delenv(registry.INDEX_BACKEND_ENV_VAR, raising=False)
        else:
            monkeypatch.setenv(registry.INDEX_BACKEND_ENV_VAR, backend_name)
        registry.reset_plugin_registry_caches()

    return _set


def _assert_process_terminated(pid: int) -> None:
    """Wait for a signalled process to disappear or become a zombie.

    Parameters
    ----------
    pid : int
        Positive identifier captured from an owned test subprocess.

    Returns
    -------
    None
        The process reaches a terminal state within two seconds. A surviving
        process fails the assertion; procfs disappearance races count as exit.
    """
    assert pid > 0
    process_state = Path(f"/proc/{pid}/stat")
    deadline = time.monotonic() + 2
    while True:
        try:
            state = process_state.read_text().split(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return
        if state == "Z":
            return
        assert time.monotonic() < deadline, f"owned descendant {pid} survived"
        time.sleep(0.01)


@pytest.fixture
def assert_process_terminated() -> Callable[[int], None]:
    """Provide a bounded process-termination assertion for lifecycle tests.

    Parameters
    ----------
    None

    Returns
    -------
    collections.abc.Callable[[int], None]
        Shared observer that retains the terminal-state requirement while
        allowing asynchronous signal delivery and process cleanup to finish.
    """
    return _assert_process_terminated
