"""Contract tests for the first-party TypeScript analyzer package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_typescript import TypeScriptAnalyzer, build_analyzer


def test_typescript_package_declares_expected_entry_point() -> None:
    """Keep package metadata aligned with autonomous plugin discovery.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Version, grammar, and entry point are asserted.
    """
    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert project["project"]["version"] == "2.0.0"
    assert "tree-sitter-typescript>=0.23.2" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "typescript": "codira_analyzer_typescript:build_analyzer"
    }


def test_typescript_analyzer_extracts_issue_37_constructs(tmp_path: Path) -> None:
    """Extract TypeScript declarations without compiler execution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Interfaces, aliases, enums, namespaces, classes, and calls persist.
    """
    source = tmp_path / "src" / "widget.tsx"
    source.parent.mkdir()
    source.write_text(
        "import { format } from './format';\n"
        "export interface Box<T> { value: T; }\n"
        "export type Result<T> = { value: T };\n"
        "export enum Mode { Fast = 'fast', Slow }\n"
        "export namespace Tools { export function run<T>(value: T): T { return format(value); } }\n"
        "export class Widget<T> { render(value: T): T { return format(value); } }\n"
        "export const render = <T,>(value: T) => <div>{format(value)}</div>;\n",
        encoding="utf-8",
    )

    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)

    assert result.module.stable_id == "typescript:module:src/widget.tsx"
    assert [item.name for item in result.imports] == ["./format"]
    assert [(item.kind, item.name) for item in result.declarations] == [
        ("struct", "Box"),
        ("type_alias", "Result"),
        ("enum", "Mode"),
        ("namespace", "Tools"),
    ]
    assert [item.name for item in result.functions] == ["run", "render"]
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [("Widget", ["render"])]
    assert [item.name for item in result.declarations[2].enum_members] == [
        "Fast",
        "Slow",
    ]


def test_typescript_analyzer_selects_tsx_only_for_tsx(tmp_path: Path) -> None:
    """Keep TSX syntax and suffix selection deterministic.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Every claimed extension is stable and TypeScript excludes JavaScript.
    """
    analyzer = TypeScriptAnalyzer()
    for suffix in (".ts", ".tsx", ".mts", ".cts"):
        source = tmp_path / f"entry{suffix}"
        source.write_text("export const value = 1;\n", encoding="utf-8")
        assert analyzer.analyze_file(source, tmp_path) == analyzer.analyze_file(
            source, tmp_path
        )
        assert analyzer.supports_path(source) is True
    assert analyzer.supports_path(tmp_path / "entry.js") is False


def test_typescript_analyzer_emits_adjacent_tsdoc_provenance(tmp_path: Path) -> None:
    """Attach only an immediately preceding explicit TSDoc block.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        TSDoc text, owner linkage, and provenance format are asserted.
    """
    source = tmp_path / "entry.ts"
    source.write_text(
        "/** Build a value.\n * @param value Input value.\n */\n"
        "export function build(value: string): string { return value; }\n",
        encoding="utf-8",
    )

    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)

    assert result.functions[0].docstring == "Build a value.\n@param value Input value."
    assert result.documentation[0].source_format == "tsdoc"
    assert result.documentation[0].owner_stable_id == result.functions[0].stable_id


def test_typescript_analyzer_handles_ambient_abstract_and_reexports(
    tmp_path: Path,
) -> None:
    """Extract declaration-only TypeScript forms without compiler emulation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Ambient namespaces, abstract members, and re-export sources are asserted.
    """
    source = tmp_path / "ambient.ts"
    source.write_text(
        "declare namespace Api { export function create(name: string): void; }\n"
        "declare namespace Outer { namespace Inner { export function nested(): void; } }\n"
        "export abstract class Base { abstract run(value: string): string; }\n"
        "export { widget as default } from './widget';\n"
        "export * from './shared';\n",
        encoding="utf-8",
    )

    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)

    assert [(item.kind, item.name) for item in result.declarations] == [
        ("namespace", "Api"),
        ("namespace", "Outer"),
        ("namespace", "Inner"),
    ]
    assert [item.name for item in result.functions] == ["create", "nested"]
    assert (
        result.functions[1].stable_id
        == "typescript:function:ambient.ts:Outer.Inner:nested"
    )
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [
        ("Base", ["run"]),
    ]
    assert [item.name for item in result.imports] == ["./widget", "./shared"]


def test_typescript_factory_builds_expected_analyzer() -> None:
    """Keep the factory aligned with the public TypeScript plugin name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Factory output and discovery globs are asserted.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, TypeScriptAnalyzer)
    assert analyzer.discovery_globs == ("*.ts", "*.tsx", "*.mts", "*.cts")
