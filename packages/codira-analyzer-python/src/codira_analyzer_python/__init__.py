"""Python language analyzer for codira.

Responsibilities
----------------
- Declare analyzer metadata such as name, version, and discovery globs.
- Parse Python files via `codira.parser_ast` and normalize them into
  `AnalysisResult` objects.
- Expose the package entry-point factory used by the plugin registry.

Design principles
-----------------
The analyzer isolates Python-specific parsing from storage concerns while
staying deterministic.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the
first-party Python analyzer distribution for Phase 2 packaging.
"""

from __future__ import annotations

import builtins
import ast
import sys
import tokenize
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer
    from codira.models import (
        AnalysisResult,
        ClassArtifact,
        DeclarationArtifact,
        EnumMemberArtifact,
        FunctionArtifact,
        OverloadArtifact,
    )

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.plugin_config import (
    AnalyzerPathFilters,
    analyzer_json_schema,
    analyzer_path_allowed,
    analyzer_path_filters_from_config,
    boolean_property,
    plugin_configuration_fingerprint,
)
from codira.models import DocumentationArtifact
from codira.normalization import analysis_result_from_parsed
from codira.parser_ast import parse_source

__all__ = ["PythonAnalyzer", "build_analyzer"]

ArtifactT = TypeVar("ArtifactT")
_PYTHON_BUILTINS = frozenset(dir(builtins))
_PYTHON_STDLIB_MODULES = frozenset(sys.stdlib_module_names)


def _read_python_source(path: Path) -> str:
    """
    Read one Python source file with PEP 263 encoding support.

    Parameters
    ----------
    path : pathlib.Path
        Python source file to decode.

    Returns
    -------
    str
        Decoded source text honoring the file's declared encoding.
    """
    with tokenize.open(path) as handle:
        return handle.read()


def _rewrite_colliding_stable_ids(
    artifacts: tuple[ArtifactT, ...],
    *,
    stable_id_getter: Callable[[ArtifactT], str],
    stable_id_setter: Callable[[ArtifactT, str], ArtifactT],
) -> tuple[ArtifactT, ...]:
    """
    Rewrite colliding stable IDs with deterministic ordinal suffixes.

    Parameters
    ----------
    artifacts : tuple[ArtifactT, ...]
        Artifacts to inspect in deterministic source order.
    stable_id_getter : collections.abc.Callable[[ArtifactT], str]
        Accessor returning the current stable ID for one artifact.
    stable_id_setter : collections.abc.Callable[[ArtifactT, str], ArtifactT]
        Rebuilder returning one artifact with a rewritten stable ID.

    Returns
    -------
    tuple[ArtifactT, ...]
        Artifacts with colliding stable IDs rewritten as ``:1``, ``:2``, and
        so on, while unique stable IDs remain unchanged.
    """
    counts = Counter(stable_id_getter(artifact) for artifact in artifacts)
    if all(count == 1 for count in counts.values()):
        return artifacts

    seen: dict[str, int] = {}
    rewritten: list[ArtifactT] = []
    for artifact in artifacts:
        stable_id = stable_id_getter(artifact)
        if counts[stable_id] == 1:
            rewritten.append(artifact)
            continue
        seen[stable_id] = seen.get(stable_id, 0) + 1
        rewritten.append(stable_id_setter(artifact, f"{stable_id}:{seen[stable_id]}"))
    return tuple(rewritten)


def _replace_function_stable_id(
    function: FunctionArtifact,
    stable_id: str,
) -> FunctionArtifact:
    """
    Replace one function or method stable ID and rebind overload parents.

    Parameters
    ----------
    function : codira.models.FunctionArtifact
        Function-like artifact to rewrite.
    stable_id : str
        New stable ID for the function or method.

    Returns
    -------
    codira.models.FunctionArtifact
        Function artifact with the updated stable ID and overload parents.
    """
    overloads = tuple(
        replace(overload, parent_stable_id=stable_id) for overload in function.overloads
    )
    return replace(function, stable_id=stable_id, overloads=overloads)


