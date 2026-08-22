"""Deterministic renderers for the shared architecture domain model.

This module owns artifact serialization only. It receives the analyzer-neutral
architecture model and policy analysis rather than inspecting analyzers,
databases, or source files directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.architecture import ArchitectureModel, ArchitecturePolicyAnalysis


@dataclass(frozen=True)
class ArchitectureArtifactResult:
    """Paths and optional SVG diagnostic from one architecture render.

    Parameters
    ----------
    output_dir : pathlib.Path
        Directory containing all mandatory artifacts.
    dot_path : pathlib.Path
        DOT graph artifact.
    markdown_path : pathlib.Path
        Human-readable architecture report.
    dependencies_path : pathlib.Path
        Structured model inventory and dependency artifact.
    hotspots_path : pathlib.Path
        Structured hotspot ranking artifact.
    violations_path : pathlib.Path
        Structured policy-violation artifact.
    manifest_path : pathlib.Path
        Artifact manifest with stable SVG status.
    svg_path : pathlib.Path | None
        SVG artifact when optional Graphviz rendering succeeded.
    warning : str | None
        Stable optional-rendering warning when SVG is unavailable.

    Returns
    -------
    None
        Instances describe files emitted during one render pass.
    """

    output_dir: Path
    dot_path: Path
    markdown_path: Path
    dependencies_path: Path
    hotspots_path: Path
    violations_path: Path
    manifest_path: Path
    svg_path: Path | None
    warning: str | None


def _json_bytes(value: object) -> bytes:
    """Serialize one architecture value as canonical UTF-8 JSON.

    Parameters
    ----------
    value : object
        JSON-compatible data to serialize.

    Returns
    -------
    bytes
        Sorted, indented UTF-8 JSON terminated by one newline.
    """
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _dot_quote(value: str) -> str:
    """Escape one DOT identifier or label string.

    Parameters
    ----------
    value : str
        Raw identifier or label value.

    Returns
    -------
    str
        Double-quoted DOT-safe representation.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_dot(model: ArchitectureModel) -> str:
    """Render one architecture model to a deterministic DOT graph.

    Parameters
    ----------
    model : codira.architecture.ArchitectureModel
        Shared architecture graph model.

    Returns
    -------
    str
        DOT text terminated by one newline.
    """
    lines = ["digraph architecture {", "  rankdir=LR;", "  node [shape=box];"]
    for module in model.modules:
        lines.append(f"  {_dot_quote(module.name)} [label={_dot_quote(module.name)}];")
    for dependency in model.dependencies:
        lines.append(
            "  "
            f"{_dot_quote(dependency.source)} -> {_dot_quote(dependency.destination)} "
            f"[label={_dot_quote(dependency.kind)}];"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_markdown(
    model: ArchitectureModel,
    analysis: ArchitecturePolicyAnalysis,
) -> str:
    """Render a deterministic human-readable architecture summary.

    Parameters
    ----------
    model : codira.architecture.ArchitectureModel
        Shared architecture graph model.
    analysis : codira.architecture.ArchitecturePolicyAnalysis
        Policy metrics and diagnostics for the model.

    Returns
    -------
    str
        Markdown report terminated by one newline.
    """
    lines = [
        "# Architecture Report",
        "",
        "## Summary",
        "",
        f"- Modules: {len(model.modules)}",
        f"- Dependencies: {len(model.dependencies)}",
        f"- Cycles: {len(model.cycles)}",
        f"- Policy violations: {len(analysis.violations)}",
        "",
        "## Module Inventory",
        "",
        "| Module | Path | Analyzer facts |",
        "| --- | --- | --- |",
    ]
    for module in model.modules:
        facts = ", ".join(f"`{fact.kind}:{fact.name}`" for fact in module.facts)
        lines.append(f"| `{module.name}` | `{module.path}` | {facts or '-'} |")
    lines.extend(
        [
            "",
            "## Hotspots",
            "",
            "| Module | Fan-in | Fan-out | Score |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for hotspot in analysis.hotspots:
        lines.append(
            f"| `{hotspot.module}` | {hotspot.fan_in} | {hotspot.fan_out} | {hotspot.score} |"
        )
    lines.extend(["", "## Cycles", ""])
    if model.cycles:
        lines.extend(f"- {' -> '.join(cycle.members)}" for cycle in model.cycles)
    else:
        lines.append("- None")
    lines.extend(["", "## Violations", ""])
    if analysis.violations:
        for violation in analysis.violations:
            lines.append(
                "- "
                f"`{violation.rule_id}` ({violation.severity}): "
                f"`{violation.source}` -> `{violation.destination}` "
                f"({violation.edge_kind})"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def _render_svg(dot_path: Path, svg_path: Path) -> tuple[Path | None, str | None]:
    """Render optional SVG through Graphviz without making it a dependency.

    Parameters
    ----------
    dot_path : pathlib.Path
        Existing DOT input artifact.
    svg_path : pathlib.Path
        Requested SVG output location.

    Returns
    -------
    tuple[pathlib.Path | None, str | None]
        SVG path on success, otherwise one stable warning.
    """
    executable = shutil.which("dot")
    if executable is None:
        return None, "Graphviz SVG not rendered: dot executable unavailable."
    try:
        completed = subprocess.run(
            [executable, "-Tsvg", "-o", str(svg_path), str(dot_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, "Graphviz SVG not rendered: dot executable unavailable."
    if completed.returncode != 0:
        return None, "Graphviz SVG not rendered: dot exited unsuccessfully."
    return svg_path, None


def write_architecture_artifacts(
    model: ArchitectureModel,
    analysis: ArchitecturePolicyAnalysis,
    output_dir: Path,
) -> ArchitectureArtifactResult:
    """Write the complete deterministic architecture artifact set.

    Parameters
    ----------
    model : codira.architecture.ArchitectureModel
        Shared architecture graph model.
    analysis : codira.architecture.ArchitecturePolicyAnalysis
        Derived policy metrics and diagnostics.
    output_dir : pathlib.Path
        Destination directory for report artifacts.

    Returns
    -------
    ArchitectureArtifactResult
        Mandatory paths plus optional SVG status.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    dot_path = output_dir / "architecture.dot"
    markdown_path = output_dir / "architecture.md"
    dependencies_path = output_dir / "dependencies.json"
    hotspots_path = output_dir / "hotspots.json"
    violations_path = output_dir / "violations.json"
    manifest_path = output_dir / "manifest.json"
    svg_path = output_dir / "architecture.svg"
    dot_path.write_text(render_dot(model), encoding="utf-8")
    markdown_path.write_text(_render_markdown(model, analysis), encoding="utf-8")
    dependencies_path.write_bytes(_json_bytes(asdict(model)))
    hotspots_path.write_bytes(
        _json_bytes([asdict(hotspot) for hotspot in analysis.hotspots])
    )
    violations_path.write_bytes(
        _json_bytes([asdict(violation) for violation in analysis.violations])
    )
    rendered_svg_path, warning = _render_svg(dot_path, svg_path)
    manifest_path.write_bytes(
        _json_bytes(
            {
                "artifacts": [
                    dot_path.name,
                    markdown_path.name,
                    dependencies_path.name,
                    hotspots_path.name,
                    violations_path.name,
                    *([svg_path.name] if rendered_svg_path is not None else []),
                ],
                "svg": {
                    "available": rendered_svg_path is not None,
                    "warning": warning,
                },
            }
        )
    )
    return ArchitectureArtifactResult(
        output_dir=output_dir,
        dot_path=dot_path,
        markdown_path=markdown_path,
        dependencies_path=dependencies_path,
        hotspots_path=hotspots_path,
        violations_path=violations_path,
        manifest_path=manifest_path,
        svg_path=rendered_svg_path,
        warning=warning,
    )
