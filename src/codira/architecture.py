"""Backend-neutral architecture graph models and deterministic aggregation.

The model deliberately receives analyzer-normalized facts and resolved relation
rows instead of querying a particular backend.  Renderers and CLI adapters can
therefore share it without coupling to analyzer-specific extraction paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from codira.contracts import BackendRelationQueryRequest, BackendSymbolInventoryItem
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection

ArchitectureEdgeKind = Literal["import", "call", "reference"]


@dataclass(frozen=True, order=True)
class ArchitectureSymbolEvidence:
    """Retained symbol-level evidence for one aggregate dependency.

    Parameters
    ----------
    module : str
        Module that owns the symbol.
    name : str
        Logical symbol name.
    path : str
        Repository-relative source path.
    lineno : int
        One-based source line.

    Returns
    -------
    None
        Instances are immutable evidence records.
    """

    module: str
    name: str
    path: str
    lineno: int


@dataclass(frozen=True, order=True)
class ArchitectureAnalyzerFact:
    """Analyzer-owned declaration fact retained in module inventory.

    Parameters
    ----------
    kind : str
        Stable analyzer declaration kind.
    name : str
        Analyzer-normalized declaration name.
    signature : str
        Analyzer-provided bounded semantic text.

    Returns
    -------
    None
        Instances carry facts without assigning report-specific meaning.
    """

    kind: str
    name: str
    signature: str


@dataclass(frozen=True, order=True)
class ArchitectureModule:
    """One indexed module or file in an architecture inventory.

    Parameters
    ----------
    name : str
        Stable logical module name.
    path : str
        Repository-relative source path.
    analyzer_name : str
        Analyzer that produced the module.
    facts : tuple[ArchitectureAnalyzerFact, ...], optional
        Analyzer-owned declaration facts associated with this module.

    Returns
    -------
    None
        Instances are immutable module inventory entries.
    """

    name: str
    path: str
    analyzer_name: str
    facts: tuple[ArchitectureAnalyzerFact, ...] = ()


@dataclass(frozen=True, order=True)
class ArchitectureRelation:
    """One resolved relation before module-level aggregation.

    Parameters
    ----------
    source_module : str
        Resolved owner module.
    destination_module : str | None
        Resolved target module, if available.
    kind : ArchitectureEdgeKind
        Relation family emitted by the index.
    evidence : ArchitectureSymbolEvidence
        Retained source-symbol evidence for this relation.

    Returns
    -------
    None
        Unresolved destinations remain ``None`` and do not create graph edges.
    """

    source_module: str
    destination_module: str | None
    kind: ArchitectureEdgeKind
    evidence: ArchitectureSymbolEvidence


@dataclass(frozen=True, order=True)
class ArchitectureDependency:
    """One deterministic aggregate dependency between indexed modules.

    Parameters
    ----------
    source : str
        Source module name.
    destination : str
        Destination module name.
    kind : ArchitectureEdgeKind
        Aggregated relation family.
    evidence : tuple[ArchitectureSymbolEvidence, ...]
        Sorted, deduplicated evidence supporting the aggregate edge.

    Returns
    -------
    None
        Instances are immutable module-level dependency edges.
    """

    source: str
    destination: str
    kind: ArchitectureEdgeKind
    evidence: tuple[ArchitectureSymbolEvidence, ...]


@dataclass(frozen=True, order=True)
class ArchitectureCycle:
    """A strongly connected component that forms an architecture cycle.

    Parameters
    ----------
    members : tuple[str, ...]
        Sorted module names in the strongly connected component.

    Returns
    -------
    None
        Single-member components appear only when a self-edge exists.
    """

    members: tuple[str, ...]


@dataclass(frozen=True, order=True)
class ArchitectureModuleMetrics:
    """Degree statistics for one architecture module.

    Parameters
    ----------
    module : str
        Module name.
    fan_in : int
        Number of distinct incoming aggregate edges.
    fan_out : int
        Number of distinct outgoing aggregate edges.

    Returns
    -------
    None
        Instances contain transparent hotspot input metrics.
    """

    module: str
    fan_in: int
    fan_out: int


@dataclass(frozen=True, order=True)
class ArchitectureModel:
    """Complete analyzer-independent architecture extraction result.

    Parameters
    ----------
    modules : tuple[ArchitectureModule, ...]
        Sorted indexed module inventory.
    dependencies : tuple[ArchitectureDependency, ...]
        Sorted aggregate dependencies with retained evidence.
    cycles : tuple[ArchitectureCycle, ...]
        Sorted strongly connected components representing cycles.
    metrics : tuple[ArchitectureModuleMetrics, ...]
        Sorted per-module degree metrics.

    Returns
    -------
    None
        Instances are deterministic domain-model snapshots for later policies
        and renderers.
    """

    modules: tuple[ArchitectureModule, ...]
    dependencies: tuple[ArchitectureDependency, ...]
    cycles: tuple[ArchitectureCycle, ...]
    metrics: tuple[ArchitectureModuleMetrics, ...]


@dataclass(frozen=True)
class ArchitectureLayer:
    """One ordered repository-relative path-prefix layer.

    Parameters
    ----------
    name : str
        Stable layer identifier referenced by policy rules.
    path_prefix : str
        Repository-relative path prefix owned by this layer.

    Returns
    -------
    None
        Earlier layers take precedence when prefixes overlap.
    """

    name: str
    path_prefix: str


@dataclass(frozen=True)
class ArchitectureForbiddenDependencyRule:
    """One explicit prohibited source-to-destination layer dependency.

    Parameters
    ----------
    rule_id : str
        Stable policy identifier reported with each violation.
    source_layer : str
        Layer that must not depend on the destination layer.
    destination_layer : str
        Prohibited target layer.
    severity : str
        User-configured severity label retained verbatim in diagnostics.

    Returns
    -------
    None
        Instances define one directed policy rule.
    """

    rule_id: str
    source_layer: str
    destination_layer: str
    severity: str


@dataclass(frozen=True)
class ArchitecturePolicy:
    """Strict layer and forbidden-dependency configuration.

    Parameters
    ----------
    layers : tuple[ArchitectureLayer, ...]
        Ordered path-prefix layers.
    forbidden_dependencies : tuple[ArchitectureForbiddenDependencyRule, ...]
        Explicit prohibited directed layer rules.

    Returns
    -------
    None
        Instances are validated before use by policy analysis.
    """

    layers: tuple[ArchitectureLayer, ...]
    forbidden_dependencies: tuple[ArchitectureForbiddenDependencyRule, ...]


@dataclass(frozen=True, order=True)
class ArchitectureLayerAssignment:
    """Layer assignment for one indexed module.

    Parameters
    ----------
    module : str
        Indexed module name.
    layer : str | None
        Matching ordered layer, or ``None`` when unlayered.

    Returns
    -------
    None
        Instances preserve unlayered modules as explicit policy input.
    """

    module: str
    layer: str | None


@dataclass(frozen=True, order=True)
class ArchitectureHotspot:
    """Transparent degree-based architecture hotspot ranking entry.

    Parameters
    ----------
    module : str
        Ranked module name.
    fan_in : int
        Distinct incoming aggregate dependency count.
    fan_out : int
        Distinct outgoing aggregate dependency count.
    score : int
        Ranking score equal to ``fan_in + fan_out``.

    Returns
    -------
    None
        Entries are ordered by descending score, then fan-out, fan-in, and name.
    """

    module: str
    fan_in: int
    fan_out: int
    score: int


@dataclass(frozen=True, order=True)
class ArchitectureViolation:
    """One dependency violating an explicit layer policy rule.

    Parameters
    ----------
    rule_id : str
        Stable matched rule identifier.
    source : str
        Source module name.
    destination : str
        Destination module name.
    edge_kind : ArchitectureEdgeKind
        Dependency relation kind.
    severity : str
        Matched rule severity.
    evidence : tuple[ArchitectureSymbolEvidence, ...]
        Evidence retained from the aggregate dependency.

    Returns
    -------
    None
        Instances are deterministic report diagnostics.
    """

    rule_id: str
    source: str
    destination: str
    edge_kind: ArchitectureEdgeKind
    severity: str
    evidence: tuple[ArchitectureSymbolEvidence, ...]


@dataclass(frozen=True, order=True)
class ArchitecturePolicyAnalysis:
    """Policy-derived architecture metrics, assignments, and diagnostics.

    Parameters
    ----------
    assignments : tuple[ArchitectureLayerAssignment, ...]
        Module-to-layer assignments including unlayered modules.
    hotspots : tuple[ArchitectureHotspot, ...]
        Stable descending degree hotspot ranking.
    violations : tuple[ArchitectureViolation, ...]
        Forbidden dependency diagnostics with retained evidence.

    Returns
    -------
    None
        Instances are renderer-ready policy-analysis snapshots.
    """

    assignments: tuple[ArchitectureLayerAssignment, ...]
    hotspots: tuple[ArchitectureHotspot, ...]
    violations: tuple[ArchitectureViolation, ...]


def _path_matches_prefix(path: str, prefix: str) -> bool:
    """Match one repository-relative path against one layer prefix.

    Parameters
    ----------
    path : str
        Repository-relative module path.
    prefix : str
        Validated repository-relative layer prefix.

    Returns
    -------
    bool
        ``True`` when the prefix owns the exact path or one descendant.
    """
    return path == prefix or path.startswith(f"{prefix}/")


def validate_architecture_policy(policy: ArchitecturePolicy) -> None:
    """Validate strict ordered layer and forbidden-dependency configuration.

    Parameters
    ----------
    policy : ArchitecturePolicy
        Policy configuration to validate.

    Returns
    -------
    None
        A valid policy can be passed to architecture policy analysis.

    Raises
    ------
    ValueError
        If layer names or prefixes, rule IDs, references, or directed rule
        pairs are empty, duplicated, or otherwise ambiguous.
    """
    layer_names: set[str] = set()
    prefixes: set[str] = set()
    for layer in policy.layers:
        if not layer.name.strip():
            msg = "Architecture layer names must not be empty."
            raise ValueError(msg)
        if layer.name in layer_names:
            msg = f"Architecture layer name is duplicated: {layer.name}"
            raise ValueError(msg)
        if (
            not layer.path_prefix
            or layer.path_prefix.startswith(("/", "./", "../"))
            or layer.path_prefix.endswith("/")
            or "//" in layer.path_prefix
        ):
            msg = f"Architecture layer path prefix is invalid: {layer.path_prefix}"
            raise ValueError(msg)
        if layer.path_prefix in prefixes:
            msg = f"Architecture layer path prefix is duplicated: {layer.path_prefix}"
            raise ValueError(msg)
        layer_names.add(layer.name)
        prefixes.add(layer.path_prefix)

    rule_ids: set[str] = set()
    directed_pairs: set[tuple[str, str]] = set()
    for rule in policy.forbidden_dependencies:
        if not rule.rule_id.strip():
            msg = "Architecture dependency rule IDs must not be empty."
            raise ValueError(msg)
        if rule.rule_id in rule_ids:
            msg = f"Architecture dependency rule ID is duplicated: {rule.rule_id}"
            raise ValueError(msg)
        if (
            rule.source_layer not in layer_names
            or rule.destination_layer not in layer_names
        ):
            msg = f"Architecture dependency rule references an unknown layer: {rule.rule_id}"
            raise ValueError(msg)
        pair = (rule.source_layer, rule.destination_layer)
        if pair in directed_pairs:
            msg = "Architecture dependency rules duplicate one directed layer pair."
            raise ValueError(msg)
        rule_ids.add(rule.rule_id)
        directed_pairs.add(pair)


def analyze_architecture_policy(
    model: ArchitectureModel,
    policy: ArchitecturePolicy,
) -> ArchitecturePolicyAnalysis:
    """Apply ordered layers and explicit dependency rules to one graph model.

    Parameters
    ----------
    model : ArchitectureModel
        Deterministic architecture graph to analyze.
    policy : ArchitecturePolicy
        Strict ordered layer and forbidden-dependency configuration.

    Returns
    -------
    ArchitecturePolicyAnalysis
        Assignments, stable hotspots, and violation diagnostics.
    """
    validate_architecture_policy(policy)
    assignments = tuple(
        ArchitectureLayerAssignment(
            module=module.name,
            layer=next(
                (
                    layer.name
                    for layer in policy.layers
                    if _path_matches_prefix(module.path, layer.path_prefix)
                ),
                None,
            ),
        )
        for module in model.modules
    )
    layer_by_module = {
        assignment.module: assignment.layer for assignment in assignments
    }
    rules = {
        (rule.source_layer, rule.destination_layer): rule
        for rule in policy.forbidden_dependencies
    }
    violations: list[ArchitectureViolation] = []
    for dependency in model.dependencies:
        source_layer = layer_by_module[dependency.source]
        destination_layer = layer_by_module[dependency.destination]
        if source_layer is None or destination_layer is None:
            continue
        rule = rules.get((source_layer, destination_layer))
        if rule is None:
            continue
        violations.append(
            ArchitectureViolation(
                rule_id=rule.rule_id,
                source=dependency.source,
                destination=dependency.destination,
                edge_kind=dependency.kind,
                severity=rule.severity,
                evidence=dependency.evidence,
            )
        )
    hotspots = tuple(
        sorted(
            (
                ArchitectureHotspot(
                    module=metric.module,
                    fan_in=metric.fan_in,
                    fan_out=metric.fan_out,
                    score=metric.fan_in + metric.fan_out,
                )
                for metric in model.metrics
            ),
            key=lambda hotspot: (
                -hotspot.score,
                -hotspot.fan_out,
                -hotspot.fan_in,
                hotspot.module,
            ),
        )
    )
    return ArchitecturePolicyAnalysis(
        assignments=assignments,
        hotspots=hotspots,
        violations=tuple(sorted(violations)),
    )


def _cycles(
    modules: tuple[ArchitectureModule, ...],
    dependencies: tuple[ArchitectureDependency, ...],
) -> tuple[ArchitectureCycle, ...]:
    """Compute deterministically ordered strongly connected components.

    Parameters
    ----------
    modules : tuple[ArchitectureModule, ...]
        Sorted architecture modules.
    dependencies : tuple[ArchitectureDependency, ...]
        Sorted aggregate dependencies.

    Returns
    -------
    tuple[ArchitectureCycle, ...]
        Cycle-forming components sorted by their member tuples.
    """
    adjacency: dict[str, set[str]] = {module.name: set() for module in modules}
    for dependency in dependencies:
        adjacency[dependency.source].add(dependency.destination)

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[ArchitectureCycle] = []

    def visit(module: str) -> None:
        """Visit one module using Tarjan's deterministic SCC traversal.

        Parameters
        ----------
        module : str
            Module currently being visited.

        Returns
        -------
        None
            Completed cycle components are appended to the enclosing collector.
        """
        nonlocal index
        indices[module] = index
        lowlinks[module] = index
        index += 1
        stack.append(module)
        on_stack.add(module)

        for destination in sorted(adjacency[module]):
            if destination not in indices:
                visit(destination)
                lowlinks[module] = min(lowlinks[module], lowlinks[destination])
            elif destination in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[destination])

        if lowlinks[module] != indices[module]:
            return
        members: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            members.append(member)
            if member == module:
                break
        ordered_members = tuple(sorted(members))
        if len(ordered_members) > 1 or module in adjacency[module]:
            components.append(ArchitectureCycle(members=ordered_members))

    for module in sorted(adjacency):
        if module not in indices:
            visit(module)
    return tuple(sorted(components))


def build_architecture_model(
    modules: tuple[ArchitectureModule, ...],
    relations: tuple[ArchitectureRelation, ...],
) -> ArchitectureModel:
    """Build a deterministic module graph from indexed artifacts and relations.

    Parameters
    ----------
    modules : tuple[ArchitectureModule, ...]
        Indexed inventory entries, including analyzer-owned facts.
    relations : tuple[ArchitectureRelation, ...]
        Resolved import, call, and reference relations.

    Returns
    -------
    ArchitectureModel
        Aggregate graph, cycles, and degree metrics.

    Raises
    ------
    ValueError
        If modules have duplicate names or a relation names an unknown source.

    Notes
    -----
    A missing destination is unresolved evidence, not a negative architecture
    fact, so it is excluded. Relations targeting modules outside the inventory
    are likewise excluded because the destination cannot be proven indexed.
    """
    ordered_modules = tuple(sorted(modules))
    module_names = {module.name for module in ordered_modules}
    if len(module_names) != len(ordered_modules):
        msg = "Architecture module names must be unique."
        raise ValueError(msg)

    aggregate: dict[
        tuple[str, str, ArchitectureEdgeKind], set[ArchitectureSymbolEvidence]
    ] = {}
    for relation in relations:
        if relation.source_module not in module_names:
            msg = (
                f"Architecture relation source is not indexed: {relation.source_module}"
            )
            raise ValueError(msg)
        if relation.destination_module not in module_names:
            continue
        key = (relation.source_module, relation.destination_module, relation.kind)
        aggregate.setdefault(key, set()).add(relation.evidence)

    dependencies = tuple(
        ArchitectureDependency(
            source=source,
            destination=destination,
            kind=kind,
            evidence=tuple(sorted(evidence)),
        )
        for (source, destination, kind), evidence in sorted(aggregate.items())
    )
    fan_in = {name: 0 for name in module_names}
    fan_out = {name: 0 for name in module_names}
    for dependency in dependencies:
        fan_out[dependency.source] += 1
        fan_in[dependency.destination] += 1
    metrics = tuple(
        ArchitectureModuleMetrics(
            module=module.name,
            fan_in=fan_in[module.name],
            fan_out=fan_out[module.name],
        )
        for module in ordered_modules
    )
    return ArchitectureModel(
        modules=ordered_modules,
        dependencies=dependencies,
        cycles=_cycles(ordered_modules, dependencies),
        metrics=metrics,
    )


def _repository_relative_path(root: Path, value: str) -> str:
    """Normalize one backend file path for architecture inventory output.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for relative output.
    value : str
        Backend-provided file path.

    Returns
    -------
    str
        Repository-relative path when the value belongs to the root, otherwise
        the backend-provided path unchanged.
    """
    path = Path(value)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return value


def _resolve_import_destination(
    import_name: str,
    module_names: set[str],
) -> str | None:
    """Resolve an import target to the longest persisted module prefix.

    Parameters
    ----------
    import_name : str
        Analyzer-normalized import target.
    module_names : set[str]
        Indexed module identities available to the report.

    Returns
    -------
    str | None
        Longest matching indexed module, or ``None`` when unavailable.
    """
    matches = [
        module
        for module in module_names
        if import_name == module or import_name.startswith(f"{module}.")
    ]
    return max(matches, key=len) if matches else None


def build_architecture_model_from_index(
    root: Path,
    *,
    conn: BackendQueryConnection | None = None,
) -> ArchitectureModel:
    """Extract an architecture model through backend-neutral indexed queries.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose current index is read.
    conn : codira.contracts.BackendQueryConnection | None, optional
        Existing backend connection to reuse for a bounded read-only query.

    Returns
    -------
    ArchitectureModel
        Deterministic architecture model built from indexed modules, declaration
        artifacts, imports, calls, and callable references.

    Notes
    -----
    Missing relation targets remain missing evidence. This function does not
    parse source files or assume database-specific schemas.
    """
    backend = active_index_backend(root=root)
    inventory = backend.symbol_inventory(
        root,
        include_tests=True,
        limit=1_000_000,
        conn=conn,
    )
    rows_by_module: dict[str, list[BackendSymbolInventoryItem]] = {}
    for item in inventory:
        rows_by_module.setdefault(item.module, []).append(item)

    modules: list[ArchitectureModule] = []
    module_paths: dict[str, str] = {}
    for module_name, items in sorted(rows_by_module.items()):
        representative = min(
            items, key=lambda item: (item.file, item.lineno, item.name)
        )
        path = _repository_relative_path(root, representative.file)
        module_paths[module_name] = path
        facts = tuple(
            sorted(
                ArchitectureAnalyzerFact(
                    kind=item.symbol_type,
                    name=item.name,
                    signature="",
                )
                for item in items
                if item.symbol_type != "module"
            )
        )
        modules.append(
            ArchitectureModule(
                name=module_name,
                path=path,
                analyzer_name="indexed",
                facts=facts,
            )
        )

    relations: list[ArchitectureRelation] = []
    module_names = set(rows_by_module)
    for module_name, items in sorted(rows_by_module.items()):
        for import_name, _import_kind, lineno in backend.module_imports(
            root, module_name, conn=conn
        ):
            relations.append(
                ArchitectureRelation(
                    source_module=module_name,
                    destination_module=_resolve_import_destination(
                        import_name, module_names
                    ),
                    kind="import",
                    evidence=ArchitectureSymbolEvidence(
                        module=module_name,
                        name=import_name,
                        path=module_paths[module_name],
                        lineno=lineno,
                    ),
                )
            )
        for item in items:
            if item.symbol_type == "module":
                continue
            request = BackendRelationQueryRequest(
                root=root,
                name=item.name,
                module=module_name,
                incoming=False,
                conn=conn,
            )
            for (
                source,
                name,
                destination,
                _target,
                _kind,
                _external,
                _resolved,
            ) in backend.find_call_edges(request):
                relations.append(
                    ArchitectureRelation(
                        source_module=source,
                        destination_module=destination,
                        kind="call",
                        evidence=ArchitectureSymbolEvidence(
                            module=source,
                            name=name,
                            path=module_paths[source],
                            lineno=item.lineno,
                        ),
                    )
                )
            for (
                source,
                name,
                destination,
                _target,
                _kind,
                _external,
                _resolved,
            ) in backend.find_callable_refs(request):
                relations.append(
                    ArchitectureRelation(
                        source_module=source,
                        destination_module=destination,
                        kind="reference",
                        evidence=ArchitectureSymbolEvidence(
                            module=source,
                            name=name,
                            path=module_paths[source],
                            lineno=item.lineno,
                        ),
                    )
                )
    return build_architecture_model(tuple(modules), tuple(relations))
