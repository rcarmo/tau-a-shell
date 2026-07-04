"""Runtime provider construction for Tau coding sessions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from os import environ
from typing import Protocol

from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentTool
from tau_ai import (
    AnthropicProvider,
    CancellationToken,
    LLMObserver,
    ModelProvider,
    OpenAICodexConfig,
    OpenAICodexCredentials,
    OpenAICodexProvider,
    OpenAICompatibleProvider,
    ProviderEvent,
)
from tau_coding.credentials import FileCredentialStore, OAuthCredential
from tau_coding.oauth import (
    account_id_from_access_token,
    github_copilot_base_url,
    oauth_credential_is_expired,
    refresh_github_copilot_token,
    refresh_openai_codex_token,
)
from tau_coding.provider_catalog import catalog_model_override
from tau_coding.provider_config import (
    AnthropicProviderConfig,
    OpenAICodexProviderConfig,
    ProviderConfig,
    ProviderConfigError,
    anthropic_config_from_provider,
    openai_compatible_config_from_provider,
    provider_thinking_levels,
)
from tau_coding.thinking import ThinkingLevel, normalize_thinking_level, reasoning_effort_for_level


class ClosableModelProvider(ModelProvider, Protocol):
    """Runtime provider object Tau owns and can close."""

    async def aclose(self) -> None:
        """Close any provider-owned resources."""
        ...


def create_model_provider(
    provider: ProviderConfig,
    *,
    credential_store: FileCredentialStore | None = None,
    model: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    llm_observer: LLMObserver | None = None,
) -> ClosableModelProvider:
    """Create a runtime model provider from durable provider settings."""
    credentials = credential_store or FileCredentialStore()
    selected_model = model or provider.default_model
    if provider.name == "github-copilot":
        return GitHubCopilotCredentialRefreshingProvider(
            provider,
            credential_store=credentials,
            thinking_level=thinking_level,
            llm_observer=llm_observer,
        )
    override = catalog_model_override(provider.name, selected_model)
    if override is not None and override.kind == "anthropic":
        provider = _anthropic_provider_config_for_model(provider, selected_model)
    if isinstance(provider, AnthropicProviderConfig):
        return AnthropicProvider(
            anthropic_config_from_provider(
                provider,
                credential_reader=credentials,
                model=selected_model,
                thinking_level=thinking_level,
            ),
            observer=llm_observer,
        )
    if isinstance(provider, OpenAICodexProviderConfig):
        return OpenAICodexProvider(
            OpenAICodexConfig(
                credential_resolver=OpenAICodexCredentialResolver(
                    provider,
                    credential_store=credentials,
                ),
                base_url=provider.base_url,
                headers=provider.headers,
                timeout_seconds=provider.timeout_seconds,
                max_retries=provider.max_retries,
                max_retry_delay_seconds=provider.max_retry_delay_seconds,
                reasoning_effort=_codex_reasoning_effort(
                    provider,
                    model=model,
                    thinking_level=thinking_level,
                ),
            ),
            observer=llm_observer,
        )
    return OpenAICompatibleProvider(
        openai_compatible_config_from_provider(
            provider,
            credential_reader=credentials,
            model=selected_model,
            thinking_level=thinking_level,
        ),
        observer=llm_observer,
    )


def _github_copilot_provider_config(
    provider: ProviderConfig,
    *,
    credential_store: FileCredentialStore,
) -> ProviderConfig:
    """Refresh and adapt GitHub Copilot OAuth settings for runtime calls."""
    credential_name = provider.credential_name
    if credential_name:
        credential = credential_store.get_oauth(credential_name)
        if credential is not None:
            credential = _refresh_github_copilot_if_needed(
                credential_name,
                credential,
                credential_store=credential_store,
            )
            base_url = github_copilot_base_url(credential.access, credential.account_id)
            return replace(
                provider,
                base_url=base_url,
                headers={**dict(provider.headers), **_github_copilot_headers()},
            )
    return replace(provider, headers={**dict(provider.headers), **_github_copilot_headers()})


def _refresh_github_copilot_if_needed(
    credential_name: str,
    credential: OAuthCredential,
    *,
    credential_store: FileCredentialStore,
) -> OAuthCredential:
    """Refresh Copilot credentials when provider setup is outside an event loop."""
    if not oauth_credential_is_expired(credential):
        return credential
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        refreshed = asyncio.run(
            refresh_github_copilot_token(
                credential.refresh,
                enterprise_domain=credential.account_id if credential.account_id != "github.com" else "",
            )
        )
        credential_store.set_oauth(credential_name, refreshed)
        return refreshed
    return credential


def _github_copilot_headers() -> dict[str, str]:
    return {
        "User-Agent": "GitHubCopilotChat/0.35.0",
        "Editor-Version": "vscode/1.107.0",
        "Editor-Plugin-Version": "copilot-chat/0.35.0",
        "Copilot-Integration-Id": "vscode-chat",
        "openai-intent": "conversation-panel",
    }


class GitHubCopilotCredentialRefreshingProvider:
    """GitHub Copilot provider wrapper with request-time OAuth refresh."""

    def __init__(
        self,
        provider: ProviderConfig,
        *,
        credential_store: FileCredentialStore,
        thinking_level: ThinkingLevel | None = None,
        llm_observer: LLMObserver | None = None,
    ) -> None:
        self._provider = provider
        self._credential_store = credential_store
        self._thinking_level = thinking_level
        self._llm_observer = llm_observer

    async def aclose(self) -> None:
        """No persistent HTTP client is owned by the wrapper."""

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Refresh Copilot credentials, then delegate one streamed request."""

        async def iterator() -> AsyncIterator[ProviderEvent]:
            inner = await self._fresh_inner_provider(model=model)
            try:
                async for event in inner.stream_response(
                    model=model,
                    system=system,
                    messages=messages,
                    tools=tools,
                    signal=signal,
                ):
                    yield event
            finally:
                await inner.aclose()

        return iterator()

    async def _fresh_inner_provider(self, *, model: str) -> ClosableModelProvider:
        provider = await self._fresh_provider_config()
        return OpenAICompatibleProvider(
            openai_compatible_config_from_provider(
                provider,
                credential_reader=self._credential_store,
                model=model,
                thinking_level=self._thinking_level,
            ),
            observer=self._llm_observer,
        )

    async def _fresh_provider_config(self) -> ProviderConfig:
        headers = {**dict(self._provider.headers), **_github_copilot_headers()}
        credential_name = self._provider.credential_name
        if not credential_name:
            return replace(self._provider, headers=headers)

        credential = self._credential_store.get_oauth(credential_name)
        if credential is None:
            return replace(self._provider, headers=headers)
        if oauth_credential_is_expired(credential):
            credential = await refresh_github_copilot_token(
                credential.refresh,
                enterprise_domain=credential.account_id if credential.account_id != "github.com" else "",
            )
            self._credential_store.set_oauth(credential_name, credential)
        return replace(
            self._provider,
            base_url=github_copilot_base_url(credential.access, credential.account_id),
            headers=headers,
        )



