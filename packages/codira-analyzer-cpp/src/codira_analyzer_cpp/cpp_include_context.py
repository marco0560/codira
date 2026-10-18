"""Capture literal C++ include inputs without invoking a build tool.

Parameters
----------
None

Returns
-------
None
    Immutable source snapshots and dependency fingerprints for later analysis.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass
from pathlib import Path

from .cpp_syntax import _new_parser


@dataclass(frozen=True)
class IncludedSource:
    """Retain one contained header and its first source include boundary.

    Parameters
    ----------
    path : pathlib.Path
        Resolved path inside the repository.
    source : bytes
        Exact bytes read for this snapshot.
    available_after : int
        End offset of the earliest source include reaching this header.

    Returns
    -------
    None
        Immutable dependency source.
    """

    path: Path
    source: bytes
    available_after: int


@dataclass(frozen=True)
class IncludeContext:
    """Bind original source bytes to observed literal include dependencies.

    Parameters
    ----------
    source : bytes
        Original translation-unit bytes, kept separate from its dependencies.
    headers : tuple[IncludedSource, ...]
        Each resolved dependency once, ordered by first availability and path.
    fingerprint : str
        Digest of exact dependency bytes, resolution outcomes and search paths.
    unresolved : tuple[tuple[str, str, str], ...]
        Including relative path, literal or macro text, and resolution status.

    Returns
    -------
    None
        Immutable context; unresolved entries do not imply malformed source.
    """

    source: bytes
    headers: tuple[IncludedSource, ...]
    fingerprint: str
    unresolved: tuple[tuple[str, str, str], ...]


def _includes(source: bytes) -> list[tuple[str, bool | None, int]]:
    """Read literal include directives from syntax nodes, including branches.

    Parameters
    ----------
    source : bytes
        Original file bytes.

    Returns
    -------
    list[tuple[str, bool | None, int]]
        Include spelling, quoted/system/macro mode, and directive end offset.
        Comments and literals containing directive-shaped text are excluded.
    """
    pending = [_new_parser().parse(source).root_node]
    result: list[tuple[str, bool | None, int]] = []
    while pending:
        node = pending.pop()
        if node.type != "preproc_include":
            pending.extend(reversed(node.children))
            continue
        path = node.child_by_field_name("path")
        if path is None:
            result.append(
                (
                    source[node.start_byte : node.end_byte].decode(
                        "utf-8", "surrogateescape"
                    ),
                    None,
                    node.end_byte,
                )
            )
            continue
        text = source[path.start_byte : path.end_byte].decode(
            "utf-8", "surrogateescape"
        )
        if (
            path.type == "string_literal"
            and text.startswith('"')
            and text.endswith('"')
        ):
            result.append((text[1:-1], True, node.end_byte))
        elif path.type == "system_lib_string":
            result.append((text[1:-1], False, node.end_byte))
        else:
            result.append((text, None, node.end_byte))
    return result


def read_include_context(
    path: Path, root: Path, *, include_paths: tuple[Path, ...] = ()
) -> IncludeContext:
    """Snapshot repository-contained literal includes and their resolution.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit whose bytes and include graph are captured.
    root : pathlib.Path
        Repository boundary; no dependency outside it is read.
    include_paths : tuple[pathlib.Path, ...], optional
        Explicit ordered search roots, relative to the repository or absolute
        inside it. Quoted includes first search the including file's directory.
        System includes search only these explicit roots.

    Returns
    -------
    IncludeContext
        Exact snapshots and an input fingerprint. Missing, external and macro
        includes remain explicit unresolved observations; branches are not chosen.

    Raises
    ------
    ValueError
        If the source or an explicit search root escapes the repository.
    OSError
        If the translation unit cannot be read. Header read errors are recorded.
    """
    root = root.resolve()
    path = path.resolve()
    search = tuple((root / item).resolve() for item in include_paths)
    if not path.is_relative_to(root) or any(
        not item.is_relative_to(root) for item in search
    ):
        raise ValueError("C++ include inputs must remain inside the repository")
    source = path.read_bytes()
    snapshots: dict[Path, IncludedSource] = {}
    observations: list[tuple[str, str, str, str]] = []
    unresolved: list[tuple[str, str, str]] = []
    pending: list[tuple[int, str, Path, bytes]] = [(0, path.as_posix(), path, source)]
    visited = {path}
    while pending:
        available_after, _, including, content = heapq.heappop(pending)
        if (
            including != path
            and snapshots[including].available_after != available_after
        ):
            continue
        for spelling, quoted, end in _includes(content):
            owner = including.relative_to(root).as_posix()
            if quoted is None:
                observations.append((owner, spelling, "macro", ""))
                unresolved.append((owner, spelling, "macro"))
                continue
            candidates = ((including.parent,) if quoted else ()) + search
            resolved: Path | None = None
            status = "missing" if quoted or search else "external"
            for directory in candidates:
                try:
                    candidate = (directory / spelling).resolve()
                    if not candidate.is_relative_to(root):
                        status = "outside_root"
                        break
                    if candidate.is_file():
                        resolved = candidate
                        break
                except OSError as exc:
                    status = f"resolution_error:{exc.errno}"
                    break
            if resolved is None:
                observations.append((owner, spelling, status, ""))
                unresolved.append((owner, spelling, status))
                continue
            target = resolved.relative_to(root).as_posix()
            observations.append((owner, spelling, "resolved", target))
            boundary = end if including == path else available_after
            if resolved in visited:
                prior = snapshots.get(resolved)
                if prior is not None and boundary < prior.available_after:
                    snapshots[resolved] = IncludedSource(
                        resolved, prior.source, boundary
                    )
                    heapq.heappush(pending, (boundary, target, resolved, prior.source))
                continue
            try:
                header = resolved.read_bytes()
            except OSError as exc:
                status = f"read_error:{exc.errno}"
                observations.append((owner, spelling, status, target))
                unresolved.append((owner, spelling, status))
                continue
            visited.add(resolved)
            snapshots[resolved] = IncludedSource(resolved, header, boundary)
            heapq.heappush(pending, (boundary, target, resolved, header))
    headers = tuple(
        sorted(snapshots.values(), key=lambda item: (item.available_after, item.path))
    )
    payload = {
        "format": 1,
        "source_path": path.relative_to(root).as_posix(),
        "search": [item.relative_to(root).as_posix() for item in search],
        "observations": observations,
        "headers": [
            (
                item.path.relative_to(root).as_posix(),
                hashlib.sha256(item.source).hexdigest(),
                item.available_after,
            )
            for item in headers
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
    return IncludeContext(source, headers, fingerprint, tuple(unresolved))
