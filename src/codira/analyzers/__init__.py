"""Language analyzer exports for codira.

Responsibilities
----------------
- Re-export the current default analyzer shims and built-ins.
- Preserve transitional imports for extracted first-party analyzers when their
  packages are installed.
- Keep analyzer imports lightweight for registry and test callers.

Design principles
-----------------
The package stays lightweight and avoids owning extracted first-party analyzer
implementations directly.

Architectural role
------------------
This module belongs to the **language analyzer registration layer** of ADR-004.
"""

import importlib

from codira.analyzers.json import JsonAnalyzer
from codira.analyzers.markdown import MarkdownAnalyzer
from codira.analyzers.python import PythonAnalyzer
from codira.analyzers.text import TextAnalyzer

__all__ = ["PythonAnalyzer", "JsonAnalyzer", "MarkdownAnalyzer", "TextAnalyzer"]

try:
    c_module = importlib.import_module("codira.analyzers.c")
except ModuleNotFoundError as exc:
    if exc.name not in {"codira_analyzer_c", "tree_sitter_c"}:
        raise
else:
    CAnalyzer = c_module.CAnalyzer
    __all__.append("CAnalyzer")

try:
    cpp_module = importlib.import_module("codira.analyzers.cpp")
except ModuleNotFoundError as exc:
    if exc.name not in {"codira_analyzer_cpp", "tree_sitter_cpp"}:
        raise
else:
    CppAnalyzer = cpp_module.CppAnalyzer
    __all__.append("CppAnalyzer")

try:
    bash_module = importlib.import_module("codira.analyzers.bash")
except ModuleNotFoundError as exc:
    if exc.name not in {"codira_analyzer_bash", "tree_sitter_bash"}:
        raise
else:
    BashAnalyzer = bash_module.BashAnalyzer
    __all__.append("BashAnalyzer")
