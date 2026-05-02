"""JSON analyzer for deterministic structured document indexing.

Responsibilities
----------------
- Classify supported JSON document families through explicit path and shape rules.
- Parse claimed JSON files and emit normalized module and declaration artifacts.
- Reject low-value or ambiguous JSON inputs deterministically without inventing symbols.

Design principles
-----------------
The analyzer is family-based rather than generic. It claims only JSON documents
with a stable symbol model and leaves all other JSON files unsupported.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the
first-party JSON analyzer distribution for Phase 2 packaging.
"""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.models import AnalysisResult, DeclarationArtifact, ModuleArtifact

JsonFamily = Literal[
    "json_schema",
    "npm_package_manifest",
    "semantic_release_config",
]
JsonFamilyOrNone = JsonFamily | None
JsonScalar = str | int | float | bool | None
_JSON_SNIFF_BYTES = 8192
_JSON_SCHEMA_MARKERS = (
    '"$schema"',
    '"properties"',
    '"$defs"',
    '"definitions"',
    '"items"',
)
_PACKAGE_MANIFEST_MARKERS = (
    '"name"',
    '"version"',
    '"scripts"',
    '"dependencies"',
    '"devDependencies"',
    '"peerDependencies"',
    '"optionalDependencies"',
    '"bin"',
)
_SEMANTIC_RELEASE_MARKERS = (
    '"plugins"',
    '"branches"',
    '"tagFormat"',
)


def _sanitize_module_segment(segment: str) -> str:
    """
    Normalize one path segment for JSON module naming.

    Parameters
    ----------
    segment : str
        Raw repository-relative path segment.

    Returns
    -------
    str
        Segment rewritten to avoid ambiguous dotted module names.
    """
    normalized = segment.strip().replace("-", "_").replace(".", "_")
    return normalized.lstrip("_") or "json"


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive the logical module name for one supported JSON file.

    Parameters
    ----------
    path : pathlib.Path
        JSON file being analyzed.
    root : pathlib.Path
        Repository root used for relative naming.

    Returns
    -------
    str
        Dotted module identity derived from the repository-relative path.
    """
    relative = path.relative_to(root)
    parent_segments = [
        _sanitize_module_segment(part) for part in relative.parent.parts if part
    ]
    filename_segment = _sanitize_module_segment(path.stem)
    return ".".join((*parent_segments, filename_segment))


def _module_stable_id(path: Path, root: Path) -> str:
    """
    Build the durable identity for one JSON-backed module.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable JSON module identity.
    """
    return f"json:module:{path.relative_to(root).as_posix()}"


def _load_json_mapping(path: Path) -> dict[str, object]:
    """
    Parse one JSON file and require an object-valued document root.

    Parameters
    ----------
    path : pathlib.Path
        JSON file to parse.

    Returns
    -------
    dict[str, object]
        Parsed top-level JSON object.

    Raises
    ------
    TypeError
        If the top-level JSON value is not an object.
    ValueError
        If the file is not valid JSON.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        msg = f"Unsupported JSON document in {path}: {exc.msg}"
        raise ValueError(msg) from exc

    if not isinstance(payload, dict):
        msg = f"Unsupported JSON document in {path}: top-level value must be an object"
        raise TypeError(msg)

    return cast("dict[str, object]", payload)


def _read_json_sniff_text(path: Path, *, limit: int = _JSON_SNIFF_BYTES) -> str:
    """
    Read one small decoded prefix for cheap JSON-family sniffing.

    Parameters
    ----------
    path : pathlib.Path
        Candidate JSON file path.
    limit : int, optional
        Maximum number of bytes read from the file prefix.

    Returns
    -------
    str
        UTF-8-decoded text prefix used for cheap marker checks.
    """
    with path.open("rb") as handle:
        prefix = handle.read(limit)
    return prefix.decode("utf-8", errors="ignore")


def _classify_json_path(path: Path) -> JsonFamilyOrNone:
    """
    Classify a JSON path through explicit repo-relative filename rules.

    Parameters
    ----------
    path : pathlib.Path
        Candidate JSON file path.

    Returns
    -------
    {"json_schema", "npm_package_manifest", "semantic_release_config"} | None
        Deterministic family chosen by the path rule, or ``None`` when the path
        is not conclusive.
    """
    if path.name == "package-lock.json":
        return None
    if ".vscode" in path.parts:
        return None
    if path.name == "package.json":
        return "npm_package_manifest"
    if path.name == ".releaserc.json":
        return "semantic_release_config"
    if path.suffix == ".json" and (
        path.parent.name == "schema" or "schema" in path.stem.lower()
    ):
        return "json_schema"
    return None


