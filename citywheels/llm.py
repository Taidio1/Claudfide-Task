"""Thin LLM client: the single point of contact with the model."""

from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from citywheels.config import LLMSettings


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # Raw JSON string as sent by the model; the toolbox validates it.
    arguments: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()
    # Provider's own view of the turn; excluded from equality as it is only for echoing.
    raw: dict[str, Any] | None = field(default=None, compare=False)

    def to_message(self) -> dict[str, Any]:
        """Serialize back to the chat format so the model sees its own previous turn."""
        if self.raw is not None:
            # Echo verbatim: some providers attach fields (e.g. thought signatures) to tool calls
            # and reject the next request if they are dropped.
            return {**self.raw, "role": "assistant"}
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


class LLMError(Exception):
    """The model could not be reached or returned an unusable response."""


class ChatModel(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage: ...


class OpenAICompatibleModel:
    """Client for OpenAI-compatible endpoints (Gemini, Grok)."""

    def __init__(self, settings: LLMSettings, max_retries: int = 3, timeout: float = 60.0) -> None:
        # The SDK retries 429/5xx with backoff, so no retry code of our own.
        self._client = openai.OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            max_retries=max_retries,
            timeout=timeout,
        )
        self._model = settings.model

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        try:
            # temperature=0 keeps answers reproducible for evaluation.
            response = self._client.chat.completions.create(
                model=self._model, messages=messages, tools=tools, temperature=0
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        if not response.choices:
            raise LLMError("LLM returned no choices.")
        message = response.choices[0].message
        return AssistantMessage(
            content=message.content,
            tool_calls=tuple(
                ToolCall(call.id, call.function.name, call.function.arguments or "")
                for call in message.tool_calls or ()
            ),
            raw=message.model_dump(exclude_none=True),
        )
