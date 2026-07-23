import pytest

from tau_agent import (
    MessageDeltaEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
)
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AssistantMessage, UserMessage
from tau_agent.provider_events import (
    AssistantDoneEvent,
    AssistantStartEvent,
    TextDeltaEvent,
)
from tau_ai import (
    FakeProvider,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderTextDeltaEvent,
)


@pytest.mark.anyio
async def test_agent_loop_emits_pi_shaped_message_updates_alongside_legacy_events() -> None:
    messages = [UserMessage(content="hi")]
    provider = FakeProvider(
        [
            [
                ProviderResponseStartEvent(model="fake"),
                ProviderTextDeltaEvent(delta="hello"),
                ProviderResponseEndEvent(message=AssistantMessage(content="hello")),
            ]
        ]
    )

    events = [
        event
        async for event in run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    ]

    assert any(isinstance(event, MessageStartEvent) for event in events)
    assert any(isinstance(event, MessageDeltaEvent) for event in events)
    assert any(isinstance(event, MessageEndEvent) for event in events)
    updates = [event for event in events if isinstance(event, MessageUpdateEvent)]
    assert isinstance(updates[0].assistant_message_event, AssistantStartEvent)
    assert isinstance(updates[1].assistant_message_event, TextDeltaEvent)
    assert isinstance(updates[-1].assistant_message_event, AssistantDoneEvent)
