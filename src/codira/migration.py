"""Plan and apply non-destructive migrations into named workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Never

from codira.model_store import ModelIdentity, SharedModelStore, resolve_model_root
from codira.workspace import WorkspaceError

if TYPE_CHECKING:
    from pathlib import Path

    from codira.workspace_registry import WorkspaceRegistry


class ConfigMigrationMode(StrEnum):
    """Select how a workspace consumes an existing configuration file.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Enumeration members are used in migration plans.
    """

    NONE = "none"
    REFERENCE = "reference"
    COPY = "copy"


class StateMigrationMode(StrEnum):
    """Select how a workspace obtains its Codira state directory.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Enumeration members are used in migration plans.
    """

    REUSE = "reuse"
    COPY = "copy"
    REBUILD = "rebuild"


def _raise_migration_error(message: str, cause: BaseException | None = None) -> Never:
    """Raise a stable migration error from one operator-facing message.

    Parameters
    ----------
    message : str
        Failure detail.

    Returns
    -------
    Never
        This helper always raises.
    """
    if cause is None:
        raise WorkspaceError(message)
    raise WorkspaceError(message) from cause


@dataclass(frozen=True)
class ModelImport:
    """Describe one existing immutable model artifact to import.

    Parameters
    ----------
    identity : codira.model_store.ModelIdentity
        Immutable identity assigned to the copied model blob.
    source : pathlib.Path
        Existing model file retained after import.
    """

    identity: ModelIdentity
    source: Path


@dataclass(frozen=True)
class WorkspaceMigrationPlan:
    """Describe one explicit migration without hidden effects.

    Parameters
    ----------
    name : str
        New workspace name.
    repository_root : pathlib.Path
        Existing repository retained by the migration.
    state_root : pathlib.Path
        State root selected for the registered workspace.
    descriptor_path : pathlib.Path
        Registry descriptor created on apply.
    recovery_record : pathlib.Path
        Durable journal used for resume and idempotence.
    config_mode : ConfigMigrationMode
        Whether configuration is omitted, referenced, or copied.
    config_source : pathlib.Path | None
        Existing configuration source when selected.
    config_destination : pathlib.Path | None
        New copied configuration path when selected.
    state_mode : StateMigrationMode
        Whether state is reused, copied, or rebuilt.
    state_source : pathlib.Path | None
        Existing state source when selected.
    model_imports : tuple[ModelImport, ...]
        Existing model artifacts copied into the shared model store.
    model_root : pathlib.Path | None
        Shared model store used for imports.
    """

    name: str
    repository_root: Path
    state_root: Path
    descriptor_path: Path
    recovery_record: Path
    config_mode: ConfigMigrationMode
    config_source: Path | None
    config_destination: Path | None
    state_mode: StateMigrationMode
    state_source: Path | None
    model_imports: tuple[ModelImport, ...]
    model_root: Path | None

    def identifier(self) -> str:
        """Return a stable identity for journal matching and resume safety.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 over the complete immutable migration description.
        """
        payload = json.dumps(_plan_payload(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def preview_workspace_migration(  # noqa: PLR0913
    registry: WorkspaceRegistry,
    *,
    name: str,
    repository_root: Path,
    state_root: Path | None = None,
    config_source: Path | None = None,
    config_mode: ConfigMigrationMode = ConfigMigrationMode.NONE,
    state_source: Path | None = None,
    state_mode: StateMigrationMode = StateMigrationMode.REBUILD,
    model_imports: tuple[ModelImport, ...] = (),
    model_root: Path | None = None,
) -> WorkspaceMigrationPlan:
    """Build a validated migration plan without writing filesystem state.

    Parameters
    ----------
    registry : codira.workspace_registry.WorkspaceRegistry
        Registry receiving the descriptor only after explicit apply.
    name : str
        Requested workspace name.
    repository_root : pathlib.Path
        Existing repository retained unchanged.
    state_root : pathlib.Path | None, optional
        Destination state root; the registry default is used when omitted.
    config_source : pathlib.Path | None, optional
        Existing configuration file to reference or copy.
    config_mode : ConfigMigrationMode, optional
        Explicit configuration handling mode.
    state_source : pathlib.Path | None, optional
        Existing state directory to reuse or copy.
    state_mode : StateMigrationMode, optional
        Explicit state handling mode.
    model_imports : tuple[ModelImport, ...], optional
        Existing model artifacts to import into a shared model store.
    model_root : pathlib.Path | None, optional
        Explicit shared model store root for model imports.

    Returns
    -------
    WorkspaceMigrationPlan
        Fully resolved, side-effect-free migration preview.

    Raises
    ------
    WorkspaceError
        If selected paths conflict, overlap, or cannot satisfy the requested mode.
    """
    repository = repository_root.expanduser().resolve(strict=False)
    if not repository.is_dir():
        msg = f"Migration repository root is not a directory: {repository}"
        _raise_migration_error(msg)
    target_state = (
        (state_root or registry.state_root / name).expanduser().resolve(strict=False)
    )
    source_state = _directory_source(state_source, "state")
    selected_state = _select_state_root(
        destination=target_state,
        source=source_state,
        mode=state_mode,
    )
    selected_config_source = _file_source(config_source, "configuration")
    config_destination = _select_config_destination(
        mode=config_mode,
        source=selected_config_source,
        state_root=selected_state,
    )
    definition = registry.with_defaults(
        name=name,
        repository_root=repository,
        state_root=selected_state,
        config_file=(
            selected_config_source
            if config_mode is ConfigMigrationMode.REFERENCE
            else config_destination
        ),
    )
    _reject_registration_conflicts(
        registry, definition.name, definition.repository_root
    )
    selected_model_root = _validate_model_imports(model_imports, model_root)
    return WorkspaceMigrationPlan(
        name=definition.name,
        repository_root=definition.repository_root,
        state_root=definition.state_root,
        descriptor_path=registry.descriptor_path(definition.name),
        recovery_record=registry.state_root / "migrations" / f"{definition.name}.json",
        config_mode=config_mode,
        config_source=selected_config_source,
        config_destination=config_destination,
        state_mode=state_mode,
        state_source=source_state,
        model_imports=tuple(
            ModelImport(item.identity, item.source.expanduser().resolve(strict=False))
            for item in model_imports
        ),
        model_root=selected_model_root,
    )


def apply_workspace_migration(
    registry: WorkspaceRegistry, plan: WorkspaceMigrationPlan
) -> WorkspaceMigrationPlan:
    """Apply one previewed plan atomically where destinations are written.

    Parameters
    ----------
    registry : codira.workspace_registry.WorkspaceRegistry
        Registry receiving the workspace descriptor after data preparation.
    plan : WorkspaceMigrationPlan
        Previewed plan to apply or resume.

    Returns
    -------
    WorkspaceMigrationPlan
        The completed immutable plan.

    Raises
    ------
    WorkspaceError
        If a recovery record belongs to a different plan or a destination is unsafe.
    """
    completed = _load_journal(plan)
    if completed == {"complete"}:
        return plan
    if plan.state_mode is StateMigrationMode.COPY and "state" not in completed:
        assert plan.state_source is not None
        _copy_directory_atomically(plan.state_source, plan.state_root)
        completed.add("state")
        _write_journal(plan, completed)
    elif plan.state_mode is StateMigrationMode.REBUILD and "state" not in completed:
        plan.state_root.mkdir(parents=True, exist_ok=True)
        completed.add("state")
        _write_journal(plan, completed)
    if plan.config_mode is ConfigMigrationMode.COPY and "config" not in completed:
        assert plan.config_source is not None
        assert plan.config_destination is not None
        _copy_file_atomically(plan.config_source, plan.config_destination)
        completed.add("config")
        _write_journal(plan, completed)
    if plan.model_imports and "models" not in completed:
        assert plan.model_root is not None
        store = SharedModelStore(plan.model_root)
        for imported in plan.model_imports:
            store.import_existing(imported.identity, imported.source)
        completed.add("models")
        _write_journal(plan, completed)
    if "workspace" not in completed:
        definition = registry.with_defaults(
            name=plan.name,
            repository_root=plan.repository_root,
            state_root=plan.state_root,
            config_file=(
                plan.config_source
                if plan.config_mode is ConfigMigrationMode.REFERENCE
                else plan.config_destination
            ),
        )
        registry.add(definition)
        completed.add("workspace")
        _write_journal(plan, completed)
    completed.add("complete")
    _write_journal(plan, completed)
    return plan


def migration_payload(plan: WorkspaceMigrationPlan) -> dict[str, object]:
    """Render every migration source, destination, and retained original.

    Parameters
    ----------
    plan : WorkspaceMigrationPlan
        Immutable preview or completed plan.

    Returns
    -------
    dict[str, object]
        JSON-ready dry-run or apply payload.
    """
    payload = _plan_payload(plan)
    payload["identifier"] = plan.identifier()
    payload["retained_originals"] = [
        str(path)
        for path in (
            plan.repository_root,
            plan.config_source,
            plan.state_source,
            *(item.source for item in plan.model_imports),
        )
        if path is not None
    ]
    payload["large_data_actions"] = [
        {
            "kind": "state",
            "mode": plan.state_mode.value,
            "source": str(plan.state_source) if plan.state_source else None,
            "destination": str(plan.state_root),
            "estimated_bytes": _directory_size(plan.state_source),
        },
        *[
            {
                "kind": "model",
                "mode": "import",
                "source": str(item.source),
                "destination": str(plan.model_root) if plan.model_root else None,
                "estimated_bytes": item.source.stat().st_size,
            }
            for item in plan.model_imports
        ],
    ]
    return payload


def _directory_source(source: Path | None, label: str) -> Path | None:
    """Resolve and validate an optional existing directory source.

    Parameters
    ----------
    source : pathlib.Path | None
        Candidate directory.
    label : str
        Operator-facing source category.

    Returns
    -------
    pathlib.Path | None
        Canonical directory or ``None``.

    Raises
    ------
    WorkspaceError
        If the provided source is not a directory.
    """
    if source is None:
        return None
    resolved = source.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        msg = f"Migration {label} source is not a directory: {resolved}"
        _raise_migration_error(msg)
    return resolved


def _file_source(source: Path | None, label: str) -> Path | None:
    """Resolve and validate an optional existing file source.

    Parameters
    ----------
    source : pathlib.Path | None
        Candidate file.
    label : str
        Operator-facing source category.

    Returns
    -------
    pathlib.Path | None
        Canonical file or ``None``.

    Raises
    ------
    WorkspaceError
        If the provided source is not a file.
    """
    if source is None:
        return None
    resolved = source.expanduser().resolve(strict=False)
    if not resolved.is_file():
        msg = f"Migration {label} source is not a file: {resolved}"
        _raise_migration_error(msg)
    return resolved


def _select_state_root(
    *,
    destination: Path,
    source: Path | None,
    mode: StateMigrationMode,
) -> Path:
    """Validate state mode and return the workspace state destination.

    Parameters
    ----------
    destination : pathlib.Path
        Requested state destination.
    source : pathlib.Path | None
        Existing source state.
    mode : StateMigrationMode
        Requested state handling mode.

    Returns
    -------
    pathlib.Path
        Selected final state root.

    Raises
    ------
    WorkspaceError
        If mode inputs overlap or would overwrite existing state.
    """
    if mode is StateMigrationMode.REUSE:
        if source is None:
            _raise_migration_error("State reuse requires --state-source.")
        if destination != source and destination.exists():
            _raise_migration_error(
                "State reuse cannot replace an existing destination."
            )
        return source
    if mode is StateMigrationMode.COPY:
        if source is None:
            _raise_migration_error("State copy requires --state-source.")
        _reject_overlap(source, destination, "state copy")
        if destination.exists():
            _raise_migration_error(
                f"State copy destination already exists: {destination}"
            )
        return destination
    if source is not None:
        _raise_migration_error("State rebuild does not accept --state-source.")
    if destination.exists() and any(destination.iterdir()):
        _raise_migration_error(f"State rebuild destination is not empty: {destination}")
    return destination


def _select_config_destination(
    *,
    mode: ConfigMigrationMode,
    source: Path | None,
    state_root: Path,
) -> Path | None:
    """Validate configuration mode and select a copied destination.

    Parameters
    ----------
    mode : ConfigMigrationMode
        Requested configuration handling mode.
    source : pathlib.Path | None
        Existing configuration source.
    state_root : pathlib.Path
        Final workspace state root used for copied configuration.

    Returns
    -------
    pathlib.Path | None
        Copied configuration destination or ``None``.

    Raises
    ------
    WorkspaceError
        If mode and source selection disagree or would overwrite data.
    """
    if mode is ConfigMigrationMode.NONE:
        if source is not None:
            _raise_migration_error(
                "Configuration source requires copy or reference mode."
            )
        return None
    if source is None:
        _raise_migration_error(f"Configuration {mode.value} requires --config-file.")
    if mode is ConfigMigrationMode.REFERENCE:
        return None
    destination = state_root / "config.toml"
    _reject_overlap(source, destination, "configuration copy")
    if destination.exists():
        _raise_migration_error(
            f"Configuration copy destination already exists: {destination}"
        )
    return destination


def _validate_model_imports(
    imports: tuple[ModelImport, ...], model_root: Path | None
) -> Path | None:
    """Validate model import sources and select their shared destination.

    Parameters
    ----------
    imports : tuple[ModelImport, ...]
        Model import entries.
    model_root : pathlib.Path | None
        Explicit shared model root.

    Returns
    -------
    pathlib.Path | None
        Selected shared model root or ``None`` when no imports were selected.

    Raises
    ------
    WorkspaceError
        If identities repeat or a source is not a file.
    """
    if not imports:
        return None
    identities: set[str] = set()
    for imported in imports:
        if not imported.source.expanduser().resolve(strict=False).is_file():
            msg = f"Migration model source is not a file: {imported.source}"
            _raise_migration_error(msg)
        key = imported.identity.key()
        if key in identities:
            _raise_migration_error("Migration model identities must be unique.")
        identities.add(key)
    return (
        resolve_model_root(explicit_root=model_root)
        if model_root
        else resolve_model_root()
    )


def _reject_registration_conflicts(
    registry: WorkspaceRegistry, name: str, repository_root: Path
) -> None:
    """Reject registrations incompatible with this migration plan.

    Parameters
    ----------
    registry : codira.workspace_registry.WorkspaceRegistry
        Existing registry to inspect.
    name : str
        Requested workspace name.
    repository_root : pathlib.Path
        Requested repository root.

    Returns
    -------
    None
        Conflicts are absent or an error is raised.

    Raises
    ------
    WorkspaceError
        If name or root is owned by a different workspace.
    """
    for existing in registry.list_definitions():
        if existing.name == name and existing.repository_root != repository_root:
            _raise_migration_error(f"Workspace name is already registered: {name}")
        if existing.name != name and existing.repository_root == repository_root:
            msg = f"Repository root is already registered by workspace: {existing.name}"
            _raise_migration_error(msg)


def _reject_overlap(source: Path, destination: Path, label: str) -> None:
    """Reject a copy whose source and destination can overwrite each other.

    Parameters
    ----------
    source : pathlib.Path
        Existing source path.
    destination : pathlib.Path
        New destination path.
    label : str
        Operator-facing operation name.

    Returns
    -------
    None
        Paths are disjoint or an error is raised.

    Raises
    ------
    WorkspaceError
        If either path contains the other.
    """
    if (
        source == destination
        or source.is_relative_to(destination)
        or destination.is_relative_to(source)
    ):
        _raise_migration_error(
            f"Unsafe overlapping {label} paths: {source} and {destination}"
        )


def _copy_directory_atomically(source: Path, destination: Path) -> None:
    """Copy one state tree into a new destination through a sibling staging tree.

    Parameters
    ----------
    source : pathlib.Path
        Existing state directory.
    destination : pathlib.Path
        Absent final destination directory.

    Returns
    -------
    None
        The copied tree becomes visible atomically.

    Raises
    ------
    WorkspaceError
        If destination appeared during the copy or copying fails.
    """
    if destination.exists():
        if _same_directory(source, destination):
            return
        _raise_migration_error(f"State copy destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copytree(source, staging)
        if destination.exists():
            if _same_directory(source, destination):
                return
            _raise_migration_error(
                f"State copy destination already exists: {destination}"
            )
        staging.replace(destination)
    except OSError as exc:
        _raise_migration_error(f"Cannot copy migration state: {exc}", exc)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _copy_file_atomically(source: Path, destination: Path) -> None:
    """Copy one configuration file through an atomic same-directory rename.

    Parameters
    ----------
    source : pathlib.Path
        Existing configuration file.
    destination : pathlib.Path
        Absent final configuration path.

    Returns
    -------
    None
        The copied file becomes visible atomically.

    Raises
    ------
    WorkspaceError
        If destination appeared during copying or copying fails.
    """
    if destination.exists():
        if destination.is_file() and destination.read_bytes() == source.read_bytes():
            return
        _raise_migration_error(
            f"Configuration copy destination already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, staging)
        if destination.exists():
            if (
                destination.is_file()
                and destination.read_bytes() == source.read_bytes()
            ):
                return
            _raise_migration_error(
                f"Configuration copy destination already exists: {destination}"
            )
        staging.replace(destination)
    except OSError as exc:
        _raise_migration_error(f"Cannot copy migration configuration: {exc}", exc)
    finally:
        staging.unlink(missing_ok=True)


def _same_directory(source: Path, destination: Path) -> bool:
    """Return whether two regular-file directory trees have identical content.

    Parameters
    ----------
    source : pathlib.Path
        Existing source directory.
    destination : pathlib.Path
        Existing destination directory.

    Returns
    -------
    bool
        ``True`` only when every regular file has the same relative path and
        SHA-256 content digest.
    """
    if not destination.is_dir():
        return False
    source_files = {
        item.relative_to(source): item for item in source.rglob("*") if item.is_file()
    }
    destination_files = {
        item.relative_to(destination): item
        for item in destination.rglob("*")
        if item.is_file()
    }
    if source_files.keys() != destination_files.keys():
        return False
    return all(
        source_file.stat().st_size == destination_files[relative].stat().st_size
        and _file_digest(source_file) == _file_digest(destination_files[relative])
        for relative, source_file in source_files.items()
    )


def _file_digest(path: Path) -> str:
    """Return one regular file's SHA-256 digest without loading it at once.

    Parameters
    ----------
    path : pathlib.Path
        Existing regular file.

    Returns
    -------
    str
        Lowercase hexadecimal content digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_journal(plan: WorkspaceMigrationPlan) -> set[str]:
    """Load and validate a prior journal for an idempotent resume.

    Parameters
    ----------
    plan : WorkspaceMigrationPlan
        Plan whose journal is loaded.

    Returns
    -------
    set[str]
        Completed operation identifiers.

    Raises
    ------
    WorkspaceError
        If the journal is malformed or belongs to a different plan.
    """
    if not plan.recovery_record.exists():
        return set()
    try:
        value = json.loads(plan.recovery_record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise_migration_error(f"Cannot read migration journal: {exc}", exc)
    if value.get("identifier") != plan.identifier():
        _raise_migration_error("Migration journal belongs to a different plan.")
    completed = value.get("completed")
    if not isinstance(completed, list) or not all(
        isinstance(item, str) for item in completed
    ):
        _raise_migration_error("Migration journal has invalid completed operations.")
    return set(completed)


def _write_journal(plan: WorkspaceMigrationPlan, completed: set[str]) -> None:
    """Atomically publish migration provenance after each completed operation.

    Parameters
    ----------
    plan : WorkspaceMigrationPlan
        Plan represented by the journal.
    completed : set[str]
        Completed operation identifiers.

    Returns
    -------
    None
        One complete journal record replaces any earlier record.
    """
    plan.recovery_record.parent.mkdir(parents=True, exist_ok=True)
    payload = migration_payload(plan)
    payload["completed"] = sorted(completed)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    staging = plan.recovery_record.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        staging.write_text(content, encoding="utf-8")
        staging.replace(plan.recovery_record)
    except OSError as exc:
        _raise_migration_error(f"Cannot write migration journal: {exc}", exc)
    finally:
        staging.unlink(missing_ok=True)


def _plan_payload(plan: WorkspaceMigrationPlan) -> dict[str, object]:
    """Render the immutable plan fields without derived preview information.

    Parameters
    ----------
    plan : WorkspaceMigrationPlan
        Migration plan to serialize.

    Returns
    -------
    dict[str, object]
        Deterministic JSON-ready immutable plan fields.
    """
    return {
        "schema_version": "1.0",
        "name": plan.name,
        "repository_root": str(plan.repository_root),
        "state_root": str(plan.state_root),
        "descriptor_path": str(plan.descriptor_path),
        "recovery_record": str(plan.recovery_record),
        "config": {
            "mode": plan.config_mode.value,
            "source": str(plan.config_source) if plan.config_source else None,
            "destination": (
                str(plan.config_destination) if plan.config_destination else None
            ),
        },
        "state": {
            "mode": plan.state_mode.value,
            "source": str(plan.state_source) if plan.state_source else None,
            "destination": str(plan.state_root),
        },
        "models": [
            {
                "identity": asdict(item.identity),
                "source": str(item.source),
                "destination": str(plan.model_root) if plan.model_root else None,
            }
            for item in plan.model_imports
        ],
    }


def _directory_size(path: Path | None) -> int | None:
    """Estimate one directory's file payload size for a dry-run report.

    Parameters
    ----------
    path : pathlib.Path | None
        Existing directory whose regular files are counted.

    Returns
    -------
    int | None
        Total bytes, or ``None`` when no source directory is selected.
    """
    if path is None:
        return None
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
