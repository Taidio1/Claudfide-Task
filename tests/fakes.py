"""Test doubles shared across test modules."""

import copy

from citywheels.llm import AssistantMessage


class FakeChatModel:
    """Replays scripted replies and records what the agent sent."""

    def __init__(self, replies: list[AssistantMessage]) -> None:
        self._replies = iter(replies)
        # Deep copies: the agent keeps mutating its message list after each call.
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        self.calls.append(copy.deepcopy(messages))
        try:
            return next(self._replies)
        except StopIteration:
            raise AssertionError("FakeChatModel has no more scripted replies") from None