def _rebase_python_stable_id(stable_id: str, old_module: str, new_module: str) -> str:
    """
    Rebase one Python stable ID from an import module to a path module.

    Parameters
    ----------
    stable_id : str
        Stable ID emitted by Python normalization.
    old_module : str
        Import-style module namespace currently encoded in ``stable_id``.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    str
        Stable ID rebased to ``new_module`` when it belongs to ``old_module``.
    """
    for symbol_type in ("module", "class", "function", "method", "overload"):
        prefix = f"python:{symbol_type}:{old_module}"
        if stable_id == prefix:
            return f"python:{symbol_type}:{new_module}"
        if stable_id.startswith(f"{prefix}:"):
            return f"python:{symbol_type}:{new_module}{stable_id[len(prefix) :]}"

    declaration_prefix = "python:"
    module_segment = f":{old_module}:"
    if stable_id.startswith(declaration_prefix) and module_segment in stable_id:
        return stable_id.replace(module_segment, f":{new_module}:", 1)
    return stable_id


def _rebase_overload_module(
    overload: OverloadArtifact,
    *,
    old_module: str,
    new_module: str,
) -> OverloadArtifact:
    """
    Rebase an overload stable ID and its parent stable ID.

    Parameters
    ----------
    overload : codira.models.OverloadArtifact
        Overload artifact to rewrite.
    old_module : str
        Import-style module namespace currently encoded in stable IDs.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    codira.models.OverloadArtifact
        Overload artifact with module-qualified identities rewritten.
    """
    return replace(
        overload,
        stable_id=_rebase_python_stable_id(overload.stable_id, old_module, new_module),
        parent_stable_id=_rebase_python_stable_id(
            overload.parent_stable_id,
            old_module,
            new_module,
        ),
    )


def _rebase_function_module(
    function: FunctionArtifact,
    *,
    old_module: str,
    new_module: str,
) -> FunctionArtifact:
    """
    Rebase a function or method and its overload identities.

    Parameters
    ----------
    function : codira.models.FunctionArtifact
        Function-like artifact to rewrite.
    old_module : str
        Import-style module namespace currently encoded in stable IDs.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    codira.models.FunctionArtifact
        Function artifact with module-qualified identities rewritten.
    """
    return replace(
        function,
        stable_id=_rebase_python_stable_id(function.stable_id, old_module, new_module),
        overloads=tuple(
            _rebase_overload_module(
                overload,
                old_module=old_module,
                new_module=new_module,
            )
            for overload in function.overloads
        ),
    )


def _rebase_class_module(
    class_artifact: ClassArtifact,
    *,
    old_module: str,
    new_module: str,
) -> ClassArtifact:
    """
    Rebase a class and its method identities.

    Parameters
    ----------
    class_artifact : codira.models.ClassArtifact
        Class artifact to rewrite.
    old_module : str
        Import-style module namespace currently encoded in stable IDs.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    codira.models.ClassArtifact
        Class artifact with module-qualified identities rewritten.
    """
    return replace(
        class_artifact,
        stable_id=_rebase_python_stable_id(
            class_artifact.stable_id,
            old_module,
            new_module,
        ),
        methods=tuple(
            _rebase_function_module(
                method,
                old_module=old_module,
                new_module=new_module,
            )
            for method in class_artifact.methods
        ),
    )


def _rebase_enum_member_module(
    enum_member: EnumMemberArtifact,
    *,
    old_module: str,
    new_module: str,
) -> EnumMemberArtifact:
    """
    Rebase an enum member identity.

    Parameters
    ----------
    enum_member : codira.models.EnumMemberArtifact
        Enum member artifact to rewrite.
    old_module : str
        Import-style module namespace currently encoded in stable IDs.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    codira.models.EnumMemberArtifact
        Enum member artifact with module-qualified identities rewritten.
    """
    return replace(
        enum_member,
        stable_id=_rebase_python_stable_id(
            enum_member.stable_id,
            old_module,
            new_module,
        ),
        parent_stable_id=_rebase_python_stable_id(
            enum_member.parent_stable_id,
            old_module,
            new_module,
        ),
    )


