#!/usr/bin/env python3
"""Provision the local sentence-transformers model used by codira.

Responsibilities
----------------
- Download or verify the configured local embedding model artifact through the embeddings backend.
- Emit clear status messages and non-zero exit codes when provisioning fails.

Design principles
-----------------
Provisioning is idempotent, quiet by default, and fails fast when the backend cannot prepare the model.

Architectural role
------------------
This script belongs to the **tooling layer** that keeps local embeddings ready for indexing and retrieval.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
    print(
        "Usage: python scripts/provision_embedding_model.py [-h|--help]\n\n"
        "Download or verify the configured local embedding model artifact."
    )
    raise SystemExit(0)

from codira.semantic.embeddings import (
    EMBEDDING_BACKEND,
    EmbeddingBackendError,
    provision_embedding_model,
)


def main() -> int:
    """
    Download or verify the configured local embedding model artifact.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """
    try:
        provision_embedding_model(quiet=True)
    except EmbeddingBackendError as exc:
        print(f"[codira] {exc}", file=sys.stderr)
        return 1
    print(f"Provisioned embedding model: {EMBEDDING_BACKEND}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
