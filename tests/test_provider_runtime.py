import pytest

from tau_ai import OpenAICodexProvider, OpenAICompatibleProvider
from tau_coding import provider_runtime
from tau_coding.credentials import FileCredentialStore, OAuthCredential
from tau_coding.provider_config import OpenAICodexProviderConfig, ProviderSettings
from tau_coding.provider_runtime import (
    GitHubCopilotCredentialRefreshingProvider,
    OpenAICodexCredentialResolver,
    create_model_provider,
)


def test_create_model_provider_returns_openai_codex_provider(tmp_path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")

    provider = create_model_provider(
        OpenAICodexProviderConfig(),
        credential_store=store,
    )

    assert isinstance(provider, OpenAICodexProvider)


@pytest.mark.anyio
async def test_create_model_provider_keeps_github_copilot_claude_openai_compatible(tmp_path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_oauth(
        "github-copilot",
        OAuthCredential(
            access="tid=1;proxy-ep=proxy.enterprise.test;token",
            refresh="github-refresh",
            expires=9999999999999,
            account_id="github.com",
        ),
    )
    provider_config = ProviderSettings().get_provider("github-copilot")

    provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="claude-sonnet-5",
    )

    assert isinstance(provider, GitHubCopilotCredentialRefreshingProvider)
    inner = await provider._fresh_inner_provider(model="claude-sonnet-5")
    try:
        assert isinstance(inner, OpenAICompatibleProvider)
        assert inner._config.base_url == "https://api.enterprise.test"
        assert inner._config.headers["Copilot-Integration-Id"] == "vscode-chat"
    finally:
        await inner.aclose()


def test_create_model_provider_maps_codex_reasoning_effort_like_pi(tmp_path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    provider_config = OpenAICodexProviderConfig(
        thinking_levels=("off", "minimal", "low", "medium", "high", "xhigh"),
        thinking_models=("gpt-5.5",),
        thinking_parameter="reasoning.effort",
    )

    off_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="off",
    )
    minimal_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="minimal",
    )
    xhigh_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="xhigh",
    )

    assert isinstance(off_provider, OpenAICodexProvider)
    assert isinstance(minimal_provider, OpenAICodexProvider)
    assert isinstance(xhigh_provider, OpenAICodexProvider)
    assert off_provider._config.reasoning_effort is None
    assert minimal_provider._config.reasoning_effort == "low"
    assert xhigh_provider._config.reasoning_effort == "xhigh"


@pytest.mark.anyio
async def test_github_copilot_provider_refreshes_expired_credentials_per_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_oauth(
        "github-copilot",
        OAuthCredential(
            access="old-token",
            refresh="github-refresh",
            expires=1,
            account_id="github.com",
        ),
    )
    provider_config = ProviderSettings().get_provider("github-copilot")

    async def fake_refresh(refresh_token: str, *, enterprise_domain: str = "") -> OAuthCredential:
        assert refresh_token == "github-refresh"
        assert enterprise_domain == ""
        return OAuthCredential(
            access="tid=1;proxy-ep=proxy.enterprise.test;new-token",
            refresh="github-refresh",
            expires=9999999999999,
            account_id="github.com",
        )

    monkeypatch.setattr(provider_runtime, "refresh_github_copilot_token", fake_refresh)

    provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="claude-sonnet-5",
    )

    assert isinstance(provider, GitHubCopilotCredentialRefreshingProvider)
    inner = await provider._fresh_inner_provider(model="claude-sonnet-5")
    try:
        assert isinstance(inner, OpenAICompatibleProvider)
        assert inner._config.api_key == "tid=1;proxy-ep=proxy.enterprise.test;new-token"
        assert inner._config.base_url == "https://api.enterprise.test"
    finally:
        await inner.aclose()
    assert store.get_oauth("github-copilot") == OAuthCredential(
        access="tid=1;proxy-ep=proxy.enterprise.test;new-token",
        refresh="github-refresh",
        expires=9999999999999,
        account_id="github.com",
    )


@pytest.mark.anyio
async def test_openai_codex_credential_resolver_refreshes_expired_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_oauth(
        "openai-codex",
        OAuthCredential(
            access="old-access",
            refresh="old-refresh",
            expires=1,
            account_id="old-account",
        ),
    )

    async def fake_refresh(refresh_token: str) -> OAuthCredential:
        assert refresh_token == "old-refresh"
        return OAuthCredential(
            access="new-access",
            refresh="new-refresh",
            expires=9999999999999,
            account_id="new-account",
        )

    monkeypatch.setattr(provider_runtime, "refresh_openai_codex_token", fake_refresh)

    resolver = OpenAICodexCredentialResolver(
        OpenAICodexProviderConfig(),
        credential_store=store,
    )

    credentials = await resolver()

    assert credentials.access_token == "new-access"
    assert credentials.account_id == "new-account"
    assert store.get_oauth("openai-codex") == OAuthCredential(
        access="new-access",
        refresh="new-refresh",
        expires=9999999999999,
        account_id="new-account",
    )
