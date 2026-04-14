"""Version lookup helpers for codira.

Responsibilities
----------------
- Expose the package version without requiring the generated ``_version.py`` file.
- Prefer installed package metadata for the explicit codira release version.
- Fall back to generated metadata or a deterministic default in source checkouts.

Design principles
-----------------
Version lookup stays lightweight and safe for editable source trees where
generated files may be absent.

Architectural role
------------------
This module belongs to the **package infrastructure layer** and decouples
runtime version access from generated source artifacts.
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as metadata_version


def installed_distribution_version(distribution_name: str) -> str | None:
    """
    Return the installed version for one distribution when available.

    Parameters
    ----------
    distribution_name : str
        Installed distribution name queried through package metadata.

    Returns
    -------
    str | None
        Installed distribution version, or ``None`` when the distribution is
        not installed in the current environment.
    """
    try:
        return metadata_version(distribution_name)
    except PackageNotFoundError:
        return None


def package_version() -> str:
    """
    Return the current codira version string.

    Parameters
    ----------
    None

    Returns
    -------
    str
        The installed package metadata version when available, otherwise the
        build-generated version, otherwise ``"0.0.0"``.

    Raises
    ------
    ModuleNotFoundError
        Propagated when importing generated version metadata fails for a module
        other than codira's optional ``_version`` module.
    """
    installed_version = installed_distribution_version("codira")
    if installed_version is not None:
        return installed_version

    package_name = __package__ or "codira"
    try:
        generated_module = import_module("._version", package=package_name)
    except ModuleNotFoundError as exc:
        if exc.name != f"{package_name}._version":
            raise
        return "0.0.0"

    generated_version: object = getattr(generated_module, "version", None)
    if isinstance(generated_version, str):
        return generated_version
    return "0.0.0"
