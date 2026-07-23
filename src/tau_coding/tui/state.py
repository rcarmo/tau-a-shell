"""Display state for Tau's Textual TUI."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentToolResult, ToolCall
from tau_agent.types import JSONValue
from tau_coding.skills import Skill, parse_skill_invocation

ChatItemRole = Literal[
    "user",
    "assistant",
    "tool",
    "error",
    "status",
    "thinking",
    "skill",
    "branch_summary",
    "compaction_summary",
]
TOOL_RESULT_PREVIEW_LINES = 8
TOOL_PATCH_PREVIEW_LINES = 32
TOOL_RESULT_PREVIEW_CHARS = 2_000
TERMINAL_COMMAND_OUTPUT_PREVIEW_LINES = 120


@dataclass(slots=True)
class ChatItem:
    """One rendered item in the TUI transcript."""

    role: ChatItemRole
    text: str
    tool_call_id: str | None = None
    tool_result_text: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, JSONValue] | None = None
    custom_type: str | None = None
    details: dict[str, JSONValue] | None = None
    always_show_tool_result: bool = False


@dataclass(slots=True)
class TuiState:
    """Mutable display state for the interactive TUI."""

    items: list[ChatItem] = field(default_factory=list)
    assistant_buffer: str = ""
    running: bool = False
    error: str | None = None
    show_tool_results: bool = False
    show_thinking: bool = False
    queued_steering: tuple[str, ...] = ()
    queued_follow_up: tuple[str, ...] = ()
    skills: tuple[Skill, ...] = ()
    custom_renderer: Callable[[str, str, dict[str, JSONValue] | None], str | None] | None = None
    tool_call_renderer: Callable[[str, dict[str, JSONValue]], str | None] | None = None
    tool_result_renderer: Callable[[AgentToolResult], str | None] | None = None

    def add_item(
        self,
        role: ChatItemRole,
        text: str,
        *,
        tool_call_id: str | None = None,
        tool_result_text: str | None = None,
        always_show_tool_result: bool = False,
        custom_type: str | None = None,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        """Append a transcript item."""
        if not text.strip() and tool_result_text is None:
            return
        self.items.append(
            ChatItem(
                role=role,
                text=text,
                tool_call_id=tool_call_id,
                tool_result_text=tool_result_text,
                custom_type=custom_type,
                details=details,
                always_show_tool_result=always_show_tool_result,
            )
        )

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Append a collapsed tool-call item."""
        if not tool_call.name.strip():
            return
        skill_name = self._read_skill_name(tool_call)
        if skill_name is not None:
            self.add_item(
                "skill",
                f"Loading skill: {skill_name}",
                tool_call_id=tool_call.id,
            )
            return
        rendered = None
        if self.tool_call_renderer is not None:
            rendered = self.tool_call_renderer(tool_call.name, tool_call.arguments)
        self.add_item(
            "tool",
            rendered or format_tool_call_block(tool_call),
            tool_call_id=tool_call.id,
        )
        self.items[-1].tool_name = tool_call.name
        self.items[-1].tool_arguments = tool_call.arguments

    def add_user_message(
        self,
        content: str,
        *,
        custom_type: str | None = None,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        """Append a user-authored message, compacting skill and summary messages."""
        if custom_type is not None:
            rendered = None
            if self.custom_renderer is not None:
                rendered = self.custom_renderer(custom_type, content, details)
            self.add_item(
                "user",
                rendered or content,
                custom_type=custom_type,
                details=details,
            )
            return

        branch_summary = _parse_branch_summary_message(content)
        if branch_summary is not None:
            self.add_item(
                "branch_summary",
                "Branch summary (Ctrl+O to expand)",
                tool_result_text=branch_summary,
            )
            return

        compaction_summary = _parse_compaction_summary_message(content)
        if compaction_summary is not None:
            self.add_item(
                "compaction_summary",
                "Compaction summary (Ctrl+O to expand)",
                tool_result_text=compaction_summary,
            )
            return

        skill_invocation = parse_skill_invocation(content)
        if skill_invocation is None:
            self.add_item("user", content)
            return
        self.add_item("skill", f"Using skill: {skill_invocation.name}")
        if skill_invocation.additional_instructions:
            self.add_item("user", skill_invocation.additional_instructions)

    def add_thinking_delta(self, delta: str) -> None:
        """Append a visible thinking/reasoning fragment to the current block."""
        if not delta.strip():
            return
        if self.items and self.items[-1].role == "thinking":
            self.items[-1].text += delta
            return
        self.add_item("thinking", delta)

    def record_tool_result(self, result: AgentToolResult) -> None:
        """Attach a tool result to its matching call, or append an orphan result."""
        if _is_blank_unknown_tool_result(result):
            return
        result_text = None
        if self.tool_result_renderer is not None:
            result_text = self.tool_result_renderer(result)
        if result_text is None:
            result_text = format_tool_result_block(
                name=result.name,
                ok=result.ok,
                content=result.content,
                data=result.data,
            )
        for item in reversed(self.items):
            if item.role in {"tool", "skill"} and item.tool_call_id == result.tool_call_id:
                item.tool_result_text = result_text
                return
        self.add_item(
            "tool",
            format_tool_result_summary(name=result.name, ok=result.ok),
            tool_call_id=result.tool_call_id,
            tool_result_text=result_text,
        )

    def toggle_tool_results(self) -> bool:
        """Toggle expanded display for tool results and return the new state."""
        self.show_tool_results = not self.show_tool_results
        return self.show_tool_results

    def toggle_thinking(self) -> bool:
        """Toggle thinking-token display and return the new state."""
        self.show_thinking = not self.show_thinking
        return self.show_thinking

    def update_queue(self, *, steering: tuple[str, ...], follow_up: tuple[str, ...]) -> None:
        """Replace visible queued-message state."""
        self.queued_steering = steering
        self.queued_follow_up = follow_up

    @property
    def queued_message_count(self) -> int:
        """Return the total number of pending queued messages."""
        return len(self.queued_steering) + len(self.queued_follow_up)

    def clear(self) -> None:
        """Clear visible transcript state without modifying durable session history."""
        self.items.clear()
        self.assistant_buffer = ""
        self.error = None

    def set_skills(self, skills: Iterable[Skill]) -> None:
        """Replace loaded skill metadata used for presentation-only path matching."""
        self.skills = tuple(skills)

    def load_messages(self, messages: Iterable[AgentMessage]) -> None:
        """Populate the transcript from restored session messages."""
        for message in messages:
            if message.role == "user":
                self.add_user_message(message.content)
            elif message.role == "assistant":
                if message.content:
                    self.add_item("assistant", message.content)
                for tool_call in message.tool_calls:
                    self.add_tool_call(tool_call)
            elif message.role == "tool":
                self.record_tool_result(
                    AgentToolResult(
                        tool_call_id=message.tool_call_id,
                        name=message.name,
                        ok=message.ok,
                        content=message.content,
                        data=message.data,
                        details=message.details,
                        error=message.error,
                    )
                )

    def _read_skill_name(self, tool_call: ToolCall) -> str | None:
        if tool_call.name != "read":
            return None
        path = _string_argument(tool_call.arguments, "path")
        if path is None:
            return None
        read_path = _normalized_path(path)
        for skill in self.skills:
            if _normalized_path(skill.path) == read_path:
                return skill.name
        return None


def _is_blank_unknown_tool_result(result: AgentToolResult) -> bool:
    return (
        not result.name.strip()
        and not result.ok
        and result.content.strip() == "Unknown tool:"
    )


def _parse_branch_summary_message(content: str) -> str | None:
    prefix = (
        "The following is a summary of a branch that this conversation "
        "came back from:\n<summary>\n"
    )
    suffix = "\n</summary>"
    if content.startswith(prefix) and content.endswith(suffix):
        return content.removeprefix(prefix).removesuffix(suffix)
    return None


def _parse_compaction_summary_message(content: str) -> str | None:
    prefix = "Previous conversation summary:\n"
    if content.startswith(prefix):
        return content.removeprefix(prefix)
    return None


def format_tool_call_block(tool_call: ToolCall) -> str:
    """Format a collapsed tool call for live and restored transcript blocks."""
    if not tool_call.name.strip():
        return ""
    invocation = format_tool_call_invocation(tool_call)
    if tool_call.name in {"sh", "bash"}:
        return invocation
    return f"→ {invocation}"


def format_tool_call_invocation(tool_call: ToolCall) -> str:
    """Format a tool call as a terse human-readable invocation."""
    arguments = tool_call.arguments
    if tool_call.name == "read":
        path = _string_argument(arguments, "path")
        if path is None:
            return _fallback_tool_call_invocation(tool_call)
        return f"read {path}{_read_line_suffix(arguments)}"
    if tool_call.name == "edit":
        path = _string_argument(arguments, "path")
        if path is None:
            return _fallback_tool_call_invocation(tool_call)
        return f"edit {path}"
    if tool_call.name == "write":
        path = _string_argument(arguments, "path")
        if path is None:
            return _fallback_tool_call_invocation(tool_call)
        return f"write {path}"
    if tool_call.name == "python":
        code = _string_argument(arguments, "code")
        if code is None:
            return _fallback_tool_call_invocation(tool_call)
        first_line = code.strip().splitlines()[0] if code.strip() else ""
        suffix = "…" if len(code.strip().splitlines()) > 1 or len(first_line) > 60 else ""
        return f"python -c {first_line[:60]!r}{suffix}"
    if tool_call.name in {"sh", "bash"}:
        command = _string_argument(arguments, "command")
        if command is None:
            return _fallback_tool_call_invocation(tool_call)
        timeout = _number_argument(arguments, "timeout")
        suffix = f" (timeout {timeout:g}s)" if timeout is not None else ""
        return f"$ {command}{suffix}"
    return _fallback_tool_call_invocation(tool_call)


def _read_line_suffix(arguments: dict[str, JSONValue]) -> str:
    offset = _int_argument(arguments, "offset")
    limit = _int_argument(arguments, "limit")
    if offset is None and limit is None:
        return ""
    start = 1 if offset is None else max(1, offset)
    if limit is None:
        return f":{start}-"
    return f":{start}-{start + max(1, limit) - 1}"


def _fallback_tool_call_invocation(tool_call: ToolCall) -> str:
    if not tool_call.name.strip():
        return ""
    display_arguments = _display_tool_arguments(tool_call.arguments)
    if display_arguments:
        return f"{tool_call.name} {display_arguments}"
    return tool_call.name


def _display_tool_arguments(arguments: dict[str, JSONValue]) -> str:
    """Return a compact human-facing argument summary for generic tool calls."""
    parts: list[str] = []
    for key, value in arguments.items():
        if key == "_raw_arguments":
            continue
        parts.append(f"{key}={_display_tool_argument_value(value)}")
        if len(parts) >= 3:
            remaining = len([name for name in arguments if name != "_raw_arguments"]) - len(parts)
            if remaining > 0:
                parts.append(f"+{remaining} more")
            break
    return " ".join(parts)


def _display_tool_argument_value(value: JSONValue) -> str:
    if isinstance(value, str):
        collapsed = " ".join(value.split())
        if len(collapsed) > 48:
            collapsed = f"{collapsed[:45]}…"
        return repr(collapsed)
    if isinstance(value, bool | int | float) or value is None:
        return repr(value)
    if isinstance(value, list):
        return f"[{len(value)} item{'s' if len(value) != 1 else ''}]"
    if isinstance(value, dict):
        return f"{{{len(value)} key{'s' if len(value) != 1 else ''}}}"
    return "…"


def _string_argument(arguments: dict[str, JSONValue], key: str) -> str | None:
    value = arguments.get(key)
    return value if isinstance(value, str) else None


def _normalized_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _int_argument(arguments: dict[str, JSONValue], key: str) -> int | None:
    value = arguments.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _number_argument(arguments: dict[str, JSONValue], key: str) -> int | float | None:
    value = arguments.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int | float) else None


