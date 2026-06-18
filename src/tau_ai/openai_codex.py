"""OpenAI Codex subscription Responses provider."""

from asyncio import sleep
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads
from platform import machine, release, system
from typing import Any

import httpx

from tau_agent.messages import AgentMessage, AssistantMessage, ToolResultMessage, UserMessage
from tau_agent.tools import AgentTool, ToolCall
from tau_agent.types import JSONValue
from tau_ai.env import (
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
)
from tau_ai.events import (
    ProviderErrorEvent,
    ProviderEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderTextDeltaEvent,
    ProviderToolCallEvent,
)
from tau_ai.provider import CancellationToken

DEFAULT_OPENAI_CODEX_BASE_URL = "https://chatgpt.com/backend-api"


@dataclass(frozen=True, slots=True)
class OpenAICodexCredentials:
    """Bearer token and account id required by ChatGPT Codex Responses."""

    access_token: str
    account_id: str


type OpenAICodexCredentialResolver = Callable[[], Awaitable[OpenAICodexCredentials]]


@dataclass(frozen=True, slots=True)
class OpenAICodexConfig:
    """Configuration for the OpenAI Codex subscription Responses endpoint."""

    credential_resolver: OpenAICodexCredentialResolver
    base_url: str = DEFAULT_OPENAI_CODEX_BASE_URL
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    originator: str = "tau"


