"""Minimal Textual app for Tau coding sessions."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Static
from textual.worker import Worker

from tau_ai import OpenAICompatibleProvider, openai_compatible_config_from_env
from tau_coding.session import CodingSession, CodingSessionConfig, jsonl_session_storage
from tau_coding.session_manager import SessionManager
from tau_coding.tui.adapter import TuiEventAdapter
from tau_coding.tui.state import TuiState
from tau_coding.tui.widgets import SessionSidebar, TranscriptView


class TauTuiApp(App[None]):
    """Interactive Textual frontend for a ``CodingSession``."""

    TITLE = "Tau"
    CSS = """
    Screen {
        layout: vertical;
        background: #0f1117;
        color: #e6edf3;
    }

    Header {
        background: #161b22;
        color: #f0f6fc;
        dock: top;
    }

    Footer {
        background: #161b22;
        color: #8b949e;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #0f1117;
        color: #8b949e;
    }

    #workspace {
        height: 1fr;
    }

    #sidebar {
        width: 32;
        min-width: 28;
        padding: 1;
        background: #161b22;
        border-right: solid #30363d;
    }

    #main-pane {
        width: 1fr;
        padding: 1 1 0 1;
    }

    #transcript {
        height: 1fr;
        border: round #30363d;
        background: #0d1117;
        padding: 0 1;
    }

    #prompt {
        dock: bottom;
        background: #0d1117;
        color: #f0f6fc;
        border: round #238636;
        margin: 0 1 1 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, session: CodingSession) -> None:
        super().__init__()
        self.session = session
        self.state = TuiState()
        self.state.load_messages(session.messages)
        self.adapter = TuiEventAdapter(self.state)
        self._prompt_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        """Compose the TUI widgets."""
        yield Header()
        yield Static("Ready", id="status")
        with Horizontal(id="workspace"):
            yield SessionSidebar(id="sidebar")
            with Vertical(id="main-pane"):
                yield TranscriptView(id="transcript", wrap=True, highlight=True, markup=False)
                yield Input(placeholder="Ask Tau…", id="prompt")
        yield Footer()

    async def on_mount(self) -> None:
        """Focus the prompt when the app starts."""
        self.query_one(Input).focus()
        self._refresh()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle a submitted prompt or slash command."""
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        command = self.session.handle_command(text)
        if command.handled:
            if command.message:
                self.state.add_item("status", command.message)
            self._refresh()
            if command.exit_requested:
                self.exit()
            return

        if self.state.running:
            self.state.add_item("status", "Tau is already working. Press Escape to cancel.")
            self._refresh()
            return

        self.state.add_item("user", text)
        self._refresh()
        self._prompt_worker = self.run_worker(self._run_prompt(text), exclusive=True)

    async def _run_prompt(self, text: str) -> None:
        """Run one prompt and stream session events into the TUI state."""
        try:
            async for event in self.session.prompt(text):
                self.adapter.apply(event)
                self._refresh()
        except Exception as exc:  # noqa: BLE001 - surface unexpected worker errors in the TUI
            self.state.error = str(exc)
            self.state.add_item("error", f"Error: {exc}")
            self.state.running = False
            self._refresh()

    def action_cancel(self) -> None:
        """Cancel the active agent turn."""
        if self.state.running:
            self.session.cancel()
            self.state.add_item("status", "Cancellation requested.")
        else:
            self.state.add_item("status", "Nothing to cancel.")
        self._refresh()

    def _refresh(self) -> None:
        sidebar = self.query_one("#sidebar", SessionSidebar)
        sidebar.update_from_session(self.session)
        transcript = self.query_one("#transcript", TranscriptView)
        transcript.update_from_state(self.state)
        status = self.query_one("#status", Static)
        status.update("Working…" if self.state.running else "Ready")


async def run_tui_app(
    *,
    model: str,
    cwd: Path,
    session_id: str | None = None,
    new_session: bool = False,
    session_manager: SessionManager | None = None,
) -> None:
    """Create the default provider/session and run the Textual app."""
    if new_session and session_id is not None:
        raise RuntimeError("--resume and --new-session cannot be used together")

    provider = OpenAICompatibleProvider(openai_compatible_config_from_env())
    manager = session_manager or SessionManager()
    try:
        if session_id is not None:
            existing_record = manager.get_session(session_id)
            if existing_record is None:
                raise RuntimeError(f"Unknown session: {session_id}")
            record = existing_record
        else:
            record = manager.create_session(cwd=cwd, model=model)

        session = await CodingSession.load(
            CodingSessionConfig(
                provider=provider,
                model=record.model or model,
                cwd=record.cwd,
                storage=jsonl_session_storage(record.path),
                session_id=record.id,
                session_manager=manager,
            )
        )
        app = TauTuiApp(session)
        await app.run_async()
    finally:
        await provider.aclose()
