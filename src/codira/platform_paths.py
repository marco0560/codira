"""Derive Codira-owned platform directories from one injected provider.

Responsibilities
----------------
- Centralize user configuration, data, state, cache, and runtime locations.
- Derive managed-runtime, workspace, and model subtrees deterministically.
- Keep platform-directory lookup injectable for isolated platform-model tests.

Architectural role
------------------
This module belongs to the **runtime environment layer** and supplies paths to
future workspace, installer, service, and model-store contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import platformdirs

APP_NAME = "codira"


class PlatformDirectoryProvider(Protocol):
    """
    Describe the platformdirs paths required by Codira.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Protocol declarations do not return values.
    """

    @property
    def user_cache_path(self) -> Path:
        """Return the user cache directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Platform-specific cache directory.
        """

    @property
    def user_config_path(self) -> Path:
        """Return the user configuration directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Platform-specific configuration directory.
        """

    @property
    def user_data_path(self) -> Path:
        """Return the user data directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Platform-specific persistent-data directory.
        """

    @property
    def user_runtime_path(self) -> Path:
        """Return the user runtime directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Platform-specific runtime directory.
        """

    @property
    def user_state_path(self) -> Path:
        """Return the user state directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Platform-specific persistent-state directory.
        """


@dataclass(frozen=True)
class PlatformPaths:
    """
    Canonical Codira platform roots and owned subtrees.

    Parameters
    ----------
    config_root : pathlib.Path
        User configuration root.
    data_root : pathlib.Path
        User persistent-data root.
    state_root : pathlib.Path
        User persistent-state root.
    cache_root : pathlib.Path
        User cache root.
    runtime_root : pathlib.Path
        User runtime-files root.
    managed_runtime_root : pathlib.Path
        Persistent root for managed Codira runtime installations.
    workspace_config_root : pathlib.Path
        Root containing workspace descriptors.
    workspace_state_root : pathlib.Path
        Root containing per-workspace mutable state.
    model_root : pathlib.Path
        Root for shared immutable model artifacts.
    """

    config_root: Path
    data_root: Path
    state_root: Path
    cache_root: Path
    runtime_root: Path
    managed_runtime_root: Path
    workspace_config_root: Path
    workspace_state_root: Path
    model_root: Path


def platform_paths(*, dirs: PlatformDirectoryProvider | None = None) -> PlatformPaths:
    """
    Resolve all Codira platform paths without creating directories.

    Parameters
    ----------
    dirs : PlatformDirectoryProvider | None, optional
        Platform path provider. ``None`` selects the current host provider.

    Returns
    -------
    PlatformPaths
        Deterministic user-level roots and Codira-owned subtrees.
    """
    provider: PlatformDirectoryProvider = dirs or platformdirs.PlatformDirs(APP_NAME)
    config_root = Path(provider.user_config_path)
    data_root = Path(provider.user_data_path)
    state_root = Path(provider.user_state_path)
    cache_root = Path(provider.user_cache_path)
    runtime_root = Path(provider.user_runtime_path)
    return PlatformPaths(
        config_root=config_root,
        data_root=data_root,
        state_root=state_root,
        cache_root=cache_root,
        runtime_root=runtime_root,
        managed_runtime_root=data_root / "runtimes",
        workspace_config_root=config_root / "workspaces",
        workspace_state_root=state_root / "workspaces",
        model_root=cache_root / "models",
    )