def _rebase_declaration_module(
    declaration: DeclarationArtifact,
    *,
    old_module: str,
    new_module: str,
) -> DeclarationArtifact:
    """
    Rebase a declaration and attached enum-member identities.

    Parameters
    ----------
    declaration : codira.models.DeclarationArtifact
        Declaration artifact to rewrite.
    old_module : str
        Import-style module namespace currently encoded in stable IDs.
    new_module : str
        Path-qualified module namespace to encode.

    Returns
    -------
    codira.models.DeclarationArtifact
        Declaration artifact with module-qualified identities rewritten.
    """
    return replace(
        declaration,
        stable_id=_rebase_python_stable_id(
            declaration.stable_id,
            old_module,
            new_module,
        ),
        enum_members=tuple(
            _rebase_enum_member_module(
                enum_member,
                old_module=old_module,
                new_module=new_module,
            )
            for enum_member in declaration.enum_members
        ),
    )


def _shadowed_module_namespace(path: Path, root: Path, module_name: str) -> str | None:
    """
    Return a path-qualified namespace for import-shadowed module files.

    Parameters
    ----------
    path : pathlib.Path
        Python source file being analyzed.
    root : pathlib.Path
        Repository root used for relative path identity.
    module_name : str
        Import-style module namespace emitted by normalization.

    Returns
    -------
    str | None
        Path-qualified module namespace when ``path`` is shadowed by a sibling
        package ``__init__.py``; otherwise ``None``.
    """
    if path.name == "__init__.py" or path.suffix != ".py":
        return None

    package_init = path.with_suffix("") / "__init__.py"
    if not package_init.is_file():
        return None

    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:
        relative_path = path.as_posix()
    return f"{module_name}:path:{relative_path}"


def _disambiguate_shadowed_module_file(
    analysis: AnalysisResult,
    *,
    path: Path,
    root: Path,
) -> AnalysisResult:
    """
    Rebase valid Python module files shadowed by sibling packages.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized Python analyzer output.
    path : pathlib.Path
        Python source file that produced ``analysis``.
    root : pathlib.Path
        Repository root used for relative path identity.

    Returns
    -------
    codira.models.AnalysisResult
        Analysis result with path-qualified stable IDs when ``path`` is an
        import-shadowed module file.
    """
    old_module = analysis.module.name
    new_module = _shadowed_module_namespace(path, root, old_module)
    if new_module is None:
        return analysis

    module = replace(
        analysis.module,
        stable_id=_rebase_python_stable_id(
            analysis.module.stable_id,
            old_module,
            new_module,
        ),
    )
    return replace(
        analysis,
        module=module,
        classes=tuple(
            _rebase_class_module(
                class_artifact,
                old_module=old_module,
                new_module=new_module,
            )
            for class_artifact in analysis.classes
        ),
        functions=tuple(
            _rebase_function_module(
                function,
                old_module=old_module,
                new_module=new_module,
            )
            for function in analysis.functions
        ),
        declarations=tuple(
            _rebase_declaration_module(
                declaration,
                old_module=old_module,
                new_module=new_module,
            )
            for declaration in analysis.declarations
        ),
    )


