from pathlib import Path

import pytest

from tau_agent import AssistantMessage, UserMessage
from tau_agent.session import JsonlSessionStorage
from tau_ai import FakeProvider, ProviderResponseEndEvent
from tau_coding import CodingSession, CodingSessionConfig, TauResourcePaths


@pytest.mark.anyio
async def test_project_extension_registers_command_tool_guideline_and_input_hook(
    tmp_path: Path,
) -> None:
    extension_dir = tmp_path / ".tau" / "extensions"
    extension_dir.mkdir(parents=True)
    (extension_dir / "demo.py").write_text(
        '''
from tau_agent import AgentTool, AgentToolResult
from tau_coding.commands import CommandResult

async def run_tool(arguments, signal=None):
    return AgentToolResult(tool_call_id="", name="demo_tool", ok=True, content="tool ok")

def setup(tau):
    tau.register_prompt_guideline("Prefer concise answers.")
    tau.register_input_hook(lambda context, text: text.replace("before", "after"))
    tau.register_command(
        "demo",
        lambda context, args: CommandResult(handled=True, message=f"demo {args.strip()}"),
    )
    tau.register_tool(AgentTool(
        name="demo_tool",
        description="Demo tool",
        input_schema={"type": "object"},
        executor=run_tool,
    ))
''',
        encoding="utf-8",
    )
    provider = FakeProvider([[ProviderResponseEndEvent(message=AssistantMessage(content="ok"))]])
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=provider,
            model="fake",
            storage=JsonlSessionStorage(tmp_path / "session.jsonl"),
            cwd=tmp_path,
            resource_paths=TauResourcePaths(root=tmp_path / ".tau", cwd=tmp_path),
        )
    )

    assert "demo_tool" in {tool.name for tool in session.tools}
    assert "Prefer concise answers." in session.system_prompt
    assert session.handle_command("/demo works").message == "demo works"

    await _drain(session.prompt("before text"))

    assert session.messages[0] == UserMessage(content="after text")


@pytest.mark.anyio
async def test_extension_setup_failure_is_diagnostic(tmp_path: Path) -> None:
    extension_dir = tmp_path / ".tau" / "extensions"
    extension_dir.mkdir(parents=True)
    (extension_dir / "bad.py").write_text("def setup(tau):\n    raise RuntimeError('boom')\n")
    session = await CodingSession.load(
        CodingSessionConfig(
            provider=FakeProvider([]),
            model="fake",
            storage=JsonlSessionStorage(tmp_path / "session.jsonl"),
            cwd=tmp_path,
            resource_paths=TauResourcePaths(root=tmp_path / ".tau", cwd=tmp_path),
        )
    )

    diagnostics = session.extension_runtime.diagnostics
    assert len(diagnostics) == 1
    assert diagnostics[0].kind == "extension"
    assert "boom" in diagnostics[0].message


async def _drain(stream: object) -> None:
    async for _event in stream:  # type: ignore[attr-defined]
        pass
