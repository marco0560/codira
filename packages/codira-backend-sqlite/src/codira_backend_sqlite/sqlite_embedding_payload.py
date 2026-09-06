"""Deterministic embedding payload helpers for the SQLite backend."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sqlite_support import EmbeddingTextRequest


def _embedding_text(request: EmbeddingTextRequest) -> str:
    """
    Build the deterministic text payload embedded for one symbol.

    Parameters
    ----------
    request : EmbeddingTextRequest
        Embedding text construction request.

    Returns
    -------
    str
        Joined text payload used for embedding generation.
    """
    parts = [request.symbol_type, request.module_name, request.symbol_name]
    if request.signature:
        parts.append(request.signature)
    if request.docstring:
        parts.append(request.docstring)
    parts.extend(line for line in request.extra_context if line)
    return "\n".join(parts)


def _embedding_content_hash(text: str) -> str:
    """
    Return the deterministic content hash for one embedding payload.

    Parameters
    ----------
    text : str
        Exact semantic payload used for embedding generation.

    Returns
    -------
    str
        Hex-encoded SHA-256 digest of ``text``.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
