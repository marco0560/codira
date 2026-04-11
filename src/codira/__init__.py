"""Top-level package for codira.

Responsibilities
----------------
- Expose package version metadata through `__version__`.
- Re-export major entrypoints or helper symbols for convenience.

Design principles
-----------------
The initializer stays minimal, avoiding heavy imports while providing essential metadata.

Architectural role
------------------
This module belongs to the **package infrastructure layer** and anchors codira versioning and exports.
"""

from .version import package_version

__version__ = package_version()