def _sniff_json_path_candidate(path: Path) -> bool:
    """
    Decide whether one JSON path is worth a full parse.

    Parameters
    ----------
    path : pathlib.Path
        Candidate JSON file path.

    Returns
    -------
    bool
        ``True`` when the path or a shallow text prefix suggests one supported
        JSON family.
    """
    path_family = _classify_json_path(path)
    if path_family == "npm_package_manifest":
        return True
    if path_family == "semantic_release_config":
        return True

    try:
        sniff = _read_json_sniff_text(path)
    except OSError:
        return False

    if path_family == "json_schema":
        return any(marker in sniff for marker in _JSON_SCHEMA_MARKERS)

    marker_groups = (
        _JSON_SCHEMA_MARKERS,
        _PACKAGE_MANIFEST_MARKERS,
        _SEMANTIC_RELEASE_MARKERS,
    )
    return any(marker in sniff for group in marker_groups for marker in group)


def _is_json_schema_document(payload: dict[str, object]) -> bool:
    """
    Decide whether one parsed JSON object is a JSON Schema document.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed JSON object to classify.

    Returns
    -------
    bool
        ``True`` when the document exposes deterministic JSON Schema markers.
    """
    schema_uri = payload.get("$schema")
    schema_markers = {"properties", "$defs", "definitions", "items"}
    marker_count = sum(1 for marker in schema_markers if marker in payload)
    return (
        isinstance(schema_uri, str)
        and bool(schema_uri.strip())
        or marker_count >= 2
        or ("type" in payload and "properties" in payload)
    )


def _is_package_manifest(payload: dict[str, object]) -> bool:
    """
    Decide whether one parsed JSON object is an npm-style package manifest.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed JSON object to classify.

    Returns
    -------
    bool
        ``True`` when the document exposes deterministic package-manifest
        markers.
    """
    name = payload.get("name")
    version = payload.get("version")
    manifest_markers = {
        "scripts",
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
        "bin",
    }
    return (
        isinstance(name, str)
        and bool(name.strip())
        and (
            isinstance(version, str)
            or any(marker in payload for marker in manifest_markers)
        )
    )


def _is_semantic_release_config(payload: dict[str, object]) -> bool:
    """
    Decide whether one parsed JSON object is a semantic-release config file.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed JSON object to classify.

    Returns
    -------
    bool
        ``True`` when the document exposes deterministic semantic-release
        configuration markers.
    """
    return "plugins" in payload and ("branches" in payload or "tagFormat" in payload)


def _classify_json_payload(payload: dict[str, object]) -> JsonFamilyOrNone:
    """
    Classify one parsed JSON object through strong structural markers.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed JSON object to classify.

    Returns
    -------
    {"json_schema", "npm_package_manifest", "semantic_release_config"} | None
        Deterministic family chosen by content, or ``None`` when the payload is
        not a supported JSON family.
    """
    if _is_json_schema_document(payload):
        return "json_schema"
    if _is_package_manifest(payload):
        return "npm_package_manifest"
    if _is_semantic_release_config(payload):
        return "semantic_release_config"
    return None


def _classify_json_document(path: Path, payload: dict[str, object]) -> JsonFamilyOrNone:
    """
    Classify one JSON file through path-first then shape-based rules.

    Parameters
    ----------
    path : pathlib.Path
        Candidate JSON file path.
    payload : dict[str, object]
        Parsed JSON object to classify.

    Returns
    -------
    {"json_schema", "npm_package_manifest", "semantic_release_config"} | None
        Deterministic supported family, or ``None`` when the file stays
        intentionally unsupported.
    """
    path_family = _classify_json_path(path)
    if path_family == "json_schema" and _is_json_schema_document(payload):
        return path_family
    if path_family == "npm_package_manifest" and _is_package_manifest(payload):
        return path_family
    if path_family == "semantic_release_config" and _is_semantic_release_config(
        payload
    ):
        return path_family
    return _classify_json_payload(payload)


