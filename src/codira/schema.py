"""Logical index schema metadata for codira-core.

Responsibilities
----------------
- Maintain the logical index contract version used by backend plugins.
- Keep codira-core independent from backend physical table definitions.

Design principles
-----------------
Physical schema definitions live in backend packages. Core code must interact
through backend contracts rather than importing SQL DDL.

Architectural role
------------------
This module belongs to the **core contract layer** and intentionally does not
define backend table DDL.
"""

from __future__ import annotations

LOGICAL_SCHEMA_VERSION = 21
