#!/usr/bin/env python3
"""Validate release tag syntax."""

from __future__ import annotations

import argparse
import re

TAG_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


def main() -> int:
    """
    Validate one release tag argument.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    parser = argparse.ArgumentParser(description="Validate a vX.Y.Z release tag.")
    parser.add_argument("tag")
    args = parser.parse_args()
    if not TAG_RE.fullmatch(args.tag):
        print("ERROR: tags must match vX.Y.Z")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
