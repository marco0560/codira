"""Identify the installed serving product without disclosing host paths.

Parameters
----------
None

Returns
-------
None
    Safe runtime receipts for discovery and offline image admission.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.metadata import distributions
from importlib.util import find_spec
from pathlib import Path

from codira.version import package_version


@lru_cache(maxsize=1)
def runtime_identity() -> dict[str, object]:
    """Fingerprint installed core source and first-party package versions.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Package version, source digest and installed analyzer/backend versions.
    """
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    packages = {
        str(dist.metadata["Name"]): dist.version
        for dist in distributions()
        if str(dist.metadata["Name"]).startswith("codira-")
    }
    analyzer_sources: dict[str, str] = {}
    for name in sorted(packages):
        if not name.startswith("codira-analyzer-"):
            continue
        spec = find_spec(name.replace("-", "_"))
        if spec is None or spec.origin is None:
            continue
        package_root = Path(spec.origin).parent
        source = hashlib.sha256()
        for path in sorted(package_root.rglob("*.py")):
            source.update(path.relative_to(package_root).as_posix().encode())
            source.update(path.read_bytes())
        analyzer_sources[name] = source.hexdigest()
    return {
        "version": package_version(),
        "source_sha256": digest.hexdigest(),
        "packages": dict(sorted(packages.items())),
        "analyzer_sources": analyzer_sources,
    }
