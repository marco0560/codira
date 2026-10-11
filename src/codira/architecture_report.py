"""Deterministic renderers for the shared architecture domain model.

This module owns artifact serialization only. It receives the analyzer-neutral
architecture model and policy analysis rather than inspecting analyzers,
databases, or source files directly.

Parameters
----------
None

Returns
-------
None
    Defines the runtime interfaces described above.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.architecture import ArchitectureModel, ArchitecturePolicyAnalysis


@dataclass(frozen=True)
class ArchitectureRenderOptions:
    """Control optional rendering and retain measured phase durations.

    Parameters
    ----------
    render_svg : bool, optional
        Whether to run optional Graphviz layout.
    svg_timeout_seconds : float, optional
        Finite nonnegative limit; zero explicitly disables the bound.
    phase_timings : dict of str to float or None, optional
        Caller-measured extraction and policy durations.

    Returns
    -------
    None
        Immutable rendering controls used by the CLI and library callers.
    """

    render_svg: bool = True
    svg_timeout_seconds: float = 60
    phase_timings: dict[str, float] | None = None


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


def _terminate_svg_renderer(process: subprocess.Popen[str]) -> None:
    """Terminate and reap only the renderer's owned process group.

    Parameters
    ----------
    process : subprocess.Popen
        Renderer started in its own session.

    Returns
    -------
    None
        The process and its inherited output pipes have been reaped.
    """
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
    process.communicate()


def _render_svg(
    dot_path: Path, svg_path: Path, *, timeout_seconds: float = 30
) -> tuple[Path | None, str | None]:
    """Render optional SVG with a bound on the owned Graphviz process group.

    Parameters
    ----------
    dot_path : pathlib.Path
        Existing DOT input artifact.
    svg_path : pathlib.Path
        Requested SVG output location.
    timeout_seconds : float, optional
        Rendering limit; zero explicitly permits unbounded rendering.

    Returns
    -------
    tuple[pathlib.Path | None, str | None]
        SVG path on success, otherwise a warning after renderer cleanup.
    """
    executable = shutil.which("dot")
    if executable is None:
        return None, "Graphviz SVG not rendered: dot executable unavailable."
    try:
        with subprocess.Popen(
            [executable, "-Tsvg", "-o", str(svg_path), str(dot_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as process:
            try:
                process.communicate(timeout=timeout_seconds or None)
            except subprocess.TimeoutExpired:
                _terminate_svg_renderer(process)
                svg_path.unlink(missing_ok=True)
                return (
                    None,
                    f"Graphviz SVG not rendered: exceeded {timeout_seconds:g} seconds.",
                )
            except BaseException:
                _terminate_svg_renderer(process)
                raise
            if process.returncode != 0:
                svg_path.unlink(missing_ok=True)
                return None, "Graphviz SVG not rendered: dot exited unsuccessfully."
    except FileNotFoundError:
        return None, "Graphviz SVG not rendered: dot executable unavailable."
    return svg_path, None


def write_architecture_artifacts(
    model: ArchitectureModel,
    analysis: ArchitecturePolicyAnalysis,
    output_dir: Path,
    *,
    options: ArchitectureRenderOptions | None = None,
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
    options : ArchitectureRenderOptions or None, optional
        Optional SVG controls and extraction/policy phase measurements.

    Returns
    -------
    ArchitectureArtifactResult
        Mandatory paths plus optional SVG status.

    Raises
    ------
    ValueError
        If the SVG timeout is negative or nonfinite.
    OSError
        If mandatory artifacts cannot be written.
    """
    options = options or ArchitectureRenderOptions()
    render_svg, svg_timeout_seconds = options.render_svg, options.svg_timeout_seconds
    if not math.isfinite(svg_timeout_seconds) or svg_timeout_seconds < 0:
        message = "SVG timeout must be finite and nonnegative."
        raise ValueError(message)
    start = time.perf_counter()
    timings = dict(options.phase_timings or {})
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
    timings["artifacts_seconds"] = time.perf_counter() - start
    start = time.perf_counter()
    svg_path.unlink(missing_ok=True)
    rendered_svg_path, warning = (
        _render_svg(dot_path, svg_path, timeout_seconds=svg_timeout_seconds)
        if render_svg
        else (None, "Graphviz SVG not rendered: disabled by operator.")
    )
    timings["svg_seconds"] = time.perf_counter() - start
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
                "timings": timings,
                "render_options": {
                    "svg": render_svg,
                    "svg_timeout_seconds": svg_timeout_seconds,
                },
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
