"""Shared pytest fixtures for repository-wide test isolation.

Responsibilities
----------------
- Neutralize ambient backend-selection environment variables that would
  otherwise leak into unrelated tests.
- Provide an explicit helper for tests that need to select one backend.

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

    Returns
    -------
    collections.abc.Iterator[None]
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
