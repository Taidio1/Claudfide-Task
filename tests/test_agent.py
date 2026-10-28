import json

from citywheels.agent import FALLBACK_ANSWER, MAX_STEPS, Agent
from citywheels.config import NOW, STAFF_EMAIL, STAFF_PHONE
from citywheels.llm import AssistantMessage, ToolCall
from citywheels.prompts import build_system_prompt
from citywheels.tools import Toolbox
from tests.fakes import FakeChatModel

SYSTEM_PROMPT = "system"


def tool_reply(*calls: ToolCall) -> AssistantMessage:
    return AssistantMessage(content=None, tool_calls=calls)


def refund_call(call_id: str = "call_1", booking_id: str = "CW-1002") -> ToolCall:
    return ToolCall(call_id, "calculate_refund", json.dumps({"booking_id": booking_id}))


def make_agent(replies: list[AssistantMessage]) -> tuple[Agent, FakeChatModel]:
    model = FakeChatModel(replies)
    return Agent(model, Toolbox.from_data(), SYSTEM_PROMPT), model


def test_agent_runs_tool_and_returns_final_answer() -> None:
    agent, model = make_agent([tool_reply(refund_call()), AssistantMessage("You get 340.00 EUR")])

    result = agent.ask("Refund for CW-1002?")

    assert result.answer == "You get 340.00 EUR"
    assert result.hit_step_limit is False
    assert result.tool_calls[0].name == "calculate_refund"
    tool_messages = [m for m in model.calls[1] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert json.loads(tool_messages[0]["content"])["total_refund_eur"] == 340.0


def test_agent_handles_multiple_tool_calls_in_one_reply() -> None:
    agent, model = make_agent(
        [
            tool_reply(
                refund_call("call_a", "CW-1002"),
                ToolCall("call_b", "get_booking", '{"booking_id":"CW-1001"}'),
            ),
            AssistantMessage("Done"),
        ]
    )

    result = agent.ask("Two things")

    assert [c.id for c in result.tool_calls] == ["call_a", "call_b"]
    tool_ids = [m["tool_call_id"] for m in model.calls[1] if m["role"] == "tool"]
    assert tool_ids == ["call_a", "call_b"]


def test_agent_stops_at_step_limit() -> None:
    agent, model = make_agent([tool_reply(refund_call(f"call_{i}")) for i in range(MAX_STEPS)])

    result = agent.ask("Loop forever")

    assert result.hit_step_limit is True
    assert result.answer == FALLBACK_ANSWER
    assert len(model.calls) == MAX_STEPS
    assert len(result.tool_calls) == MAX_STEPS


def test_empty_final_answer_falls_back() -> None:
    agent, _ = make_agent([AssistantMessage(content=None)])
    assert agent.ask("Hello").answer == FALLBACK_ANSWER


def test_whitespace_final_answer_falls_back() -> None:
    agent, _ = make_agent([AssistantMessage(content="  \n")])
    assert agent.ask("Hello").answer == FALLBACK_ANSWER


def test_conversation_memory_keeps_history() -> None:
    agent, model = make_agent(
        [tool_reply(refund_call()), AssistantMessage("340.00 EUR"), AssistantMessage("Sure")]
    )

    agent.ask("Refund for CW-1002?")
    agent.ask("And tomorrow?")

    third_call = model.calls[2]
    contents = [m.get("content") for m in third_call]
    assert "Refund for CW-1002?" in contents
    assert any(m["role"] == "tool" and "total_refund_eur" in m["content"] for m in third_call)
    assert third_call[-1] == {"role": "user", "content": "And tomorrow?"}


def test_reset_clears_history() -> None:
    agent, model = make_agent([AssistantMessage("one"), AssistantMessage("two")])

    agent.ask("first question")
    agent.reset()
    agent.ask("second question")

    assert [m["role"] for m in model.calls[1]] == ["system", "user"]
    assert model.calls[1][0]["content"] == SYSTEM_PROMPT


def test_system_prompt_contains_now_and_contact() -> None:
    prompt = build_system_prompt(NOW)

    assert NOW.isoformat() in prompt
    assert NOW.strftime("%A") in prompt
    assert STAFF_EMAIL in prompt
    assert STAFF_PHONE in prompt
    for tool in ("search_policies", "get_booking", "calculate_refund"):
        assert tool in prompt


def test_step_limit_keeps_history_valid() -> None:
    agent, model = make_agent(
        [tool_reply(refund_call(f"call_{i}")) for i in range(MAX_STEPS)]
        + [AssistantMessage("Next answer")]
    )

    agent.ask("Loop forever")
    agent.ask("Still there?")

    # The follow-up must not see a history that ends in orphan tool messages.
    follow_up = model.calls[MAX_STEPS]
    assert follow_up[-2] == {"role": "assistant", "content": FALLBACK_ANSWER}
    assert follow_up[-1] == {"role": "user", "content": "Still there?"}
