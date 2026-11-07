"""Contract tests for the first-party TypeScript analyzer package."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_typescript import TypeScriptAnalyzer, build_analyzer


def test_tsx_text_ampersands_preserve_expression_calls(tmp_path: Path) -> None:
    """Recover literal JSX ampersands without changing boolean expressions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        JSX text, boolean call sites and original source remain faithful.
    """
    source = tmp_path / "text.tsx"
    text = (
        "export const Render = (props: Props) =>\n"
        "  <div>{props.a && props.b()} A & B {render()}</div>;\n"
    )
    source.write_text(text, encoding="utf-8")
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    assert [(call.kind, call.target) for call in result.functions[0].calls] == [
        ("attribute", "b"),
        ("name", "render"),
    ]
    assert source.read_text(encoding="utf-8") == text


def test_optional_in_properties_preserve_interface_signature(tmp_path: Path) -> None:
    """Keep reserved-prefix property names after union annotations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Both optional property names remain present in the original signature.
    """
    source = tmp_path / "properties.ts"
    source.write_text(
        "export interface SVG {\n"
        "  color?: string | undefined\n"
        "  in2?: Numberish | undefined\n"
        "  in?: string | undefined\n"
        "}\n",
        encoding="utf-8",
    )
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    assert result.declarations[0].name == "SVG"
    assert "in2?: Numberish" in result.declarations[0].signature
    assert "in?: string" in result.declarations[0].signature


def test_abstract_override_readonly_preserves_methods(tmp_path: Path) -> None:
    """Recover supported property modifiers without changing method artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The class and its method call remain available for indexing.
    """
    source = tmp_path / "modifiers.ts"
    source.write_text(
        "export abstract class Cache<T> extends Parent<T> {\n"
        "  abstract override readonly rows: Rows<T>;\n"
        "  run() { return helper(); }\n"
        "}\n",
        encoding="utf-8",
    )
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    assert result.classes[0].name == "Cache"
    assert [method.name for method in result.classes[0].methods] == ["run"]
    assert result.classes[0].methods[0].calls[0].target == "helper"
    source.write_text(
        "abstract class Reserved extends Parent {\n"
        "  abstract override readonly: Rows;\n"
        "}\n",
        encoding="utf-8",
    )
    reserved = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert reserved.index_symbols
    assert reserved.classes[0].name == "Reserved"


def test_generic_import_query_is_not_a_runtime_import_call(tmp_path: Path) -> None:
    """Separate type-only import queries from runtime dynamic imports.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Only the generic callee and actual runtime import are call sites.
    """
    source = tmp_path / "query.ts"
    source.write_text(
        "export async function Build() {\n"
        '  const value = load<typeof import("types")>();\n'
        '  const runtime = typeof import("runtime");\n'
        "  return value;\n"
        "}\n",
        encoding="utf-8",
    )
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    calls = result.functions[0].calls
    assert [call.target for call in calls] == ["load", "import"]
    assert [(call.lineno, call.col_offset) for call in calls] == [(2, 16), (3, 25)]
    assert calls[1].kind == "unresolved"


def test_context_repairs_keep_unrelated_invalid_syntax(tmp_path: Path) -> None:
    """Retain partial coverage when a candidate still contains invalid syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        JSX, property, modifier and import-query damage is never hidden.
    """
    for index, text in enumerate(
        (
            "const Render = () => <div>A & B;\n",
            "interface SVG { a: string | undefined in2?: number | undefined }\n",
            "abstract class Cache { abstract override readonly rows: ; }\n",
            'const value = load<typeof import("types")>(,);\n',
            "interface Script { ast: import(moduleName).Statement[]; }\n",
        )
    ):
        source = tmp_path / f"broken-context-{index}.tsx"
        source.write_text(text, encoding="utf-8")
        result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
        assert not result.index_symbols
        assert result.status is not None
        assert result.status.diagnostics


def test_qualified_import_arrays_preserve_source_types(tmp_path: Path) -> None:
    """Recover qualified import array types without runtime call artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Original type signatures and actual body calls survive projection.
    """
    source = tmp_path / "qualified.ts"
    text = (
        'export interface Script { ast?: import("módules").Statement[]; }\n'
        'export function Read(value: import("módules").Statement[]) {\n'
        "  return work(value);\n"
        "}\n"
    )
    source.write_text(text, encoding="utf-8")
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    assert 'import("módules").Statement[]' in result.declarations[0].signature
    assert 'import("módules").Statement[]' in result.functions[0].signature
    assert [call.target for call in result.functions[0].calls] == ["work"]
    assert source.read_text(encoding="utf-8") == text


def test_parenthesized_decorators_preserve_expression_calls(tmp_path: Path) -> None:
    """Recover decorator IIFEs without adding synthetic call targets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Original decorator, nested method and ordinary underscore calls remain.
    """
    source = tmp_path / "decorators.ts"
    text = (
        "export function Build() {\n"
        "  class C {\n"
        "    @(((): MethodDecorator => (target, key, descriptor) => mark())())\n"
        "    run() { return work(); }\n"
        "  }\n"
        "  _();\n"
        "  return C;\n"
        "}\n"
        "export class Direct {\n"
        "  @(((): MethodDecorator => (target, key, descriptor) => mark())())\n"
        "  run() { return work(); }\n"
        "}\n"
    )
    source.write_text(text, encoding="utf-8")
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    calls = result.functions[0].calls
    assert [(call.kind, call.target) for call in calls] == [
        (
            "unresolved",
            "((): MethodDecorator => (target, key, descriptor) => mark())",
        ),
        ("name", "mark"),
        ("name", "work"),
        ("name", "_"),
    ]
    assert (calls[0].lineno, calls[0].col_offset) == (3, 6)
    assert calls[1].col_offset == text.splitlines()[2].encode().index(b"mark()")
    assert result.classes[0].name == "Direct"
    assert [call.target for call in result.classes[0].methods[0].calls] == ["work"]
    assert source.read_text(encoding="utf-8") == text


def test_decorator_repairs_retain_invalid_expressions(tmp_path: Path) -> None:
    """Reject malformed or nonempty-hole decorator IIFEs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Decorator compatibility never removes genuine expression errors.
    """
    for index, decorator in enumerate(
        (
            "@(((): MethodDecorator => mark())()",
            "@(((): => mark())())",
            "@(((): MethodDecorator => mark())(,))",
        )
    ):
        source = tmp_path / f"broken-decorator-{index}.ts"
        source.write_text(
            f"class C {{ {decorator} run() {{ return work(); }} }}\n",
            encoding="utf-8",
        )
        result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
        assert not result.index_symbols
        assert result.status is not None
        assert result.status.diagnostics


def test_awaited_generic_calls_preserve_actual_callee(tmp_path: Path) -> None:
    """Resolve a generic call whose await expression was grouped as callee.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Query receivers and byte positions match the actual call, while a
        parenthesized awaited function remains an unresolved expression.
    """
    source = tmp_path / "awaited.ts"
    text = (
        "export async function Build() {\n"
        '  const value = await client.query<{ value: string }>({ key: "x" });\n'
        "  return (await factory)();\n"
        "}\n"
    )
    source.write_text(text, encoding="utf-8")
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    calls = result.functions[0].calls
    assert [(call.kind, call.target, call.base) for call in calls] == [
        ("attribute", "query", "client"),
        ("unresolved", "(await factory)", ""),
    ]
    assert calls[0].lineno == 2
    assert calls[0].col_offset == text.splitlines()[1].encode().index(b"client.query")


def test_generic_tagged_templates_preserve_artifacts(tmp_path: Path) -> None:
    """Index generic tagged templates without inventing a non-null assertion.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Declarations, call targets, original signatures and positions survive.
    """
    text = (
        "interface Props { name: string; }\n"
        "export const Styled = styled.div<{ name: string }>`name ${renderName()}`;\n"
        "export function Build() {\n"
        '  const label = "é"; return tag<Props>`hello ${helper(label)}`;\n'
        "}\n"
        "export const BuildObject = (value = unused()) =>\n"
        "  styled.div<{ name: string }>`hello ${helper(value)}`;\n"
        "export const BuildSimple = () => tag<Props>`hello`;\n"
    )
    for suffix in (".ts", ".tsx"):
        source = tmp_path / f"templates{suffix}"
        source.write_text(text, encoding="utf-8")
        result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
        assert result.index_symbols
        assert result.status is None
        assert [item.name for item in result.declarations] == ["Props", "Styled"]
        assert result.declarations[1].signature == (
            "Styled = styled.div<{ name: string }>`name ${renderName()}`"
        )
        function = result.functions[0]
        assert function.name == "Build"
        assert [(call.kind, call.target) for call in function.calls] == [
            ("name", "tag"),
            ("name", "helper"),
        ]
        assert function.calls[0].lineno == 4
        assert function.calls[0].col_offset == text.splitlines()[3].encode().index(
            b"tag<Props>"
        )
        object_function = result.functions[1]
        assert object_function.name == "BuildObject"
        assert [
            (call.kind, call.target, call.base) for call in object_function.calls
        ] == [
            ("attribute", "div", "styled"),
            ("name", "helper", ""),
        ]
        assert object_function.calls[0].lineno == 7
        assert object_function.calls[0].col_offset == 2
        assert object_function.end_lineno == 7
        assert object_function.returns_value == 1
        simple_function = result.functions[2]
        assert simple_function.name == "BuildSimple"
        assert [call.target for call in simple_function.calls] == ["tag"]
        assert source.read_text(encoding="utf-8") == text


def test_generic_tagged_templates_keep_other_syntax_errors(tmp_path: Path) -> None:
    """Retain diagnostics for malformed types, templates and unrelated syntax.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Only the exact tagged-template grammar false positive can be resolved.
    """
    for index, text in enumerate(
        (
            "const good = tag<Props>`ok`; const broken = ;\n",
            "const broken = tag<{ value: }>`bad`;\n",
            "const broken = tag<Props>`unterminated\n",
        )
    ):
        source = tmp_path / f"broken{index}.tsx"
        source.write_text(text, encoding="utf-8")
        result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
        assert not result.index_symbols
        assert result.status is not None
        assert result.status.diagnostics


def test_typescript_comparisons_do_not_become_template_calls(tmp_path: Path) -> None:
    """Keep genuine comparisons distinct from generic tagged templates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Parenthesized comparisons and non-type operands produce no tag calls.
    """
    source = tmp_path / "comparisons.ts"
    source.write_text(
        "function Compare() { return (a < b) > `literal`; }\n"
        "function Add() { return a < b + 1 > `literal`; }\n",
        encoding="utf-8",
    )
    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    assert result.index_symbols
    assert all(not function.calls for function in result.functions)


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

    assert project["project"]["version"] == "2.0.3"
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
    assert [item.name for item in result.imports] == ["./format", "src.format.format"]
    assert result.imports[1].alias == "format"
    assert result.imports[1].kind == "import"
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
        == "typescript:function:ambient.ts:Outer.Inner:nested:overload:2"
    )
    assert [
        (item.name, [method.name for method in item.methods]) for item in result.classes
    ] == [
        ("Base", ["run"]),
    ]
    assert [item.name for item in result.imports] == [
        "./widget",
        "./shared",
        "widget.widget",
    ]
    assert result.imports[2].alias == "default"
    assert result.imports[2].kind == "reexport"


def test_typescript_analyzer_disambiguates_overload_stable_ids(tmp_path: Path) -> None:
    """Assign deterministic IDs to top-level and method overload signatures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts overload signatures, implementations, and attached
        TSDoc provenance all have unique stable ownership identities.
    """
    source = tmp_path / "overloads.ts"
    source.write_text(
        "/** Parse text. */\n"
        "export function parse(value: string): string;\n"
        "/** Parse count. */\n"
        "export function parse(value: number): number;\n"
        "export function parse(value: string | number): string | number { return value; }\n"
        "export class Formatter {\n"
        "  /** Format text. */\n"
        "  format(value: string): string;\n"
        "  /** Format count. */\n"
        "  format(value: number): number;\n"
        "  format(value: string | number): string | number { return value; }\n"
        "}\n",
        encoding="utf-8",
    )

    result = TypeScriptAnalyzer().analyze_file(source, tmp_path)
    callables = result.functions + result.classes[0].methods
    stable_ids = [item.stable_id for item in callables]

    assert len(stable_ids) == len(set(stable_ids)) == 6
    assert [item.stable_id for item in result.functions] == [
        "typescript:function:overloads.ts:parse:overload:2",
        "typescript:function:overloads.ts:parse:overload:4",
        "typescript:function:overloads.ts:parse",
    ]
    assert [item.stable_id for item in result.classes[0].methods] == [
        "typescript:method:overloads.ts:Formatter:format:overload:8",
        "typescript:method:overloads.ts:Formatter:format:overload:10",
        "typescript:method:overloads.ts:Formatter:format",
    ]
    assert {item.owner_stable_id for item in result.documentation} == {
        "typescript:function:overloads.ts:parse:overload:2",
        "typescript:function:overloads.ts:parse:overload:4",
        "typescript:method:overloads.ts:Formatter:format:overload:8",
        "typescript:method:overloads.ts:Formatter:format:overload:10",
    }


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


def test_typescript_accessor_and_static_member_identities(tmp_path: Path) -> None:
    """Keep accessors, static members, overloads, and their docs distinct.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Identities, attached TSDoc, call sites, and ordinary names are asserted.
    """
    from codira.indexer import _duplicate_analysis_stable_ids

    source = tmp_path / "members.ts"
    source.write_text(
        "namespace Tools { export class Box {\n"
        "/** Read value. */\nget value() { return read(); }\n"
        "/** Write value. */\nset value(x: number) { write(x); }\n"
        "/** Read static. */\nstatic get value() { return readStatic(); }\n"
        "/** Write static. */\nstatic set value(x: number) { writeStatic(x); }\n"
        "/** Run instance. */\nrun() { instanceRun(); }\n"
        "/** Run static. */\nstatic run() { staticRun(); }\n"
        "static parse(x: string): string;\n"
        "parse(x: number): number;\n"
        "static parse(x: string) { return x; }\n"
        "parse(x: number) { return x; }\n"
        "get() {} set() {} static() {}\n"
        "}}\n",
        encoding="utf-8",
    )
    analyzer = TypeScriptAnalyzer()
    result = analyzer.analyze_file(source, tmp_path)
    assert result.index_symbols
    assert not _duplicate_analysis_stable_ids(result)
    methods = result.classes[0].methods
    prefix = "typescript:method:members.ts:Tools:Box:"
    assert [item.stable_id.removeprefix(prefix) for item in methods] == [
        "value:get",
        "value:set",
        "value:static:get",
        "value:static:set",
        "run",
        "run:static",
        "parse:static:overload:14",
        "parse:overload:15",
        "parse:static",
        "parse",
        "get",
        "set",
        "static",
    ]
    assert [item.calls[0].target for item in methods[:6]] == [
        "read",
        "write",
        "readStatic",
        "writeStatic",
        "instanceRun",
        "staticRun",
    ]
    assert [item.docstring for item in methods[:6]] == [
        "Read value.",
        "Write value.",
        "Read static.",
        "Write static.",
        "Run instance.",
        "Run static.",
    ]
    assert {item.owner_stable_id for item in result.documentation} == {
        item.stable_id for item in methods[:6]
    }
    assert result == analyzer.analyze_file(source, tmp_path)