def format_tool_result_summary(*, name: str, ok: bool) -> str:
    """Format a terse tool result line for orphaned results."""
    status = "✓" if ok else "✗"
    label = name.strip() or "tool"
    return f"{status} {label}"


def format_tool_result_block(
    *,
    name: str,
    ok: bool,
    content: str,
    data: dict[str, JSONValue] | None = None,
) -> str:
    """Format a tool result for live and restored transcript blocks."""
    status = "✓" if ok else "✗"
    label = name.strip() or "tool"
    lines = [f"{status} {label}"]
    if content.strip():
        lines.append(_preview_text(content, max_lines=TOOL_RESULT_PREVIEW_LINES))
    patch = _result_patch(name=name, ok=ok, data=data)
    if patch:
        lines.extend(["", "Patch:", _preview_text(patch, max_lines=TOOL_PATCH_PREVIEW_LINES)])
    return "\n".join(lines)


def format_terminal_command_result_block(
    *,
    ok: bool,
    added_to_context: bool,
    output: str,
) -> str:
    """Format an input-bar terminal command result for visible TUI display."""
    status = "✓" if ok else "✗"
    suffix = " · added to context" if added_to_context else " · not added to context"
    lines = [f"{status} sh{suffix}"]
    if output:
        lines.append(_preview_text(output, max_lines=TERMINAL_COMMAND_OUTPUT_PREVIEW_LINES))
    return "\n".join(lines)


def _result_patch(
    *,
    name: str,
    ok: bool,
    data: dict[str, JSONValue] | None,
) -> str | None:
    if name != "edit" or not ok or data is None:
        return None
    patch = data.get("patch")
    return patch if isinstance(patch, str) and patch.strip() else None


def _preview_text(text: str, *, max_lines: int) -> str:
    lines = text.splitlines()
    if not lines:
        return text[:TOOL_RESULT_PREVIEW_CHARS]

    preview_lines = lines[:max_lines]
    preview = "\n".join(preview_lines)
    hidden_lines = max(0, len(lines) - len(preview_lines))

    truncated_by_chars = len(preview) > TOOL_RESULT_PREVIEW_CHARS
    if truncated_by_chars:
        preview = preview[:TOOL_RESULT_PREVIEW_CHARS].rstrip()

    if hidden_lines or truncated_by_chars:
        details: list[str] = []
        if hidden_lines:
            details.append(f"{hidden_lines} more line{'s' if hidden_lines != 1 else ''}")
        if truncated_by_chars:
            details.append("additional text")
        preview = f"{preview}\n\n[Preview only: {', '.join(details)} hidden from the TUI.]"
    return preview
