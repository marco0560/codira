"""Shared type aliases used across codira.

Responsibilities
----------------
- Provide stable aliases for symbols such as `SymbolRow`, `ChannelResults`, and diagnostics structures.
- Centralize type declarations for bundles, references, and scoring metadata.
- Keep typing consistent without introducing circular imports between modules.

Design principles
-----------------
Aliases remain thin and descriptive so the rest of the codebase can depend on consistent typing without logic.

Architectural role
------------------
This module belongs to the **typing infrastructure layer** that glues codira modules together with structured metadata.
"""

from __future__ import annotations

import ast
from pathlib import Path

SymbolRow = tuple[str, str, str, str, int]
OverloadRow = tuple[str, str, int, str, int, int | None, str | None]
DocstringIssueRow = tuple[str, str, str, str, str, str, str, int, int | None]
ScoredSymbol = tuple[float, SymbolRow]
ChannelResults = list[ScoredSymbol]
ChannelName = str
ChannelBundle = tuple[ChannelName, ChannelResults]
ReferenceRow = tuple[str, int]
IncludeEdgeRow = tuple[str, str, str, int]
CodeContext = tuple[str | None, str | None, list[str]]
CacheType = dict[Path, tuple[str, list[str], ast.Module]]
