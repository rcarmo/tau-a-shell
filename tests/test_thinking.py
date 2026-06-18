import pytest

from tau_coding.thinking import (
    DEFAULT_THINKING_LEVEL,
    THINKING_LEVELS,
    next_thinking_level,
    normalize_thinking_level,
)


def test_normalize_thinking_level_accepts_supported_modes() -> None:
    assert normalize_thinking_level("HIGH") == "high"
    assert normalize_thinking_level(None) == DEFAULT_THINKING_LEVEL


def test_normalize_thinking_level_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Unknown thinking mode"):
        normalize_thinking_level("maximum")


def test_next_thinking_level_cycles_supported_modes() -> None:
    assert next_thinking_level("medium") == "high"
    assert next_thinking_level("xhigh") == "off"
    assert next_thinking_level("missing", available=("low", "high")) == "low"
    assert THINKING_LEVELS == ("off", "minimal", "low", "medium", "high", "xhigh")
