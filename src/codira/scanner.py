"""Filesystem and Git-backed file discovery helpers for indexing.

Responsibilities
----------------
- Walk repository directories, apply gitignore patterns, and filter canonical source directories.
- Build cross-language discovery globs and evaluate analyzer predicates.
- Provide predicate helpers for ignore matching and coverage instrumentation.

Design principles
-----------------
Scanner logic relies solely on git and filesystem state to stay deterministic and consistent with cleanup rules.

Architectural role
------------------
This module belongs to the **scanner layer** that feeds eligible files into the indexer and analyzers.
"""

from __future__ import annotations

import fnmatch
import hashlib
import shutil
import subprocess
from typing import TYPE_CHECKING

from codira.repository_scope import is_repository_scope_excluded

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer


CANONICAL_SOURCE_DIRS: tuple[str, ...] = ("src", "tests", "scripts")
GIT_EXE = shutil.which("git") or "git"


def discovery_file_globs(analyzers: Sequence[LanguageAnalyzer]) -> tuple[str, ...]:
    """
    Return deterministic file-discovery globs for the active analyzers.

    Parameters
    ----------
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Analyzer instances participating in the current indexing or query
        operation.

    Returns
    -------
    tuple[str, ...]
        Deduplicated discovery globs in analyzer-registration order.

    Raises
    ------
    ValueError
        If no discovery globs are declared.
    """
    globs: list[str] = []
    seen: set[str] = set()

    for analyzer in analyzers:
        for pattern in analyzer.discovery_globs:
            normalized_pattern = str(pattern).strip()
            if not normalized_pattern or normalized_pattern in seen:
                continue
            seen.add(normalized_pattern)
            globs.append(normalized_pattern)

    if globs:
        return tuple(globs)

    msg = "No analyzer discovery globs are registered for codira"
    raise ValueError(msg)


def _load_gitignore(root: Path) -> list[str]:
    """
    Load raw ignore patterns from ``.gitignore``.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.

    Returns
    -------
    list[str]
        Non-comment, non-empty ignore patterns.
    """
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return []

    patterns: list[str] = []
    for line in gitignore.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _match_gitignore(path: Path, root: Path, patterns: list[str]) -> bool:
    """
    Check whether a path matches any loaded ignore patterns.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path to evaluate.
    root : pathlib.Path
        Repository root used to compute relative paths.
    patterns : list[str]
        Ignore patterns loaded from ``.gitignore``.

    Returns
    -------
    bool
        ``True`` when the path matches at least one pattern.
    """
    rel = path.relative_to(root).as_posix()

    for pat in patterns:
        if pat.endswith("/"):
            if any(part == pat.rstrip("/") for part in path.parts):
                return True
        elif fnmatch.fnmatch(rel, pat):
            return True

    return False


def _is_excluded(path: Path, root: Path, patterns: list[str]) -> bool:
    """
    Decide whether a path should be excluded from scanning.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path to evaluate.
    root : pathlib.Path
        Repository root used to compute relative paths.
    patterns : list[str]
        Ignore patterns loaded from ``.gitignore``.

    Returns
    -------
    bool
        ``True`` when the path belongs to an excluded directory or matches
        an ignore pattern.
    """
    if is_repository_scope_excluded(path, root):
        return True

    return bool(_match_gitignore(path, root, patterns))


def _iter_source_files(
    root: Path,
    *,
    discovery_globs: Sequence[str],
    analyzers: Sequence[LanguageAnalyzer],
) -> Iterator[Path]:
    """
    Yield supported source files from a filesystem scan.

    Parameters
    ----------
    root : pathlib.Path
        Repository root to scan recursively.
    discovery_globs : collections.abc.Sequence[str]
        Filename patterns contributed by the active analyzers.
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Active analyzers used to confirm that a discovered path is actually
        claimed.

    Yields
    ------
    pathlib.Path
        Supported source files that survive exclusion filtering and are claimed
        by at least one active analyzer.
    """
    patterns = _load_gitignore(root)

    seen: set[Path] = set()
    for pattern in discovery_globs:
        for path in root.rglob(pattern):
            if path in seen:
                continue
            seen.add(path)
            if _is_excluded(path, root, patterns):
                continue
            if not any(analyzer.supports_path(path) for analyzer in analyzers):
                continue
            yield path


