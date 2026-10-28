import json

import pytest

from citywheels import cli
from citywheels.cli import main
from citywheels.llm import AssistantMessage, LLMError, ToolCall
from tests.fakes import FakeChatModel


class FailingModel:
    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        raise LLMError("LLM request failed: boom")


def test_single_question_prints_answer(capsys: pytest.CaptureFixture[str]) -> None:
    model = FakeChatModel([AssistantMessage("You get 340.00 EUR")])

    code = main(["Refund", "for", "CW-1002?"], model=model)

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "You get 340.00 EUR"
    assert model.calls[0][-1] == {"role": "user", "content": "Refund for CW-1002?"}


def test_verbose_prints_tool_calls_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    arguments = json.dumps({"booking_id": "CW-1002"})
    model = FakeChatModel(
        [
            AssistantMessage(None, (ToolCall("call_1", "calculate_refund", arguments),)),
            AssistantMessage("340.00 EUR"),
        ]
    )

    code = main(["Refund?", "--verbose"], model=model)

    captured = capsys.readouterr()
    assert code == 0
    assert f"→ calculate_refund({arguments})" in captured.err
    assert captured.out.strip() == "340.00 EUR"


def test_llm_error_exits_with_code_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["Hello"], model=FailingModel())

    captured = capsys.readouterr()
    assert code == 1
    assert "Error: LLM request failed: boom" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_missing_key_exits_with_code_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    code = main(["Hello"])

    captured = capsys.readouterr()
    assert code == 1
    assert "GEMINI_API_KEY" in captured.err
    assert "Traceback" not in captured.err


def test_interactive_mode_answers_until_exit(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = iter(["", "Hi there", "EXIT"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    model = FakeChatModel([AssistantMessage("Hello!")])

    code = main([], model=model)

    captured = capsys.readouterr()
    assert code == 0
    assert "Agent: Hello!" in captured.out
    assert len(model.calls) == 1


def test_interactive_mode_survives_llm_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailsOnce(FakeChatModel):
        def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
            if not self.calls:
                self.calls.append(messages)
                raise LLMError("LLM request failed: boom")
            return super().complete(messages, tools)

    inputs = iter(["First", "Second", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    code = main([], model=FailsOnce([AssistantMessage("Hello!")]))

    captured = capsys.readouterr()
    assert code == 0
    assert "Error: LLM request failed: boom" in captured.err
    assert "Agent: Hello!" in captured.out


def test_interactive_mode_ends_cleanly_on_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert main([], model=FakeChatModel([])) == 0


def test_interactive_mode_keeps_memory_between_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["Refund for CW-1007?", "And tomorrow?", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    model = FakeChatModel([AssistantMessage("186.00 EUR"), AssistantMessage("168.00 EUR")])

    main([], model=model)

    second_call = model.calls[1]
    assert {"role": "user", "content": "Refund for CW-1007?"} in second_call
    assert {"role": "assistant", "content": "186.00 EUR"} in second_call


def test_reset_command_clears_memory(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = iter(["Refund for CW-1007?", "/reset", "Opening hours?", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))
    model = FakeChatModel([AssistantMessage("186.00 EUR"), AssistantMessage("08:00-20:00")])

    main([], model=model)

    assert "Conversation cleared." in capsys.readouterr().out
    assert [m["role"] for m in model.calls[1]] == ["system", "user"]
