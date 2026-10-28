"""Grade native Clang linkage against identities persisted in backend snapshots.

Parameters
----------
None

Returns
-------
None
    The command writes a source-bound supplemental qualification receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, NoReturn, cast


class NativeLinkageError(ValueError):
    """One malformed or mismatched native linkage evidence item."""

    def __init__(self, context: str, requirement: str) -> None:
        """Create a source or snapshot validation failure.

        Parameters
        ----------
        context : str
            Evidence item or file under validation.
        requirement : str
            Missing or mismatched property.

        Returns
        -------
        None
            The exception carries the formatted failure message.
        """
        super().__init__(f"{context}: {requirement}")


def _fail(context: str, requirement: str) -> NoReturn:
    """Raise a consistent source-linked qualification error.

    Parameters
    ----------
    context : str
        Evidence item or file under validation.
    requirement : str
        Missing or mismatched property.

    Returns
    -------
    None
        This function always raises.
    """
    raise NativeLinkageError(context, requirement)


def _require(condition: bool, context: str, requirement: str) -> None:
    """Reject one unmet evidence requirement.

    Parameters
    ----------
    condition : bool
        Whether the required property holds.
    context : str
        Evidence item or file under validation.
    requirement : str
        Required property description.

    Returns
    -------
    None
        Returns only when the condition holds.
    """
    if not condition:
        _fail(context, requirement)


def _mapping(value: object, context: str) -> dict[str, Any]:
    """Require a JSON object at one evidence path.

    Parameters
    ----------
    value : object
        Decoded JSON value.
    context : str
        Evidence path included in failures.

    Returns
    -------
    dict[str, Any]
        Validated object.
    """
    _require(
        isinstance(value, dict) and all(isinstance(key, str) for key in value),
        context,
        "must be an object with string keys",
    )
    return cast("dict[str, Any]", value)


def _array(value: object, context: str) -> list[Any]:
    """Require a JSON array at one evidence path.

    Parameters
    ----------
    value : object
        Decoded JSON value.
    context : str
        Evidence path included in failures.

    Returns
    -------
    list[Any]
        Validated array.
    """
    _require(isinstance(value, list), context, "must be an array")
    return cast("list[Any]", value)


def _string(value: object, context: str) -> str:
    """Require a nonempty string at one evidence path.

    Parameters
    ----------
    value : object
        Decoded JSON value.
    context : str
        Evidence path included in failures.

    Returns
    -------
    str
        Validated nonempty string.
    """
    _require(
        isinstance(value, str) and bool(value), context, "must be a nonempty string"
    )
    return cast("str", value)


def _file_digest(path: Path, context: str) -> str:
    """Hash one required regular file.

    Parameters
    ----------
    path : pathlib.Path
        File whose bytes are captured in the receipt.
    context : str
        Evidence path included in failures.

    Returns
    -------
    str
        Lowercase SHA-256 hexadecimal digest.
    """
    _require(path.is_file(), context, "required file is missing")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observe_native_request(
    request: dict[str, Any],
    profile: dict[str, Any],
    repository_root: Path,
) -> dict[str, Any]:
    """Validate and project one exact native callable declaration.

    Parameters
    ----------
    request : dict[str, Any]
        Source-authored linkage and identity request.
    profile : dict[str, Any]
        Manifest row binding a TU to native stdout bytes.
    repository_root : pathlib.Path
        Private indexed source checkout.

    Returns
    -------
    dict[str, Any]
        Source-bound linkage, identity, and evidence digests.
    """
    reference = _string(request.get("reference"), "request.reference")
    source = _string(request.get("source"), f"{reference}.source")
    source_path = (repository_root / source).resolve(strict=True)
    source_digest = _file_digest(source_path, reference)
    _require(
        profile.get("source_path") == str(source_path)
        and profile.get("source_sha256") == source_digest,
        reference,
        "profile source path or digest differs from the indexed source",
    )
    stdout_path = Path(_string(profile.get("stdout_path"), f"{reference}.stdout_path"))
    stdout_digest = _file_digest(stdout_path, reference)
    _require(
        profile.get("stdout_sha256") == stdout_digest,
        reference,
        "raw native stdout digest differs from manifest",
    )
    response = _mapping(
        json.loads(stdout_path.read_text(encoding="utf-8")),
        f"{reference}.native_response",
    )
    _require(
        response.get("translation_unit_file") == str(source_path)
        and response.get("tool_return_code") == 0
        and response.get("capture_mode") == "source_relevant",
        reference,
        "native response is not a successful bound translation-unit capture",
    )
    name = _string(request.get("name"), f"{reference}.name")
    line = request.get("definition_line")
    declarations = _array(response.get("declarations"), f"{reference}.declarations")
    matching = [
        declaration_value
        for declaration_value in declarations
        if _native_definition_matches(
            declaration_value, name, line, str(source_path), reference
        )
    ]
    _require(
        len(matching) == 1,
        reference,
        f"expected one native definition, found {len(matching)}",
    )
    declaration = _mapping(matching[0], f"{reference}.declaration")
    linkage = _string(declaration.get("linkage_kind"), f"{reference}.linkage_kind")
    _require(
        linkage == request.get("linkage_kind"),
        reference,
        f"native linkage kind differs: {linkage}",
    )
    identity = _mapping(declaration.get("identity"), f"{reference}.identity")
    return {
        "source": source,
        "source_sha256": source_digest,
        "stdout_sha256": stdout_digest,
        "name": name,
        "definition_line": line,
        "linkage_kind": linkage,
        "semantic_identity_value": _string(
            identity.get("usr"), f"{reference}.identity.usr"
        ),
        "identity_observation_reference": _string(
            request.get("identity_observation_reference"),
            f"{reference}.identity_observation_reference",
        ),
    }


def _native_definition_matches(
    value: object,
    name: str,
    line: object,
    source_path: str,
    context: str,
) -> bool:
    """Match a raw declaration by exact name, physical coordinate, and role.

    Parameters
    ----------
    value : object
        One compiler response declaration.
    name : str
        Fully qualified Clang declaration name.
    line : object
        Authored one-based definition line.
    source_path : str
        Canonical physical TU path.
    context : str
        Evidence path used to validate nested objects.

    Returns
    -------
    bool
        Whether the declaration matches all requested source coordinates.
    """
    declaration = _mapping(value, f"{context}.declaration")
    location = _mapping(declaration.get("location"), f"{context}.location")
    expansion = _mapping(location.get("expansion"), f"{context}.expansion")
    return (
        declaration.get("qualified_name") == name
        and expansion.get("line") == line
        and expansion.get("path") == source_path
        and declaration.get("is_definition") is True
    )


def _native_observations(
    oracle: dict[str, Any], manifest: dict[str, Any], repository_root: Path
) -> dict[str, dict[str, Any]]:
    """Collect all native linkage assertions from the retained helper output.

    Parameters
    ----------
    oracle : dict[str, Any]
        Source-authored native linkage requests.
    manifest : dict[str, Any]
        Source-to-native stdout digest manifest.
    repository_root : pathlib.Path
        Private indexed source checkout.

    Returns
    -------
    dict[str, dict[str, Any]]
        Native declaration facts keyed by source-authored reference.
    """
    profiles = _array(manifest.get("profiles"), "manifest.profiles")
    profile_by_source: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(profiles):
        row = _mapping(value, f"manifest.profiles[{index}]")
        source = _string(row.get("source"), f"manifest.profiles[{index}].source")
        _require(source not in profile_by_source, source, "profile is duplicated")
        profile_by_source[source] = row
    requests = _array(
        oracle.get("native_linkage_requests"), "oracle.native_linkage_requests"
    )
    observations: dict[str, dict[str, Any]] = {}
    for request_value in requests:
        request = _mapping(request_value, "oracle native linkage request")
        reference = _string(request.get("reference"), "request.reference")
        source = _string(request.get("source"), f"{reference}.source")
        profile = profile_by_source.get(source)
        if profile is None:
            _fail(reference, "native profile is missing")
        observations[reference] = _observe_native_request(
            request, profile, repository_root
        )
    return observations


def _verify_database_joins(
    observations: dict[str, dict[str, Any]], snapshots: list[dict[str, Any]]
) -> list[str]:
    """Require both backends to persist each matching exact identity.

    Parameters
    ----------
    observations : dict[str, dict[str, Any]]
        Raw native facts keyed by oracle reference.
    snapshots : list[dict[str, Any]]
        Database-only snapshots from SQLite and DuckDB.

    Returns
    -------
    list[str]
        Sorted names of the two validated backends.
    """
    _require(len(snapshots) == 2, "snapshots", "exactly two backends are required")
    backends: set[str] = set()
    for snapshot_value in snapshots:
        snapshot = _mapping(snapshot_value, "snapshot")
        backend = _string(snapshot.get("backend"), "snapshot.backend")
        _require(backend in {"sqlite", "duckdb"}, backend, "unexpected backend")
        _require(backend not in backends, backend, "backend snapshot is duplicated")
        backends.add(backend)
        identities = _mapping(
            snapshot.get("identity_observations"), "identity_observations"
        )
        cases = _mapping(snapshot.get("cases"), "cases")
        namespaces = _mapping(
            snapshot.get("identity_namespace_observations"),
            "identity_namespace_observations",
        )
        for _reference, native in observations.items():
            source = _string(native.get("source"), "native.source")
            case = _mapping(cases.get(source), f"{backend}.cases.{source}")
            _require(
                case.get("source_sha256") == native["source_sha256"],
                f"{backend}.{source}",
                "snapshot source digest differs from native source digest",
            )
            db_reference = str(native["identity_observation_reference"])
            _require(
                identities.get(db_reference) == native["semantic_identity_value"],
                f"{backend}.{db_reference}",
                "native USR does not equal persisted DB identity",
            )
            _require(
                namespaces.get(db_reference) == "clang.usr.v1",
                f"{backend}.{db_reference}",
                "persisted semantic identity namespace is absent or incorrect",
            )
    _require(
        backends == {"sqlite", "duckdb"}, "snapshots", "SQLite and DuckDB are required"
    )
    return sorted(backends)


def grade_native_linkage(
    oracle: dict[str, Any],
    manifest: dict[str, Any],
    snapshots: list[dict[str, Any]],
    repository_root: Path,
) -> dict[str, Any]:
    """Verify native internal linkage against exact identities in DB snapshots.

    Parameters
    ----------
    oracle : dict[str, Any]
        Source-authored oracle with native linkage requests.
    manifest : dict[str, Any]
        Retained source-to-helper-stdout bindings.
    snapshots : list[dict[str, Any]]
        Database-only SQLite and DuckDB snapshots.
    repository_root : pathlib.Path
        Private indexed source checkout containing authored translation units.

    Returns
    -------
    dict[str, Any]
        Supplemental proof with raw native linkage and exact DB identity joins.
    """
    observations = _native_observations(oracle, manifest, repository_root)
    backends = _verify_database_joins(observations, snapshots)
    values = [row["semantic_identity_value"] for row in observations.values()]
    _require(
        len(values) >= 2 and len(set(values)) == len(values),
        "anonymous namespace identities",
        "callables must have distinct TU-scoped identities",
    )
    return {
        "supplement_version": 1,
        "proof_scope": "native_linkage_to_persisted_exact_identity",
        "snapshot_backends": backends,
        "assertion_count": len(observations),
        "observations": [observations[key] for key in sorted(observations)],
        "result": "passed",
    }


def main() -> int:
    """Grade and persist a supplemental native-linkage proof.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero when every source-bound identity assertion passes.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--native-manifest", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    oracle = _mapping(json.loads(args.oracle.read_text(encoding="utf-8")), "oracle")
    manifest = _mapping(
        json.loads(args.native_manifest.read_text(encoding="utf-8")), "manifest"
    )
    snapshots = [
        _mapping(json.loads(path.read_text(encoding="utf-8")), f"snapshot {path}")
        for path in args.snapshot
    ]
    receipt = grade_native_linkage(oracle, manifest, snapshots, args.repository_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
