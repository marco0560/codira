#!/usr/bin/env python3
"""Generate the installer catalog from the official package manifest.

The generated catalog is packaged by ``codira-installer`` and deliberately
contains data only; loading it never imports Textual or an optional plugin.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "packages" / "first_party_packages.json"
CATALOG_PATH = (
    REPO_ROOT
    / "packages"
    / "codira-installer"
    / "src"
    / "codira_installer"
    / "catalog.json"
)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, object]:
    """Load and minimally validate the canonical first-party manifest.

    Parameters
    ----------
    path : pathlib.Path, optional
        Manifest file to load.

    Returns
    -------
    dict[str, object]
        Parsed manifest object.

    Raises
    ------
    ValueError
        If package paths or names are duplicated.
    """
    manifest = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    packages = cast("list[dict[str, object]]", manifest["packages"])
    names = [cast("str", package["name"]) for package in packages]
    paths = [cast("str", package["path"]) for package in packages]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        message = "first-party package names and paths must be unique"
        raise ValueError(message)
    return manifest


def _schema_for(package: dict[str, object]) -> dict[str, object] | None:
    """Return a plugin configuration schema for one manifest package.

    Parameters
    ----------
    package : dict[str, object]
        One validated package record.

    Returns
    -------
    dict[str, object] | None
        The plugin schema, or ``None`` for non-plugin distributions.
    """
    entry_point = package["entry_point"]
    if entry_point is None:
        return None
    package_root = REPO_ROOT / cast("str", package["path"]) / "src"
    sys.path.insert(0, str(package_root))
    try:
        module_name, factory_name = cast("str", entry_point).split(":", maxsplit=1)
        factory = getattr(importlib.import_module(module_name), factory_name)
        return cast("dict[str, object]", factory().configuration_json_schema())
    finally:
        sys.path.remove(str(package_root))


def build_catalog(manifest: dict[str, object]) -> dict[str, object]:
    """Build the deterministic data-only installer catalog.

    Parameters
    ----------
    manifest : dict[str, object]
        Validated canonical package manifest.

    Returns
    -------
    dict[str, object]
        Installer catalog with plugin configuration schemas.
    """
    catalog_packages: list[dict[str, object]] = []
    for source_package in cast("list[dict[str, object]]", manifest["packages"]):
        package = {
            key: value for key, value in source_package.items() if key != "entry_point"
        }
        schema = _schema_for(source_package)
        if schema is not None:
            package["configuration_schema"] = schema
        catalog_packages.append(package)
    return {
        "schema_version": manifest["schema_version"],
        "coordinated_version": manifest["coordinated_version"],
        "packages": catalog_packages,
    }


def render_catalog(catalog: dict[str, object]) -> str:
    """Render catalog JSON with deterministic formatting.

    Parameters
    ----------
    catalog : dict[str, object]
        Catalog object to serialize.

    Returns
    -------
    str
        Canonical JSON document ending in one newline.
    """
    return json.dumps(catalog, indent=2, sort_keys=True) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse generator command line arguments.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when output drifts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Generate or verify the packaged installer catalog.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional argument override.

    Returns
    -------
    int
        Zero when the catalog was generated or already current.
    """
    args = parse_args(argv)
    rendered = render_catalog(build_catalog(load_manifest()))
    if args.check:
        if (
            not CATALOG_PATH.is_file()
            or CATALOG_PATH.read_text(encoding="utf-8") != rendered
        ):
            print(f"installer catalog drift: run {Path(__file__).name}")
            return 1
        return 0
    CATALOG_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