def _disambiguate_overload_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Rewrite colliding overload stable IDs while preserving parent order.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Canonical callables whose overloads should be inspected.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Functions with overload stable IDs rewritten only when collisions are
        present.
    """
    overload_counts = tuple(len(function.overloads) for function in functions)
    overloads = tuple(
        overload for function in functions for overload in function.overloads
    )
    rewritten_overloads = _rewrite_colliding_stable_ids(
        overloads,
        stable_id_getter=lambda overload: overload.stable_id,
        stable_id_setter=lambda overload, stable_id: replace(
            overload,
            stable_id=stable_id,
        ),
    )
    if rewritten_overloads == overloads:
        return functions

    rewritten_functions: list[FunctionArtifact] = []
    cursor = 0
    for function, overload_count in zip(functions, overload_counts, strict=True):
        rewritten_functions.append(
            replace(
                function,
                overloads=rewritten_overloads[cursor : cursor + overload_count],
            )
        )
        cursor += overload_count
    return tuple(rewritten_functions)


def _disambiguate_function_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Rewrite colliding function or method stable IDs deterministically.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Function-like artifacts in deterministic source order.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Functions with colliding stable IDs rewritten, including overload
        parent bindings.
    """
    rewritten_functions = _rewrite_colliding_stable_ids(
        functions,
        stable_id_getter=lambda function: function.stable_id,
        stable_id_setter=_replace_function_stable_id,
    )
    return _disambiguate_overload_stable_ids(rewritten_functions)


def _disambiguate_method_stable_ids(
    classes: tuple[ClassArtifact, ...],
) -> tuple[ClassArtifact, ...]:
    """
    Rewrite colliding method stable IDs across all classes in one file.

    Parameters
    ----------
    classes : tuple[codira.models.ClassArtifact, ...]
        Class artifacts in deterministic source order.

    Returns
    -------
    tuple[codira.models.ClassArtifact, ...]
        Classes with rewritten method stable IDs when collisions are present.
    """
    method_counts = tuple(len(class_artifact.methods) for class_artifact in classes)
    methods = tuple(
        method for class_artifact in classes for method in class_artifact.methods
    )
    rewritten_methods = _disambiguate_function_stable_ids(methods)
    if rewritten_methods == methods:
        return classes

    rewritten_classes: list[ClassArtifact] = []
    cursor = 0
    for class_artifact, method_count in zip(classes, method_counts, strict=True):
        rewritten_classes.append(
            replace(
                class_artifact,
                methods=rewritten_methods[cursor : cursor + method_count],
            )
        )
        cursor += method_count
    return tuple(rewritten_classes)


def _disambiguate_analysis_stable_ids(analysis: AnalysisResult) -> AnalysisResult:
    """
    Enforce analyzer-owned stable ID uniqueness within one Python result.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized Python analyzer output.

    Returns
    -------
    codira.models.AnalysisResult
        Analysis result with deterministic suffixes added only for colliding
        classes, functions, methods, declarations, and overloads.
    """
    classes = _rewrite_colliding_stable_ids(
        analysis.classes,
        stable_id_getter=lambda class_artifact: class_artifact.stable_id,
        stable_id_setter=lambda class_artifact, stable_id: replace(
            class_artifact,
            stable_id=stable_id,
        ),
    )
    classes = _disambiguate_method_stable_ids(classes)
    functions = _disambiguate_function_stable_ids(analysis.functions)
    declarations = _rewrite_colliding_stable_ids(
        analysis.declarations,
        stable_id_getter=lambda declaration: declaration.stable_id,
        stable_id_setter=lambda declaration, stable_id: replace(
            declaration,
            stable_id=stable_id,
        ),
    )
    if (
        classes == analysis.classes
        and functions == analysis.functions
        and declarations == analysis.declarations
    ):
        return analysis
    return replace(
        analysis,
        classes=classes,
        functions=functions,
        declarations=declarations,
    )


def _import_aliases(analysis: AnalysisResult) -> dict[str, str]:
    """
    Build Python import aliases visible to relation target classification.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer result.

    Returns
    -------
    dict[str, str]
        Mapping from local binding names to imported dotted targets.
    """
    aliases: dict[str, str] = {}
    for imported in analysis.imports:
        if imported.kind != "import":
            continue
        local_name = imported.alias
        if local_name is None:
            local_name = imported.name.split(".")[-1]
        aliases[local_name] = imported.name
    return aliases


