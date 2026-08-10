"""Tests for the canonical first-party installer catalog generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Protocol, cast


class _InstallerCatalogGenerator(Protocol):
    """Protocol for the standalone installer catalog generator."""

    CATALOG_PATH: Path

    def load_manifest(self, path: Path = ...) -> dict[str, object]:
        """Load the canonical package manifest.

        Parameters
        ----------
        path : pathlib.Path, optional
            Manifest file to load.

        Returns
        -------
        dict[str, object]
            Manifest data.
        """
        ...

    def build_catalog(self, manifest: dict[str, object]) -> dict[str, object]:
        """Build the generated catalog.

        Parameters
        ----------
        manifest : dict[str, object]
            Manifest data.

        Returns
        -------
        dict[str, object]
            Generated catalog data.
        """
        ...

    def main(self, argv: list[str] | None = ...) -> int:
        """Run the catalog generator.

        Parameters
        ----------
        argv : list[str] | None, optional
            Argument override.

        Returns
        -------
        int
            Process exit code.
        """
        ...


def _load_generator() -> _InstallerCatalogGenerator:
    """Load the generator from its repository-local script path.

    Parameters
    ----------
    None

    Returns
    -------
    _InstallerCatalogGenerator
        Loaded generator module.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "generate_installer_catalog.py"
    )
    spec = importlib.util.spec_from_file_location("generate_installer_catalog", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_InstallerCatalogGenerator", module)


def test_manifest_represents_every_local_first_party_package_once() -> None:
    """Keep the manifest aligned to all local package distributions.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts paths and package names are complete and unique.
    """
    generator = _load_generator()
    manifest = generator.load_manifest()
    packages = cast("list[dict[str, object]]", manifest["packages"])
    names = [cast("str", package["name"]) for package in packages]
    paths = [cast("str", package["path"]) for package in packages]
    repo_root = Path(__file__).resolve().parents[1]

    assert len(names) == len(set(names))
    assert len(paths) == len(set(paths))
    assert {
        path.name for path in (repo_root / "packages").iterdir() if path.is_dir()
    } == {Path(path).name for path in paths}


def test_generated_catalog_is_current_and_contains_selectable_schemas() -> None:
    """Keep the packaged catalog synchronized with plugin contracts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts drift checks pass and every selectable plugin has a schema.
    """
    generator = _load_generator()
    catalog = generator.build_catalog(generator.load_manifest())

    assert generator.main(["--check"]) == 0
    for package in cast("list[dict[str, object]]", catalog["packages"]):
        if package["selectable"] and package["family"] is not None:
            schema = cast("dict[str, object]", package["configuration_schema"])
            assert schema["additionalProperties"] is False
