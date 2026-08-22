"""Tests for analyzer-independent architecture model extraction."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codira.architecture import (
    ArchitectureAnalyzerFact,
    ArchitectureForbiddenDependencyRule,
    ArchitectureLayer,
    ArchitectureModule,
    ArchitecturePolicy,
    ArchitectureRelation,
    ArchitectureSymbolEvidence,
    analyze_architecture_policy,
    build_architecture_model,
    build_architecture_model_from_index,
    validate_architecture_policy,
)
from codira.architecture_report import write_architecture_artifacts
from codira.cli import main
from codira.indexer import index_repo


def _module(
    name: str, *, facts: tuple[ArchitectureAnalyzerFact, ...] = ()
) -> ArchitectureModule:
    """Build one compact module fixture.

    Parameters
    ----------
    name : str
        Module name.
    facts : tuple[ArchitectureAnalyzerFact, ...], optional
        Analyzer facts retained by the fixture module.

    Returns
    -------
    ArchitectureModule
        Deterministic indexed module fixture.
    """
    return ArchitectureModule(
        name=name,
        path=name.replace(".", "/") + ".py",
        analyzer_name="python",
        facts=facts,
    )


def _relation(
    source: str,
    destination: str | None,
    kind: str = "import",
    name: str = "symbol",
) -> ArchitectureRelation:
    """Build one compact resolved-relation fixture.

    Parameters
    ----------
    source : str
        Source module name.
    destination : str | None
        Resolved destination module name.
    kind : str, optional
        Architecture relation family.
    name : str, optional
        Retained source symbol name.

    Returns
    -------
    ArchitectureRelation
        Relation with stable fixture evidence.
    """
    return ArchitectureRelation(
        source_module=source,
        destination_module=destination,
        kind=kind,  # type: ignore[arg-type]
        evidence=ArchitectureSymbolEvidence(
            module=source,
            name=name,
            path=source.replace(".", "/") + ".py",
            lineno=1,
        ),
    )


def test_build_architecture_model_aggregates_relations_and_retains_json_facts() -> None:
    """Preserve analyzer facts while aggregating evidence by module edge.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts deterministic aggregate graph contents.
    """
    json_fact = ArchitectureAnalyzerFact(
        kind="json_manifest_top_level_key",
        name="services",
        signature="manifest top-level key services",
    )
    model = build_architecture_model(
        (_module("pkg.api"), _module("pkg.config", facts=(json_fact,))),
        (
            _relation("pkg.api", "pkg.config", name="load"),
            _relation("pkg.api", "pkg.config", name="configure"),
            _relation("pkg.api", None, kind="call", name="unknown"),
        ),
    )

    assert model.modules[1].facts == (json_fact,)
    assert len(model.dependencies) == 1
    assert model.dependencies[0].source == "pkg.api"
    assert model.dependencies[0].destination == "pkg.config"
    assert [evidence.name for evidence in model.dependencies[0].evidence] == [
        "configure",
        "load",
    ]
    assert [
        (metric.module, metric.fan_in, metric.fan_out) for metric in model.metrics
    ] == [
        ("pkg.api", 0, 1),
        ("pkg.config", 1, 0),
    ]


def test_build_architecture_model_is_deterministic_and_reports_cycles() -> None:
    """Sort modules, edges, evidence, and strongly connected components.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts permutation-independent output and SCC detection.
    """
    modules = (_module("pkg.c"), _module("pkg.a"), _module("pkg.b"))
    relations = (
        _relation("pkg.b", "pkg.a", kind="call", name="b"),
        _relation("pkg.a", "pkg.b", kind="reference", name="a"),
        _relation("pkg.c", "pkg.c", name="self"),
    )

    model = build_architecture_model(modules, relations)
    replay = build_architecture_model(
        tuple(reversed(modules)), tuple(reversed(relations))
    )

    assert model == replay
    assert [cycle.members for cycle in model.cycles] == [("pkg.a", "pkg.b"), ("pkg.c",)]


def test_build_architecture_model_rejects_unknown_sources() -> None:
    """Reject relations that cannot be tied to indexed source inventory.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts source-inventory validation.
    """
    with pytest.raises(ValueError, match="source is not indexed"):
        build_architecture_model((_module("pkg.a"),), (_relation("pkg.b", "pkg.a"),))


def test_build_architecture_model_from_index_reads_persisted_facts_and_edges(
    tmp_path: Path,
) -> None:
    """Extract aggregate architecture data through backend-neutral queries.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary indexed repository root.

    Returns
    -------
    None
        The test asserts imports, calls, and JSON artifacts originate in index data.
    """
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "core.py").write_text(
        'def target() -> int:\n    """Return a fixed value."""\n    return 1\n',
        encoding="utf-8",
    )
    (package / "api.py").write_text(
        'from pkg.core import target\n\ndef caller() -> int:\n    """Call the core target."""\n    return target()\n',
        encoding="utf-8",
    )
    config = tmp_path / "config"
    config.mkdir()
    (config / "service-manifest.json").write_text(
        '{"services":{"api":{"path":"pkg/api.py"}},"deployments":[],"homepage":"https://example.invalid"}',
        encoding="utf-8",
    )

    index_repo(tmp_path)
    model = build_architecture_model_from_index(tmp_path)

    dependencies = {
        (edge.source, edge.destination, edge.kind) for edge in model.dependencies
    }
    assert ("pkg.api", "pkg.core", "import") in dependencies
    assert ("pkg.api", "pkg.core", "call") in dependencies
    manifest = next(
        module for module in model.modules if module.name == "config.service_manifest"
    )
    assert any(fact.kind == "json_manifest_top_level_key" for fact in manifest.facts)


def test_architecture_policy_uses_first_layer_for_overlapping_prefixes() -> None:
    """Resolve overlapping path prefixes by declared configuration order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts ordered layers, unlayered modules, violations, and ties.
    """
    modules = (
        ArchitectureModule("api", "src/api/handlers.py", "python"),
        ArchitectureModule("core", "src/core/logic.py", "python"),
        ArchitectureModule("tool", "tools/check.py", "python"),
    )
    model = build_architecture_model(
        modules,
        (
            _relation("api", "core", name="route"),
            _relation("core", "api", kind="call", name="callback"),
        ),
    )
    policy = ArchitecturePolicy(
        layers=(
            ArchitectureLayer("application", "src"),
            ArchitectureLayer("api", "src/api"),
            ArchitectureLayer("core", "src/core"),
        ),
        forbidden_dependencies=(
            ArchitectureForbiddenDependencyRule(
                "api-must-not-call-core", "application", "core", "error"
            ),
        ),
    )

    analysis = analyze_architecture_policy(model, policy)

    assert [(row.module, row.layer) for row in analysis.assignments] == [
        ("api", "application"),
        ("core", "application"),
        ("tool", None),
    ]
    assert analysis.violations == ()
    assert [row.module for row in analysis.hotspots] == ["api", "core", "tool"]


def test_architecture_policy_reports_forbidden_edges_with_evidence() -> None:
    """Report explicit forbidden dependencies with their aggregate evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts allowed and forbidden layer edges remain distinguishable.
    """
    model = build_architecture_model(
        (
            ArchitectureModule("api", "src/api/handlers.py", "python"),
            ArchitectureModule("core", "src/core/logic.py", "python"),
        ),
        (
            _relation("api", "core", kind="call", name="route"),
            _relation("core", "api", name="callback"),
        ),
    )
    policy = ArchitecturePolicy(
        layers=(
            ArchitectureLayer("api", "src/api"),
            ArchitectureLayer("core", "src/core"),
        ),
        forbidden_dependencies=(
            ArchitectureForbiddenDependencyRule(
                "api-must-not-call-core", "api", "core", "error"
            ),
        ),
    )

    analysis = analyze_architecture_policy(model, policy)

    assert [(row.module, row.layer) for row in analysis.assignments] == [
        ("api", "api"),
        ("core", "core"),
    ]
    assert [
        (row.rule_id, row.source, row.destination, row.edge_kind)
        for row in analysis.violations
    ] == [
        ("api-must-not-call-core", "api", "core", "call"),
    ]
    assert analysis.violations[0].evidence[0].name == "route"


def test_architecture_artifacts_replay_and_record_missing_graphviz(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render byte-stable mandatory artifacts without optional Graphviz.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary artifact output root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to make Graphviz deterministically unavailable.

    Returns
    -------
    None
        The test asserts shared-model render replay and stable SVG diagnostics.
    """
    fact = ArchitectureAnalyzerFact(
        kind="json_manifest_top_level_key",
        name="services",
        signature="manifest top-level key services",
    )
    model = build_architecture_model(
        (_module("pkg.api"), _module("pkg.core", facts=(fact,))),
        (_relation("pkg.api", "pkg.core", kind="call", name="route"),),
    )
    policy = ArchitecturePolicy(layers=(), forbidden_dependencies=())
    analysis = analyze_architecture_policy(model, policy)
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    first = write_architecture_artifacts(model, analysis, tmp_path / "first")
    second = write_architecture_artifacts(model, analysis, tmp_path / "second")

    for name in (
        "architecture.dot",
        "architecture.md",
        "dependencies.json",
        "hotspots.json",
        "violations.json",
    ):
        assert (first.output_dir / name).read_bytes() == (
            second.output_dir / name
        ).read_bytes()
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert first.svg_path is None
    assert manifest["svg"] == {
        "available": False,
        "warning": "Graphviz SVG not rendered: dot executable unavailable.",
    }
    assert "json_manifest_top_level_key:services" in first.markdown_path.read_text(
        encoding="utf-8"
    )


