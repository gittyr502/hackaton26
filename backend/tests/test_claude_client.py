"""ClaudeClient against a fake Messages API: tool_choice auto, tool-only system prompt,
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


def test_uses_auto_tool_choice_and_tool_only_instruction():
    client, fake = make_client([TOOL_REPLY])
    assert call(client) == {"full_name": {"value": "דנה"}}
    kwargs = fake.calls[0]
    assert kwargs["tool_choice"] == {"type": "auto"}
    assert kwargs["tools"] == [TOOL]
    assert kwargs["system"].startswith("SYS")
    assert "ONLY by calling the `record_form` tool" in kwargs["system"]


def test_tool_only_instruction_without_system_prompt():
    client, fake = make_client([TOOL_REPLY])
    call(client, system=None)
    assert "record_form" in fake.calls[0]["system"]


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
