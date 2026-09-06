"""Canonical package-layout expectations for bootstrap-script tests.

The helpers render the repository's expected first-party package order for
monorepo and exported split-repository command assertions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


EXPECTED_FIRST_PARTY_PACKAGE_DIRS: tuple[str, ...] = (
    "packages/codira-analyzer-python",
    "packages/codira-analyzer-json",
    "packages/codira-analyzer-c",
    "packages/codira-analyzer-cpp",
    "packages/codira-analyzer-rust",
    "packages/codira-analyzer-javascript",
    "packages/codira-analyzer-typescript",
    "packages/codira-analyzer-go",
    "packages/codira-analyzer-bash",
    "packages/codira-analyzer-markdown",
    "packages/codira-analyzer-text",
    "packages/codira-documentation-audit-numpy",
    "packages/codira-documentation-audit-google",
    "packages/codira-documentation-audit-doxygen",
    "packages/codira-documentation-audit-rustdoc",
    "packages/codira-documentation-audit-jsdoc",
    "packages/codira-documentation-audit-tsdoc",
    "packages/codira-documentation-audit-go-doc-comments",
    "packages/codira-backend-sqlite",
    "packages/codira-backend-duckdb",
    "packages/codira-embedding-sentence-transformers",
    "packages/codira-embedding-onnx",
    "packages/codira-vector-store-sqlite",
    "packages/codira-vector-store-duckdb",
    "packages/codira-similarity-index-faiss",
    "packages/codira-similarity-index-qdrant",
    "packages/codira-installer",
    "packages/codira-bundle-official",
)
EXPECTED_NON_BUNDLE_PACKAGE_DIRS: tuple[str, ...] = tuple(
    item
    for item in EXPECTED_FIRST_PARTY_PACKAGE_DIRS
    if item != "packages/codira-bundle-official"
)


def _expected_monorepo_package_paths(
    root: Path,
    *,
    include_bundle: bool = True,
) -> tuple[Path, ...]:
    """
    Return expected monorepo package paths in release/install order.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to resolve package directories.
    include_bundle : bool, optional
        Whether to include the curated bundle package path.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Expected package paths.
    """
    entries = (
        EXPECTED_FIRST_PARTY_PACKAGE_DIRS
        if include_bundle
        else EXPECTED_NON_BUNDLE_PACKAGE_DIRS
    )
    return tuple(root / relative for relative in entries)


def _expected_split_package_paths(
    package_root: Path,
    *,
    include_bundle: bool = True,
) -> tuple[Path, ...]:
    """
    Return expected split-repository package paths in release/install order.

    Parameters
    ----------
    package_root : pathlib.Path
        Directory containing split first-party repositories.
    include_bundle : bool, optional
        Whether to include the curated bundle package path.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Expected split package paths.
    """
    entries = (
        EXPECTED_FIRST_PARTY_PACKAGE_DIRS
        if include_bundle
        else EXPECTED_NON_BUNDLE_PACKAGE_DIRS
    )
    return tuple(
        package_root / relative.removeprefix("packages/") for relative in entries
    )


def _editable_args(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """
    Render editable-install argument pairs for expected package paths.

    Parameters
    ----------
    paths : tuple[pathlib.Path, ...]
        Package paths to render.

    Returns
    -------
    tuple[str, ...]
        Flattened ``-e`` and path argument pairs.
    """
    args: list[str] = []
    for path in paths:
        args.extend(("-e", str(path)))
    return tuple(args)
