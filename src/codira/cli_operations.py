"""Operational CLI command families for plugins, configuration, and services."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import shutil
import sys
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

from codira.calibration import (
    calibrate_embeddings,
    embeddings_config_update,
    render_embeddings_calibration_toml,
)
from codira.cli_render import _emit_json
from codira.config import (
    ConfigError,
    LevelName,
    ProfileName,
    config_path,
    config_to_mapping,
    explain_key,
    load_config_level,
    load_effective_config,
    render_config_toml,
    update_config_file,
    user_config_path,
    validate_config_mapping,
    write_config_file,
)
from codira.daemon import (
    DaemonStatusStore,
    LaunchdUserAgent,
    QueryDaemonLaunchdUserAgent,
    QueryDaemonSystemdUserService,
    QueryDaemonWindowsScmService,
    SystemdUserService,
    WindowsScmService,
    run_foreground_daemon,
)
from codira.daemon.service_spec import ServiceSpecification
from codira.migration import (
    ConfigMigrationMode,
    ModelImport,
    StateMigrationMode,
    apply_workspace_migration,
    migration_payload,
    preview_workspace_migration,
)
from codira.model_store import ModelIdentity
from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_cli import emit_execution_mode
from codira.query_daemon_lifecycle import (
    QueryDaemonStatusStore,
    install_query_daemon_signal_handlers,
    run_foreground_query_daemon,
)
from codira.registry import (
    active_embedding_engine,
    plugin_registrations,
    validate_plugin_configuration,
)
from codira.semantic.embeddings import (
    embedding_engine_config,
)
from codira.storage import (
    get_storage_root,
)
from codira.version import package_version
from codira.workspace import ResolvedWorkspace, WorkspaceDefinition, WorkspaceError
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from typing import Protocol

    from codira.path_resolution import ResolvedRuntimePaths

    class _IndexedFileHashLoader(Protocol):
        """
        Backend read surface used by CLI freshness fallback checks.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Protocol definitions are only evaluated by type checkers.
        """

        def load_existing_file_hashes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> dict[str, str]: ...


GIT_EXE = shutil.which("git") or "git"
__version__ = package_version()

QUERY_JSON_SCHEMA_VERSION = "2.0"
INDEX_METADATA_ANALYZER_INVENTORY = "analyzer_inventory"
INDEX_METADATA_BACKEND_NAME = "backend_name"
INDEX_METADATA_BACKEND_VERSION = "backend_version"
INDEX_METADATA_FILE_COUNT = "indexed_file_count"
_REPO_PATH_COMMANDS = frozenset(
    {
        "index",
        "cov",
        "sym",
        "symlist",
        "arch",
        "emb",
        "docs",
        "calls",
        "refs",
        "audit",
        "ctx",
        "config",
        "daemon",
        "query-daemon",
        "setup",
    }
)
_CONFIG_INSPECTION_ACTIONS = frozenset({"dump", "explain", "validate"})


def _run_plugins(*, root: Path | None = None, as_json: bool = False) -> int:
    """
    Print built-in and entry-point plugin registrations.

    Parameters
    ----------
    as_json : bool, optional
        Whether to render structured JSON output.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should mark the active backend.

    Returns
    -------
    int
        Zero after printing deterministic plugin diagnostics.
    """
    from codira.cli import _plugin_is_active_backend

    registrations = plugin_registrations(root=root)

    if as_json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "plugins",
                "status": "ok",
                "results": [
                    {
                        "family": registration.family,
                        "name": registration.name,
                        "active": _plugin_is_active_backend(
                            registration.family,
                            registration.name,
                            root=root,
                        ),
                        "provider": registration.provider,
                        "origin": registration.origin,
                        "source": registration.source,
                        "status": registration.status,
                        "version": registration.version,
                        "entry_point": registration.entry_point,
                        "detail": registration.detail,
                    }
                    for registration in registrations
                ],
            }
        )
        return 0

    for registration in registrations:
        status_tokens: list[str] = [registration.status]
        if _plugin_is_active_backend(
            registration.family,
            registration.name,
            root=root,
        ):
            status_tokens.insert(0, "active")
        line = (
            f"{registration.family}: {registration.name} "
            f"[{', '.join(status_tokens)}] "
            f"provider={registration.provider} "
            f"origin={registration.origin} "
            f"source={registration.source} "
            f"version={registration.version}"
        )
        if registration.entry_point is not None:
            line += f" entry_point={registration.entry_point}"
        if registration.detail is not None:
            line += f" detail={registration.detail}"
        print(line)

    return 0


def _run_plugins_command(args: argparse.Namespace, root: Path) -> int:
    """Run plugin diagnostics through the optional warm daemon.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed plugin command arguments.
    root : pathlib.Path
        Current repository root used for daemon identity.

    Returns
    -------
    int
        Original plugin command exit status.
    """
    from codira.cli_queries import _route_eligible_cli_read

    routing = _route_eligible_cli_read(root, "cli.plugins", {"as_json": args.json})
    if routing.stdout is not None:
        print(routing.stdout, end="")
        emit_execution_mode(routing, requested=args.execution_mode)
        return cast("int", routing.exit_code)
    result = _run_plugins(root=root, as_json=args.json)
    emit_execution_mode(routing, requested=args.execution_mode)
    return result


def _run_config_init(args: argparse.Namespace, root: Path) -> int:
    """
    Create one generated Codira configuration file.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after writing the config file.
    """

    level = cast("LevelName", args.level)
    profile = cast("ProfileName", args.profile)
    path = config_path(level, root=root)
    write_config_file(path, profile=profile, force=args.force, full=args.full)
    print(f"Wrote {level} config: {path}")
    return 0


def _run_config_dump(args: argparse.Namespace, root: Path) -> int:
    """
    Print one config file or the effective configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after printing the requested config.
    """

    from codira.cli_queries import _config_origin_payload

    level = cast("LevelName", args.level)
    if level == "effective":
        config = load_effective_config(root=root)
        payload = config_to_mapping(config)
        if args.json:
            _emit_json(
                {
                    "schema_version": QUERY_JSON_SCHEMA_VERSION,
                    "command": "config dump",
                    "status": "ok",
                    "level": level,
                    "results": payload,
                    "origins": {
                        key: _config_origin_payload(origin)
                        for key, origin in sorted(config.origins.items())
                    },
                }
            )
            return 0
        print(render_config_toml(payload), end="")
        return 0

    path = config_path(level, root=root)
    values = load_config_level(level, root=root)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config dump",
                "status": "ok",
                "level": level,
                "path": str(path),
                "results": values,
            }
        )
        return 0
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def _run_config_explain(args: argparse.Namespace, root: Path) -> int:
    """
    Explain one effective configuration value and origin.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config resolution.

    Returns
    -------
    int
        Zero after printing explanation output.
    """

    from codira.cli_queries import _config_origin_payload

    config = load_effective_config(root=root)
    value, origin = explain_key(config, args.key)
    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config explain",
                "status": "ok",
                "key": args.key,
                "value": value,
                "origin": _config_origin_payload(origin),
            }
        )
        return 0
    origin_path = "" if origin.path is None else f" path={origin.path}"
    print(f"{args.key} = {value!r}")
    print(f"origin = {origin.level}{origin_path} ({origin.detail})")
    return 0


def _run_config_validate(args: argparse.Namespace, root: Path) -> int:
    """
    Validate one config level or the effective configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed config command arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Zero after successful validation.
    """

    level = cast("LevelName", args.level)
    warnings: list[dict[str, object]] = []
    if level == "effective":
        config = load_effective_config(root=root)
        validate_config_mapping(config_to_mapping(config))
        _validate_config_runtime_plugins(config.backend.name, root=root)
        warnings = [
            {"key": warning.key, "reason": warning.reason}
            for warning in validate_plugin_configuration(root=root)
        ]
        path: str | None = None
    else:
        path_obj = config_path(level, root=root)
        validate_config_mapping(load_config_level(level, root=root))
        path = str(path_obj)

    if args.json:
        _emit_json(
            {
                "schema_version": QUERY_JSON_SCHEMA_VERSION,
                "command": "config validate",
                "status": "ok_with_warnings" if warnings else "ok",
                "level": level,
                "path": path,
                "warnings": warnings,
            }
        )
        return 0
    print(f"Config valid: {level}" if path is None else f"Config valid: {path}")
    for warning in warnings:
        print(f"Warning: plugins.{warning['key']}: {warning['reason']}")
    return 0


def _validate_config_runtime_plugins(
    backend_name: str,
    *,
    root: Path | None = None,
) -> None:
    """
    Validate plugin names that require registry discovery.

    Parameters
    ----------
    backend_name : str
        Effective backend name to validate.
    root : pathlib.Path | None, optional
        Repository root whose repo-local config should participate in plugin
        diagnostics.

    Returns
    -------
    None
        Runtime plugin references are valid.

    Raises
    ------
    ConfigError
        If the configured backend is not loaded.
    ValueError
        If registry-level analyzer validation fails.
    """

    registrations = plugin_registrations(root=root)
    loaded_backends = {
        registration.name
        for registration in registrations
        if registration.family == "backend" and registration.status == "loaded"
    }
    if backend_name not in loaded_backends:
        available = ", ".join(sorted(loaded_backends))
        msg = (
            f"Unsupported configured backend '{backend_name}'. "
            f"Available backends: {available}"
        )
        raise ConfigError(msg)


def _run_config_command(args: argparse.Namespace, root: Path) -> int:
    """
    Dispatch one ``codira config`` subcommand.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.
    root : pathlib.Path
        Repository root used for repo-level config paths.

    Returns
    -------
    int
        Process exit status for the config subcommand.

    Raises
    ------
    ConfigError
        If the parsed config action is not supported.
    """

    action = args.config_action or "dump"
    if action == "init":
        return _run_config_init(args, root)
    if action == "dump":
        return _run_config_dump(args, root)
    if action == "explain":
        return _run_config_explain(args, root)
    if action == "validate":
        return _run_config_validate(args, root)
    msg = f"Unsupported config action: {action}"
    raise ConfigError(msg)


def _workspace_payload(
    definition: WorkspaceDefinition | ResolvedWorkspace,
    *,
    status: str,
) -> dict[str, object]:
    """Render one workspace definition as deterministic JSON-compatible data.

    Parameters
    ----------
    definition : object
        Workspace definition or resolved workspace object.
    status : str
        Stable operation status.

    Returns
    -------
    dict[str, object]
        Versioned workspace operation payload.
    """
    return {
        "schema_version": "1.0",
        "status": status,
        "workspace": {
            "name": definition.name,
            "repository_root": str(definition.repository_root),
            "state_root": str(definition.state_root),
            "config_file": (
                str(definition.config_file)
                if definition.config_file is not None
                else None
            ),
        },
    }


def _run_workspace_command(args: argparse.Namespace) -> int:
    """Dispatch deterministic named workspace administration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed workspace subcommand arguments.

    Returns
    -------
    int
        Zero after a successful workspace operation.
    """
    registry = WorkspaceRegistry.default()
    action = args.workspace_action or "list"
    if action == "list":
        definitions = registry.list_definitions()
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "status": "ok",
            "workspaces": [
                _workspace_payload(definition, status="ok")["workspace"]
                for definition in definitions
            ],
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for definition in definitions:
                print(f"{definition.name}\t{definition.repository_root}")
        return 0
    if action == "migrate":
        plan = preview_workspace_migration(
            registry,
            name=args.name,
            repository_root=Path(args.path),
            state_root=Path(args.state_root) if args.state_root else None,
            config_source=Path(args.config_file) if args.config_file else None,
            config_mode=ConfigMigrationMode(args.config_mode),
            state_source=Path(args.state_source) if args.state_source else None,
            state_mode=StateMigrationMode(args.state_mode),
            model_imports=tuple(
                _parse_model_import(value) for value in args.model_import
            ),
            model_root=Path(args.model_root) if args.model_root else None,
        )
        if args.apply:
            apply_workspace_migration(registry, plan)
        payload = {
            "schema_version": "1.0",
            "status": "applied" if args.apply else "preview",
            "migration": migration_payload(plan),
        }
    elif action in {"add", "update"}:
        definition = registry.with_defaults(
            name=args.name,
            repository_root=Path(args.path),
            state_root=Path(args.state_root) if args.state_root else None,
            config_file=Path(args.config_file) if args.config_file else None,
        )
        if action == "add":
            definition, created = registry.add(definition)
            status = "created" if created else "unchanged"
        else:
            definition = registry.update(definition)
            status = "updated"
        payload = _workspace_payload(definition, status=status)
    elif action == "show":
        payload = _workspace_payload(registry.show(args.name), status="ok")
    elif action == "validate":
        payload = _workspace_payload(registry.validate(args.name), status="valid")
    elif action == "remove":
        payload = _workspace_payload(registry.remove(args.name), status="removed")
    else:
        msg = f"Unsupported workspace action: {action}"
        raise WorkspaceError(msg)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        workspace = payload["workspace"]
        assert isinstance(workspace, dict)
        print(f"{payload['status']}: {workspace['name']}")
    return 0


def _parse_model_import(value: str) -> ModelImport:
    """Parse one explicit model-import CLI value.

    Parameters
    ----------
    value : str
        ``ENGINE|MODEL|VERSION|ARTIFACT|PATH`` import specification.

    Returns
    -------
    codira.migration.ModelImport
        Typed immutable model import request.

    Raises
    ------
    argparse.ArgumentTypeError
        If the value does not contain exactly five non-empty components.
    """
    parts = value.split("|", maxsplit=4)
    if len(parts) != 5 or any(not part.strip() for part in parts):
        msg = "model import must be ENGINE|MODEL|VERSION|ARTIFACT|PATH"
        raise argparse.ArgumentTypeError(msg)
    engine, model, version, artifact, source = parts
    return ModelImport(ModelIdentity(engine, model, version, artifact), Path(source))


def _service_specification(
    *,
    kind: str,
    root: Path,
    runtime_paths: ResolvedRuntimePaths | None,
) -> ServiceSpecification:
    """Build one current direct-path or workspace-bound service specification.

    Parameters
    ----------
    kind : {"daemon", "query-daemon"}
        Foreground service family to specify.
    root : pathlib.Path
        Canonical repository root selected for the command.
    runtime_paths : codira.path_resolution.ResolvedRuntimePaths | None
        Fully resolved command routing, including workspace fingerprint when
        startup selected a workspace.

    Returns
    -------
    codira.daemon.service_spec.ServiceSpecification
        Fixed service definition suitable for rendering and drift checks.
    """
    output_root = get_storage_root(root)
    if (
        runtime_paths is not None
        and runtime_paths.workspace_name is not None
        and runtime_paths.workspace_descriptor_fingerprint is not None
    ):
        return ServiceSpecification.workspace(
            kind=kind,
            root=root,
            output_root=output_root,
            workspace_name=runtime_paths.workspace_name,
            descriptor_fingerprint=runtime_paths.workspace_descriptor_fingerprint,
            effective_config=config_to_mapping(load_effective_config(root=root)),
        )
    if kind == "daemon":
        return ServiceSpecification.indexing(root, output_root)
    return ServiceSpecification.query(root, output_root)


def _run_daemon_command(
    args: argparse.Namespace,
    root: Path,
    specification: ServiceSpecification,
) -> int:
    """Run foreground daemon mode or report unavailable service operations.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed daemon command arguments.
    root : pathlib.Path
        Repository root used to resolve effective daemon configuration.

    Returns
    -------
    int
        Zero after foreground daemon shutdown, otherwise nonzero for disabled
        configuration or a service command not implemented in this slice.
    """

    action = args.daemon_action or "help"
    if action == "run":
        config = load_effective_config(root=root)
        if not config.daemon.enabled:
            print(
                "[codira] daemon run requires daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
        with contextlib.suppress(KeyboardInterrupt):
            run_foreground_daemon(root, config.daemon)
        return 0
    if action not in {"install", "uninstall", "start", "stop", "status"}:
        print(f"[codira] Unsupported daemon action: {action}", file=sys.stderr)
        return 2
    if sys.platform.startswith("linux"):
        service = (
            SystemdUserService(root, specification=specification)
            if specification.workspace_name is not None
            else SystemdUserService(root)
        )
        service_kind = "systemd user unit"
    elif sys.platform == "darwin":
        service = (
            LaunchdUserAgent(root, specification=specification)
            if specification.workspace_name is not None
            else LaunchdUserAgent(root)
        )
        service_kind = "launchd user agent"
    elif sys.platform == "win32":
        service = (
            WindowsScmService(root, specification=specification)
            if specification.workspace_name is not None
            else WindowsScmService(root)
        )
        service_kind = "Windows SCM service"
    else:
        print(
            "[codira] daemon service commands require Linux systemd, macOS launchd, or Windows SCM services.",
            file=sys.stderr,
        )
        return 2
    if action in {"install", "start"}:
        config = load_effective_config(root=root)
        if not config.daemon.enabled:
            print(
                f"[codira] daemon {action} requires daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
    if action == "install":
        print(f"[codira] Installed {service_kind}: {service.install()}")
        return 0
    if action == "uninstall":
        service.uninstall()
        print(f"[codira] Uninstalled {service_kind}: {service.identifier}")
        return 0
    if action == "start":
        service.start()
        print(f"[codira] Started {service_kind}: {service.identifier}")
        return 0
    if action == "stop":
        service.stop()
        print(f"[codira] Stopped {service_kind}: {service.identifier}")
        return 0
    status = service.status()
    state = "active" if status.active else "inactive"
    print(f"[codira] {service_kind.capitalize()} {service.identifier}: {state}")
    durable_status = DaemonStatusStore(root).read()
    if durable_status is None:
        print("[codira] No durable daemon status record.")
        return 0
    print(
        "[codira] Daemon reconciliation: "
        f"{durable_status.state.value}; "
        f"pending={durable_status.pending_reconciliation}; "
        f"commit={durable_status.last_reconciled_commit or '-'}; "
        f"last_success={durable_status.last_success_at or '-'}; "
        f"last_error={durable_status.last_error or '-'}"
    )
    return 0


def _run_query_daemon_command(
    args: argparse.Namespace,
    root: Path,
    specification: ServiceSpecification,
) -> int:
    """Run or inspect the repository-local foreground query daemon.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed query-daemon command arguments.
    root : pathlib.Path
        Repository root used to resolve effective configuration.

    Returns
    -------
    int
        Zero after foreground shutdown or status inspection; ``2`` for
        disabled foreground mode or service actions deferred to Slice 6.
    """
    action = args.query_daemon_action or "help"
    config = load_effective_config(root=root)
    identity = QueryDaemonIdentity.from_paths(root, get_storage_root(root))
    if action == "status":
        specification.require_current_definition()
        try:
            status = QueryDaemonStatusStore(identity).read()
        except ValueError as error:
            print(f"[codira] Query daemon status is corrupt: {error}", file=sys.stderr)
            return 2
        if status is None:
            print("[codira] No durable query-daemon status record.")
            return 0
        print(
            "[codira] Query daemon: "
            f"{status.state.value}; "
            f"identity={status.identity}; "
            f"pid={status.pid or '-'}; "
            f"backend={status.backend}; "
            f"embedding={status.embedding_backend}; "
            f"current_generation={status.current_generation or '-'}; "
            f"observed_generation={status.observed_generation or '-'}; "
            f"connection_warm={status.connection_warm}; "
            f"model_warm={status.model_warm}; "
            f"queued={status.queued_requests}; "
            f"active={status.active_requests}; "
            f"fallback={status.fallback_available}; "
            f"last_error={status.last_error or '-'}"
        )
        return 0
    if action == "run":
        if not config.query_daemon.enabled:
            print(
                "[codira] query-daemon run requires query_daemon.enabled = true.",
                file=sys.stderr,
            )
            return 2
        stop_event = Event()
        restore_handlers = install_query_daemon_signal_handlers(stop_event)
        try:
            run_foreground_query_daemon(identity, config, stop_event=stop_event)
        finally:
            restore_handlers()
        return 0
    if action not in {"install", "uninstall", "start", "stop"}:
        print(f"[codira] Unsupported query-daemon action: {action}", file=sys.stderr)
        return 2
    if not config.query_daemon.enabled:
        print(
            f"[codira] query-daemon {action} requires query_daemon.enabled = true.",
            file=sys.stderr,
        )
        return 2
    output_root = get_storage_root(root)
    if sys.platform.startswith("linux"):
        service = (
            SystemdUserService(root, specification=specification)
            if specification.workspace_name is not None
            else QueryDaemonSystemdUserService(root, output_root)
        )
    elif sys.platform == "darwin":
        service = (
            LaunchdUserAgent(root, specification=specification)
            if specification.workspace_name is not None
            else QueryDaemonLaunchdUserAgent(root, output_root)
        )
    elif sys.platform == "win32":
        service = (
            QueryDaemonWindowsScmService(
                root,
                output_root,
                specification=specification,
            )
            if specification.workspace_name is not None
            else QueryDaemonWindowsScmService(root, output_root)
        )
    else:
        print(
            "[codira] query-daemon services require Linux, macOS, or Windows.",
            file=sys.stderr,
        )
        return 2
    if action == "install":
        print(f"[codira] Installed query-daemon service: {service.install()}")
    elif action == "uninstall":
        service.uninstall()
        print(f"[codira] Uninstalled query-daemon service: {service.identifier}")
    elif action == "start":
        service.start()
        print(f"[codira] Started query-daemon service: {service.identifier}")
    else:
        service.stop()
        print(f"[codira] Stopped query-daemon service: {service.identifier}")
    return 0


def _run_calibrate_embeddings(args: argparse.Namespace) -> int:
    """
    Run embeddings calibration and emit or write config-compatible output.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed calibration command arguments.

    Returns
    -------
    int
        Zero after successful calibration output handling.
    """

    root = Path.cwd()
    engine = active_embedding_engine(root=root)
    engine_config = embedding_engine_config(root=root)
    identity = engine.spec(engine_config)
    result = calibrate_embeddings(runner=engine.calibration_runner(engine_config))
    snippet = render_embeddings_calibration_toml(result, engine=identity)
    output_path = cast("Path | None", args.output)
    if args.write:
        path = user_config_path()
        update_config_file(path, embeddings_config_update(result, engine=identity))
        print(f"Wrote user config: {path}")
        return 0
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(snippet, encoding="utf-8")
        print(f"Wrote calibration output: {output_path}")
        return 0
    print(snippet, end="")
    return 0


def _run_calibrate_command(args: argparse.Namespace) -> int:
    """
    Dispatch one ``codira calibrate`` target command.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Process exit status for the calibration target.

    Raises
    ------
    ConfigError
        If the parsed calibration target is not supported.
    """

    target = args.calibration_target
    if target == "embeddings":
        return _run_calibrate_embeddings(args)
    msg = f"Unsupported calibration target: {target}"
    raise ConfigError(msg)


def _run_setup(arguments: list[str]) -> int:
    """Delegate setup to the optional coordinated installer provider.

    Parameters
    ----------
    arguments : list[str]
        Arguments forwarded unchanged to the provider.

    Returns
    -------
    int
        Provider exit status, or ``2`` when the provider is unavailable.
    """
    try:
        provider = importlib.import_module("codira_installer.cli")
    except ModuleNotFoundError as exc:
        if exc.name != "codira_installer":
            raise
        print(
            "[codira] setup requires the coordinated codira-installer package. "
            "Install codira-installer with the same Codira version.",
            file=sys.stderr,
        )
        return 2
    provider_main = getattr(provider, "main", None)
    if not callable(provider_main):
        print(
            "[codira] installed setup provider has no callable main.", file=sys.stderr
        )
        return 2
    return int(provider_main(arguments))
