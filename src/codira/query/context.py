"""Public context-query API and compatibility boundary."""

from __future__ import annotations

from codira.query.context_models import ContextRequest, SimilarityContextResults
from codira.query.context_orchestration import context_for
from codira.version import package_version

__all__ = ("ContextRequest", "SimilarityContextResults", "context_for")

__version__ = package_version()
