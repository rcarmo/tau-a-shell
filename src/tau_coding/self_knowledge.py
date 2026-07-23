"""Bundled Tau Prime self-knowledge for the system prompt."""

from __future__ import annotations

from importlib.resources import files

from tau_coding.system_prompt import ProjectContextFile

SELF_KNOWLEDGE_PACKAGE = "tau_coding.data.self_knowledge"


def bundled_self_knowledge_context() -> tuple[ProjectContextFile, ...]:
    """Return built-in Tau Prime reference notes as system context files."""
    root = files(SELF_KNOWLEDGE_PACKAGE)
    context: list[ProjectContextFile] = []
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if resource.name.endswith(".md"):
            context.append(
                ProjectContextFile(
                    path=f"builtin://tau-prime/{resource.name}",
                    content=resource.read_text(encoding="utf-8"),
                )
            )
    return tuple(context)