def test_architecture_artifacts_record_successful_optional_svg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record SVG in the manifest when the optional renderer succeeds.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary artifact output root.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the external Graphviz process.

    Returns
    -------
    None
        The test asserts the successful optional-rendering path.
    """
    model = build_architecture_model((_module("pkg.api"),), ())
    analysis = analyze_architecture_policy(
        model, ArchitecturePolicy(layers=(), forbidden_dependencies=())
    )

    def _render_svg(arguments: list[str], **_kwargs: object) -> object:
        """Write a minimal SVG through the mocked Graphviz command.

        Parameters
        ----------
        arguments : list[str]
            Graphviz argument vector.
        _kwargs : object
            Ignored subprocess keyword arguments.

        Returns
        -------
        object
            Result object carrying a successful return code.
        """
        Path(arguments[3]).write_text("<svg />", encoding="utf-8")
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/dot")
    monkeypatch.setattr(subprocess, "run", _render_svg)

    result = write_architecture_artifacts(model, analysis, tmp_path)

    assert result.svg_path == tmp_path / "architecture.svg"
    assert json.loads(result.manifest_path.read_text(encoding="utf-8"))["svg"] == {
        "available": True,
        "warning": None,
    }


def test_architecture_report_cli_writes_requested_output_and_policy_diagnostics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render architecture artifacts through the public CLI command.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture command output.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to patch command arguments and current directory.

    Returns
    -------
    None
        The test asserts explicit routing and layer-policy output.
    """
    source = tmp_path / "src"
    source.mkdir()
    (source / "core.py").write_text(
        'def target() -> int:\n    """Return a fixed value."""\n    return 1\n',
        encoding="utf-8",
    )
    (source / "api.py").write_text(
        'from core import target\n\ndef caller() -> int:\n    """Call the target."""\n    return target()\n',
        encoding="utf-8",
    )
    index_repo(tmp_path)
    output = tmp_path / "report"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "arch",
            "--output",
            str(output),
            "--layer",
            "api=src/api.py",
            "--layer",
            "core=src/core.py",
            "--forbid",
            "no-api-core:api:core:error",
        ],
    )

    assert main() == 0
    assert "Wrote architecture report" in capsys.readouterr().out
    violations = json.loads((output / "violations.json").read_text(encoding="utf-8"))
    assert violations[0]["rule_id"] == "no-api-core"


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (
            ArchitecturePolicy(
                layers=(
                    ArchitectureLayer("core", "src/core"),
                    ArchitectureLayer("core", "src/api"),
                ),
                forbidden_dependencies=(),
            ),
            "name is duplicated",
        ),
        (
            ArchitecturePolicy(
                layers=(ArchitectureLayer("core", "src/core"),),
                forbidden_dependencies=(
                    ArchitectureForbiddenDependencyRule(
                        "bad", "core", "missing", "error"
                    ),
                ),
            ),
            "unknown layer",
        ),
    ],
)
def test_validate_architecture_policy_rejects_ambiguous_rules(
    policy: ArchitecturePolicy,
    message: str,
) -> None:
    """Reject ambiguous layers and rules before policy evaluation.

    Parameters
    ----------
    policy : ArchitecturePolicy
        Invalid policy fixture.
    message : str
        Expected deterministic validation error fragment.

    Returns
    -------
    None
        The test asserts strict configuration validation.
    """
    with pytest.raises(ValueError, match=message):
        validate_architecture_policy(policy)