class OpenAICodexProvider:
    """Provider adapter for ChatGPT subscription Codex Responses over SSE."""

    def __init__(
        self,
        config: OpenAICodexConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one Codex Responses request as provider-neutral events."""

        async def iterator() -> AsyncIterator[ProviderEvent]:
            client = self._get_client()
            payload = _build_codex_payload(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
            )
            url = _resolve_codex_url(self._config.base_url)

            yield ProviderResponseStartEvent(model=model)

            attempt = 0
            while True:
                emitted_content = False
                try:
                    credentials = await self._config.credential_resolver()
                    headers = _build_codex_headers(
                        self._config.headers,
                        access_token=credentials.access_token,
                        account_id=credentials.account_id,
                        originator=self._config.originator,
                    )
                    async with client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code >= 400:
                            body = await response.aread()
                            body_text = body.decode(errors="replace")
                            if await self._should_retry(
                                attempt,
                                status_code=response.status_code,
                                body=body_text,
                            ):
                                attempt += 1
                                continue
                            yield ProviderErrorEvent(
                                message=(
                                    "OpenAI Codex request failed with status "
                                    f"{response.status_code}"
                                ),
                                data={
                                    "body": body_text,
                                    "attempts": attempt + 1,
                                },
                            )
                            return

                        async for event in _codex_provider_events(response, signal=signal):
                            if isinstance(
                                event,
                                ProviderTextDeltaEvent | ProviderToolCallEvent,
                            ):
                                emitted_content = True
                            yield event
                        return
                except httpx.HTTPError as exc:
                    if not emitted_content and await self._should_retry(attempt):
                        attempt += 1
                        continue
                    yield ProviderErrorEvent(
                        message=str(exc),
                        data={"attempts": attempt + 1},
                    )
                    return
                except Exception as exc:  # noqa: BLE001 - provider errors are surfaced as events
                    yield ProviderErrorEvent(message=str(exc), data={"attempts": attempt + 1})
                    return

        return iterator()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._config.timeout_seconds)
        return self._client

    async def _should_retry(
        self,
        attempt: int,
        *,
        status_code: int | None = None,
        body: str = "",
    ) -> bool:
        if attempt >= self._config.max_retries:
            return False
        if status_code is not None and not _is_retryable_status(status_code, body):
            return False
        if self._config.max_retry_delay_seconds:
            await sleep(self._config.max_retry_delay_seconds)
        return True


class _ToolCallBuilder:
    def __init__(self, *, call_id: str, item_id: str | None, name: str) -> None:
        self.call_id = call_id
        self.item_id = item_id
        self.name = name
        self.arguments_parts: list[str] = []

    def add_delta(self, delta: str) -> None:
        """Append a streamed tool-argument fragment."""
        self.arguments_parts.append(delta)

    def set_arguments(self, arguments: str) -> None:
        """Replace streamed tool arguments with final provider arguments."""
        self.arguments_parts = [arguments]

    def build(self) -> ToolCall:
        """Build a complete Tau tool call."""
        arguments_text = "".join(self.arguments_parts)
        arguments = _loads_object(arguments_text) if arguments_text else {}
        if arguments is None:
            arguments = {"_raw_arguments": arguments_text}
        item_id = self.item_id or f"fc_{self.call_id}"
        return ToolCall(
            id=f"{self.call_id}|{item_id}",
            name=self.name,
            arguments=arguments,
        )


def _build_codex_payload(
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system or "You are a helpful assistant.",
        "input": _messages_to_responses_input(messages),
        "text": {"verbosity": "low"},
        "include": ["reasoning.encrypted_content"],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
    }
    if tools:
        payload["tools"] = [_tool_to_codex(tool) for tool in tools]
    return payload


def _messages_to_responses_input(messages: list[AgentMessage]) -> list[JSONValue]:
    items: list[JSONValue] = []
    assistant_index = 0
    for message in messages:
        if isinstance(message, UserMessage):
            items.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": message.content}],
                }
            )
        elif isinstance(message, AssistantMessage):
            if message.content:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": message.content,
                                "annotations": [],
                            }
                        ],
                        "status": "completed",
                        "id": f"msg_{assistant_index}",
                    }
                )
                assistant_index += 1
            for tool_call in message.tool_calls:
                call_id, item_id = _split_tool_call_id(tool_call.id)
                item: dict[str, JSONValue] = {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": tool_call.name,
                    "arguments": dumps(tool_call.arguments),
                }
                if item_id:
                    item["id"] = item_id
                items.append(item)
        elif isinstance(message, ToolResultMessage):
            call_id, _item_id = _split_tool_call_id(message.tool_call_id)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": message.content,
                }
            )
    return items


def _tool_to_codex(tool: AgentTool) -> dict[str, JSONValue]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": dict(tool.input_schema),
        "strict": None,
    }


async def _codex_provider_events(
    response: httpx.Response,
    *,
    signal: CancellationToken | None,
) -> AsyncIterator[ProviderEvent]:
    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    current_tool: _ToolCallBuilder | None = None
    finish_reason: str | None = None

    async for event in _iter_sse_objects(response):
        if signal is not None and signal.is_cancelled():
            return
        event_type = event.get("type")
        if not isinstance(event_type, str):
            continue

        if event_type == "error":
            yield ProviderErrorEvent(
                message=_error_message(event, fallback="OpenAI Codex returned an error"),
                data={"event": event},
            )
            return

        if event_type == "response.failed":
            yield ProviderErrorEvent(
                message=_response_error_message(event),
                data={"event": event},
            )
            return

        if event_type == "response.output_item.added":
            item = event.get("item")
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                current_tool = _tool_builder_from_item(item)

        elif event_type == "response.function_call_arguments.delta":
            delta = event.get("delta")
            if current_tool is not None and isinstance(delta, str):
                current_tool.add_delta(delta)

        elif event_type == "response.function_call_arguments.done":
            arguments = event.get("arguments")
            if current_tool is not None and isinstance(arguments, str):
                current_tool.set_arguments(arguments)

        elif event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                content_parts.append(delta)
                yield ProviderTextDeltaEvent(delta=delta)

        elif event_type in {
            "response.output_item.done",
            "response.output_item.completed",
        }:
            item = event.get("item")
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                tool_builder = current_tool or _tool_builder_from_item(item)
                arguments = item.get("arguments")
                if isinstance(arguments, str):
                    tool_builder.set_arguments(arguments)
                tool_call = tool_builder.build()
                tool_calls.append(tool_call)
                current_tool = None
                yield ProviderToolCallEvent(tool_call=tool_call)
            elif isinstance(item, Mapping) and item.get("type") == "message" and not content_parts:
                text = _text_from_done_message(item)
                if text:
                    content_parts.append(text)
                    yield ProviderTextDeltaEvent(delta=text)

        elif event_type in {
            "response.done",
            "response.completed",
            "response.incomplete",
        }:
            finish_reason = _finish_reason_from_response(event)
            break

    yield ProviderResponseEndEvent(
        message=AssistantMessage(content="".join(content_parts), tool_calls=tool_calls),
        finish_reason=finish_reason,
    )


async def _iter_sse_objects(response: httpx.Response) -> AsyncIterator[dict[str, JSONValue]]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        stripped = line.strip()
        if not stripped:
            if data_lines:
                data = "\n".join(data_lines).strip()
                data_lines = []
                parsed = _loads_object(data)
                if parsed is not None:
                    yield parsed
            continue
        if not stripped.startswith("data:"):
            continue
        value = stripped.removeprefix("data:").strip()
        if value == "[DONE]":
            break
        data_lines.append(value)

    if data_lines:
        parsed = _loads_object("\n".join(data_lines).strip())
        if parsed is not None:
            yield parsed


def _tool_builder_from_item(item: Mapping[str, Any]) -> _ToolCallBuilder:
    call_id = item.get("call_id")
    name = item.get("name")
    item_id = item.get("id")
    return _ToolCallBuilder(
        call_id=call_id if isinstance(call_id, str) and call_id else "call_0",
        item_id=item_id if isinstance(item_id, str) and item_id else None,
        name=name if isinstance(name, str) else "",
    )


def _text_from_done_message(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        if part.get("type") == "output_text":
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif part.get("type") == "refusal":
            refusal = part.get("refusal")
            if isinstance(refusal, str):
                parts.append(refusal)
    return "".join(parts)


def _finish_reason_from_response(event: Mapping[str, Any]) -> str | None:
    response = event.get("response")
    if not isinstance(response, Mapping):
        return None
    status = response.get("status")
    if isinstance(status, str):
        return status
    return None


def _response_error_message(event: Mapping[str, Any]) -> str:
    response = event.get("response")
    if isinstance(response, Mapping):
        error = response.get("error")
        if isinstance(error, Mapping):
            message = error.get("message")
            code = error.get("code")
            if isinstance(message, str) and message:
                return message
            if isinstance(code, str) and code:
                return f"OpenAI Codex response failed: {code}"
    return "OpenAI Codex response failed"


def _error_message(event: Mapping[str, Any], *, fallback: str) -> str:
    message = event.get("message")
    if isinstance(message, str) and message:
        return message
    code = event.get("code")
    if isinstance(code, str) and code:
        return code
    return fallback


def _build_codex_headers(
    configured_headers: Mapping[str, str] | None,
    *,
    access_token: str,
    account_id: str,
    originator: str,
) -> dict[str, str]:
    headers = {
        **dict(configured_headers or {}),
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "originator": originator,
        "User-Agent": f"tau ({system()} {release()}; {machine()})",
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    return headers


def _resolve_codex_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/codex/responses"):
        return normalized
    if normalized.endswith("/codex"):
        return f"{normalized}/responses"
    return f"{normalized}/codex/responses"


def _split_tool_call_id(value: str) -> tuple[str, str | None]:
    if "|" not in value:
        return value, None
    call_id, item_id = value.split("|", 1)
    return call_id, item_id or None


def _loads_object(value: str) -> dict[str, JSONValue] | None:
    try:
        loaded = loads(value)
    except JSONDecodeError:
        return None
    if isinstance(loaded, dict):
        return loaded
    return None


def _is_retryable_status(status_code: int, body: str) -> bool:
    if status_code == 429 and _is_terminal_rate_limit(body):
        return False
    return status_code in {408, 409, 425, 429} or status_code >= 500


def _is_terminal_rate_limit(body: str) -> bool:
    normalized = body.lower()
    markers = (
        "gousagelimiterror",
        "freeusagelimiterror",
        "monthly usage limit reached",
        "available balance",
        "insufficient_quota",
        "out of budget",
        "quota exceeded",
        "billing",
    )
    return any(marker in normalized for marker in markers)
