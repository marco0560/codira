#!/usr/bin/env python3
"""Shared benchmark timing and metadata helpers.

Responsibilities
----------------
- Collect deterministic phase timing totals for benchmark scripts.
- Build benchmark artifact metadata with Codira version, plugin inventory, and Git revision.
- Write JSON artifacts without changing normal Codira CLI behavior.

Design principles
-----------------
The helper stays in the developer tooling layer so benchmark instrumentation
does not become part of the runtime command contract.

Architectural role
------------------
This module belongs to the **developer tooling layer** shared by benchmark
scripts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from codira.registry import plugin_registrations
from codira.version import installed_distribution_version, package_version

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

FIRST_PARTY_PLUGIN_PROVIDERS: tuple[str, ...] = (
    "codira-analyzer-python",
    "codira-analyzer-json",
    "codira-analyzer-c",
    "codira-analyzer-bash",
    "codira-backend-sqlite",
    "codira-backend-duckdb",
)


@dataclass
class PhaseTimer:
    """
    Accumulate elapsed seconds by stable benchmark phase name.

    Parameters
    ----------
    phase_seconds : dict[str, float], optional
        Accumulated timing values keyed by phase name.
    """

    phase_seconds: dict[str, float] = field(default_factory=dict)

    def add(self, name: str, elapsed: float) -> None:
        """
        Add one elapsed duration to a phase total.

        Parameters
        ----------
        name : str
            Stable phase name.
        elapsed : float
            Duration in seconds.

        Returns
        -------
        None
            The phase total is updated in place.
        """
        self.phase_seconds[name] = self.phase_seconds.get(name, 0.0) + elapsed

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        """
        Measure one block and accumulate its elapsed duration.

        Parameters
        ----------
        name : str
            Stable phase name.

        Yields
        ------
        None
            Control returns to the measured block.
        """
        start = perf_counter()
        try:
            yield
        finally:
            self.add(name, perf_counter() - start)

    def timed_call(
        self,
        name: str,
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        """
        Execute one callable while accumulating elapsed duration.

        Parameters
        ----------
        name : str
            Stable phase name.
        func : collections.abc.Callable[..., object]
            Callable to execute.
        *args : object
            Positional arguments forwarded to ``func``.
        **kwargs : object
            Keyword arguments forwarded to ``func``.

        Returns
        -------
        object
            Return value from ``func``.
        """
        with self.measure(name):
            return func(*args, **kwargs)

    def rounded(self) -> dict[str, float]:
        """
        Return rounded phase totals sorted by phase name.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, float]
            Phase totals rounded to six decimal places.
        """
        return {
            name: round(value, 6) for name, value in sorted(self.phase_seconds.items())
        }


def utc_run_timestamp() -> str:
    """
    Return the current UTC timestamp for benchmark artifact metadata.

    Parameters
    ----------
    None

    Returns
    -------
    str
        ISO-8601 timestamp with second precision and ``Z`` suffix.
    """
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_commit(root: Path) -> str | None:
    """
    Return the current Git commit for a repository when available.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the Git working directory.

    Returns
    -------
    str | None
        Current ``HEAD`` commit SHA, or ``None`` outside a readable Git checkout.
    """
    git_executable = shutil.which("git")
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            [git_executable, "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    commit = result.stdout.strip()
    return commit or None


def loaded_plugin_inventory() -> list[dict[str, object]]:
    """
    Return loaded plugin inventory rows for benchmark metadata.

    Parameters
    ----------
    None

    Returns
    -------
    list[dict[str, object]]
        Loaded plugin rows sorted by origin, family, name, and version.
    """
    rows: list[dict[str, object]] = []
    for registration in plugin_registrations():
        if registration.status != "loaded":
            continue
        version = (
            installed_distribution_version(registration.provider)
            or registration.version
        )
        rows.append(
            {
                "family": registration.family,
                "name": registration.name,
                "origin": registration.origin,
                "provider": registration.provider,
                "source": registration.source,
                "version": version,
            }
        )
    return sorted(
        rows,
        key=lambda item: (
            str(item["origin"]),
            str(item["family"]),
            str(item["name"]),
            str(item["version"]),
        ),
    )


def first_party_plugin_providers() -> tuple[str, ...]:
    """
    Return first-party plugin providers expected in benchmark metadata.

    Parameters
    ----------
    None

    Returns
    -------
    tuple[str, ...]
        First-party analyzer and backend distribution names.
    """
    return FIRST_PARTY_PLUGIN_PROVIDERS


def executable_available(name: str) -> bool:
    """
    Return whether an executable is available on the current PATH.

    Parameters
    ----------
    name : str
        Executable name or explicit path.

    Returns
    -------
    bool
        ``True`` when the executable can be resolved.
    """
    if "/" in name:
        return Path(name).exists()
    return shutil.which(name) is not None


def profiler_availability() -> dict[str, bool]:
    """
    Return optional profiler availability for benchmark metadata.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, bool]
        Availability flags for optional profiling tools.
    """
    return {
        "pyinstrument": executable_available("pyinstrument"),
        "snakeviz": executable_available("snakeviz"),
    }


def benchmark_metadata(
    root: Path,
    *,
    manifest: Path | None = None,
    hyperfine: str = "hyperfine",
) -> dict[str, object]:
    """
    Build common metadata included in benchmark artifacts.

    Parameters
    ----------
    root : pathlib.Path
        Repository root associated with the benchmark run.
    manifest : pathlib.Path | None, optional
        Campaign manifest path when a campaign run is used.
    hyperfine : str, optional
        Hyperfine executable name or path checked for availability.

    Returns
    -------
    dict[str, object]
        JSON-serializable metadata payload.
    """
    return {
        "run_at": utc_run_timestamp(),
        "codira_version": package_version(),
        "git_commit": git_commit(root),
        "manifest": None if manifest is None else str(manifest),
        "plugins": loaded_plugin_inventory(),
        "tools": {
            "hyperfine": executable_available(hyperfine),
            **profiler_availability(),
        },
    }


def write_json_artifact(path: Path, payload: dict[str, object]) -> None:
    """
    Write one JSON artifact with deterministic formatting.

    Parameters
    ----------
    path : pathlib.Path
        Artifact path to write.
    payload : dict[str, object]
        JSON-serializable payload.

    Returns
    -------
    None
        The artifact is written to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
