"""Read the installer catalog without importing Textual or plugin packages."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast


def load_catalog() -> dict[str, object]:
    """Load the packaged official installer catalog.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Catalog data generated from the canonical package manifest.
    """
    catalog_file = files("codira_installer").joinpath("catalog.json")
    return cast(
        "dict[str, object]", json.loads(catalog_file.read_text(encoding="utf-8"))
    )
