"""Resolve disposable benchmark storage across workstations and CI runners.

Parameters
----------
None

Returns
-------
None
    Exposes the resolved scratch root without changing durable evidence paths.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

WORKSTATION_TEMP_ROOT = Path("/home/marco/Personalia/Progetti/.Temp")


def project_temp_root() -> Path:
    """Select and create the host directory for disposable benchmark work.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        Absolute existing directory. An explicit ``CODIRA_BENCHMARK_TEMP_ROOT``
        overrides the existing workstation root; elsewhere the platform's
        temporary directory is used, honoring its standard environment settings.

    Raises
    ------
    OSError
        If the selected directory cannot be created or is a non-directory file.
    """
    configured = os.environ.get("CODIRA_BENCHMARK_TEMP_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
    elif WORKSTATION_TEMP_ROOT.is_dir():
        root = WORKSTATION_TEMP_ROOT
    else:
        root = Path(tempfile.gettempdir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


PROJECT_TEMP_ROOT = project_temp_root()
