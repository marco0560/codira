"""Capture literal C include inputs without invoking a build tool.

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

from .c_parser import _new_parser


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
    identity : str, optional
        Versioned input manifest permitting validation without parsing C again.

    Returns
    -------
    None
        Immutable context; unresolved entries do not imply malformed source.
    """

    source: bytes
    headers: tuple[IncludedSource, ...]
    fingerprint: str
    unresolved: tuple[tuple[str, str, str], ...]
    identity: str = ""


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


def _resolve_include_path(
    spelling: str,
    quoted: bool | None,
    including: Path,
    root: Path,
    search: tuple[Path, ...],
) -> tuple[Path | None, str]:
    """Resolve one literal include inside the repository using explicit roots.

    Parameters
    ----------
    spelling : str
        Include path or unexpanded macro text.
    quoted : bool | None
        Quoted, system or macro include mode.
    including : pathlib.Path
        Canonical path of the including source.
    root : pathlib.Path
        Canonical repository boundary.
    search : tuple[pathlib.Path, ...]
        Explicit ordered search roots.

    Returns
    -------
    tuple[pathlib.Path | None, str]
        Contained selected path or a deterministic unresolved status.
    """
    if quoted is None:
        return None, "macro"
    candidates = ((including.parent,) if quoted else ()) + search
    for directory in candidates:
        try:
            candidate = (directory / spelling).resolve()
            if not candidate.is_relative_to(root):
                return None, "outside_root"
            if candidate.is_file():
                return candidate, "resolved"
        except OSError as exc:
            return None, f"resolution_error:{exc.errno}"
    return None, "missing" if quoted or search else "external"


def read_include_context(
    path: Path,
    root: Path,
    *,
    include_paths: tuple[Path, ...] = (),
    preinclude_headers: tuple[Path, ...] = (),
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

    preinclude_headers : tuple[pathlib.Path, ...], optional
        Explicit contained context headers, available before the source begins.
        Their transitive literal includes use the same search roots.

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
    preinclude = tuple((root / item).resolve() for item in preinclude_headers)
    if not path.is_relative_to(root) or any(
        not item.is_relative_to(root) for item in (*search, *preinclude)
    ):
        raise ValueError("C include inputs must remain inside the repository")
    source = path.read_bytes()
    snapshots: dict[Path, IncludedSource] = {}
    observations: list[tuple[str, str, str, str]] = []
    lookups: list[tuple[str, str, bool | None, str, str]] = []
    unresolved: list[tuple[str, str, str]] = []
    pending: list[tuple[int, str, Path, bytes]] = [(0, path.as_posix(), path, source)]
    visited = {path}
    for header_path in preinclude:
        if header_path in visited:
            continue
        header = header_path.read_bytes()
        snapshots[header_path] = IncludedSource(header_path, header, 0)
        visited.add(header_path)
        heapq.heappush(pending, (0, header_path.as_posix(), header_path, header))
    while pending:
        available_after, _, including, content = heapq.heappop(pending)
        if (
            including != path
            and snapshots[including].available_after != available_after
        ):
            continue
        for spelling, quoted, end in _includes(content):
            owner = including.relative_to(root).as_posix()
            resolved, status = _resolve_include_path(
                spelling, quoted, including, root, search
            )
            lookups.append(
                (
                    owner,
                    spelling,
                    quoted,
                    status,
                    "" if resolved is None else resolved.relative_to(root).as_posix(),
                )
            )
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
                lookups.append((owner, spelling, quoted, status, target))
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
        "preinclude": [item.relative_to(root).as_posix() for item in preinclude],
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
    identity_payload = {
        **payload,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "lookups": lookups,
    }
    checksum = hashlib.sha256(
        json.dumps(
            identity_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    identity = json.dumps(
        {**identity_payload, "manifest_sha256": checksum},
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return IncludeContext(source, headers, fingerprint, tuple(unresolved), identity)


def _contained_path(root: Path, relative: str) -> Path:
    """Validate a manifest path before reading any referenced source bytes.

    Parameters
    ----------
    root : pathlib.Path
        Canonical repository boundary.
    relative : str
        Manifest path relative to that boundary.

    Returns
    -------
    pathlib.Path
        Canonical contained path.

    Raises
    ------
    ValueError
        If the manifest references a path outside the repository.
    """
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("C input manifest escapes the repository")
    return path


def include_identity_matches(
    path: Path,
    root: Path,
    identity: str,
    *,
    include_paths: tuple[Path, ...] | None = None,
    preinclude_headers: tuple[Path, ...] | None = None,
) -> bool:
    """Check captured hashes and lookup outcomes without parsing source syntax.

    Parameters
    ----------
    path : pathlib.Path
        Translation unit being checked.
    root : pathlib.Path
        Repository resolution boundary.
    identity : str
        Previously captured canonical input manifest.
    include_paths : tuple[pathlib.Path, ...] or None, optional
        Current configured search roots, when supplied. Their resolved order
        must still match the manifest, including after a symlink changes target.

    preinclude_headers : tuple[pathlib.Path, ...] or None, optional
        Current explicitly configured context headers, including their order.

    Returns
    -------
    bool
        Whether source/header bytes and every include resolution still match.
        Malformed, unavailable or escaping manifests require fresh analysis.
    """
    try:
        payload = json.loads(identity)
        if not isinstance(payload, dict) or payload.get("format") != 1:
            return False
        checksum = payload.pop("manifest_sha256", None)
        payload.pop("configuration_fingerprint", None)
        if (
            hashlib.sha256(
                json.dumps(
                    payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            != checksum
        ):
            return False
        root = root.resolve()
        source_path = _contained_path(root, payload["source_path"])
        if source_path != path and source_path != path.resolve():
            return False
        if (
            hashlib.sha256(source_path.read_bytes()).hexdigest()
            != payload["source_sha256"]
        ):
            return False
        search = tuple(_contained_path(root, item) for item in payload["search"])
        if include_paths is not None:
            configured = tuple((root / item).resolve() for item in include_paths)
            if configured != search or any(
                not item.is_relative_to(root) for item in configured
            ):
                return False
        preinclude = tuple(
            _contained_path(root, item) for item in payload["preinclude"]
        )
        if preinclude_headers is not None:
            configured_preinclude = tuple(
                (root / item).resolve() for item in preinclude_headers
            )
            if configured_preinclude != preinclude or any(
                not item.is_relative_to(root) for item in configured_preinclude
            ):
                return False
        input_paths = {payload["source_path"]: source_path}
        for relative, digest, _ in payload["headers"]:
            header_path = _contained_path(root, relative)
            if hashlib.sha256(header_path.read_bytes()).hexdigest() != digest:
                return False
            input_paths[relative] = header_path
        for owner, spelling, quoted, status, target in payload["lookups"]:
            if quoted is not None and not isinstance(quoted, bool):
                return False
            if "error:" in status:
                return False
            selected, observed = _resolve_include_path(
                spelling, quoted, input_paths[owner], root, search
            )
            selected_name = (
                "" if selected is None else selected.relative_to(root).as_posix()
            )
            if (observed, selected_name) != (status, target):
                return False
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return True
