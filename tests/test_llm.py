from citywheels.llm import AssistantMessage, ToolCall


def test_to_message_echoes_raw_turn_with_provider_fields() -> None:
    raw = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_booking", "arguments": "{}"},
                "extra_content": {"google": {"thought_signature": "abc"}},
            }
        ],
    }
    message = AssistantMessage(None, (ToolCall("call_1", "get_booking", "{}"),), raw=raw)

    result = message.to_message()

    assert result["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "abc"}}
    assert result is not raw


def test_to_message_forces_assistant_role_for_raw() -> None:
    assert AssistantMessage("hi", raw={"content": "hi"}).to_message()["role"] == "assistant"


def test_to_message_without_raw_builds_standard_format() -> None:
    message = AssistantMessage("hi", (ToolCall("c1", "get_booking", '{"a":1}'),))

    assert message.to_message() == {
        "role": "assistant",
        "content": "hi",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "get_booking", "arguments": '{"a":1}'},
            }
        ],
    }
    assert AssistantMessage("plain").to_message() == {"role": "assistant", "content": "plain"}
