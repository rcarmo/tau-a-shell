"""Provider and model streaming layer for Tau."""

from __future__ import annotations

from tau_ai.anthropic import AnthropicProvider
from tau_ai.env import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    AnthropicConfig,
    OpenAICompatibleConfig,
    openai_compatible_config_from_env,
)
from tau_ai.events import (
    ProviderErrorEvent,
    ProviderEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    ProviderThinkingDeltaEvent,
    ProviderToolCallEvent,
)
from tau_ai.fake import FakeProvider
from tau_ai.model_limits import ModelLimitsProvider, RuntimeModelLimits
from tau_ai.models import ModelInfo, list_openai_compatible_models
from tau_ai.observability import (
    LLMObservation,
    LLMObserver,
    observe_llm_error,
    observe_llm_request,
    observe_llm_response,
    redact_headers,
    redact_json_value,
)
from tau_ai.openai_codex import (
    DEFAULT_OPENAI_CODEX_BASE_URL,
    OpenAICodexConfig,
    OpenAICodexCredentials,
    OpenAICodexProvider,
)
from tau_ai.openai_compatible import OpenAICompatibleProvider
from tau_ai.provider import CancellationToken, ModelProvider
from tau_ai.remote_compaction import (
    REMOTE_COMPACTION_SENTINEL,
    RemoteCompactionProvider,
    RemoteCompactionState,
)

__all__ = [
    "CancellationToken",
    "AnthropicConfig",
    "AnthropicProvider",
    "DEFAULT_ANTHROPIC_BASE_URL",
    "DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES",
    "DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS",
    "DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
    "DEFAULT_OPENAI_CODEX_BASE_URL",
    "FakeProvider",
    "ModelInfo",
    "ModelLimitsProvider",
    "ModelProvider",
    "OpenAICodexConfig",
    "OpenAICodexCredentials",
    "OpenAICodexProvider",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "LLMObservation",
    "LLMObserver",
    "ProviderErrorEvent",
    "ProviderEvent",
    "ProviderResponseEndEvent",
    "ProviderResponseStartEvent",
    "ProviderRetryEvent",
    "ProviderThinkingDeltaEvent",
    "ProviderTextDeltaEvent",
    "ProviderToolCallEvent",
    "REMOTE_COMPACTION_SENTINEL",
    "RemoteCompactionProvider",
    "RemoteCompactionState",
    "RuntimeModelLimits",
    "list_openai_compatible_models",
    "observe_llm_error",
    "observe_llm_request",
    "observe_llm_response",
    "openai_compatible_config_from_env",
    "redact_headers",
    "redact_json_value",
]
