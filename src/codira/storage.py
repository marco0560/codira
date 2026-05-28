"""Backend-neutral local storage path, metadata, and lock helpers.

Responsibilities
----------------
- Resolve repository-local storage paths through optional storage-root overrides.
- Persist index metadata atomically for whichever backend owns the index files.
- Provide cross-process advisory locking for index mutations.

Design principles
-----------------
Storage helpers keep persistence deterministic, backend-neutral, and limited to filesystem coordination.

Architectural role
------------------
This module belongs to the **storage infrastructure layer** shared by backend plugins and CLI workflows.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import tempfile
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Protocol

    class _FcntlModule(Protocol):
        LOCK_EX: int
        LOCK_UN: int

        def flock(self, fd: int, operation: int, /) -> None: ...

    class _MsvcrtModule(Protocol):
        LK_LOCK: int
        LK_UNLCK: int

        def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


_STORAGE_ROOT_OVERRIDES: ContextVar[dict[Path, Path] | None] = ContextVar(
    "_STORAGE_ROOT_OVERRIDES",
    default=None,
)


def _read_metadata_file(path: Path) -> dict[str, str]:
    """
    Load persisted index metadata from one JSON file.

    Parameters
    ----------
    path : pathlib.Path
        Metadata JSON path to decode.

    Returns
    -------
    dict[str, str]
        Parsed metadata values, or an empty mapping when the file does not
        exist or cannot be decoded.
    """
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_metadata_file(path: Path, data: dict[str, str]) -> None:
    """
    Persist index metadata atomically as JSON.

    Parameters
    ----------
    path : pathlib.Path
        Metadata JSON path to replace.
    data : dict[str, str]
        Metadata payload to serialize.

    Returns
    -------
    None
        The metadata file is replaced atomically in place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temp_path = Path(handle.name)
    temp_path.replace(path)


def get_index_lock_path(root: Path) -> Path:
    """
    Return the advisory lock path used for index mutations.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``index.lock`` file under ``.codira``.
    """
    return get_codira_dir(root) / "index.lock"


def get_storage_root(root: Path) -> Path:
    """
    Return the effective storage root for one repository target root.

    Parameters
    ----------
    root : pathlib.Path
        Repository target root.

    Returns
    -------
    pathlib.Path
        Effective storage root after applying any active CLI override.
    """

    resolved_root = root.resolve()
    overrides = _STORAGE_ROOT_OVERRIDES.get()
    if overrides is None:
        return resolved_root
    return overrides.get(resolved_root, resolved_root)


@contextlib.contextmanager
def override_storage_root(root: Path, storage_root: Path) -> Iterator[None]:
    """
    Temporarily route ``.codira`` storage for one target root elsewhere.

    Parameters
    ----------
    root : pathlib.Path
        Repository target root used for reads and prefix normalization.
    storage_root : pathlib.Path
        Output root under which ``.codira`` state should be read and written.

    Yields
    ------
    None
        Control while the storage override remains active.
    """

    current = _STORAGE_ROOT_OVERRIDES.get()
    overrides = {} if current is None else dict(current)
    overrides[root.resolve()] = storage_root.resolve()
    token = _STORAGE_ROOT_OVERRIDES.set(overrides)
    try:
        yield
    finally:
        _STORAGE_ROOT_OVERRIDES.reset(token)


def _lock_file_handle(handle: TextIO) -> None:
    """
    Acquire an exclusive advisory lock on an open lock file.

    Parameters
    ----------
    handle : object
        Open text file handle exposing ``fileno`` and ``seek``.

    Returns
    -------
    None
        The call returns after the exclusive lock is held.
    """

    if os.name == "nt":
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl as _fcntl

    fcntl = cast("_FcntlModule", _fcntl)
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file_handle(handle: TextIO) -> None:
    """
    Release an advisory lock on an open lock file.

    Parameters
    ----------
    handle : object
        Open text file handle exposing ``fileno`` and ``seek``.

    Returns
    -------
    None
        The lock is released in place.
    """

    if os.name == "nt":
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl as _fcntl

    fcntl = cast("_FcntlModule", _fcntl)
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def acquire_index_lock(root: Path) -> Iterator[None]:
    """
    Acquire the advisory cross-process lock for index mutations.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose local index should be locked.

    Yields
    ------
    None
        Control while the exclusive lock is held.
    """
    lock_path = get_index_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        handle.seek(0)
        handle.write("0")
        handle.flush()
        _lock_file_handle(handle)
        try:
            yield
        finally:
            _unlock_file_handle(handle)


def get_codira_dir(root: Path) -> Path:
    """
    Return the repository-local storage directory.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``.codira`` directory under the effective storage root.
    """
    return get_storage_root(root) / ".codira"


def get_metadata_path(root: Path) -> Path:
    """
    Return the metadata JSON path for a repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    pathlib.Path
        Path to the ``metadata.json`` file under ``.codira``.
    """
    return get_codira_dir(root) / "metadata.json"
