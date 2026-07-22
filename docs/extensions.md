# Extensions

Tau Prime supports a small Python extension seam for local automation. This is a Tau Prime-shaped subset of upstream Tau/Pi extension ideas; it does not yet expose arbitrary Textual component hosting or the full Pi-compatible event stream.

## Discovery

Python files with a top-level `setup(tau)` function are loaded from:

- `~/.tau/extensions/*.py`
- `~/.agents/extensions/*.py`
- `<project>/.tau/extensions/*.py`
- `<project>/.agents/extensions/*.py`

Loading is best-effort. A failing extension records a diagnostic instead of stopping session startup.

## API

The `tau` object passed to `setup()` supports:

- `register_tool(tool)` — add an `AgentTool` to the model tool list.
- `register_command(name, handler, description="", usage=None, aliases=())` — add a slash command.
- `register_prompt_guideline(text)` — append a system-prompt guideline.
- `register_input_hook(hook)` — transform user input before prompt-template and skill expansion.

Command handlers receive `(context, args)` and return `CommandResult`. Input hooks receive `(context, text)` and may return replacement text or `None`.

## Example

```python
from tau_agent import AgentTool, AgentToolResult
from tau_coding.commands import CommandResult

async def run_tool(arguments, signal=None):
    return AgentToolResult(tool_call_id="", name="hello", ok=True, content="hello")

def setup(tau):
    tau.register_prompt_guideline("Prefer concise answers.")
    tau.register_command(
        "hello",
        lambda context, args: CommandResult(handled=True, message="hello"),
    )
    tau.register_tool(AgentTool(
        name="hello",
        description="Say hello",
        input_schema={"type": "object"},
        executor=run_tool,
    ))
```

## Current limits

This first phase deliberately excludes provider-payload hooks, TUI widget hosting, key interception, and full Pi-shaped message update events. Those can be layered later after the core runtime has settled.
