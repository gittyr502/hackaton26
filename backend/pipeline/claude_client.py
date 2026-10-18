"""Thin async wrapper around the Claude API: forced tool use, concurrency limit, backoff."""
import asyncio
import random
from typing import Any, Dict, Optional

import anthropic

from app.logging_utils import get_logger, log_event

log = get_logger("claude")

RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)

TOOL_ONLY_INSTRUCTION = (
    "Return your result ONLY by calling the `{name}` tool, exactly once. "
    "Do not reply with plain text, explanations, or markdown."
)


class NoToolUseError(RuntimeError):
    """The model answered without calling the required tool (retried like a transient error)."""


class ClaudeClient:
    def __init__(self, api_key: str, model: str, concurrency: int = 5,
                 max_retries: int = 4, base_delay: float = 1.0, max_tokens: int = 2048):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self.model = model
        self._concurrency = concurrency
        self._sem: Optional[asyncio.Semaphore] = None
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_tokens = max_tokens

    @property
    def sem(self) -> asyncio.Semaphore:
        # created lazily so it binds to the running event loop
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._concurrency)
        return self._sem

    async def call_tool(self, image_b64: str, media_type: str, prompt: str,
                        tool: Dict[str, Any], system: Optional[str] = None) -> Dict[str, Any]:
        """Send one page image + prompt, force `tool`, return the tool input dict."""
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }]
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            tools=[tool],
            # Some models reject tool_choice "tool"/"any"; with "auto" the system prompt
            # requires the tool, and a reply without tool_use is retried below.
            tool_choice={"type": "auto"},
            messages=messages,
            system=f"{system}\n\n{TOOL_ONLY_INSTRUCTION.format(name=tool['name'])}"
            if system else TOOL_ONLY_INSTRUCTION.format(name=tool["name"]),
        )

        attempt = 0
        while True:
            try:
                async with self.sem:
                    resp = await self._client.messages.create(**kwargs)
                for block in resp.content:
                    if block.type == "tool_use" and block.name == tool["name"]:
                        return dict(block.input)
                raise NoToolUseError(f"model returned no {tool['name']} tool_use block")
            except RETRYABLE + (NoToolUseError,) as e:
                attempt += 1
                if attempt > self.max_retries:
                    raise
                delay = self.base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log_event(log, "claude_retry", attempt=attempt, error=type(e).__name__)
                await asyncio.sleep(delay)