def iter_project_files(
    root: Path,
    *,
    analyzers: Sequence[LanguageAnalyzer],
) -> Iterator[Path]:
    """
    Yield supported source files for indexing.

    Parameters
    ----------
    root : pathlib.Path
        Repository root to inspect.
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Active analyzers whose discovery globs define eligible source files.

    Returns
    -------
    collections.abc.Iterator[pathlib.Path]
        Supported source files selected for indexing.

    Raises
    ------
    subprocess.CalledProcessError
        If ``git ls-files`` fails for a reason other than "not a git
        repository".

    Notes
    -----
    If the root is inside a Git repository, only tracked supported source
    files are used so Git remains the source of truth. Outside Git
    repositories, the function falls back to a filesystem scan filtered by
    ``.gitignore`` rules.
    """
    try:
        result = subprocess.run(
            [GIT_EXE, "ls-files", "--cached", *discovery_file_globs(analyzers)],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )

        files = [
            root / line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        supported_files = [
            path
            for path in sorted(files)
            if not is_repository_scope_excluded(path, root)
            and any(analyzer.supports_path(path) for analyzer in analyzers)
        ]
        return iter(supported_files)

    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        # fallback only if git is unavailable or not a repository
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = (exc.stderr or "").lower()
            if "not a git repository" not in stderr:
                raise

        return iter(
            sorted(
                _iter_source_files(
                    root,
                    discovery_globs=discovery_file_globs(analyzers),
                    analyzers=analyzers,
                )
            )
        )


def file_metadata(path: Path) -> dict[str, object]:
    """
    Collect stable metadata for a file.

    Parameters
    ----------
    path : pathlib.Path
        File whose metadata should be collected.

    Returns
    -------
    dict[str, object]
        File path, hash, modification time, and size.
    """
    data = path.read_bytes()
    return {
        "path": str(path),
        "hash": hashlib.sha256(data).hexdigest(),
        "mtime": path.stat().st_mtime,
        "size": path.stat().st_size,
    }


def _iter_canonical_files_from_filesystem(root: Path) -> Iterator[Path]:
    """
    Yield files under canonical source directories outside Git repositories.

    Parameters
    ----------
    root : pathlib.Path
        Repository root to inspect.

    Yields
    ------
    pathlib.Path
        Files under canonical directories that survive exclusion filtering.
    """
    patterns = _load_gitignore(root)
    seen: set[Path] = set()

    for dirname in CANONICAL_SOURCE_DIRS:
        base_dir = root / dirname
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*"):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if _is_excluded(path, root, patterns):
                continue
            yield path


def iter_canonical_project_files(root: Path) -> Iterator[Path]:
    """
    Yield tracked files under canonical source directories.

    Parameters
    ----------
    root : pathlib.Path
        Repository root to inspect.

    Returns
    -------
    collections.abc.Iterator[pathlib.Path]
        Deterministically ordered files under ``src/``, ``tests/``, and
        ``scripts/``.

    Raises
    ------
    subprocess.CalledProcessError
        If ``git ls-files`` fails for a reason other than "not a git
        repository".
    """
    try:
        result = subprocess.run(
            [GIT_EXE, "ls-files", "--cached", "--", *CANONICAL_SOURCE_DIRS],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        files = [
            root / line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        return iter(
            sorted(
                path
                for path in files
                if path.is_file() and not is_repository_scope_excluded(path, root)
            )
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = (exc.stderr or "").lower()
            if "not a git repository" not in stderr:
                raise

        return iter(sorted(_iter_canonical_files_from_filesystem(root)))