def _stdlib_target_name(base: str, target: str, aliases: dict[str, str]) -> str | None:
    """
    Resolve a Python attribute target to a stdlib display name when possible.

    Parameters
    ----------
    base : str
        Static receiver path from the call or reference record.
    target : str
        Target attribute token.
    aliases : dict[str, str]
        Local import aliases mapped to imported dotted targets.

    Returns
    -------
    str | None
        Fully qualified stdlib target name, or ``None`` when unknown.
    """
    if not base:
        return None
    base_head, _, base_tail = base.partition(".")
    imported = aliases.get(base_head)
    if imported is None:
        return None
    imported_root = imported.split(".", 1)[0]
    if imported_root not in _PYTHON_STDLIB_MODULES:
        return None
    rebased = imported if not base_tail else f"{imported}.{base_tail}"
    return f"{rebased}.{target}" if target else rebased


def _classify_python_external_target(
    *,
    kind: str,
    base: str,
    target: str,
    aliases: dict[str, str],
) -> tuple[str | None, str | None]:
    """
    Classify one Python relation target using analyzer-local language rules.

    Parameters
    ----------
    kind : str
        Normalized relation target kind.
    base : str
        Static receiver path for attribute targets.
    target : str
        Target token.
    aliases : dict[str, str]
        Local import aliases mapped to imported dotted targets.

    Returns
    -------
    tuple[str | None, str | None]
        External target classifier and display name.
    """
    if kind == "name" and target in _PYTHON_BUILTINS:
        return ("Python:<builtin>", target)
    if kind == "name":
        imported = aliases.get(target)
        if imported is not None and imported.split(".", 1)[0] in _PYTHON_STDLIB_MODULES:
            return ("Python:<stdlib>", imported)
    if kind == "attribute":
        stdlib_name = _stdlib_target_name(base, target, aliases)
        if stdlib_name is not None:
            return ("Python:<stdlib>", stdlib_name)
        if base:
            return ("Python:<object-method>", f"{base}.{target}")
    if target:
        return ("Python:<external>", target)
    return (None, None)


def _classify_function_python_targets(
    function: FunctionArtifact,
    aliases: dict[str, str],
) -> FunctionArtifact:
    """
    Attach Python external target labels to one function artifact.

    Parameters
    ----------
    function : codira.models.FunctionArtifact
        Function or method artifact to classify.
    aliases : dict[str, str]
        Local import aliases mapped to imported dotted targets.

    Returns
    -------
    codira.models.FunctionArtifact
        Function artifact with classified call and reference records.
    """
    calls = tuple(
        replace(
            call,
            external_target_kind=external_target_kind,
            external_target_name=external_target_name,
        )
        for call in function.calls
        for external_target_kind, external_target_name in (
            _classify_python_external_target(
                kind=call.kind,
                base=call.base,
                target=call.target,
                aliases=aliases,
            ),
        )
    )
    refs = tuple(
        replace(
            ref,
            external_target_kind=external_target_kind,
            external_target_name=external_target_name,
        )
        for ref in function.callable_refs
        for external_target_kind, external_target_name in (
            _classify_python_external_target(
                kind=ref.kind,
                base=ref.base,
                target=ref.target,
                aliases=aliases,
            ),
        )
    )
    return replace(function, calls=calls, callable_refs=refs)


def _classify_python_relation_targets(analysis: AnalysisResult) -> AnalysisResult:
    """
    Attach Python-owned external target labels to call and reference records.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized Python analyzer result.

    Returns
    -------
    codira.models.AnalysisResult
        Analysis result with analyzer-provided unresolved target labels.
    """
    aliases = _import_aliases(analysis)
    functions = tuple(
        _classify_function_python_targets(function, aliases)
        for function in analysis.functions
    )
    classes = tuple(
        replace(
            class_artifact,
            methods=tuple(
                _classify_function_python_targets(method, aliases)
                for method in class_artifact.methods
            ),
        )
        for class_artifact in analysis.classes
    )
    return replace(analysis, functions=functions, classes=classes)


