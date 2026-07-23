"""Lightweight Tau Prime extension loading and dispatch."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tau_agent.events import AgentEvent
from tau_agent.tools import AgentTool, AgentToolResult, ToolCall, ToolCancellationToken
from tau_agent.types import JSONValue
from tau_coding.commands import CommandContext, CommandRegistry, CommandResult, SlashCommand
from tau_coding.extensions.api import (
    ExtensionAPI,
    ExtensionCommandHandler,
    ExtensionContext,
    ExtensionEventListener,
    ExtensionInputHook,
    ExtensionLifecycleListener,
    ExtensionToolCallHook,
    ExtensionToolResultHook,
    MessageRenderer,
    ToolCallRenderer,
    ToolResultRenderer,
)
from tau_coding.resources import ResourceDiagnostic, TauResourcePaths


@dataclass(frozen=True, slots=True)
class ExtensionCommand:
    extension: str
    name: str
    handler: ExtensionCommandHandler
    description: str
    usage: str
    aliases: tuple[str, ...]


class ExtensionRuntime:
    """Owns loaded Python extensions and their registrations."""

    def __init__(self) -> None:
        self.tools: dict[str, AgentTool] = {}
        self.commands: dict[str, ExtensionCommand] = {}
        self.prompt_guidelines: list[str] = []
        self.input_hooks: list[ExtensionInputHook] = []
        self.event_listeners: list[ExtensionEventListener] = []
        self.lifecycle_listeners: list[ExtensionLifecycleListener] = []
        self.tool_call_hooks: list[ExtensionToolCallHook] = []
        self.tool_result_hooks: list[ExtensionToolResultHook] = []
        self.message_renderers: dict[str, MessageRenderer] = {}
        self.tool_call_renderers: dict[str, ToolCallRenderer] = {}
        self.tool_result_renderers: dict[str, ToolResultRenderer] = {}
        self.diagnostics: list[ResourceDiagnostic] = []
        self._modules: list[str] = []

    def load(self, paths: TauResourcePaths) -> None:
        for directory in _extension_dirs(paths):
            if not directory.exists():
                continue
            for file in sorted(directory.glob("*.py")):
                self._load_file(file)

    def reset_for_reload(self) -> None:
        for module_name in self._modules:
            sys.modules.pop(module_name, None)
        self._modules.clear()
        self.tools.clear()
        self.commands.clear()
        self.prompt_guidelines.clear()
        self.input_hooks.clear()
        self.event_listeners.clear()
        self.lifecycle_listeners.clear()
        self.tool_call_hooks.clear()
        self.tool_result_hooks.clear()
        self.message_renderers.clear()
        self.tool_call_renderers.clear()
        self.tool_result_renderers.clear()
        self.diagnostics.clear()

    def command_registry(self, base: CommandRegistry) -> CommandRegistry:
        for command in self.commands.values():
            base.register(
                SlashCommand(
                    name=command.name,
                    usage=command.usage,
                    description=command.description,
                    aliases=command.aliases,
                    handler=_command_handler(command.handler),
                )
            )
        return base

    def extension_context(self, context: CommandContext) -> ExtensionContext:
        return ExtensionContext(
            cwd=context.session.cwd,
            model=context.session.model,
            provider_name=getattr(context.session, "provider_name", None),
            session_id=getattr(context.session, "session_id", None),
        )

    def transform_input(self, context: ExtensionContext, text: str) -> str:
        current = text
        for hook in self.input_hooks:
            try:
                updated = hook(context, current)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self.diagnostics.append(
                    ResourceDiagnostic(
                        kind="extension",
                        message=f"input hook failed: {exc!r}",
                        severity="error",
                    )
                )
                continue
            if updated is not None:
                current = updated
        return current

    def _load_file(self, path: Path) -> None:
        name = f"tau_extension_{path.stem}_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        try:
            sys.modules[name] = module
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if not callable(setup):
                return
            setup(ExtensionAPI(self, path.stem))
            self._modules.append(name)
        except Exception as exc:  # noqa: BLE001 - extensions must not crash startup
            sys.modules.pop(name, None)
            self.diagnostics.append(
                ResourceDiagnostic(
                    kind="extension",
                    name=path.stem,
                    path=path,
                    message=f"setup failed: {exc!r}",
                    severity="error",
                )
            )

    def register_tool(self, extension_name: str, tool: AgentTool) -> None:
        if tool.name in self.tools:
            self.diagnostics.append(
                ResourceDiagnostic(
                    kind="extension",
                    name=extension_name,
                    message=f"duplicate tool ignored: {tool.name}",
                )
            )
            return
        self.tools[tool.name] = tool

    def register_command(
        self,
        extension_name: str,
        name: str,
        handler: ExtensionCommandHandler,
        *,
        description: str,
        usage: str | None,
        aliases: tuple[str, ...],
    ) -> None:
        normalized = name.strip().removeprefix("/").lower()
        if not normalized or normalized in self.commands:
            return
        self.commands[normalized] = ExtensionCommand(
            extension=extension_name,
            name=normalized,
            handler=handler,
            description=description,
            usage=usage or f"/{normalized}",
            aliases=aliases,
        )

    def register_prompt_guideline(self, extension_name: str, guideline: str) -> None:
        text = guideline.strip()
        if text:
            self.prompt_guidelines.append(f"[{extension_name}] {text}")

    def register_input_hook(self, extension_name: str, hook: ExtensionInputHook) -> None:
        del extension_name
        self.input_hooks.append(hook)

    def register_event_listener(
        self,
        extension_name: str,
        listener: ExtensionEventListener,
    ) -> None:
        del extension_name
        self.event_listeners.append(listener)

    def register_lifecycle_listener(
        self,
        extension_name: str,
        listener: ExtensionLifecycleListener,
    ) -> None:
        del extension_name
        self.lifecycle_listeners.append(listener)

    def register_tool_call_hook(
        self,
        extension_name: str,
        hook: ExtensionToolCallHook,
    ) -> None:
        del extension_name
        self.tool_call_hooks.append(hook)

    def register_tool_result_hook(
        self,
        extension_name: str,
        hook: ExtensionToolResultHook,
    ) -> None:
        del extension_name
        self.tool_result_hooks.append(hook)

    def dispatch_lifecycle(self, context: ExtensionContext, reason: str) -> None:
        for listener in self.lifecycle_listeners:
            try:
                listener(context, reason)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self._record_runtime_error(f"lifecycle listener failed: {exc!r}")

    def dispatch_agent_event(self, context: ExtensionContext, event: AgentEvent) -> None:
        for listener in self.event_listeners:
            try:
                listener(context, event)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self._record_runtime_error(f"agent event listener failed: {exc!r}")

    def transform_tool_call(self, context: ExtensionContext, tool_call: ToolCall) -> ToolCall:
        current = tool_call
        for hook in self.tool_call_hooks:
            try:
                updated = hook(context, current)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self._record_runtime_error(f"tool call hook failed: {exc!r}")
                continue
            if updated is not None:
                current = updated
        return current

    def transform_tool_result(
        self,
        context: ExtensionContext,
        result: AgentToolResult,
    ) -> AgentToolResult:
        current = result
        for hook in self.tool_result_hooks:
            try:
                updated = hook(context, current)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self._record_runtime_error(f"tool result hook failed: {exc!r}")
                continue
            if updated is not None:
                current = updated
        return current

    def register_message_renderer(
        self,
        extension_name: str,
        custom_type: str,
        renderer: MessageRenderer,
    ) -> None:
        del extension_name
        if custom_type.strip():
            self.message_renderers[custom_type.strip()] = renderer

    def register_tool_call_renderer(
        self,
        extension_name: str,
        tool_name: str,
        renderer: ToolCallRenderer,
    ) -> None:
        del extension_name
        if tool_name.strip():
            self.tool_call_renderers[tool_name.strip()] = renderer

    def register_tool_result_renderer(
        self,
        extension_name: str,
        tool_name: str,
        renderer: ToolResultRenderer,
    ) -> None:
        del extension_name
        if tool_name.strip():
            self.tool_result_renderers[tool_name.strip()] = renderer

    def render_tool_call(self, name: str, arguments: dict[str, JSONValue]) -> str | None:
        renderer = self.tool_call_renderers.get(name)
        if renderer is None:
            return None
        try:
            return renderer(name, arguments)
        except Exception as exc:  # noqa: BLE001 - extension isolation boundary
            self._record_runtime_error(f"tool call renderer failed: {exc!r}")
            return None

    def render_tool_result(self, result: AgentToolResult) -> str | None:
        renderer = self.tool_result_renderers.get(result.name)
        if renderer is None:
            return None
        try:
            return renderer(result)
        except Exception as exc:  # noqa: BLE001 - extension isolation boundary
            self._record_runtime_error(f"tool result renderer failed: {exc!r}")
            return None

    def render_message(
        self,
        custom_type: str,
        content: str,
        details: dict[str, JSONValue] | None,
    ) -> str | None:
        renderer = self.message_renderers.get(custom_type)
        if renderer is None:
            return None
        try:
            return renderer(content, details)
        except Exception as exc:  # noqa: BLE001 - extension isolation boundary
            self._record_runtime_error(f"message renderer failed: {exc!r}")
            return None

    def wrap_tools(
        self,
        tools: list[AgentTool],
        context_factory: Callable[[], ExtensionContext],
    ) -> list[AgentTool]:
        if not self.tool_call_hooks and not self.tool_result_hooks:
            return tools
        return [_wrap_tool(self, tool, context_factory) for tool in tools]

    def _record_runtime_error(self, message: str) -> None:
        self.diagnostics.append(
            ResourceDiagnostic(
                kind="extension",
                message=message,
                severity="error",
            )
        )


def _wrap_tool(
    runtime: ExtensionRuntime,
    tool: AgentTool,
    context_factory: Callable[[], ExtensionContext],
) -> AgentTool:
    async def execute(
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
    ) -> AgentToolResult:
        context = context_factory()
        tool_call = ToolCall(id="extension-hook", name=tool.name, arguments=dict(arguments))
        transformed_call = runtime.transform_tool_call(context, tool_call)
        result = await tool.execute(transformed_call.arguments, signal=signal)
        return runtime.transform_tool_result(context, result)

    return AgentTool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        executor=execute,
        prompt_snippet=tool.prompt_snippet,
        prompt_guidelines=tool.prompt_guidelines,
    )


def _extension_dirs(paths: TauResourcePaths) -> tuple[Path, ...]:
    dirs = [paths.root / "extensions"]
    if paths.agents_root is not None:
        dirs.append(paths.agents_root / "extensions")
    if paths.cwd is not None:
        tau_paths = paths._paths()
        dirs.extend(
            [
                tau_paths.project_tau_dir(paths.cwd) / "extensions",
                tau_paths.project_agents_dir(paths.cwd) / "extensions",
            ]
        )
    deduped: list[Path] = []
    seen: set[Path] = set()
    for directory in dirs:
        expanded = directory.expanduser()
        if expanded in seen:
            continue
        seen.add(expanded)
        deduped.append(expanded)
    return tuple(deduped)


def _command_handler(handler: ExtensionCommandHandler) -> Callable[[CommandContext], CommandResult]:
    def run(context: CommandContext) -> CommandResult:
        runtime = getattr(context.session, "extension_runtime", None)
        if isinstance(runtime, ExtensionRuntime):
            extension_context = runtime.extension_context(context)
        else:
            extension_context = ExtensionContext(
                cwd=context.session.cwd,
                model=context.session.model,
            )
        return handler(extension_context, context.args)

    return run
