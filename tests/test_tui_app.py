from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console

from tau_agent import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tau_coding.session_manager import CodingSessionRecord
from tau_coding.skills import Skill
from tau_coding.tools import create_coding_tools
from tau_coding.tui import app as tui_app
from tau_coding.tui.app import TauTuiApp
from tau_coding.tui.widgets import render_session_sidebar


class FakeSession:
    def __init__(self, messages=(), events=()) -> None:
        self.messages = tuple(messages)
        self.events = tuple(events)
        self.cwd = Path("/workspace/project")
        self.model = "fake-model"
        self.tools = tuple(create_coding_tools(cwd=self.cwd))
        self.skills = (Skill(name="review", path=self.cwd / "review.md", content="Review code"),)
        self.prompt_templates = ()

    async def prompt(self, text: str) -> AsyncIterator[AgentEvent]:
        for event in self.events:
            yield event


def test_session_sidebar_renders_session_metadata() -> None:
    console = Console(record=True, width=80)

    console.print(render_session_sidebar(FakeSession()))

    output = console.export_text()
    assert "session" in output
    assert "fake-model" in output
    assert "tools" in output
    assert "read" in output
    assert "skills" in output
    assert "review" in output


@pytest.mark.anyio
async def test_tui_app_mounts_sidebar_and_transcript() -> None:
    app = TauTuiApp(FakeSession())

    async with app.run_test():
        assert app.query_one("#sidebar") is not None
        assert app.query_one("#transcript") is not None
        assert app.query_one("#prompt") is not None


def test_tui_app_loads_restored_messages_into_display_state() -> None:
    app = TauTuiApp(
        FakeSession(
            messages=[
                UserMessage(content="Read the file"),
                AssistantMessage(
                    content="I'll inspect it.",
                    tool_calls=[
                        ToolCall(id="call-1", name="read", arguments={"path": "README.md"})
                    ],
                ),
                ToolResultMessage(
                    tool_call_id="call-1",
                    name="read",
                    content="README contents",
                    ok=True,
                ),
            ]
        )
    )

    assert [(item.role, item.text) for item in app.state.items] == [
        ("user", "Read the file"),
        ("assistant", "I'll inspect it."),
        ("tool", "→ read {'path': 'README.md'}"),
        ("tool", "✓ read\nREADME contents"),
    ]


@pytest.mark.anyio
async def test_tui_prompt_worker_refreshes_directly() -> None:
    app = TauTuiApp(FakeSession(events=[AgentStartEvent(), AgentEndEvent()]))
    refreshes = 0

    def fake_refresh() -> None:
        nonlocal refreshes
        refreshes += 1

    app._refresh = fake_refresh  # type: ignore[method-assign]

    await app._run_prompt("hello")

    assert refreshes == 2
    assert app.state.running is False


@pytest.mark.anyio
async def test_run_tui_app_creates_new_session_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    record = CodingSessionRecord(
        id="new-session",
        path=tmp_path / "new-session.jsonl",
        cwd=tmp_path,
        model="fake-model",
        title=None,
        created_at=1.0,
        updated_at=1.0,
    )

    class FakeProvider:
        async def aclose(self) -> None:
            calls.append("provider_closed")

    class FakeManager:
        def create_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            calls.append(f"create:{cwd}:{model}")
            return record

        def get_session(self, session_id: str) -> CodingSessionRecord | None:
            calls.append(f"get:{session_id}")
            return None

        def get_or_create_default_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            raise AssertionError("default session should not be opened implicitly")

    class FakeCodingSession:
        @classmethod
        async def load(cls, config: object) -> str:
            calls.append("load")
            return "session"

    class FakeApp:
        def __init__(self, session: str) -> None:
            assert session == "session"

        async def run_async(self) -> None:
            calls.append("run")

    monkeypatch.setattr(tui_app, "openai_compatible_config_from_env", lambda: object())
    monkeypatch.setattr(tui_app, "OpenAICompatibleProvider", lambda config: FakeProvider())
    monkeypatch.setattr(tui_app, "CodingSession", FakeCodingSession)
    monkeypatch.setattr(tui_app, "TauTuiApp", FakeApp)

    await tui_app.run_tui_app(model="fake-model", cwd=tmp_path, session_manager=FakeManager())

    assert calls == [f"create:{tmp_path}:fake-model", "load", "run", "provider_closed"]


@pytest.mark.anyio
async def test_run_tui_app_resumes_explicit_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    record = CodingSessionRecord(
        id="session-1",
        path=tmp_path / "session-1.jsonl",
        cwd=tmp_path,
        model="fake-model",
        title=None,
        created_at=1.0,
        updated_at=1.0,
    )

    class FakeProvider:
        async def aclose(self) -> None:
            calls.append("provider_closed")

    class FakeManager:
        def create_session(self, *, cwd: Path, model: str) -> CodingSessionRecord:
            raise AssertionError("explicit resume should not create a new session")

        def get_session(self, session_id: str) -> CodingSessionRecord | None:
            calls.append(f"get:{session_id}")
            return record

    class FakeCodingSession:
        @classmethod
        async def load(cls, config: object) -> str:
            calls.append("load")
            return "session"

    class FakeApp:
        def __init__(self, session: str) -> None:
            assert session == "session"

        async def run_async(self) -> None:
            calls.append("run")

    monkeypatch.setattr(tui_app, "openai_compatible_config_from_env", lambda: object())
    monkeypatch.setattr(tui_app, "OpenAICompatibleProvider", lambda config: FakeProvider())
    monkeypatch.setattr(tui_app, "CodingSession", FakeCodingSession)
    monkeypatch.setattr(tui_app, "TauTuiApp", FakeApp)

    await tui_app.run_tui_app(
        model="fake-model",
        cwd=tmp_path,
        session_id="session-1",
        session_manager=FakeManager(),
    )

    assert calls == ["get:session-1", "load", "run", "provider_closed"]
