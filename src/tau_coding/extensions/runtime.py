"""Lightweight Tau Prime extension loading and dispatch."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tau_agent.events import AgentEvent
from tau_agent.tools import AgentTool
from tau_coding.commands import CommandContext, CommandRegistry, CommandResult, SlashCommand
from tau_coding.extensions.api import (
    ExtensionAPI,
    ExtensionCommandHandler,
    ExtensionContext,
    ExtensionEventListener,
    ExtensionInputHook,
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

    def dispatch_agent_event(self, context: ExtensionContext, event: AgentEvent) -> None:
        for listener in self.event_listeners:
            try:
                listener(context, event)
            except Exception as exc:  # noqa: BLE001 - extension isolation boundary
                self.diagnostics.append(
                    ResourceDiagnostic(
                        kind="extension",
                        message=f"agent event listener failed: {exc!r}",
                        severity="error",
                    )
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
