"""Textual screens for the interactive Codira installer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static
from textual.worker import Worker, WorkerState

from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    InstallationProfile,
    InstallSource,
    RuntimeKind,
    RuntimeTarget,
)

if TYPE_CHECKING:
    from codira_installer.controller import InstallerController
    from codira_installer.models import ExecutionJournal


class InstallerScreen(Screen[None]):
    """Base screen that supplies deterministic keyboard navigation.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    heading = "Installer"
    detail = ""
    position = 0
    fields: ClassVar[tuple[tuple[str, str], ...]] = ()

    def compose(self) -> ComposeResult:
        """Compose the common screen heading and navigation controls.

        Parameters
        ----------
        None

        Yields
        ------
        textual.app.ComposeResult
            Widgets for one installer stage.
        """
        yield Header()
        with Container():
            yield Label(self.heading, classes="title")
            yield Static(self.detail, classes="detail")
            for field_id, placeholder in self.fields:
                yield Input(
                    value=self._field_value(field_id),
                    placeholder=placeholder,
                    id=field_id,
                )
            yield Static("Use Tab/Enter or the buttons to navigate.", classes="help")
            with Container(classes="actions"):
                if self.position:
                    yield Button("Back", id="back")
                yield Button("Next", id="next", variant="primary")
        yield Footer()

    def _field_value(self, field_id: str) -> str:
        """Return the current shared-request value for one editable field.

        Parameters
        ----------
        field_id : str
            Stable screen field identifier.

        Returns
        -------
        str
            Textual input value for the current installer choice.
        """
        request = cast("InstallerApp", self.app).controller.request
        values = {
            "source": str(request.source),
            "checkout": "" if request.checkout is None else str(request.checkout),
            "target": str(request.target.kind),
            "environment": ""
            if request.target.path is None
            else str(request.target.path),
            "runtime": str(request.runtime.kind),
            "runtime_root": ""
            if request.runtime.path is None
            else str(request.runtime.path),
            "profile": str(request.profile),
            "packages": ",".join(request.packages),
        }
        return values[field_id]


class SourceScreen(InstallerScreen):
    """Present the coordinated PyPI or local-checkout source stage."""

    heading = "1. Package source"
    detail = "Choose the coordinated PyPI release or the cloned Codira checkout."
    fields = (
        ("source", "pypi or local-checkout"),
        ("checkout", "cloned Codira root (required for local-checkout)"),
    )


class TargetScreen(InstallerScreen):
    """Present the standalone runtime destination and Advanced environment mode."""

    heading = "2. Runtime destination"
    detail = "Managed standalone is recommended; environment targets remain Advanced."
    position = 1
    fields = (
        ("runtime", "managed, current, existing, or new"),
        ("runtime_root", "managed, existing, or new runtime root"),
        ("target", "current, existing, or new"),
        ("environment", "environment root for existing or new"),
    )


class RepositoryScreen(InstallerScreen):
    """Present repository scope before optional repository operations."""

    heading = "3. Repository scope"
    detail = "Repository-scoped daemon operations remain optional and explicit."
    position = 2


class ProfileScreen(InstallerScreen):
    """Present Core-only, Recommended, and Full-official profile selection."""

    heading = "4. Installation profile"
    detail = "Profiles select only official first-party packages; deselected packages stay installed."
    position = 3
    fields = (("profile", "core-only, recommended, or full-official"),)


class FeatureScreen(InstallerScreen):
    """Present Advanced feature overrides for official packages only."""

    heading = "5. Features"
    detail = "Advanced selections are constrained to the generated official catalog."
    position = 4
    fields = (("packages", "comma-separated official package overrides"),)


class ConfigurationScreen(InstallerScreen):
    """Present user and repository configuration review."""

    heading = "6. Configuration"
    detail = (
        "Configuration is previewed and atomically replaced only after confirmation."
    )
    position = 5


class ModelScreen(InstallerScreen):
    """Present optional target-environment model provisioning."""

    heading = "7. Model provisioning"
    detail = "Model provisioning is optional, target-scoped, and idempotent."
    position = 6


