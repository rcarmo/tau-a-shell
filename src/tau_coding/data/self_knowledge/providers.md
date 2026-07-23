# Tau Prime providers

Tau Prime keeps upstream OpenAI-compatible providers but adds fork-specific provider behavior.

## GitHub Copilot

- Uses OAuth/device login and token refresh.
- Resolves public and enterprise Copilot endpoints from credential metadata.
- Preserves required Copilot IDE/integration headers.
- Dynamically refreshes model IDs and context metadata.
- GPT 5.6 Copilot models must use the Responses endpoint, not `/chat/completions`.

## LM Studio

- First-class, credential-free provider.
- Defaults to `http://localhost:1234/v1`.
- On mobile, users normally configure a LAN URL for the machine running LM Studio.
- Always uses `/v1/chat/completions`; do not send an `Authorization` header.
- Dynamic model discovery is best-effort and must leave the UI usable when offline.

## Codex and Responses

- Codex subscription uses the ChatGPT backend Responses transport.
- Runtime Codex context limits may refine static context windows.
- Codex rejects a function named `python`; expose Tau's internal `python` tool to Codex as `tau_python` and map calls back internally.

## Local catalog notes

Tau Prime includes Kimi, ZAI/GLM, OpenCode, OpenRouter, Hugging Face, DeepSeek, Nebius, Anthropic, OpenAI, OpenAI Codex, Copilot, LM Studio, and custom OpenAI-compatible endpoints. Runtime discovery may overlay static bootstrap metadata, but endpoint capabilities must not be inferred from model IDs alone.
