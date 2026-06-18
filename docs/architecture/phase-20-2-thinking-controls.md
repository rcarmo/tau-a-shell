# Phase 20.2: Thinking Mode Controls

Phase 20.2 makes thinking mode an explicit Tau coding-session setting and adds
a TUI control for changing it.

## What Was Added

`tau_coding.thinking` defines Tau's supported thinking modes:

```text
off
minimal
low
medium
high
xhigh
```

The default is `medium`, matching Pi's default reasoning-depth preference. Tau
does not yet pass provider-specific reasoning options through `tau_ai`; this
phase models and persists the coding-session preference so providers can consume
it later without changing the UI or session format.

## Session Persistence

New sessions append an initial `thinking_level_change` entry after the initial
model entry. Explicit changes append another `thinking_level_change` entry and a
leaf pointer, so resume reconstructs the active thinking mode from the session
tree.

`CodingSession` exposes:

```python
session.thinking_level
session.available_thinking_levels
await session.set_thinking_level("high")
await session.cycle_thinking_level()
```

This keeps thinking state in `tau_coding`, while `tau_agent.session` remains the
portable replay layer that knows how to reconstruct `ThinkingLevelChangeEntry`
values.

## Commands And TUI

The shared command registry includes:

```text
/thinking
/thinking high
```

The Textual TUI binds thinking cycling to `Shift-Tab` by default. The key is
configurable in `~/.tau/tui.json`:

```json
{
  "keybindings": {
    "thinking_cycle": "f3"
  }
}
```

The sidebar and compact session line now read `session.thinking_level` directly,
with a fallback for simple custom session adapters.

## Boundary

Thinking controls remain outside `tau_agent` provider execution. This phase
does not add provider-specific reasoning payloads, model capability clamping, or
thinking trace rendering. Those can be added later in `tau_ai` and provider
runtime code without changing the session/TUI contract introduced here.

## Tests

The phase is covered by:

```text
tests/test_thinking.py
tests/test_commands.py
tests/test_coding_session.py
tests/test_tui_config.py
tests/test_tui_app.py
```
