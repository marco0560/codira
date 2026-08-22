"""Tests for codira Layer 0 capability contract export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import jsonschema  # type: ignore[import-untyped]
import pytest
from codira_analyzer_c import CAnalyzer
from codira_analyzer_cpp import CppAnalyzer
from codira_analyzer_python import PythonAnalyzer

from codira.capabilities import build_capability_contract
from codira.cli import main
from codira.registry import reset_plugin_registry_caches

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira.contracts import LanguageAnalyzer
    from codira.models import AnalysisResult


def _capabilities_schema() -> dict[str, object]:
    """
    Load the capability JSON schema from the source tree.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Parsed JSON schema payload.
    """
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "codira"
        / "schema"
        / "capabilities.schema.json"
    )
    return cast(
        "dict[str, object]", json.loads(schema_path.read_text(encoding="utf-8"))
    )


def test_python_analyzer_declares_explicit_ontology_mapping() -> None:
    """
    Keep the Python analyzer aligned to the issue #7 declaration contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the Python analyzer maps native artifacts explicitly.
    """
    declaration = PythonAnalyzer().analyzer_capability_declaration()

    assert declaration.analyzer_name == "python"
    assert declaration.supports == (
        "module",
        "type",
        "callable",
        "import",
        "constant",
        "documentation",
    )
    assert declaration.does_not_support == ("variable", "namespace")
    assert declaration.mappings == {
        "module": "module",
        "class": "type",
        "type_alias": "type",
        "constant": "constant",
        "function": "callable",
        "method": "callable",
        "import": "import",
        "module_docstring": "documentation",
    }
    assert declaration.target_compatibility is not None
    assert declaration.target_compatibility.configuration_key == (
        "plugins.analyzer-python.target_python"
    )
    assert declaration.target_compatibility.parser_compatibility == (
        "plugin_owned_tree_sitter"
    )


def test_c_analyzer_declares_explicit_ontology_mapping() -> None:
    """
    Keep the C analyzer aligned to the declaration-ontology contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the C analyzer maps native artifacts explicitly.
    """
    declaration = CAnalyzer().analyzer_capability_declaration()

    assert declaration.analyzer_name == "c"
    assert declaration.supports == (
        "module",
        "type",
        "callable",
        "import",
        "constant",
        "documentation",
    )
    assert declaration.does_not_support == ("variable", "namespace")
    assert declaration.mappings == {
        "module": "module",
        "function": "callable",
        "constant": "constant",
        "macro": "constant",
        "struct": "type",
        "union": "type",
        "enum": "type",
        "typedef": "type",
        "include_local": "import",
        "include_system": "import",
        "doxygen": "documentation",
    }


def test_cpp_analyzer_declares_explicit_ontology_mapping() -> None:
    """
    Keep the C++ analyzer aligned to the declaration-ontology contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the C++ analyzer maps native artifacts explicitly.
    """
    declaration = CppAnalyzer().analyzer_capability_declaration()

    assert declaration.analyzer_name == "cpp"
    assert declaration.supports == (
        "module",
        "type",
        "callable",
        "import",
        "constant",
        "namespace",
        "documentation",
    )
    assert declaration.does_not_support == ("variable",)
    assert declaration.mappings == {
        "module": "module",
        "class": "type",
        "struct": "type",
        "union": "type",
        "enum": "type",
        "type_alias": "type",
        "function": "callable",
        "method": "callable",
        "namespace": "namespace",
        "macro": "constant",
        "include_local": "import",
        "include_system": "import",
        "doxygen": "documentation",
    }


def test_capability_contract_validates_against_schema() -> None:
    """
    Build a deterministic capability contract for a declared analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the generated contract satisfies its JSON schema.
    """
    payload = build_capability_contract([PythonAnalyzer()])

    jsonschema.validate(payload, _capabilities_schema())
    assert payload["schema_version"] == "1.9"
    assert payload["ontology"] == {
        "version": "2",
        "types": [
            "module",
            "type",
            "callable",
            "import",
            "constant",
            "variable",
            "namespace",
            "documentation",
        ],
    }
    assert payload["validation"] == {"status": "ok", "issues": []}
    analyzers = cast("list[Mapping[str, object]]", payload["analyzers"])
    channels = cast("dict[str, object]", payload["channels"])
    commands = cast("dict[str, object]", payload["commands"])
    mcp = cast("Mapping[str, object]", payload["mcp"])
    plugins = cast("list[Mapping[str, object]]", payload["plugins"])
    plugin_families = cast("list[Mapping[str, object]]", payload["plugin_families"])
    retrieval_capabilities = cast("list[str]", payload["retrieval_capabilities"])
    assert [item["analyzer_name"] for item in analyzers] == ["python"]
    assert [item["declaration_status"] for item in analyzers] == ["declared"]
    python_plugin = next(
        item
        for item in plugins
        if item["family"] == "analyzer" and item["name"] == "python"
    )
    assert python_plugin["provider"] == "codira-analyzer-python"
    assert python_plugin["version"] == "11"
    assert python_plugin["distribution_version"] == "1.61.0"
    assert "symbol" in channels
    assert "docs" in channels
    assert "help" in commands
    assert "ctx" in commands
    assert "docs" in commands
    query_daemon_command = cast("Mapping[str, object]", commands["query-daemon"])
    assert query_daemon_command["intent"] == (
        "repository_local_warm_query_service_lifecycle"
    )
    assert payload["query_daemon"] == {
        "supported": True,
        "enabled": False,
        "lifecycle_commands": [
            "run",
            "install",
            "uninstall",
            "start",
            "stop",
            "status",
        ],
        "repository_scope": "one fixed repository root and effective output directory",
        "mutation_policy": "read_only; indexing daemon remains the automatic writer",
    }
    caps_command = cast("Mapping[str, object]", commands["caps"])
    assert "aliases" not in caps_command
    assert mcp == {
        "server_command": "codira-mcp",
        "config_command": "codira-mcp-config",
        "contract_version": "1.4.0",
        "transport": "stdio",
        "read_only": True,
        "tools": [
            "capabilities",
            "index_status",
            "symbol",
            "symbols",
            "references",
            "callers",
            "callees",
            "documentation_findings",
            "context_for_task",
            "impact_analysis",
            "repository_map",
            "arch",
            "emb",
            "docs",
        ],
    }
    emb_command = cast("Mapping[str, object]", commands["emb"])
    emb_subcommands = cast("Mapping[str, object]", emb_command["subcommands"])
    emb_purge = cast("Mapping[str, object]", emb_subcommands["purge"])
    assert emb_purge["modes"] == ["stale", "all"]
    emb_purge_options = cast("list[str]", emb_purge["options"])
    assert {"-S", "--stale", "-A", "--all"} <= set(emb_purge_options)
    assert {"-n", "--dry-run", "-b", "--backend"} <= set(emb_purge_options)
    assert {"-O", "--older-than"} <= set(emb_purge_options)
    assert {"-K", "--keep", "-y", "--yes"} <= set(emb_purge_options)
    declared_channels = set(channels)
    referenced_channels: set[str] = set()
    for command in commands.values():
        command_channels = cast(
            "Sequence[str]",
            cast("Mapping[str, object]", command)["channels"],
        )
        referenced_channels.update(command_channels)
    assert referenced_channels <= declared_channels
    help_command = cast("Mapping[str, object]", commands["help"])
    assert help_command["intent"] == "cli_help_rendering"
    assert help_command["channels"] == []
    symlist_command = cast("Mapping[str, object]", commands["symlist"])
    assert symlist_command["intent"] == "symbol_inventory"
    docs_command = cast("Mapping[str, object]", commands["docs"])
    assert docs_command["channels"] == ["docs"]
    assert {
        (item["family"], item["name"])
        for item in plugins
        if item["family"] in {"embedding", "vector-store"}
    } >= {
        ("embedding", "sentence-transformers"),
        ("embedding", "onnx"),
        ("vector-store", "sqlite"),
        ("vector-store", "duckdb"),
    }
    assert {(item["family"], item["name"]) for item in plugins if item["active"]} >= {
        ("backend", "sqlite"),
        ("embedding", "sentence-transformers"),
        ("vector-store", "sqlite"),
    }
    documentation_audit_family = {item["family"]: item for item in plugin_families}[
        "documentation-audit"
    ]
    assert documentation_audit_family["selection"] == "route_active"
    assert (
        documentation_audit_family["configuration"]
        == "plugins.documentation_audit_routes and plugins.documentation-audit-*"
    )
    assert "symbol_lookup" in retrieval_capabilities


def test_capability_contract_marks_routed_documentation_audit_plugins_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    Report documentation-audit plugins as active when selected by route config.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate config paths and current directory.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts ``codira caps`` treats documentation-audit as a
        route-selected plugin family.
    """
    repo_root = tmp_path / "repo"
    repo_config = repo_root / ".codira" / "config.toml"
    repo_config.parent.mkdir(parents=True)
    repo_config.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "python", convention = "numpy", plugin = "numpy" },
]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo_root)
    reset_plugin_registry_caches()

    payload = build_capability_contract([PythonAnalyzer()], root=repo_root)
    plugins = cast("list[Mapping[str, object]]", payload["plugins"])

    assert {
        (item["family"], item["name"], item["active"])
        for item in plugins
        if item["family"] == "documentation-audit"
    } >= {
        ("documentation-audit", "numpy", True),
        ("documentation-audit", "google", False),
        ("documentation-audit", "doxygen", False),
    }


