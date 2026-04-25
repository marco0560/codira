"""Tests for codira Layer 0 capability contract export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import jsonschema  # type: ignore[import-untyped]
import pytest
from codira_analyzer_c import CAnalyzer
from codira_analyzer_python import PythonAnalyzer

from codira.capabilities import build_capability_contract
from codira.cli import main

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    assert declaration.supports == ("module", "type", "callable", "import", "constant")
    assert declaration.does_not_support == ("variable", "namespace")
    assert declaration.mappings == {
        "module": "module",
        "class": "type",
        "type_alias": "type",
        "constant": "constant",
        "function": "callable",
        "method": "callable",
        "import": "import",
    }


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
    assert declaration.supports == ("module", "type", "callable", "import", "constant")
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
    assert payload["schema_version"] == "1.0"
    assert payload["ontology"] == {
        "version": "1",
        "types": [
            "module",
            "type",
            "callable",
            "import",
            "constant",
            "variable",
            "namespace",
        ],
    }
    assert payload["validation"] == {"status": "ok", "issues": []}
    analyzers = cast("list[Mapping[str, object]]", payload["analyzers"])
    channels = cast("dict[str, object]", payload["channels"])
    commands = cast("dict[str, object]", payload["commands"])
    retrieval_capabilities = cast("list[str]", payload["retrieval_capabilities"])
    assert [item["analyzer_name"] for item in analyzers] == ["python"]
    assert [item["declaration_status"] for item in analyzers] == ["declared"]
    assert "symbol" in channels
    assert "ctx" in commands
    symlist_command = cast("Mapping[str, object]", commands["symlist"])
    assert symlist_command["intent"] == "symbol_inventory"
    assert "symbol_lookup" in retrieval_capabilities


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
    assert payload["commands"]["caps"]["aliases"] == ["capabilities"]


def test_capabilities_cli_keeps_long_alias(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Preserve ``codira capabilities`` as a compatibility alias.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to set command-line arguments.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.

    Returns
    -------
    None
        The test asserts the long alias emits schema-valid JSON.
    """
    monkeypatch.setattr("sys.argv", ["codira", "capabilities", "--json"])

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    jsonschema.validate(payload, _capabilities_schema())
    assert payload["validation"]["status"] == "ok"
