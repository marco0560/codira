"""Tests for the repository-scoped Windows SCM daemon adapter.

Responsibilities
----------------
- Verify deterministic SCM service identity and root persistence.
- Exercise lifecycle calls through injected pywin32 API fakes.
- Avoid importing pywin32 or creating host SCM services on non-Windows tests.

Design principles
-----------------
Tests model only the pywin32 calls used by the adapter, keeping service-manager
behavior deterministic without a Windows host.

Architectural role
------------------
This module belongs to the daemon service-adapter verification layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.daemon.service_spec import ServiceSpecification
from codira.daemon.windows import WindowsScmApi, WindowsScmService

if TYPE_CHECKING:
    from pathlib import Path


class _FakeServiceUtil:
    """Record pywin32 service utility calls for deterministic tests.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances retain lifecycle and custom-option requests.
    """

    def __init__(self, status: tuple[object, ...]) -> None:
        """Initialize a fake SCM state tuple and call recorder.

        Parameters
        ----------
        status : tuple[object, ...]
            QueryServiceStatus result returned by this fake.

        Returns
        -------
        None
            The fake starts with no recorded calls.
        """
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self._status = status

    def InstallService(
        self,
        python_class_string: str,
        service_name: str,
        display_name: str,
        **kwargs: object,
    ) -> None:
        """Record one SCM installation request.

        Parameters
        ----------
        python_class_string : str
            ServiceFramework class import path.
        service_name : str
            SCM service identity.
        display_name : str
            Human-readable SCM display name.
        **kwargs : object
            pywin32 installation controls.

        Returns
        -------
        None
            The installation request is recorded.
        """
        self.calls.append(
            ("install", (python_class_string, service_name, display_name), kwargs)
        )

    def GetServiceCustomOption(
        self,
        service_name: object,
        option: str,
        default_value: object = None,
    ) -> object:
        """Return a default value for unused service-host configuration reads.

        Parameters
        ----------
        service_name : object
            Service identity ignored by this adapter-level fake.
        option : str
            Service option ignored by this adapter-level fake.
        default_value : object, optional
            Value returned because this fake does not host a Windows service.

        Returns
        -------
        object
            Configured default value.
        """
        del service_name, option
        return default_value

    def SetServiceCustomOption(
        self,
        service_name: str,
        option: str,
        value: str,
    ) -> None:
        """Record one persisted service option.

        Parameters
        ----------
        service_name : str
            SCM service identity.
        option : str
            Service parameter name.
        value : str
            Persisted service parameter value.

        Returns
        -------
        None
            The option request is recorded.
        """
        self.calls.append(("set-option", (service_name, option, value), {}))

    def RemoveService(self, service_name: str) -> None:
        """Record one SCM removal request.

        Parameters
        ----------
        service_name : str
            SCM service identity.

        Returns
        -------
        None
            The removal request is recorded.
        """
        self.calls.append(("remove", (service_name,), {}))

    def StartService(self, service_name: str) -> None:
        """Record one SCM start request.

        Parameters
        ----------
        service_name : str
            SCM service identity.

        Returns
        -------
        None
            The start request is recorded.
        """
        self.calls.append(("start", (service_name,), {}))

    def StopService(self, service_name: str) -> None:
        """Record one SCM stop request.

        Parameters
        ----------
        service_name : str
            SCM service identity.

        Returns
        -------
        None
            The stop request is recorded.
        """
        self.calls.append(("stop", (service_name,), {}))

    def QueryServiceStatus(self, service_name: str) -> tuple[object, ...]:
        """Record one SCM status request and return the configured result.

        Parameters
        ----------
        service_name : str
            SCM service identity.

        Returns
        -------
        tuple[object, ...]
            Configured pywin32 service status tuple.
        """
        self.calls.append(("status", (service_name,), {}))
        return self._status


class _FakeWin32Service:
    """Supply pywin32 service constants used by the SCM adapter.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances expose deterministic SCM state constants.
    """

    SERVICE_AUTO_START = 2
    SERVICE_RUNNING = 4
    SERVICE_STOP_PENDING = 3


def test_windows_scm_service_persists_repository_root_and_lifecycle(
    tmp_path: Path,
) -> None:
    """Install and control one repository service through fake pywin32 APIs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts installation persists the canonical root and lifecycle
        methods use a stable repository-scoped service identity.
    """
    root = tmp_path / "project"
    root.mkdir()
    serviceutil = _FakeServiceUtil((0, _FakeWin32Service.SERVICE_RUNNING))
    service = WindowsScmService(
        root,
        api=WindowsScmApi(serviceutil=serviceutil, service=_FakeWin32Service()),
    )
    other_service = WindowsScmService(
        tmp_path / "other-project",
        api=WindowsScmApi(serviceutil=serviceutil, service=_FakeWin32Service()),
    )

    installed_root = service.install()
    service.start()
    service.stop()
    assert service.status().active is True
    service.uninstall()

    assert installed_root == root.resolve()
    assert service.service_name.startswith("CodiraDaemon_")
    assert service.service_name != other_service.service_name
    assert serviceutil.calls == [
        (
            "install",
            (
                "codira.daemon.windows.CodiraWindowsService",
                service.service_name,
                f"Codira automatic indexing ({root.name})",
            ),
            {
                "startType": _FakeWin32Service.SERVICE_AUTO_START,
                "description": "Repository-scoped Codira automatic indexing daemon.",
            },
        ),
        ("set-option", (service.service_name, "root", str(root.resolve())), {}),
        (
            "set-option",
            (service.service_name, "output_root", str(root.resolve())),
            {},
        ),
        ("start", (service.service_name,), {}),
        ("stop", (service.service_name,), {}),
        ("status", (service.service_name,), {}),
        ("remove", (service.service_name,), {}),
    ]


def test_windows_scm_service_reports_nonrunning_status(tmp_path: Path) -> None:
    """Map a non-running SCM state to inactive daemon service status.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.

    Returns
    -------
    None
        The test asserts SCM status is readable without starting a service.
    """
    serviceutil = _FakeServiceUtil((0, 1))
    service = WindowsScmService(
        tmp_path,
        api=WindowsScmApi(serviceutil=serviceutil, service=_FakeWin32Service()),
    )

    status = service.status()

    assert status.active is False
    assert status.service_name == service.service_name


def test_windows_workspace_service_persists_drift_guard(tmp_path: Path) -> None:
    """Persist workspace identity before the SCM service is installed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and state roots.

    Returns
    -------
    None
        The test asserts Windows hosts receive the workspace drift guard.
    """
    root = tmp_path / "repository"
    root.mkdir()
    specification = ServiceSpecification.workspace(
        kind="daemon",
        root=root,
        output_root=tmp_path / "state",
        workspace_name="sample",
        descriptor_fingerprint="a" * 64,
        effective_config={"daemon": {"enabled": True}},
    )
    serviceutil = _FakeServiceUtil((0, _FakeWin32Service.SERVICE_RUNNING))
    service = WindowsScmService(
        root,
        specification=specification,
        api=WindowsScmApi(serviceutil=serviceutil, service=_FakeWin32Service()),
    )

    service.install()

    assert ("set-option", (service.service_name, "workspace", "sample"), {}) in (
        serviceutil.calls
    )
    assert (
        "set-option",
        (service.service_name, "workspace_fingerprint", "a" * 64),
        {},
    ) in serviceutil.calls