def test_capability_contract_degrades_analyzers_without_declarations() -> None:
    """
    Preserve exports when an active analyzer omits Layer 0 declarations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts missing declarations become degraded metadata.
    """

    class UndeclaredAnalyzer:
        """Analyzer stub intentionally missing capability declarations."""

        name = "undeclared"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.txt",)

        def supports_path(self, path: Path) -> bool:
            """
            Report no path support for the stub analyzer.

            Parameters
            ----------
            path : pathlib.Path
                Candidate path.

            Returns
            -------
            bool
                Always ``False``.
            """
            del path
            return False

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            """
            Reject analysis for the stub analyzer.

            Parameters
            ----------
            path : pathlib.Path
                Candidate path.
            root : pathlib.Path
                Repository root.

            Returns
            -------
            object
                This method never returns a usable analysis result.

            Raises
            ------
            RuntimeError
                Always raised because the stub is never meant to analyze files.
            """
            del path, root
            msg = "not used"
            raise RuntimeError(msg)

    payload = build_capability_contract(
        [cast("LanguageAnalyzer", UndeclaredAnalyzer())]
    )

    jsonschema.validate(payload, _capabilities_schema())
    assert payload["validation"] == {
        "status": "degraded",
        "issues": ["undeclared: analyzer does not declare capabilities"],
    }
    analyzers = cast("list[Mapping[str, object]]", payload["analyzers"])
    assert analyzers == [
        {
            "analyzer_name": "undeclared",
            "analyzer_version": "1",
            "source": "unknown",
            "entrypoint": "unknown",
            "declaration_status": "missing",
            "supports": [],
            "does_not_support": [],
            "mappings": {},
            "checksum": None,
            "default_coverage_roots": [],
            "target_compatibility": None,
            "concurrency": {
                "declaration_status": "missing",
                "process_workers": False,
                "thread_workers": False,
                "reentrant_after_configure": False,
                "notes": [],
            },
        }
    ]