def _module_docstring_location(source: str) -> tuple[int, int | None] | None:
    """
    Return source coordinates for a module docstring.

    Parameters
    ----------
    source : str
        Python source text to inspect.

    Returns
    -------
    tuple[int, int | None] | None
        Start and inclusive end line for the module docstring, or ``None``
        when no syntactic module docstring exists.
    """
    tree = ast.parse(source)
    if not tree.body:
        return None
    first_node = tree.body[0]
    if not isinstance(first_node, ast.Expr):
        return None
    value = first_node.value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    return first_node.lineno, first_node.end_lineno


def _module_documentation_artifacts(
    analysis: AnalysisResult,
    *,
    path: Path,
    source: str,
) -> tuple[DocumentationArtifact, ...]:
    """
    Build Python module-level documentation artifacts for V1 retrieval.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized Python analyzer result.
    path : pathlib.Path
        Source path that produced ``analysis``.
    source : str
        Python source text used to locate the docstring.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        One module-docstring artifact when present, otherwise an empty tuple.
    """
    docstring = analysis.module.docstring
    if not docstring:
        return ()
    location = _module_docstring_location(source)
    if location is None:
        return ()
    lineno, end_lineno = location
    return (
        DocumentationArtifact(
            stable_id=f"doc:module:{analysis.module.stable_id}:module_docstring",
            kind="module",
            source_format="module_docstring",
            source_path=path,
            lineno=lineno,
            end_lineno=end_lineno,
            title=analysis.module.name,
            heading_path=(),
            text=docstring,
            owner_stable_id=analysis.module.stable_id,
        ),
    )


class PythonAnalyzer:
    """
    Concrete Python analyzer for repository indexing.

    Parameters
    ----------
    None

    Notes
    -----
    This analyzer owns Python-specific parsing and normalization only. It does
    not own backend persistence or indexing policy.
    """

    name = "python"
    version = "6"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def __init__(self) -> None:
        self._path_filters = AnalyzerPathFilters()
        self._emit_module_documentation = True
        self._emit_imports = True
        self._emit_constants = True
        self._emit_type_aliases = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the Python analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for Python analyzer options.
        """

        return analyzer_json_schema(
            {
                "emit_module_documentation": boolean_property(True),
                "emit_imports": boolean_property(True),
                "emit_constants": boolean_property(True),
                "emit_type_aliases": boolean_property(True),
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply Python analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.
        """

        self._path_filters = analyzer_path_filters_from_config(config)
        self._emit_module_documentation = bool(
            config.get("emit_module_documentation", True)
        )
        self._emit_imports = bool(config.get("emit_imports", True))
        self._emit_constants = bool(config.get("emit_constants", True))
        self._emit_type_aliases = bool(config.get("emit_type_aliases", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return Python analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from Python artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_python:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "documentation",
            ),
            does_not_support=("variable", "namespace"),
            mappings={
                "module": "module",
                "class": "type",
                "type_alias": "type",
                "constant": "constant",
                "function": "callable",
                "method": "callable",
                "import": "import",
                "module_docstring": "documentation",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file is a Python source file.
        """
        return path.suffix == ".py"

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported Python path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the path is allowed by include/exclude filters.
        """

        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one Python source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Python source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        source = _read_python_source(path)
        analysis = analysis_result_from_parsed(path, parse_source(path, root, source))
        analysis = _disambiguate_shadowed_module_file(analysis, path=path, root=root)
        analysis = _classify_python_relation_targets(analysis)
        analysis = _disambiguate_analysis_stable_ids(analysis)
        declarations = tuple(
            declaration
            for declaration in analysis.declarations
            if (self._emit_constants or declaration.kind != "constant")
            and (self._emit_type_aliases or declaration.kind != "type_alias")
        )
        documentation = (
            _module_documentation_artifacts(
                analysis,
                path=path,
                source=source,
            )
            if self._emit_module_documentation
            else ()
        )
        return replace(
            analysis,
            declarations=declarations,
            imports=analysis.imports if self._emit_imports else (),
            documentation=documentation,
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party Python analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh Python analyzer instance for registry discovery.
    """
    return PythonAnalyzer()
