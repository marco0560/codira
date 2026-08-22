"""Integration characterization for persisted architecture-report inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from codira.architecture import build_architecture_model_from_index
from codira.indexer import index_repo


def test_architecture_index_fixture_retains_recognized_json_and_rejects_decoys(
    tmp_path: Path,
) -> None:
    """Characterize report inventory for all supported JSON families.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root containing JSON-family fixtures.

    Returns
    -------
    None
        The test asserts persisted facts survive into architecture inventory.
    """
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "item.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","properties":{"name":{"type":"string"}}}',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name":"fixture","version":"1.0.0","scripts":{"test":"pytest"}}',
        encoding="utf-8",
    )
    (tmp_path / ".releaserc.json").write_text(
        '{"branches":["main"],"plugins":["@semantic-release/commit-analyzer"]}',
        encoding="utf-8",
    )
    config = tmp_path / "config"
    config.mkdir()
    (config / "project-manifest.json").write_text(
        '{"services":{"web":{"path":"src/web"}},"deployments":[],"homepage":"https://example.invalid"}',
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text('{"task":"build"}', encoding="utf-8")

    index_repo(tmp_path)
    model = build_architecture_model_from_index(tmp_path)
    facts_by_module = {
        module.name: {fact.kind for fact in module.facts} for module in model.modules
    }

    assert "json_schema_property" in facts_by_module["schema.item_schema"]
    assert "json_manifest_ecosystem" in facts_by_module["package"]
    assert "json_release_plugin" in facts_by_module["releaserc"]
    assert "json_manifest_top_level_key" in facts_by_module["config.project_manifest"]
    assert "manifest" not in facts_by_module


def test_architecture_model_from_index_supports_duckdb(tmp_path: Path) -> None:
    """Exercise architecture extraction through the DuckDB backend contract.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary DuckDB-configured repository root.

    Returns
    -------
    None
        The test asserts persisted imports survive backend-neutral extraction.
    """
    pytest.importorskip("duckdb")
    config = tmp_path / ".codira"
    config.mkdir()
    (config / "config.toml").write_text(
        '[backend]\nname = "duckdb"\n\n[embeddings]\nenabled = false\n',
        encoding="utf-8",
    )
    source = tmp_path / "src"
    source.mkdir()
    (source / "target.py").write_text(
        'def value() -> int:\n    """Return a fixed value."""\n    return 1\n',
        encoding="utf-8",
    )
    (source / "caller.py").write_text(
        'from target import value\n\ndef run() -> int:\n    """Call the target."""\n    return value()\n',
        encoding="utf-8",
    )

    index_repo(tmp_path)
    model = build_architecture_model_from_index(tmp_path)

    assert ("caller", "target", "import") in {
        (edge.source, edge.destination, edge.kind) for edge in model.dependencies
    }
