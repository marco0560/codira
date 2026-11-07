"""Bind pilot measurements to source, profile, producer, and toolchain bytes.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CaseIdentity:
    """Carry all deterministic inputs that qualify a per-file measurement.

    Parameters
    ----------
    source_sha256 : str
        SHA-256 of the exact translation-unit source bytes.
    profile_sha256 : str
        SHA-256 of the exact compile profile and adapter transformation ledger.
    dependency_sha256 : str
        SHA-256 of the canonical dependency-closure identity.
    compiler_sha256 : str
        SHA-256 of the selected compiler binary.
    producer_sha256 : str
        SHA-256 of the producer executable and adapter implementation.
    configuration_sha256 : str
        SHA-256 of the effective pilot configuration.
    """

    source_sha256: str
    profile_sha256: str
    dependency_sha256: str
    compiler_sha256: str
    producer_sha256: str
    configuration_sha256: str

    def digest(self) -> str:
        """Return a stable digest after validating each identity component.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 over the canonically serialized identity.

        Raises
        ------
        ValueError
            If any component is not a lowercase SHA-256 digest.
        """

        values = asdict(self)
        invalid = [
            name for name, value in values.items() if not _SHA256.fullmatch(value)
        ]
        if invalid:
            message = f"invalid SHA-256 identity fields: {', '.join(invalid)}"
            raise ValueError(message)
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()