class McpScreen(InstallerScreen):
    """Present optional idempotent MCP client configuration."""

    heading = "8. MCP integration"
    detail = (
        "Codex, Claude, and Cursor configuration merges preserve unrelated entries."
    )
    position = 7


class ServiceScreen(InstallerScreen):
    """Present optional repository-scoped daemon operations."""

    heading = "9. Services"
    detail = "Daemon configuration, installation, start, and status stay visible and privilege-free."
    position = 8


class ReviewScreen(InstallerScreen):
    """Validate the shared plan before allowing an apply request."""

    heading = "10. Review plan"
    detail = "Resolving the plan before execution…"
    position = 9

    def compose(self) -> ComposeResult:
        """Compose the review screen with an initially disabled Apply action.

        Parameters
        ----------
        None

        Yields
        ------
        textual.app.ComposeResult
            Review widgets and confirmation controls.
        """
        yield Header()
        with Container():
            yield Label(self.heading, classes="title")
            yield Static(self.detail, id="plan-summary")
            with Container(classes="actions"):
                yield Button("Back", id="back")
                yield Button("Apply", id="apply", variant="success", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        """Resolve the plan and enable Apply only after validation succeeds.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        try:
            installer = cast("InstallerApp", self.app)
            plan = installer.controller.resolve()
        except ValueError as error:
            self.query_one("#plan-summary", Static).update(f"Plan error: {error}")
            return
        self.query_one("#plan-summary", Static).update(
            f"{len(plan.steps)} steps; fingerprint {plan.fingerprint[:12]}"
        )
        self.query_one("#apply", Button).disabled = False


class ProgressScreen(InstallerScreen):
    """Show cooperative worker progress and allow a safe cancellation request."""

    heading = "11. Applying plan"
    detail = (
        "No command is interrupted mid-step; completed work is journaled for resume."
    )
    position = 10

    def compose(self) -> ComposeResult:
        """Compose worker progress and cancellation controls.

        Parameters
        ----------
        None

        Yields
        ------
        textual.app.ComposeResult
            Progress widgets.
        """
        yield Header()
        with Container():
            yield Label(self.heading, classes="title")
            yield Static(self.detail, id="progress-detail")
            yield Button("Cancel after current step", id="cancel", variant="warning")
        yield Footer()


class ResultScreen(InstallerScreen):
    """Present success, failure, cancellation, and resume outcomes."""

    heading = "12. Result"
    detail = ""
    position = 11

    def compose(self) -> ComposeResult:
        """Compose outcome text and an exit action.

        Parameters
        ----------
        None

        Yields
        ------
        textual.app.ComposeResult
            Result widgets.
        """
        yield Header()
        with Container():
            yield Label(self.heading, classes="title")
            installer = cast("InstallerApp", self.app)
            yield Static(installer.result_detail, id="result-detail")
            yield Button("Quit", id="quit", variant="primary")
        yield Footer()


class InstallerApp(App[None]):
    """Run the installer UI over the front-end-independent controller.

    Parameters
    ----------
    controller : codira_installer.controller.InstallerController
        Shared plan-resolution and execution session.
    """

    CSS = """
    .title { text-style: bold; margin-bottom: 1; }
    .detail, .help { margin-bottom: 1; }
    .actions { height: auto; layout: horizontal; }
    Button { margin-right: 1; }
    """
    STAGES: ClassVar[tuple[type[InstallerScreen], ...]] = (
        SourceScreen,
        TargetScreen,
        RepositoryScreen,
        ProfileScreen,
        FeatureScreen,
        ConfigurationScreen,
        ModelScreen,
        McpScreen,
        ServiceScreen,
        ReviewScreen,
    )

    def __init__(self, controller: InstallerController) -> None:
        """Initialize the app with an unresolved installer session.

        Parameters
        ----------
        controller : codira_installer.controller.InstallerController
            Shared session used by every UI action.

        Returns
        -------
        None
        """
        super().__init__()
        self.controller = controller
        self.cancel_requested = False
        self.result_detail = ""

    def on_mount(self) -> None:
        """Open the first installer screen after the application mounts.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        self.push_screen(SourceScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route navigation and execution controls without widget-side mutations.

        Parameters
        ----------
        event : textual.widgets.Button.Pressed
            User button event.

        Returns
        -------
        None
        """
        button_id = event.button.id
        if button_id == "next":
            self._commit_screen_choices()
            self._advance()
        elif button_id == "back":
            self.pop_screen()
        elif button_id == "apply":
            self.push_screen(ProgressScreen())
            self.run_worker(self._apply, thread=True, exclusive=True)
        elif button_id == "cancel":
            self.cancel_requested = True
            self.query_one("#progress-detail", Static).update(
                "Cancellation requested; the current atomic operation will finish first."
            )
        elif button_id == "quit":
            self.exit()

    def _advance(self) -> None:
        """Push the next requested installer screen.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        if isinstance(self.screen, InstallerScreen):
            position = self.screen.position
            if position < len(self.STAGES) - 1:
                self.push_screen(self.STAGES[position + 1]())

    def _commit_screen_choices(self) -> None:
        """Commit editable source, target, profile, and feature choices to the controller.

        Parameters
        ----------
        None

        Returns
        -------
        None
        """
        if not isinstance(self.screen, InstallerScreen):
            return
        request = self.controller.request
        screen = self.screen
        try:
            if isinstance(screen, SourceScreen):
                source = InstallSource(screen.query_one("#source", Input).value)
                checkout_text = screen.query_one("#checkout", Input).value.strip()
                checkout = Path(checkout_text) if checkout_text else request.checkout
                self.controller.update_request(
                    replace(request, source=source, checkout=checkout)
                )
            elif isinstance(screen, TargetScreen):
                kind = EnvironmentKind(screen.query_one("#target", Input).value)
                environment_text = screen.query_one("#environment", Input).value.strip()
                environment = Path(environment_text) if environment_text else None
                runtime_kind = RuntimeKind(screen.query_one("#runtime", Input).value)
                runtime_root_text = screen.query_one(
                    "#runtime_root", Input
                ).value.strip()
                runtime_root = Path(runtime_root_text) if runtime_root_text else None
                self.controller.update_request(
                    replace(
                        request,
                        target=EnvironmentTarget(kind, environment),
                        runtime=RuntimeTarget(runtime_kind, runtime_root),
                    )
                )
            elif isinstance(screen, ProfileScreen):
                profile = InstallationProfile(screen.query_one("#profile", Input).value)
                self.controller.update_request(replace(request, profile=profile))
            elif isinstance(screen, FeatureScreen):
                packages = tuple(
                    item.strip()
                    for item in screen.query_one("#packages", Input).value.split(",")
                    if item.strip()
                )
                self.controller.update_request(replace(request, packages=packages))
        except ValueError as error:
            self.notify(f"Invalid choice: {error}", severity="error")

    def _apply(self) -> ExecutionJournal:
        """Apply in a worker while checking cancellation only between steps.

        Parameters
        ----------
        None

        Returns
        -------
        codira_installer.models.ExecutionJournal
            Completed or partially completed journal.
        """
        return self.controller.apply(cancelled=lambda: self.cancel_requested)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Convert worker completion into a deterministic result screen.

        Parameters
        ----------
        event : textual.worker.Worker.StateChanged
            State transition emitted by the apply worker.

        Returns
        -------
        None
        """
        if event.worker.name != "_apply":
            return
        if event.worker.state is WorkerState.SUCCESS:
            journal = cast("ExecutionJournal", event.worker.result)
            self.result_detail = f"Completed {len(journal.results)} steps."
            self.push_screen(ResultScreen())
        elif event.worker.state is WorkerState.ERROR:
            error = event.worker.error
            self.result_detail = (
                f"Apply failed: {error}. Resume with the preserved journal at "
                f"{self.controller.journal_path}."
            )
            self.push_screen(ResultScreen())
        elif event.worker.state is WorkerState.CANCELLED:
            self.result_detail = (
                f"Cancellation preserved the journal at {self.controller.journal_path}."
            )
            self.push_screen(ResultScreen())