def _scalar_text(value: object) -> str | None:
    """
    Convert one JSON scalar into deterministic text.

    Parameters
    ----------
    value : object
        Candidate scalar value.

    Returns
    -------
    str | None
        Text representation for supported scalar values, or ``None`` when the
        value is not a scalar.
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return str(cast("JsonScalar", value))
    return None


def _schema_docstring(payload: dict[str, object]) -> str:
    """
    Build the module summary used for one JSON Schema document.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed JSON Schema document.

    Returns
    -------
    str
        Concise module summary for indexing and explain output.
    """
    title = payload.get("title")
    description = payload.get("description")

    if isinstance(title, str) and title.strip():
        summary = f"JSON Schema: {title.strip()}."
    else:
        summary = "JSON Schema document."

    if isinstance(description, str) and description.strip():
        return f"{summary} {description.strip()}"
    return summary


def _package_docstring(payload: dict[str, object]) -> str:
    """
    Build the module summary used for one package manifest.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed package manifest.

    Returns
    -------
    str
        Concise package-manifest summary.
    """
    package_name = _scalar_text(payload.get("name")) or "unnamed package"
    version = _scalar_text(payload.get("version"))
    if version is None:
        return f"Package manifest: {package_name}."
    return f"Package manifest: {package_name} version {version}."


def _release_docstring(payload: dict[str, object]) -> str:
    """
    Build the module summary used for one semantic-release config.

    Parameters
    ----------
    payload : dict[str, object]
        Parsed semantic-release config.

    Returns
    -------
    str
        Concise semantic-release configuration summary.
    """
    branches = payload.get("branches")
    plugins = payload.get("plugins")
    branch_count = len(branches) if isinstance(branches, list) else 0
    plugin_count = len(plugins) if isinstance(plugins, list) else 0
    return (
        "semantic-release config with "
        f"{branch_count} branch entries and {plugin_count} plugin entries."
    )


def _join_path_segments(segments: Iterable[str]) -> str:
    """
    Join normalized schema path segments into one symbol name.

    Parameters
    ----------
    segments : collections.abc.Iterable[str]
        Ordered path fragments to join.

    Returns
    -------
    str
        Dotted path string for symbol naming.
    """
    return ".".join(segment for segment in segments if segment)


def _extract_schema_property_declarations(
    path: Path,
    payload: dict[str, object],
) -> tuple[DeclarationArtifact, ...]:
    """
    Extract deterministic property-path symbols from one JSON Schema document.

    Parameters
    ----------
    path : pathlib.Path
        Schema file being analyzed.
    payload : dict[str, object]
        Parsed JSON Schema payload.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Property-path declarations in deterministic order.
    """
    declarations: list[DeclarationArtifact] = []

    def walk_schema(node: object, prefix: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return

        properties = node.get("properties")
        if isinstance(properties, dict):
            for property_name in sorted(properties):
                child = properties[property_name]
                property_path = (*prefix, str(property_name))
                if isinstance(child, dict):
                    description = _scalar_text(child.get("description"))
                    type_name = _scalar_text(child.get("type")) or "unknown"
                else:
                    description = None
                    type_name = "unknown"
                dotted_path = _join_path_segments(property_path)
                declarations.append(
                    DeclarationArtifact(
                        name=dotted_path,
                        stable_id=(
                            "json:schema_property:" f"{path.as_posix()}:{dotted_path}"
                        ),
                        kind="json_schema_property",
                        lineno=1,
                        signature=f"property path={dotted_path} type={type_name}",
                        docstring=description,
                    )
                )
                walk_schema(child, property_path)

        items = node.get("items")
        if isinstance(items, dict):
            walk_schema(items, (*prefix, "[]"))

    walk_schema(payload, ())
    return tuple(declarations)


def _extract_schema_definition_declarations(
    path: Path,
    payload: dict[str, object],
) -> tuple[DeclarationArtifact, ...]:
    """
    Extract deterministic definition symbols from one JSON Schema document.

    Parameters
    ----------
    path : pathlib.Path
        Schema file being analyzed.
    payload : dict[str, object]
        Parsed JSON Schema payload.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Definition declarations in deterministic order.
    """
    declarations: list[DeclarationArtifact] = []
    for section_name in ("$defs", "definitions"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for definition_name in sorted(section):
            definition = section[definition_name]
            description = (
                _scalar_text(definition.get("description"))
                if isinstance(definition, dict)
                else None
            )
            type_name = (
                _scalar_text(definition.get("type"))
                if isinstance(definition, dict)
                else None
            ) or "unknown"
            declarations.append(
                DeclarationArtifact(
                    name=str(definition_name),
                    stable_id=(
                        "json:schema_definition:" f"{path.as_posix()}:{definition_name}"
                    ),
                    kind="json_schema_definition",
                    lineno=1,
                    signature=f"definition {definition_name} type={type_name}",
                    docstring=description,
                )
            )
    return tuple(declarations)


def _extract_package_declarations(
    path: Path,
    payload: dict[str, object],
) -> tuple[DeclarationArtifact, ...]:
    """
    Extract deterministic symbols from one package manifest.

    Parameters
    ----------
    path : pathlib.Path
        Package manifest file being analyzed.
    payload : dict[str, object]
        Parsed package manifest.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Manifest declarations in deterministic order.
    """
    declarations: list[DeclarationArtifact] = []
    package_name = _scalar_text(payload.get("name"))
    version = _scalar_text(payload.get("version"))

    if package_name is not None:
        declarations.append(
            DeclarationArtifact(
                name=package_name,
                stable_id=f"json:package_name:{path.as_posix()}:{package_name}",
                kind="json_manifest_name",
                lineno=1,
                signature=(
                    f"package name={package_name}"
                    if version is None
                    else f"package name={package_name} version={version}"
                ),
                docstring=None,
            )
        )

    scripts = payload.get("scripts")
    if isinstance(scripts, dict):
        for script_name in sorted(scripts):
            script_body = _scalar_text(scripts[script_name])
            declarations.append(
                DeclarationArtifact(
                    name=str(script_name),
                    stable_id=f"json:package_script:{path.as_posix()}:{script_name}",
                    kind="json_manifest_script",
                    lineno=1,
                    signature=(
                        f"package script {script_name}"
                        if script_body is None
                        else f"package script {script_name}: {script_body}"
                    ),
                    docstring=None,
                )
            )

    dependency_sections = (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    )
    for section_name in dependency_sections:
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for dependency_name in sorted(section):
            version_range = _scalar_text(section[dependency_name]) or "unknown"
            declarations.append(
                DeclarationArtifact(
                    name=str(dependency_name),
                    stable_id=(
                        "json:package_dependency:"
                        f"{path.as_posix()}:{section_name}:{dependency_name}"
                    ),
                    kind="json_manifest_dependency",
                    lineno=1,
                    signature=(
                        f"package dependency section={section_name} "
                        f"name={dependency_name} version={version_range}"
                    ),
                    docstring=None,
                )
            )

    return tuple(declarations)


def _release_plugin_name(entry: object) -> str | None:
    """
    Extract one semantic-release plugin name from a plugin entry.

    Parameters
    ----------
    entry : object
        Plugin entry from the ``plugins`` array.

    Returns
    -------
    str | None
        Plugin identifier when one is present.
    """
    if isinstance(entry, str):
        stripped = entry.strip()
        return stripped or None
    if (
        isinstance(entry, list)
        and entry
        and isinstance(entry[0], str)
        and entry[0].strip()
    ):
        return entry[0].strip()
    return None


def _release_branch_name(entry: object) -> str | None:
    """
    Extract one semantic-release branch name from a branch entry.

    Parameters
    ----------
    entry : object
        Branch entry from the ``branches`` array.

    Returns
    -------
    str | None
        Branch identifier when one is present.
    """
    if isinstance(entry, str):
        stripped = entry.strip()
        return stripped or None
    if isinstance(entry, dict):
        branch_name = entry.get("name")
        if isinstance(branch_name, str) and branch_name.strip():
            return branch_name.strip()
    return None


def _extract_release_declarations(
    path: Path,
    payload: dict[str, object],
) -> tuple[DeclarationArtifact, ...]:
    """
    Extract deterministic symbols from one semantic-release config.

    Parameters
    ----------
    path : pathlib.Path
        semantic-release config file being analyzed.
    payload : dict[str, object]
        Parsed semantic-release config.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        semantic-release declarations in deterministic order.
    """
    declarations: list[DeclarationArtifact] = []

    branches = payload.get("branches")
    if isinstance(branches, list):
        branch_names = sorted(
            {
                branch_name
                for entry in branches
                if (branch_name := _release_branch_name(entry)) is not None
            }
        )
        for branch_name in branch_names:
            declarations.append(
                DeclarationArtifact(
                    name=branch_name,
                    stable_id=f"json:release_branch:{path.as_posix()}:{branch_name}",
                    kind="json_release_branch",
                    lineno=1,
                    signature=f"semantic-release branch {branch_name}",
                    docstring=None,
                )
            )

    plugins = payload.get("plugins")
    if isinstance(plugins, list):
        plugin_names = sorted(
            {
                plugin_name
                for entry in plugins
                if (plugin_name := _release_plugin_name(entry)) is not None
            }
        )
        for plugin_name in plugin_names:
            declarations.append(
                DeclarationArtifact(
                    name=plugin_name,
                    stable_id=f"json:release_plugin:{path.as_posix()}:{plugin_name}",
                    kind="json_release_plugin",
                    lineno=1,
                    signature=f"semantic-release plugin {plugin_name}",
                    docstring=None,
                )
            )

    return tuple(declarations)


def _module_docstring_for_family(
    family: JsonFamily,
    payload: dict[str, object],
) -> str:
    """
    Build one module summary for the resolved JSON family.

    Parameters
    ----------
    family : {"json_schema", "npm_package_manifest", "semantic_release_config"}
        Resolved JSON family for the file.
    payload : dict[str, object]
        Parsed family payload.

    Returns
    -------
    str
        Family-specific module summary.
    """
    if family == "json_schema":
        return _schema_docstring(payload)
    if family == "npm_package_manifest":
        return _package_docstring(payload)
    return _release_docstring(payload)


def _declarations_for_family(
    family: JsonFamily,
    *,
    path: Path,
    payload: dict[str, object],
) -> tuple[DeclarationArtifact, ...]:
    """
    Return declaration artifacts for one classified JSON family.

    Parameters
    ----------
    family : {"json_schema", "npm_package_manifest", "semantic_release_config"}
        Resolved JSON family for the file.
    path : pathlib.Path
        JSON file being analyzed.
    payload : dict[str, object]
        Parsed family payload.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Family-specific declarations in deterministic order.
    """
    if family == "json_schema":
        return (
            *_extract_schema_definition_declarations(path, payload),
            *_extract_schema_property_declarations(path, payload),
        )
    if family == "npm_package_manifest":
        return _extract_package_declarations(path, payload)
    return _extract_release_declarations(path, payload)


class JsonAnalyzer:
    """
    Concrete JSON analyzer for deterministic structured documents.

    Parameters
    ----------
    None

    Notes
    -----
    Supported families are currently:

    - JSON Schema documents
    - npm-style ``package.json`` manifests
    - semantic-release ``.releaserc.json`` files

    Explicitly unsupported inputs include lockfiles, VS Code workspace JSONC
    files, and unclassified generic JSON blobs.
    """

    name = "json"
    version = "3"
    discovery_globs: tuple[str, ...] = ("*.json",)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return JSON analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from JSON artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_json:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "variable",
            ),
            does_not_support=("namespace",),
            mappings={
                "module": "module",
                "json_schema_definition": "type",
                "json_schema_property": "variable",
                "json_manifest_name": "constant",
                "json_manifest_script": "callable",
                "json_manifest_dependency": "import",
                "json_release_plugin": "import",
                "json_release_branch": "constant",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a JSON source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file belongs to a supported JSON family.
        """
        if path.suffix != ".json":
            return False
        if not _sniff_json_path_candidate(path):
            return False

        try:
            payload = _load_json_mapping(path)
        except (TypeError, ValueError):
            return False

        return _classify_json_document(path, payload) is not None

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one supported JSON file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            JSON file to analyze.
        root : pathlib.Path
            Repository root used for module naming.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the JSON file.

        Raises
        ------
        TypeError
            If the parsed JSON document is not object-valued.
        ValueError
            If ``path`` does not hold a supported JSON family.
        """
        payload = _load_json_mapping(path)
        family = _classify_json_document(path, payload)
        if family is None:
            msg = f"Unsupported JSON document in {path}: no recognized JSON family"
            raise ValueError(msg)

        return AnalysisResult(
            source_path=path,
            module=ModuleArtifact(
                name=_module_name_for_path(path, root),
                stable_id=_module_stable_id(path, root),
                docstring=_module_docstring_for_family(family, payload),
                has_docstring=1,
            ),
            classes=(),
            functions=(),
            declarations=_declarations_for_family(family, path=path, payload=payload),
            imports=(),
        )


__all__ = ["JsonAnalyzer", "build_analyzer"]


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party JSON analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh JSON analyzer instance for registry discovery.
    """
    return JsonAnalyzer()