def _anthropic_provider_config_for_model(
    provider: ProviderConfig,
    model: str,
) -> AnthropicProviderConfig:
    """Adapt shared connection settings for a model served via Messages API."""
    if isinstance(provider, AnthropicProviderConfig):
        return provider
    return AnthropicProviderConfig(
        name=provider.name,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        credential_name=provider.credential_name,
        models=provider.models,
        default_model=model,
        context_windows=provider.context_windows,
        headers=provider.headers,
        timeout_seconds=provider.timeout_seconds,
        max_retries=provider.max_retries,
        max_retry_delay_seconds=provider.max_retry_delay_seconds,
        thinking_levels=provider.thinking_levels,
        thinking_models=provider.thinking_models,
        thinking_default=provider.thinking_default,
        thinking_parameter="anthropic.thinking",
    )


def _codex_reasoning_effort(
    provider: OpenAICodexProviderConfig,
    *,
    model: str | None,
    thinking_level: ThinkingLevel | None,
) -> str | None:
    if thinking_level is None or provider.thinking_parameter != "reasoning.effort":
        return None
    levels = provider_thinking_levels(provider, model=model)
    if not levels:
        return None
    normalized = normalize_thinking_level(thinking_level)
    if normalized not in levels:
        selected_model = model or provider.default_model
        available = ", ".join(levels)
        raise ProviderConfigError(
            f"Thinking mode {normalized} is not available for "
            f"{provider.name}:{selected_model}. Available modes: {available}"
        )
    if normalized == "off":
        return None
    if normalized == "minimal":
        return "low"
    return reasoning_effort_for_level(normalized)


class OpenAICodexCredentialResolver:
    """Resolve and refresh OpenAI Codex OAuth credentials for one request."""

    def __init__(
        self,
        provider: OpenAICodexProviderConfig,
        *,
        credential_store: FileCredentialStore,
    ) -> None:
        self._provider = provider
        self._credential_store = credential_store

    async def __call__(self) -> OpenAICodexCredentials:
        """Return a valid Codex access token and account id."""
        credential_name = self._provider.credential_name
        if credential_name:
            credential = self._credential_store.get_oauth(credential_name)
            if credential is not None:
                credential = await self._refresh_if_needed(credential_name, credential)
                return OpenAICodexCredentials(
                    access_token=credential.access,
                    account_id=credential.account_id,
                )

        access_token = environ.get(self._provider.api_key_env)
        if access_token:
            account_id = account_id_from_access_token(access_token)
            if account_id is None:
                raise RuntimeError(
                    f"{self._provider.api_key_env} must contain an OpenAI Codex access JWT"
                )
            return OpenAICodexCredentials(access_token=access_token, account_id=account_id)

        credential_hint = f"Run /login {self._provider.name}."
        raise RuntimeError(f"Missing OpenAI Codex OAuth credentials. {credential_hint}")

    async def _refresh_if_needed(
        self,
        credential_name: str,
        credential: OAuthCredential,
    ) -> OAuthCredential:
        if not oauth_credential_is_expired(credential):
            return credential
        refreshed = await refresh_openai_codex_token(credential.refresh)
        self._credential_store.set_oauth(credential_name, refreshed)
        return refreshed
