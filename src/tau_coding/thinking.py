"""Thinking-mode primitives for Tau coding sessions."""

from typing import Literal

ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]

THINKING_LEVELS: tuple[ThinkingLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
DEFAULT_THINKING_LEVEL: ThinkingLevel = "medium"

THINKING_LEVEL_DESCRIPTIONS: dict[ThinkingLevel, str] = {
    "off": "No reasoning",
    "minimal": "Very brief reasoning",
    "low": "Light reasoning",
    "medium": "Moderate reasoning",
    "high": "Deep reasoning",
    "xhigh": "Maximum reasoning",
}


def normalize_thinking_level(value: str | None) -> ThinkingLevel:
    """Return a valid Tau thinking level or raise a user-facing error."""
    if value is None:
        return DEFAULT_THINKING_LEVEL
    normalized = value.strip().lower()
    if normalized in THINKING_LEVELS:
        return normalized
    allowed = ", ".join(THINKING_LEVELS)
    raise ValueError(f"Unknown thinking mode: {value}. Available modes: {allowed}")


def next_thinking_level(
    current: str | None,
    *,
    available: tuple[ThinkingLevel, ...] = THINKING_LEVELS,
) -> ThinkingLevel:
    """Return the next thinking level in a stable cycle."""
    if not available:
        return DEFAULT_THINKING_LEVEL
    try:
        normalized_current = normalize_thinking_level(current)
        index = available.index(normalized_current)
    except ValueError:
        return available[0]
    return available[(index + 1) % len(available)]
