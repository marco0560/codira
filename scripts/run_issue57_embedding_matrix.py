#!/usr/bin/env python3
"""Run the issue #57 embedding benchmark matrix."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import resolve_codira, resolve_python


def manifest_repositories(manifest_path: Path) -> tuple[Path, ...]:
    """
    Read repository paths from a benchmark manifest.

    Parameters
    ----------
    manifest_path : pathlib.Path
        Benchmark manifest path.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Absolute repository paths.
    """

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return tuple(
        Path(row["path"]).expanduser().resolve() for row in payload["repositories"]
    )


def write_config(path: Path, body: str) -> None:
    """
    Write one TOML config fixture.

    Parameters
    ----------
    path : pathlib.Path
        Output config path.
    body : str
        TOML body.

    Returns
    -------
    None
        The file is written.
    """

    path.write_text(body.strip() + "\n", encoding="utf-8")


def write_matrix_configs(config_root: Path) -> None:
    """
    Write benchmark scenario configs.

    Parameters
    ----------
    config_root : pathlib.Path
        Output config directory.

    Returns
    -------
    None
        Config files are written.
    """

    config_root.mkdir(parents=True, exist_ok=True)
    scenarios = {
        "immediate-full": 'mode = "immediate"\nobject_types = ["symbol", "documentation"]\nmax_text_chars = 0',
        "deferred-full": 'mode = "deferred"\nobject_types = ["symbol", "documentation"]\nmax_text_chars = 0',
        "immediate-symbol-only": 'mode = "immediate"\nobject_types = ["symbol"]\nmax_text_chars = 0',
        "immediate-documentation-only": 'mode = "immediate"\nobject_types = ["documentation"]\nmax_text_chars = 0',
        "immediate-no-embeddings": 'mode = "immediate"\nobject_types = []\nmax_text_chars = 0',
        "immediate-capped-docs": 'mode = "immediate"\nobject_types = ["symbol", "documentation"]\nmax_text_chars = 2000',
    }
    for name, body in scenarios.items():
        write_config(
            config_root / f"{name}.toml",
            f"""
            config_version = 1

            [embeddings.indexing]
            {body}
            include_paths = []
            exclude_paths = []
            """,
        )


def run_campaign_scenario(  # noqa: PLR0913
    scenario: str,
    config_file: Path,
    *,
    manifest_path: Path,
    repos: tuple[Path, ...],
    matrix_root: Path,
    artifact_root: Path,
    log_root: Path,
    metadata_root: Path,
    stamp: str,
    python: str,
    codira: str,
) -> int:
    """
    Run one matrix scenario.

    Parameters
    ----------
    scenario : str
        Scenario name.
    config_file : pathlib.Path
        Config applied before running.
    manifest_path : pathlib.Path
        Benchmark manifest.
    repos : tuple[pathlib.Path, ...]
        Repositories listed in the manifest.
    matrix_root : pathlib.Path
        Matrix artifact root.
    artifact_root : pathlib.Path
        Campaign artifact root.
    log_root : pathlib.Path
        Log output directory.
    metadata_root : pathlib.Path
        Metadata output directory.
    stamp : str
        Matrix stamp.
    python : str
        Python executable.
    codira : str
        Codira executable.

    Returns
    -------
    int
        Scenario status.
    """

    print(f"== Scenario: {scenario} ==")
    (metadata_root / f"{scenario}.started-at.txt").write_text(
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "MANIFEST": str(manifest_path),
            "ARTIFACT_ROOT": str(artifact_root),
            "STAMP": f"{stamp}-{scenario}",
            "PYTHON": python,
            "CODIRA": codira,
        }
    )
    with (log_root / f"{scenario}.log").open("w", encoding="utf-8") as log_file:
        status = subprocess.call(
            [
                python,
                "-m",
                "scripts.run_manifest_baseline",
                str(manifest_path),
                "--config-file",
                str(config_file),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
    (metadata_root / f"{scenario}.finished-at.txt").write_text(
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    (metadata_root / f"{scenario}.status").write_text(f"{status}\n", encoding="utf-8")
    print(f"Scenario {scenario} status={status}")
    return status


def run_embeddings_only_after_deferred(  # noqa: PLR0913
    *,
    repos: tuple[Path, ...],
    config_file: Path,
    artifact_root: Path,
    log_root: Path,
    metadata_root: Path,
    stamp: str,
    codira: str,
) -> int:
    """
    Run embeddings-only indexing after the deferred-full scenario.

    Parameters
    ----------
    repos : tuple[pathlib.Path, ...]
        Repository roots to index.
    config_file : pathlib.Path
        Deferred scenario config used for the embeddings-only pass.
    artifact_root : pathlib.Path
        Campaign artifact root.
    log_root : pathlib.Path
        Log output directory.
    metadata_root : pathlib.Path
        Metadata output directory.
    stamp : str
        Matrix stamp.
    codira : str
        Codira executable.

    Returns
    -------
    int
        Scenario status.
    """

    scenario = "embeddings-only-after-deferred"
    print(f"== Scenario: {scenario} ==")
    status = 0
    log_path = log_root / f"{scenario}.log"
    (metadata_root / f"{scenario}.started-at.txt").write_text(
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        for backend in ("sqlite", "duckdb"):
            for repo in repos:
                label = repo.name
                print(f"== {backend}: {label} embeddings-only ==")
                print(f"== {backend}: {label} embeddings-only ==", file=log_file)
                env = dict(os.environ)
                env.update(
                    {
                        "CODIRA_INDEX_BACKEND": backend,
                        "CODIRA_DISABLE_THIRD_PARTY_PLUGINS": os.environ.get(
                            "CODIRA_DISABLE_THIRD_PARTY_PLUGINS", "1"
                        ),
                        "CODIRA_EMBED_BATCH_SIZE": os.environ.get(
                            "CODIRA_EMBED_BATCH_SIZE", "32"
                        ),
                        "CODIRA_TORCH_NUM_THREADS": os.environ.get(
                            "CODIRA_TORCH_NUM_THREADS", "10"
                        ),
                        "CODIRA_TORCH_NUM_INTEROP_THREADS": os.environ.get(
                            "CODIRA_TORCH_NUM_INTEROP_THREADS", "1"
                        ),
                    }
                )
                with (
                    (log_root / f"{scenario}.{backend}.{label}.json").open(
                        "w", encoding="utf-8"
                    ) as stdout_file,
                    (log_root / f"{scenario}.{backend}.{label}.stderr").open(
                        "w", encoding="utf-8"
                    ) as stderr_file,
                ):
                    rc = subprocess.call(
                        [
                            codira,
                            "index",
                            "--embeddings-only",
                            "--json",
                            "--path",
                            str(repo),
                            "--output-dir",
                            str(
                                artifact_root
                                / f"{stamp}-deferred-full-bk-cpp-{backend}"
                                / "indexes"
                                / repo.name
                            ),
                            "--config-file",
                            str(config_file),
                        ],
                        stdout=stdout_file,
                        stderr=stderr_file,
                        env=env,
                    )
                print(f"{backend} {label} status={rc}")
                print(f"{backend} {label} status={rc}", file=log_file)
                if rc and not status:
                    status = rc
    (metadata_root / f"{scenario}.finished-at.txt").write_text(
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    (metadata_root / f"{scenario}.status").write_text(f"{status}\n", encoding="utf-8")
    print(f"Scenario {scenario} status={status}")
    return status


def write_index(  # noqa: PLR0913
    *,
    matrix_root: Path,
    manifest_path: Path,
    artifact_root: Path,
    config_root: Path,
    log_root: Path,
    metadata_root: Path,
    stamp: str,
) -> None:
    """
    Write matrix README.

    Parameters
    ----------
    matrix_root : pathlib.Path
        Matrix root.
    manifest_path : pathlib.Path
        Benchmark manifest.
    artifact_root : pathlib.Path
        Campaign artifact root.
    config_root : pathlib.Path
        Config directory.
    log_root : pathlib.Path
        Log directory.
    metadata_root : pathlib.Path
        Metadata directory.
    stamp : str
        Matrix stamp.

    Returns
    -------
    None
        README is written.
    """

    lines = [
        "# Issue #57 embedding benchmark matrix",
        "",
        f"- Started stamp: `{stamp}`",
        f"- Manifest: `{manifest_path}`",
        f"- Matrix root: `{matrix_root}`",
        "",
        "## Scenarios",
        "",
    ]
    for status_file in sorted(metadata_root.glob("*.status")):
        lines.append(
            f"- `{status_file.stem}`: status `{status_file.read_text(encoding='utf-8').strip()}`"
        )
    lines.extend(["", "## Campaign artifact directories", ""])
    lines.extend(
        f"- `{path}`" for path in sorted(artifact_root.glob("*")) if path.is_dir()
    )
    lines.extend(["", "## Logs", ""])
    lines.extend(
        f"- `{path}`" for path in sorted(log_root.rglob("*")) if path.is_file()
    )
    lines.extend(["", "## Configs", ""])
    lines.extend(
        f"- `{path}`" for path in sorted(config_root.rglob("*")) if path.is_file()
    )
    (matrix_root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """
    Run the issue #57 matrix.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments.

    Returns
    -------
    int
        Process exit status.
    """

    parser = argparse.ArgumentParser(description="Run the issue #57 embedding matrix.")
    parser.add_argument("manifest", nargs="?", default="benchmarks/bk-cpp.local.json")
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        parser.error(f"manifest not found: {manifest_path}")

    python = resolve_python()
    codira = resolve_codira()
    stamp = os.environ.get("STAMP", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    matrix_root = Path(
        os.environ.get("MATRIX_ROOT", f".artifacts/issue-057-embedding-matrix/{stamp}")
    )
    artifact_root = matrix_root / "campaigns"
    config_root = matrix_root / "configs"
    log_root = matrix_root / "logs"
    metadata_root = matrix_root / "metadata"
    for path in (artifact_root, config_root, log_root, metadata_root):
        path.mkdir(parents=True, exist_ok=True)

    shutil.copy2(manifest_path, metadata_root / "manifest.json")
    repos = manifest_repositories(manifest_path)
    (metadata_root / "manifest-repositories.txt").write_text(
        "".join(f"{repo}\n" for repo in repos),
        encoding="utf-8",
    )
    write_matrix_configs(config_root)

    status = 0
    for scenario in (
        "deferred-full",
        "immediate-symbol-only",
        "immediate-documentation-only",
        "immediate-no-embeddings",
        "immediate-capped-docs",
    ):
        config_file = config_root / f"{scenario}.toml"
        rc = run_campaign_scenario(
            scenario,
            config_file,
            manifest_path=manifest_path,
            repos=repos,
            matrix_root=matrix_root,
            artifact_root=artifact_root,
            log_root=log_root,
            metadata_root=metadata_root,
            stamp=stamp,
            python=python,
            codira=codira,
        )
        if rc and not status:
            status = rc
        if scenario == "deferred-full":
            rc = run_embeddings_only_after_deferred(
                repos=repos,
                config_file=config_file,
                artifact_root=artifact_root,
                log_root=log_root,
                metadata_root=metadata_root,
                stamp=stamp,
                codira=codira,
            )
            if rc and not status:
                status = rc

    write_index(
        matrix_root=matrix_root,
        manifest_path=manifest_path,
        artifact_root=artifact_root,
        config_root=config_root,
        log_root=log_root,
        metadata_root=metadata_root,
        stamp=stamp,
    )
    print()
    print(f"Matrix root: {matrix_root}")
    print(f"Index: {matrix_root}/README.md")
    print(f"Status: {status}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
