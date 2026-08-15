"""Launchd user-agent adapter for Codira's foreground daemon.

Responsibilities
----------------
- Render repository-scoped macOS LaunchAgent property lists.
- Install and control agents through ``launchctl`` in a GUI user domain.
- Keep host launchd effects behind one injectable command boundary.

Design principles
-----------------
The adapter manages no index state. Its agent invokes ``codira daemon run`` so
foreground watch and reconciliation semantics remain the single runtime path.

Architectural role
------------------
This module belongs to the daemon service-adapter layer for macOS launchd user
agents.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codira.daemon.service_spec import ServiceSpecification

LaunchctlRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_LABEL_PREFIX = "io.codira.daemon"
LAUNCHCTL_EXE = shutil.which("launchctl") or "launchctl"


class LaunchdServiceError(RuntimeError):
    """Report a failed launchd user-agent operation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the failed launchctl operation diagnostic.
    """


@dataclass(frozen=True)
class LaunchdServiceStatus:
    """Report one repository agent's launchd activation state.

    Parameters
    ----------
    label : str
        Repository-scoped launchd agent label.
    active : bool
        Whether ``launchctl print`` reports the agent loaded in the GUI domain.

    Returns
    -------
    None
        Instances expose immutable service-manager status.
    """

    label: str
    active: bool


def _default_agent_directory() -> Path:
    """Return the conventional per-user LaunchAgents directory.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        Current user's ``~/Library/LaunchAgents`` directory.
    """
    return Path.home() / "Library" / "LaunchAgents"


def _run_launchctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one launchctl command without shell interpolation.

    Parameters
    ----------
    arguments : list[str]
        launchctl arguments for one GUI-domain lifecycle operation.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed command result retained for service-operation handling.
    """
    return subprocess.run(
        [LAUNCHCTL_EXE, *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _current_uid() -> int:
    """Return the current operating-system user identifier.

    Parameters
    ----------
    None

    Returns
    -------
    int
        UID used to address the current user's launchd GUI domain.

    Raises
    ------
    OSError
        If the platform cannot provide a current user identifier.
    """
    try:
        return os.getuid()
    except AttributeError as error:
        msg = "launchd user agents require a POSIX user identifier"
        raise OSError(msg) from error


class LaunchdUserAgent:
    """Manage one repository-scoped launchd user agent.

    Parameters
    ----------
    root : pathlib.Path
        Repository root served by the foreground daemon command.
    executable : pathlib.Path | None, optional
        Absolute Codira console-script path. ``None`` uses the active command.
    agent_directory : pathlib.Path | None, optional
        LaunchAgents directory override used by deterministic tests.
    uid : int | None, optional
        GUI user identifier override used by deterministic tests.
    run_launchctl : collections.abc.Callable[[list[str]], subprocess.CompletedProcess[str]], optional
        Host command boundary used for launchctl lifecycle actions.

    Returns
    -------
    None

    Notes
    -----
    The agent label is repository-scoped by a digest of the canonical root, so
    one user can install independent automatic-indexing agents for many roots.
    """

    def __init__(  # noqa: PLR0913
        self,
        root: Path,
        *,
        specification: ServiceSpecification | None = None,
        executable: Path | None = None,
        agent_directory: Path | None = None,
        uid: int | None = None,
        run_launchctl: LaunchctlRunner = _run_launchctl,
    ) -> None:
        """Initialize one repository-scoped launchd user-agent adapter.

        Parameters
        ----------
        root : pathlib.Path
            Repository root served by the foreground daemon command.
        executable : pathlib.Path | None, optional
            Absolute Codira console-script path, defaulting to the active CLI.
        agent_directory : pathlib.Path | None, optional
            LaunchAgents directory override used by deterministic tests.
        uid : int | None, optional
            GUI user identifier override used by deterministic tests.
        run_launchctl : collections.abc.Callable[[list[str]], subprocess.CompletedProcess[str]], optional
            Host command boundary used for launchctl lifecycle actions.

        Returns
        -------
        None
            The adapter retains only deterministic agent identity and paths.
        """
        self._specification = specification or ServiceSpecification.indexing(root)
        self._root = self._specification.root
        self._executable = (executable or Path(sys.argv[0])).resolve()
        self._agent_directory = agent_directory or _default_agent_directory()
        self._uid = uid if uid is not None else _current_uid()
        self._run_launchctl = run_launchctl

    @property
    def label(self) -> str:
        """Return the deterministic repository-scoped launchd agent label.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Stable LaunchAgent label for the canonical repository root.
        """
        prefix = (
            _LABEL_PREFIX
            if self._specification.kind == "daemon"
            else "io.codira.query-daemon"
        )
        return f"{prefix}.{self._specification.identity}"

    @property
    def plist_path(self) -> Path:
        """Return the LaunchAgent property-list path for this repository.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Agent file location under the configured LaunchAgents directory.
        """
        return self._agent_directory / f"{self.label}.plist"

    @property
    def identifier(self) -> str:
        """Return the service-manager identifier used in lifecycle messages.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Repository-scoped launchd agent label.
        """
        return self.label

    @property
    def domain(self) -> str:
        """Return this user's launchd GUI domain target.

        Parameters
        ----------
        None

        Returns
        -------
        str
            ``gui/<uid>`` domain used for per-user launchctl operations.
        """
        return f"gui/{self._uid}"

    @property
    def target(self) -> str:
        """Return the fully qualified launchd service target.

        Parameters
        ----------
        None

        Returns
        -------
        str
            ``gui/<uid>/<label>`` service target for lifecycle operations.
        """
        return f"{self.domain}/{self.label}"

    def render_plist(self) -> bytes:
        """Render the complete XML LaunchAgent property list.

        Parameters
        ----------
        None

        Returns
        -------
        bytes
            Deterministic XML plist content for foreground daemon mode.
        """
        arguments = [
            str(self._executable),
            *self._specification.command[:-1],
            *self._specification.startup_arguments(),
        ]
        arguments.append(self._specification.command[-1])
        return plistlib.dumps(
            {
                "KeepAlive": True,
                "Label": self.label,
                "ProgramArguments": arguments,
                "RunAtLoad": True,
                "WorkingDirectory": str(self._root),
            },
            fmt=plistlib.FMT_XML,
            sort_keys=True,
        )

    def install(self) -> Path:
        """Write, reload, and bootstrap this repository's user agent.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Installed LaunchAgent property-list path.

        Raises
        ------
        LaunchdServiceError
            If launchctl cannot bootstrap the written agent.
        """
        self.plist_path.parent.mkdir(parents=True, exist_ok=True)
        self.plist_path.write_bytes(self.render_plist())
        self._run_launchctl(["bootout", self.target])
        self._require_success(["bootstrap", self.domain, str(self.plist_path)])
        self._specification.write_definition()
        return self.plist_path

    def uninstall(self) -> None:
        """Boot out and remove this repository's LaunchAgent property list.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The agent is removed when present.

        Notes
        -----
        Bootout failures are ignored to make cleanup idempotent when an agent
        was already removed outside Codira.
        """
        self._run_launchctl(["bootout", self.target])
        self.plist_path.unlink(missing_ok=True)
        self._specification.remove_definition()

    def start(self) -> None:
        """Start or restart this repository's installed launchd user agent.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The agent is bootstrapped when absent or kickstarted when present.

        Raises
        ------
        LaunchdServiceError
            If launchctl rejects the start request.
        """
        self._specification.require_current_definition()
        if self.status().active:
            self._require_success(["kickstart", "-k", self.target])
        else:
            self._require_success(["bootstrap", self.domain, str(self.plist_path)])

    def stop(self) -> None:
        """Boot out this repository's launchd agent for this login session.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The agent is unloaded while its installed property list remains.
        """
        self._run_launchctl(["bootout", self.target])

    def status(self) -> LaunchdServiceStatus:
        """Inspect whether this repository's user agent is loaded.

        Parameters
        ----------
        None

        Returns
        -------
        LaunchdServiceStatus
            Immutable active/inactive result for the repository agent.
        """
        self._specification.require_current_definition()
        result = self._run_launchctl(["print", self.target])
        return LaunchdServiceStatus(label=self.label, active=result.returncode == 0)

    def _require_success(self, arguments: list[str]) -> None:
        """Run one required launchctl operation or raise a stable error.

        Parameters
        ----------
        arguments : list[str]
            launchctl arguments for an operation that must succeed.

        Returns
        -------
        None
            The operation completed successfully.

        Raises
        ------
        LaunchdServiceError
            If launchctl exits unsuccessfully or cannot be invoked.
        """
        try:
            result = self._run_launchctl(arguments)
        except FileNotFoundError as error:
            msg = "launchctl is not available for the current user session"
            raise LaunchdServiceError(msg) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            msg = f"launchctl {' '.join(arguments)} failed"
            if detail:
                msg = f"{msg}: {detail}"
            raise LaunchdServiceError(msg)


class QueryDaemonLaunchdUserAgent(LaunchdUserAgent):
    """Manage a launchd user agent for one warm query-daemon identity."""

    def __init__(
        self,
        root: Path,
        output_root: Path,
        *,
        specification: ServiceSpecification | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize a query-daemon agent with fixed repository/output paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        output_root : pathlib.Path
            Effective output root.
        specification : codira.daemon.service_spec.ServiceSpecification | None, optional
            Fixed direct-path or workspace service definition.
        **kwargs : object
            Existing launchd adapter keyword arguments.

        Returns
        -------
        None
        """
        super().__init__(
            root,
            specification=specification
            or ServiceSpecification.query(root, output_root),
            **kwargs,  # type: ignore[arg-type]
        )
