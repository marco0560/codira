"""Backend-neutral failure snapshots and reader coverage metadata.

Parameters
----------
None

Returns
-------
None
    Shared publication diagnostics for CLI and MCP readers.
"""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import TYPE_CHECKING

from codira.config import load_effective_config
from codira.index_generation import IndexGenerationStore
from codira.plugin_config import analyzer_inventory_discovery_json
from codira.registry import active_index_backend, active_language_analyzers
from codira.runtime_identity import runtime_identity
from codira.storage import _read_metadata_file, get_metadata_path

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_RESPONSE_ROOT: ContextVar[Path | None] = ContextVar(
    "index_coverage_root", default=None
)
PARTIAL_INDEX_MESSAGE = (
    "The ready index omitted one or more failed source files. "
    "Results describe indexed content only; absence is not repository-wide evidence."
)


def analysis_fingerprint(root: Path) -> str:
    """Hash effective configuration and analyzer identity for failure reuse.

    Parameters
    ----------
    root : pathlib.Path
        Repository whose effective configuration is active.

    Returns
    -------
    str
        Digest binding snapshots to the generation format and analysis inputs.
    """
    inventory = [
        (str(a.name), str(a.version), analyzer_inventory_discovery_json(a))
        for a in sorted(active_language_analyzers(root=root), key=lambda a: str(a.name))
    ]
    backend = active_index_backend(root=root)
    payload = {
        "format": 2,
        "backend": [str(backend.name), str(backend.version)],
        "config": asdict(load_effective_config(root=root)),
        "analyzers": inventory,
        "runtime": runtime_identity(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def index_coverage(root: Path) -> dict[str, object]:
    """Describe published coverage without equating absence with completeness.

    Parameters
    ----------
    root : pathlib.Path
        Repository owning the effective index state.

    Returns
    -------
    dict[str, object]
        Usability, selected-file coverage, and retained failed paths.
    """
    store = IndexGenerationStore(root)
    record = store.read()
    metadata = _read_metadata_file(get_metadata_path(root))
    count = metadata.get("indexed_file_count")
    indexed = (
        (0 if record is None else record.indexed_file_count or 0)
        if count is None
        else int(count)
        if count.isdecimal()
        else 0
    )
    partial = record is not None and record.partial
    usable = (
        indexed > 0
        and not (store.path.exists() and record is None)
        and (
            record is None
            or record.state == "ready"
            and (
                record.indexed_file_count is None
                or record.indexed_file_count == indexed
            )
        )
    )
    return {
        "usable": usable,
        "partial": partial,
        "complete": usable
        and not partial
        and (record is None or record.coverage_complete),
        "scope": "selected analyzer-supported files",
        "repository_wide_completeness": "not_established",
        "indexed_file_count": indexed,
        "attempted_file_count": None if record is None else record.attempted_file_count,
        "failed_file_count": 0 if record is None else record.failed_file_count,
        "failed_paths": []
        if record is None
        else [f["path"] for f in record.failed_files or []],
    }


def response_coverage() -> dict[str, object] | None:
    """Return coverage for the current CLI response scope.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object] | None
        Coverage metadata when rendering an index-dependent command.
    """
    root = _RESPONSE_ROOT.get()
    return None if root is None else index_coverage(root)


@contextmanager
def index_response_scope(root: Path | None, *, warn: bool = True) -> Iterator[None]:
    """Bind reader metadata and emit one human-readable partial warning.

    Parameters
    ----------
    root : pathlib.Path | None
        Repository for index-dependent commands, or no coverage binding.
    warn : bool, optional
        Emit the diagnostic to stderr on scope exit.

    Returns
    -------
    collections.abc.Iterator[None]
        Context preserving independent request-local roots.
    """
    token = _RESPONSE_ROOT.set(root)
    try:
        yield
    finally:
        try:
            coverage = None if root is None else index_coverage(root)
            if (
                warn
                and coverage is not None
                and coverage["usable"]
                and coverage["partial"]
            ):
                print(
                    f"[codira] Partial index: {PARTIAL_INDEX_MESSAGE}", file=sys.stderr
                )
        finally:
            _RESPONSE_ROOT.reset(token)
