"""ClaudeClient against a fake Messages API: forced tool_choice (auto for models that reject it), tool-only system prompt,
and a reply without tool_use is retried through the existing backoff loop."""
import asyncio
from types import SimpleNamespace

import pytest

from pipeline.claude_client import ClaudeClient, NoToolUseError

TOOL = {"name": "record_form", "description": "d", "input_schema": {"type": "object", "properties": {}}}
TOOL_REPLY = SimpleNamespace(content=[
    SimpleNamespace(type="text", text="Here you go"),
    SimpleNamespace(type="tool_use", name="record_form", input={"full_name": {"value": "דנה"}}),
])
TEXT_REPLY = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"full_name": "דנה"}')])


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def make_client(replies, max_retries=2):
    client = ClaudeClient(api_key="test", model="m", max_retries=max_retries, base_delay=0)
    fake = FakeMessages(replies)
    client._client = SimpleNamespace(messages=fake)
    return client, fake


def call(client, system="SYS"):
    return asyncio.run(client.call_tool("b64", "image/jpeg", "prompt", TOOL, system=system))


def test_forces_the_tool_and_adds_tool_only_instruction():
    client, fake = make_client([TOOL_REPLY])
    assert call(client) == {"full_name": {"value": "דנה"}}
    kwargs = fake.calls[0]
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_form"}
    assert [dict(t, cache_control=None) for t in kwargs["tools"]] == [dict(TOOL, cache_control=None)]
    assert system_text(kwargs).startswith("SYS")
    assert "ONLY by calling the `record_form` tool" in system_text(kwargs)


def system_text(kwargs) -> str:
    return "".join(b["text"] for b in kwargs["system"])


def test_tool_only_instruction_without_system_prompt():
    client, fake = make_client([TOOL_REPLY])
    call(client, system=None)
    assert "record_form" in system_text(fake.calls[0])


def test_text_only_reply_is_retried_then_succeeds():
    client, fake = make_client([TEXT_REPLY, TEXT_REPLY, TOOL_REPLY], max_retries=2)
    assert call(client) == {"full_name": {"value": "דנה"}}
    assert len(fake.calls) == 3


def test_gives_up_after_max_retries():
    client, fake = make_client([TEXT_REPLY] * 3, max_retries=2)
    with pytest.raises(NoToolUseError):
        call(client)
    assert len(fake.calls) == 3  # first try + 2 retries


def test_wrong_tool_name_counts_as_missing():
    other = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="other_tool", input={})])
    client, fake = make_client([other, TOOL_REPLY], max_retries=1)
    assert call(client) == {"full_name": {"value": "דנה"}}
    assert len(fake.calls) == 2


def test_model_rejecting_forced_tool_choice_falls_back_to_auto_and_remembers():
    import anthropic
    import httpx

    resp = httpx.Response(400, request=httpx.Request("POST", "https://x"))
    rejected = anthropic.BadRequestError('tool_choice: type "tool" and "any" are not supported for this model.',
                                         response=resp, body=None)

    class Rejecting(FakeMessages):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["tool_choice"]["type"] != "auto":
                raise rejected
            return TOOL_REPLY

    client = ClaudeClient(api_key="test", model="m", max_retries=0, base_delay=0)
    fake = Rejecting([])
    client._client = SimpleNamespace(messages=fake)
    assert call(client) == {"full_name": {"value": "דנה"}}
    assert call(client) == {"full_name": {"value": "דנה"}}
    assert [c["tool_choice"]["type"] for c in fake.calls] == ["tool", "auto", "auto"]
