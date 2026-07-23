"""Small extension-facing API for Tau Prime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tau_agent.events import AgentEvent
from tau_agent.tools import AgentTool, AgentToolResult, ToolCall
from tau_agent.types import JSONValue
from tau_coding.commands import CommandResult


@dataclass(frozen=True, slots=True)
class ExtensionContext:
    """Read-only context passed to extension hooks."""

    cwd: Path
    model: str
    provider_name: str | None = None
    session_id: str | None = None


class ExtensionCommandHandler(Protocol):
    def __call__(self, context: ExtensionContext, args: str) -> CommandResult: ...


class ExtensionInputHook(Protocol):
    def __call__(self, context: ExtensionContext, text: str) -> str | None: ...


class ExtensionEventListener(Protocol):
    def __call__(self, context: ExtensionContext, event: AgentEvent) -> None: ...


class ExtensionLifecycleListener(Protocol):
    def __call__(self, context: ExtensionContext, reason: str) -> None: ...


class ExtensionToolCallHook(Protocol):
    def __call__(self, context: ExtensionContext, tool_call: ToolCall) -> ToolCall | None: ...


class ExtensionToolResultHook(Protocol):
    def __call__(
        self,
        context: ExtensionContext,
        result: AgentToolResult,
    ) -> AgentToolResult | None: ...


class MessageRenderer(Protocol):
    def __call__(self, content: str, details: dict[str, JSONValue] | None = None) -> str: ...


class ToolCallRenderer(Protocol):
    def __call__(self, name: str, arguments: dict[str, JSONValue]) -> str: ...


class ToolResultRenderer(Protocol):
    def __call__(self, result: AgentToolResult) -> str: ...


class ExtensionAPI:
    """Registration API exposed to extension setup functions."""

    def __init__(self, runtime: ExtensionRuntimeProtocol, name: str) -> None:
        self._runtime = runtime
        self._name = name

    def register_tool(self, tool: AgentTool) -> None:
        self._runtime.register_tool(self._name, tool)

    def register_command(
        self,
        name: str,
        handler: ExtensionCommandHandler,
        *,
        description: str = "",
        usage: str | None = None,
        aliases: tuple[str, ...] = (),
    ) -> None:
        self._runtime.register_command(
            self._name,
            name,
            handler,
            description=description,
            usage=usage,
            aliases=aliases,
        )

    def register_prompt_guideline(self, guideline: str) -> None:
        self._runtime.register_prompt_guideline(self._name, guideline)

    def register_input_hook(self, hook: ExtensionInputHook) -> None:
        self._runtime.register_input_hook(self._name, hook)

    def on_agent_event(self, listener: ExtensionEventListener) -> None:
        self._runtime.register_event_listener(self._name, listener)

    def on_lifecycle(self, listener: ExtensionLifecycleListener) -> None:
        self._runtime.register_lifecycle_listener(self._name, listener)

    def on_tool_call(self, hook: ExtensionToolCallHook) -> None:
        self._runtime.register_tool_call_hook(self._name, hook)

    def on_tool_result(self, hook: ExtensionToolResultHook) -> None:
        self._runtime.register_tool_result_hook(self._name, hook)

    def register_message_renderer(self, custom_type: str, renderer: MessageRenderer) -> None:
        self._runtime.register_message_renderer(self._name, custom_type, renderer)

    def register_tool_call_renderer(self, tool_name: str, renderer: ToolCallRenderer) -> None:
        self._runtime.register_tool_call_renderer(self._name, tool_name, renderer)

    def register_tool_result_renderer(self, tool_name: str, renderer: ToolResultRenderer) -> None:
        self._runtime.register_tool_result_renderer(self._name, tool_name, renderer)


class ExtensionRuntimeProtocol(Protocol):
    def register_tool(self, extension_name: str, tool: AgentTool) -> None: ...

    def register_command(
        self,
        extension_name: str,
        name: str,
        handler: ExtensionCommandHandler,
        *,
        description: str,
        usage: str | None,
        aliases: tuple[str, ...],
    ) -> None: ...

    def register_prompt_guideline(self, extension_name: str, guideline: str) -> None: ...

    def register_input_hook(self, extension_name: str, hook: ExtensionInputHook) -> None: ...

    def register_event_listener(
        self,
        extension_name: str,
        listener: ExtensionEventListener,
    ) -> None: ...

    def register_lifecycle_listener(
        self,
        extension_name: str,
        listener: ExtensionLifecycleListener,
    ) -> None: ...

    def register_tool_call_hook(
        self,
        extension_name: str,
        hook: ExtensionToolCallHook,
    ) -> None: ...

    def register_tool_result_hook(
        self,
        extension_name: str,
        hook: ExtensionToolResultHook,
    ) -> None: ...

    def register_message_renderer(
        self,
        extension_name: str,
        custom_type: str,
        renderer: MessageRenderer,
    ) -> None: ...

    def register_tool_call_renderer(
        self,
        extension_name: str,
        tool_name: str,
        renderer: ToolCallRenderer,
    ) -> None: ...

    def register_tool_result_renderer(
        self,
        extension_name: str,
        tool_name: str,
        renderer: ToolResultRenderer,
    ) -> None: ...
