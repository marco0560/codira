"""Windows Service Control Manager adapter for Codira's daemon.

Responsibilities
----------------
- Install a repository-scoped pywin32 service with SCM lifecycle operations.
- Persist the canonical repository root in service-local SCM parameters.
- Run the existing foreground daemon through a real ServiceFramework host.

Design principles
-----------------
Windows SCM requires a process that handles service controls. The adapter does
not register the foreground console command directly; its ServiceFramework
host translates SCM stop requests into the foreground watch stop event.

Architectural role
------------------
This module belongs to the daemon service-adapter layer for Windows SCM.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol, cast

from codira.config import load_effective_config, override_repo_config_path
from codira.daemon.runtime import run_foreground_daemon
from codira.daemon.service_spec import ServiceSpecification
from codira.query_daemon import QueryDaemonIdentity
from codira.query_daemon_lifecycle import run_foreground_query_daemon
from codira.storage import override_storage_root
from codira.workspace_registry import WorkspaceRegistry


class _ServiceUtilModule(Protocol):
    """Describe the pywin32 service utility calls used by this adapter.

    Parameters
    ----------
    None

    Returns
    -------
    None
        This protocol exists only for dynamic optional-dependency typing.
    """

    def GetServiceCustomOption(
        self,
        service_name: object,
        option: str,
        default_value: object = None,
    ) -> object:
        """Return one persisted SCM service option.

        Parameters
        ----------
        service_name : object
            SCM service identity.
        option : str
            Option key to read.
        default_value : object, optional
            Value returned when the option is absent.

        Returns
        -------
        object
            Persisted option value or the provided default.
        """
        ...

    def InstallService(
        self,
        python_class_string: str,
        service_name: str,
        display_name: str,
        **kwargs: object,
    ) -> None:
        """Install one SCM service implementation.

        Parameters
        ----------
        python_class_string : str
            Dotted ServiceFramework implementation path.
        service_name : str
            Stable SCM service identity.
        display_name : str
            Human-readable service name.
        **kwargs : object
            Additional pywin32 installation controls.

        Returns
        -------
        None
            The service definition is installed by pywin32.
        """
        ...

    def QueryServiceStatus(self, service_name: str) -> tuple[object, ...]:
        """Return the raw SCM status tuple for one service.

        Parameters
        ----------
        service_name : str
            Stable SCM service identity.

        Returns
        -------
        tuple[object, ...]
            pywin32 status tuple whose first value is the current state.
        """
        ...

    def RemoveService(self, service_name: str) -> None:
        """Remove one installed SCM service.

        Parameters
        ----------
        service_name : str
            Stable SCM service identity.

        Returns
        -------
        None
            The service is removed by pywin32.
        """
        ...

    def StartService(self, service_name: str) -> None:
        """Request that one SCM service starts.

        Parameters
        ----------
        service_name : str
            Stable SCM service identity.

        Returns
        -------
        None
            The start request is delegated to pywin32.
        """
        ...

    def StopService(self, service_name: str) -> None:
        """Request that one SCM service stops.

        Parameters
        ----------
        service_name : str
            Stable SCM service identity.

        Returns
        -------
        None
            The stop request is delegated to pywin32.
        """
        ...

    def SetServiceCustomOption(
        self,
        service_name: str,
        option: str,
        value: str,
    ) -> None:
        """Persist one SCM service option.

        Parameters
        ----------
        service_name : str
            Stable SCM service identity.
        option : str
            Option key to write.
        value : str
            Serialized option value.

        Returns
        -------
        None
            The option is stored by pywin32.
        """
        ...


class _Win32ServiceModule(Protocol):
    """Describe the pywin32 service constants used by this adapter.

    Parameters
    ----------
    None

    Returns
    -------
    None
        This protocol exists only for dynamic optional-dependency typing.
    """

    SERVICE_AUTO_START: int
    SERVICE_RUNNING: int
    SERVICE_STOP_PENDING: int


_serviceutil: _ServiceUtilModule | None = None


@dataclass(frozen=True)
class WindowsScmApi:
    """Hold pywin32 service APIs required by one SCM adapter instance.

    Parameters
    ----------
    serviceutil : _ServiceUtilModule
        pywin32 service utility module.
    service : _Win32ServiceModule
        pywin32 service constants module.

    Returns
    -------
    None
        Instances make the optional Windows boundary injectable in tests.
    """

    serviceutil: _ServiceUtilModule
    service: _Win32ServiceModule


class WindowsScmServiceError(RuntimeError):
    """Report a failed Windows Service Control Manager operation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the failed service-manager operation diagnostic.
    """


@dataclass(frozen=True)
class WindowsScmServiceStatus:
    """Report one repository service's Windows SCM activation state.

    Parameters
    ----------
    service_name : str
        Repository-scoped SCM service name.
    active : bool
        Whether the SCM reports the service in the running state.

    Returns
    -------
    None
        Instances expose immutable service-manager status.
    """

    service_name: str
    active: bool


def _resolve_workspace_service_paths(
    service: object,
    root: Path,
    output_root: Path,
) -> tuple[Path, Path, Path | None]:
    """Validate SCM workspace identity and return fixed runtime paths.

    Parameters
    ----------
    service : object
        SCM service instance used to read persisted custom options.
    root : pathlib.Path
        Repository root persisted when the service was installed.
    output_root : pathlib.Path
        State root persisted when the service was installed.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, pathlib.Path | None]
        Canonical repository root, state root, and optional workspace config.

    Raises
    ------
    RuntimeError
        If a workspace descriptor has drifted or no longer matches the SCM
        service's persisted paths.
    """
    serviceutil = _serviceutil
    if serviceutil is None:
        msg = "Windows service utility is unavailable"
        raise RuntimeError(msg)
    workspace_name = serviceutil.GetServiceCustomOption(service, "workspace")
    expected_fingerprint = serviceutil.GetServiceCustomOption(
        service, "workspace_fingerprint"
    )
    if workspace_name is None and expected_fingerprint is None:
        return root, output_root, None
    if not isinstance(workspace_name, str) or not isinstance(expected_fingerprint, str):
        msg = "Windows service workspace identity is incomplete"
        raise TypeError(msg)
    workspace = WorkspaceRegistry.default().validate(workspace_name)
    observed_fingerprint = hashlib.sha256(
        workspace.descriptor_path.read_bytes()
    ).hexdigest()
    if observed_fingerprint != expected_fingerprint:
        msg = "Workspace descriptor drift detected; regenerate the service definition"
        raise RuntimeError(msg)
    if workspace.repository_root != root or workspace.state_root != output_root:
        msg = "Workspace descriptor no longer matches the installed service paths"
        raise RuntimeError(msg)
    return workspace.repository_root, workspace.state_root, workspace.config_file


def _load_windows_scm_api() -> WindowsScmApi:
    """Load pywin32 SCM modules only when a Windows adapter is requested.

    Parameters
    ----------
    None

    Returns
    -------
    WindowsScmApi
        Dynamically loaded pywin32 service utilities and constants.

    Raises
    ------
    WindowsScmServiceError
        If the Windows-only pywin32 dependency is unavailable.
    """
    try:
        serviceutil = cast(
            "_ServiceUtilModule",
            importlib.import_module("win32serviceutil"),
        )
        service = cast(
            "_Win32ServiceModule",
            importlib.import_module("win32service"),
        )
    except ModuleNotFoundError as error:
        msg = "Windows daemon services require the pywin32 dependency"
        raise WindowsScmServiceError(msg) from error
    return WindowsScmApi(serviceutil=serviceutil, service=service)


class WindowsScmService:
    """Manage one repository-scoped Windows SCM service.

    Parameters
    ----------
    root : pathlib.Path
        Repository root served by the foreground daemon command.
    api : WindowsScmApi | None, optional
        pywin32 API override used by deterministic tests. ``None`` loads the
        Windows-only dependency when this adapter is constructed.

    Returns
    -------
    None

    Notes
    -----
    Installation requires permission to create an SCM service and write its
    parameters. The installed service starts automatically and reads its own
    repository root from SCM parameters on each launch.
    """

    def __init__(
        self,
        root: Path,
        *,
        specification: ServiceSpecification | None = None,
        api: WindowsScmApi | None = None,
    ) -> None:
        """Initialize one repository-scoped Windows SCM service adapter.

        Parameters
        ----------
        root : pathlib.Path
            Repository root served by the foreground daemon command.
        specification : codira.daemon.service_spec.ServiceSpecification | None, optional
            Fixed direct-path or workspace service definition.
        api : WindowsScmApi | None, optional
            pywin32 API override used by deterministic tests.

        Returns
        -------
        None
            The adapter retains deterministic service identity and API access.
        """
        self._specification = specification or ServiceSpecification.indexing(root)
        self._root = self._specification.root
        self._api = api or _load_windows_scm_api()

    @property
    def service_name(self) -> str:
        """Return the deterministic repository-scoped SCM service name.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Stable SCM service name for the canonical repository root.
        """
        if self._specification.workspace_name is not None:
            return f"CodiraDaemon_{self._specification.identity}"
        digest = hashlib.sha256(str(self._root).encode("utf-8")).hexdigest()[:16]
        return f"CodiraDaemon_{digest}"

    @property
    def identifier(self) -> str:
        """Return the service-manager identifier used in lifecycle messages.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Repository-scoped Windows SCM service name.
        """
        return self.service_name

    def install(self) -> Path:
        """Install and configure this repository's automatic-start SCM service.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Canonical repository root persisted in the service parameters.
        """
        self._api.serviceutil.InstallService(
            f"{__name__}.CodiraWindowsService",
            self.service_name,
            f"Codira automatic indexing ({self._root.name})",
            startType=self._api.service.SERVICE_AUTO_START,
            description="Repository-scoped Codira automatic indexing daemon.",
        )
        self._api.serviceutil.SetServiceCustomOption(
            self.service_name,
            "root",
            str(self._root),
        )
        self._api.serviceutil.SetServiceCustomOption(
            self.service_name,
            "output_root",
            str(self._specification.output_root),
        )
        if self._specification.workspace_name is not None:
            assert self._specification.descriptor_fingerprint is not None
            self._api.serviceutil.SetServiceCustomOption(
                self.service_name,
                "workspace",
                self._specification.workspace_name,
            )
            self._api.serviceutil.SetServiceCustomOption(
                self.service_name,
                "workspace_fingerprint",
                self._specification.descriptor_fingerprint,
            )
        self._specification.write_definition()
        return self._root

    def uninstall(self) -> None:
        """Remove this repository's SCM service registration.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The SCM service and its repository parameters are removed.
        """
        self._api.serviceutil.RemoveService(self.service_name)
        self._specification.remove_definition()

    def start(self) -> None:
        """Start this repository's installed SCM service.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The command returns after SCM accepts the start request.
        """
        self._specification.require_current_definition()
        self._api.serviceutil.StartService(self.service_name)

    def stop(self) -> None:
        """Request a graceful stop for this repository's SCM service.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The command returns after SCM accepts the stop request.
        """
        self._specification.require_current_definition()
        self._api.serviceutil.StopService(self.service_name)

    def status(self) -> WindowsScmServiceStatus:
        """Inspect whether this repository's SCM service is running.

        Parameters
        ----------
        None

        Returns
        -------
        WindowsScmServiceStatus
            Immutable active/inactive result for the repository service.
        """
        self._specification.require_current_definition()
        status = self._api.serviceutil.QueryServiceStatus(self.service_name)
        current_state = status[1]
        return WindowsScmServiceStatus(
            service_name=self.service_name,
            active=current_state == self._api.service.SERVICE_RUNNING,
        )


class QueryDaemonWindowsScmService(WindowsScmService):
    """Manage one output-isolated Windows SCM query-daemon service."""

    def __init__(
        self,
        root: Path,
        output_root: Path,
        *,
        specification: ServiceSpecification | None = None,
        api: WindowsScmApi | None = None,
    ) -> None:
        """Initialize fixed repository/output SCM query service identity.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        output_root : pathlib.Path
            Effective output root.
        specification : codira.daemon.service_spec.ServiceSpecification | None, optional
            Fixed direct-path or workspace service definition.
        api : WindowsScmApi | None, optional
            pywin32 adapter override.

        Returns
        -------
        None
        """
        super().__init__(
            root,
            specification=specification
            or ServiceSpecification.query(root, output_root),
            api=api,
        )

    @property
    def service_name(self) -> str:
        """Return the output-isolated SCM query service identity.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Stable Windows SCM service name.
        """
        return f"CodiraQueryDaemon_{self._specification.identity}"

    def install(self) -> Path:
        """Install query service identity and persist its output root.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Effective output root persisted for the service host.
        """
        self._api.serviceutil.InstallService(
            f"{__name__}.CodiraQueryWindowsService",
            self.service_name,
            f"Codira warm query daemon ({self._root.name})",
            startType=self._api.service.SERVICE_AUTO_START,
            description="Repository-scoped Codira warm query daemon.",
        )
        self._api.serviceutil.SetServiceCustomOption(
            self.service_name, "root", str(self._root)
        )
        self._api.serviceutil.SetServiceCustomOption(
            self.service_name, "output_root", str(self._specification.output_root)
        )
        if self._specification.workspace_name is not None:
            assert self._specification.descriptor_fingerprint is not None
            self._api.serviceutil.SetServiceCustomOption(
                self.service_name,
                "workspace",
                self._specification.workspace_name,
            )
            self._api.serviceutil.SetServiceCustomOption(
                self.service_name,
                "workspace_fingerprint",
                self._specification.descriptor_fingerprint,
            )
        self._specification.write_definition()
        return self._specification.output_root


if sys.platform == "win32":
    _serviceutil = cast(
        "_ServiceUtilModule", importlib.import_module("win32serviceutil")
    )
    _win32service = importlib.import_module("win32service")

    class CodiraWindowsService(_serviceutil.ServiceFramework):  # type: ignore[misc]
        """Host one Codira daemon under Windows Service Control Manager.

        Parameters
        ----------
        args : list[str]
            SCM-provided service arguments containing the installed service name.

        Returns
        -------
        None
            The service host registers its stop handler with SCM.
        """

        _svc_name_ = "CodiraDaemon"
        _svc_display_name_ = "Codira automatic indexing"

        def __init__(self, args: list[str]) -> None:
            """Initialize the SCM stop event for the installed service instance.

            Parameters
            ----------
            args : list[str]
                SCM-provided service arguments containing the installed name.

            Returns
            -------
            None
                The service host is initialized for control dispatch.
            """
            self._svc_name_ = args[0]
            self._stop_event = Event()
            super().__init__(args)

        def SvcStop(self) -> None:
            """Translate SCM stop control into a foreground watch stop event.

            Parameters
            ----------
            None

            Returns
            -------
            None
                The active watch loop receives the stop event.
            """
            self.ReportServiceStatus(_win32service.SERVICE_STOP_PENDING)
            self._stop_event.set()

        def SvcDoRun(self) -> None:
            """Run foreground daemon reconciliation for this service's root.

            Parameters
            ----------
            None

            Returns
            -------
            None
                The daemon runs until SCM sends a stop control.

            Raises
            ------
            RuntimeError
                If the installed service has no persisted repository root.
            """
            root_value = _serviceutil.GetServiceCustomOption(self, "root")
            if not isinstance(root_value, str) or not root_value:
                msg = "Windows service has no configured repository root"
                raise TypeError(msg)
            root = Path(root_value)
            output_value = _serviceutil.GetServiceCustomOption(
                self, "output_root", root_value
            )
            if not isinstance(output_value, str) or not output_value:
                msg = "Windows service has no configured output root"
                raise TypeError(msg)
            root, output_root, config_file = _resolve_workspace_service_paths(
                self, root, Path(output_value)
            )
            with (
                override_storage_root(root, output_root),
                override_repo_config_path(config_file),
            ):
                config = load_effective_config(root=root)
                run_foreground_daemon(root, config.daemon, stop_event=self._stop_event)

    class CodiraQueryWindowsService(CodiraWindowsService):  # type: ignore[misc]
        """Host one warm query daemon under Windows Service Control Manager."""

        def SvcDoRun(self) -> None:
            """Run the fixed repository/output foreground query daemon.

            Parameters
            ----------
            None

            Returns
            -------
            None

            Raises
            ------
            RuntimeError
                If required SCM root or output-root configuration is missing.
            """
            root_value = _serviceutil.GetServiceCustomOption(self, "root")
            output_value = _serviceutil.GetServiceCustomOption(self, "output_root")
            if not isinstance(root_value, str) or not isinstance(output_value, str):
                msg = "Windows query service has no configured repository/output roots"
                raise TypeError(msg)
            root, output_root, config_file = _resolve_workspace_service_paths(
                self, Path(root_value), Path(output_value)
            )
            with (
                override_storage_root(root, output_root),
                override_repo_config_path(config_file),
            ):
                config = load_effective_config(root=root)
                identity = QueryDaemonIdentity.from_paths(root, output_root)
                run_foreground_query_daemon(
                    identity, config, stop_event=self._stop_event
                )

else:

    class CodiraWindowsService:
        """Placeholder exported on non-Windows hosts for service registration.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Windows imports replace this placeholder with the SCM host class.
        """

    class CodiraQueryWindowsService(CodiraWindowsService):
        """Placeholder exported on non-Windows hosts for query registration."""
