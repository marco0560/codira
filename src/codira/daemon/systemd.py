"""Systemd user-service adapter for Codira's foreground daemon.

Responsibilities
----------------
- Render one repository-scoped user-service unit.
- Install and control the unit through ``systemctl --user``.
- Keep host-service effects behind one injectable command boundary.

Design principles
-----------------
The adapter manages no index state. Its unit invokes ``codira daemon run`` so
foreground watch and reconciliation semantics remain the single runtime path.

Architectural role
------------------
This module belongs to the daemon service-adapter layer for Linux systemd user
managers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from codira.daemon.service_spec import ServiceSpecification

SystemctlRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_UNIT_PREFIX = "codira-daemon"
SYSTEMCTL_EXE = shutil.which("systemctl") or "systemctl"


class SystemdServiceError(RuntimeError):
    """Report a failed systemd user-service operation.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances carry the failed systemctl operation diagnostic.
    """


@dataclass(frozen=True)
class SystemdServiceStatus:
    """Report one repository service's systemd activation state.

    Parameters
    ----------
    unit_name : str
        Repository-scoped systemd unit name.
    active : bool
        Whether ``systemctl --user is-active`` reports the unit active.

    Returns
    -------
    None
        Instances expose immutable service-manager status.
    """

    unit_name: str
    active: bool


def _default_unit_directory() -> Path:
    """Return the conventional systemd user-unit directory.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        XDG user configuration directory followed by ``systemd/user``.
    """
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base_directory = Path(config_home) if config_home else Path.home() / ".config"
    return base_directory / "systemd" / "user"


def _quote_unit_argument(value: str) -> str:
    """Quote one unit-file argument without allowing directive injection.

    Parameters
    ----------
    value : str
        One executable path, working directory, or command argument.

    Returns
    -------
    str
        Double-quoted systemd unit-file argument with control characters and
        backslashes escaped.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _run_systemctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one systemctl user-manager command without shell interpolation.

    Parameters
    ----------
    arguments : list[str]
        systemctl arguments following the mandatory ``--user`` scope.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed command result retained for service-operation handling.
    """
    return subprocess.run(
        [SYSTEMCTL_EXE, "--user", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


class SystemdUserService:
    """Manage one repository-scoped systemd user service.

    Parameters
    ----------
    root : pathlib.Path
        Repository root served by the foreground daemon command.
    executable : pathlib.Path | None, optional
        Absolute Codira console-script path. ``None`` uses the current command
        path, which is appropriate when invoked through the Codira CLI.
    unit_directory : pathlib.Path | None, optional
        User-unit directory override used by deterministic tests.
    run_systemctl : collections.abc.Callable[[list[str]], subprocess.CompletedProcess[str]], optional
        Host command boundary used for systemctl lifecycle actions.

    Returns
    -------
    None

    Notes
    -----
    The unit is repository-scoped by a digest of the canonical root, so one
    user can install independent daemon services for multiple repositories.
    """

    def __init__(
        self,
        root: Path,
        *,
        specification: ServiceSpecification | None = None,
        executable: Path | None = None,
        unit_directory: Path | None = None,
        run_systemctl: SystemctlRunner = _run_systemctl,
    ) -> None:
        """Initialize one repository-scoped systemd service adapter.

        Parameters
        ----------
        root : pathlib.Path
            Repository root served by the foreground daemon command.
        executable : pathlib.Path | None, optional
            Absolute Codira console-script path, defaulting to the active CLI.
        unit_directory : pathlib.Path | None, optional
            User-unit directory override used by deterministic tests.
        run_systemctl : collections.abc.Callable[[list[str]], subprocess.CompletedProcess[str]], optional
            Host command boundary used for systemctl lifecycle actions.

        Returns
        -------
        None
            The adapter retains only deterministic service identity and paths.
        """
        self._specification = specification or ServiceSpecification.indexing(root)
        self._root = self._specification.root
        self._executable = (executable or Path(sys.argv[0])).resolve()
        self._unit_directory = unit_directory or _default_unit_directory()
        self._run_systemctl = run_systemctl

    @property
    def unit_name(self) -> str:
        """Return the deterministic repository-scoped systemd unit name.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Stable user-unit filename for the canonical repository root.
        """
        prefix = (
            _UNIT_PREFIX
            if self._specification.kind == "daemon"
            else "codira-query-daemon"
        )
        return f"{prefix}-{self._specification.identity}.service"

    @property
    def unit_path(self) -> Path:
        """Return the user-unit file path for this repository service.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Unit file location under the configured user-unit directory.
        """
        return self._unit_directory / self.unit_name

    @property
    def identifier(self) -> str:
        """Return the service-manager identifier used in lifecycle messages.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Repository-scoped systemd unit name.
        """
        return self.unit_name

    def render_unit(self) -> str:
        """Render the complete systemd unit definition for this repository.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Deterministic UTF-8 unit-file content for foreground daemon mode.
        """
        arguments = [
            _quote_unit_argument(str(self._executable)),
            *self._specification.command[:-1],
            "--path",
            _quote_unit_argument(str(self._root)),
        ]
        if self._specification.kind == "query-daemon":
            arguments.extend(
                (
                    "--output-dir",
                    _quote_unit_argument(str(self._specification.output_root)),
                )
            )
        arguments.append(self._specification.command[-1])
        command = " ".join(arguments)
        return "\n".join(
            (
                "[Unit]",
                f"Description=Codira {self._specification.kind} for {self.unit_name}",
                "After=default.target",
                "",
                "[Service]",
                "Type=simple",
                f"WorkingDirectory={_quote_unit_argument(str(self._root))}",
                f"ExecStart={command}",
                "Restart=on-failure",
                "RestartSec=5",
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            )
        )

    def install(self) -> Path:
        """Write, reload, and enable this repository's user-service unit.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Installed user-unit path.

        Raises
        ------
        SystemdServiceError
            If systemctl cannot reload or enable the written unit.
        """
        self.unit_path.parent.mkdir(parents=True, exist_ok=True)
        self.unit_path.write_text(self.render_unit(), encoding="utf-8")
        self._require_success(["daemon-reload"])
        self._require_success(["enable", self.unit_name])
        return self.unit_path

    def uninstall(self) -> None:
        """Disable, remove, and reload this repository's user-service unit.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The unit is removed when present and systemd is reloaded.

        Notes
        -----
        Disable failures are ignored to make cleanup idempotent when a unit was
        already removed outside Codira.
        """
        self._run_systemctl(["disable", "--now", self.unit_name])
        self.unit_path.unlink(missing_ok=True)
        self._require_success(["daemon-reload"])

    def start(self) -> None:
        """Start this repository's installed systemd user service.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The command returns after systemctl accepts the start request.

        Raises
        ------
        SystemdServiceError
            If systemctl rejects the start request.
        """
        self._require_success(["start", self.unit_name])

    def stop(self) -> None:
        """Stop this repository's installed systemd user service.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The command returns after systemctl accepts the stop request.

        Raises
        ------
        SystemdServiceError
            If systemctl rejects the stop request.
        """
        self._require_success(["stop", self.unit_name])

    def status(self) -> SystemdServiceStatus:
        """Inspect whether this repository's user service is active.

        Parameters
        ----------
        None

        Returns
        -------
        SystemdServiceStatus
            Immutable active/inactive result for the repository unit.
        """
        result = self._run_systemctl(["is-active", "--quiet", self.unit_name])
        return SystemdServiceStatus(
            unit_name=self.unit_name,
            active=result.returncode == 0,
        )

    def _require_success(self, arguments: list[str]) -> None:
        """Run one required systemctl operation or raise a stable error.

        Parameters
        ----------
        arguments : list[str]
            systemctl arguments for an operation that must succeed.

        Returns
        -------
        None
            The operation completed successfully.

        Raises
        ------
        SystemdServiceError
            If systemctl exits unsuccessfully or cannot be invoked.
        """
        try:
            result = self._run_systemctl(arguments)
        except FileNotFoundError as error:
            msg = "systemctl is not available for the current user session"
            raise SystemdServiceError(msg) from error
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            msg = f"systemctl --user {' '.join(arguments)} failed"
            if detail:
                msg = f"{msg}: {detail}"
            raise SystemdServiceError(msg)


class QueryDaemonSystemdUserService(SystemdUserService):
    """Manage a systemd user unit for one warm query-daemon identity."""

    def __init__(self, root: Path, output_root: Path, **kwargs: object) -> None:
        """Initialize a query-daemon unit with fixed repository/output paths.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        output_root : pathlib.Path
            Effective output root.
        **kwargs : object
            Existing systemd adapter keyword arguments.

        Returns
        -------
        None
        """
        super().__init__(
            root,
            specification=ServiceSpecification.query(root, output_root),
            **kwargs,  # type: ignore[arg-type]
        )
