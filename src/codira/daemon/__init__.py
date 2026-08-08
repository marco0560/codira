"""Public runtime declarations for Codira's optional indexing daemon.

The scheduler is watcher- and service-manager-neutral. Later slices adapt it
to filesystem notifications and platform service managers.
"""

from codira.daemon.launchd import (
    LaunchdServiceError,
    LaunchdServiceStatus,
    LaunchdUserAgent,
    QueryDaemonLaunchdUserAgent,
)
from codira.daemon.models import DaemonState, DaemonStatus
from codira.daemon.runtime import build_watch_filter, run_foreground_daemon
from codira.daemon.scheduler import DaemonScheduler
from codira.daemon.status_store import DaemonStatusStore
from codira.daemon.systemd import (
    QueryDaemonSystemdUserService,
    SystemdServiceError,
    SystemdServiceStatus,
    SystemdUserService,
)
from codira.daemon.windows import (
    QueryDaemonWindowsScmService,
    WindowsScmService,
    WindowsScmServiceError,
    WindowsScmServiceStatus,
)

__all__ = [
    "DaemonScheduler",
    "DaemonState",
    "DaemonStatus",
    "DaemonStatusStore",
    "LaunchdServiceError",
    "LaunchdServiceStatus",
    "LaunchdUserAgent",
    "QueryDaemonLaunchdUserAgent",
    "SystemdServiceError",
    "SystemdServiceStatus",
    "SystemdUserService",
    "QueryDaemonSystemdUserService",
    "WindowsScmService",
    "QueryDaemonWindowsScmService",
    "WindowsScmServiceError",
    "WindowsScmServiceStatus",
    "build_watch_filter",
    "run_foreground_daemon",
]