def test_capability_contract_strict_rejects_missing_declarations() -> None:
    """
    Fail fast in strict mode when an analyzer omits Layer 0 declarations.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts strict mode remains available for release gates.
    """

    class UndeclaredAnalyzer:
        """Analyzer stub intentionally missing capability declarations."""

        name = "undeclared"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.txt",)

        def supports_path(self, path: Path) -> bool:
            """
            Report no path support for the stub analyzer.

            Parameters
            ----------
            path : pathlib.Path
                Candidate path.

            Returns
            -------
            bool
                Always ``False``.
            """
            del path
            return False

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            """
            Reject analysis for the stub analyzer.

            Parameters
            ----------
            path : pathlib.Path
                Candidate path.
            root : pathlib.Path
                Repository root.

            Returns
            -------
            object
                This method never returns a usable analysis result.

            Raises
            ------
            RuntimeError
                Always raised because the stub is never meant to analyze files.
            """
            del path, root
            msg = "not used"
            raise RuntimeError(msg)

    with pytest.raises(ValueError, match="does not declare capabilities"):
        build_capability_contract(
            [cast("LanguageAnalyzer", UndeclaredAnalyzer())],
            strict=True,
        )


def test_capabilities_cli_exports_json_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Expose the capability contract through ``codira caps --json``.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set command-line arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts the CLI emits schema-valid JSON.
    """
    monkeypatch.setattr("sys.argv", ["codira", "caps", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    jsonschema.validate(payload, _capabilities_schema())
    analyzer_names = {item["analyzer_name"] for item in payload["analyzers"]}
    assert "python" in analyzer_names
    assert payload["commands"]["caps"]["intent"] == "capability_contract_export"
    assert "aliases" not in payload["commands"]["caps"]
    assert payload["mcp"]["server_command"] == "codira-mcp"


def test_capabilities_cli_human_summary_includes_embedding_plugins_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Expose embedding plugin state and MCP discovery in human ``caps`` output.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set command-line arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts the summary includes both human-facing surfaces.
    """
    monkeypatch.setattr("sys.argv", ["codira", "caps"])

    assert main() == 0
    output = capsys.readouterr().out

    assert "embedding_plugins: onnx" in output
    assert "sentence-transformers" in output
    assert "mcp: codira-mcp (stdio, read-only, tools: capabilities" in output


def test_top_level_help_advertises_local_mcp(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expose the separate local MCP entry points in top-level CLI help.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set command-line arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts help advertises both local MCP entry points.
    """
    monkeypatch.setattr("sys.argv", ["codira", "--help"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "Local MCP:" in output
    assert "codira-mcp --root ." in output
    assert "codira-mcp-config codex --root ." in output


def test_capabilities_cli_rejects_removed_long_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the removed ``codira capabilities`` compatibility alias.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set command-line arguments.

    Returns
    -------
    None
        The test asserts the removed compatibility alias remains unavailable.
    """
    monkeypatch.setattr("sys.argv", ["codira", "capabilities"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
