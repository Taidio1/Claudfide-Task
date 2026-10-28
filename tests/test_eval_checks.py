import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from citywheels.cli import build_agent
from citywheels.config import STAFF_EMAIL, STAFF_PHONE
from citywheels.llm import AssistantMessage, LLMError, ToolCall
from eval.checks import EvalCase, check_case, extract_amounts, load_cases
from eval.run_eval import CaseResult, ReportMeta, format_report, run_case
from tests.fakes import FakeChatModel

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions.toml"


def test_extract_amounts_formats() -> None:
    assert extract_amounts("You get 340 EUR") == {Decimal("340")}
    assert extract_amounts("Total: 340.00") == {Decimal("340")}
    assert extract_amounts("About 11,53 EUR") == {Decimal("11.53")}


def test_check_case_pass() -> None:
    case = EvalCase(
        id="c",
        turns=("q",),
        expect_tools=("calculate_refund",),
        must_contain_amounts=(Decimal("340"),),
        must_contain=("refund",),
    )
    assert check_case(case, "Your Refund is 340.00 EUR.", {"calculate_refund", "get_booking"}) == []


def test_check_case_missing_amount() -> None:
    case = EvalCase(id="c", turns=("q",), must_contain_amounts=(Decimal("340"),))
    reasons = check_case(case, "You get 170 EUR.", set())
    assert len(reasons) == 1
    assert "340" in reasons[0]


def test_check_case_missing_tool() -> None:
    case = EvalCase(id="c", turns=("q",), expect_tools=("calculate_refund",))
    reasons = check_case(case, "340", {"get_booking"})
    assert len(reasons) == 1
    assert "calculate_refund" in reasons[0]


def test_check_case_phrase_rules() -> None:
    case = EvalCase(
        id="c",
        turns=("q",),
        must_contain_any=("not found", "no booking"),
        must_not_contain=("canberra",),
    )
    assert check_case(case, "There is NO BOOKING with that id.", set()) == []
    assert len(check_case(case, "Canberra, and a booking was seen.", set())) == 2


@pytest.mark.parametrize(
    "answer",
    [
        f"Please write to {STAFF_EMAIL}.",
        f"Call {STAFF_PHONE.replace(' ', '')} please.",
        f"Call {STAFF_PHONE}.",
    ],
)
def test_refusal_detected_by_contact(answer: str) -> None:
    case = EvalCase(id="c", turns=("q",), expect_refusal=True)
    assert check_case(case, answer, set()) == []


def test_refusal_missing_contact_fails() -> None:
    case = EvalCase(id="c", turns=("q",), expect_refusal=True)
    assert len(check_case(case, "The capital is Canberra.", set())) == 1


def test_load_cases_from_repo_file() -> None:
    cases = load_cases(QUESTIONS_PATH)
    assert len(cases) >= 10
    assert sum("calculate_refund" in c.expect_tools for c in cases) >= 2
    assert sum(c.expect_refusal for c in cases) >= 2
    assert any(len(c.turns) > 1 for c in cases)


def test_load_cases_rejects_bad_files(tmp_path: Path) -> None:
    both = tmp_path / "both.toml"
    both.write_text('[[case]]\nid = "a"\nquestion = "q"\nturns = ["q"]\n', encoding="utf-8")
    neither = tmp_path / "neither.toml"
    neither.write_text('[[case]]\nid = "a"\n', encoding="utf-8")
    dup = tmp_path / "dup.toml"
    dup.write_text(
        '[[case]]\nid = "a"\nquestion = "q"\n[[case]]\nid = "a"\nquestion = "r"\n',
        encoding="utf-8",
    )
    for path in (both, neither, dup):
        with pytest.raises(ValueError):
            load_cases(path)


def test_run_case_collects_tools_across_turns() -> None:
    args = json.dumps({"booking_id": "CW-1002"})
    model = FakeChatModel(
        [
            AssistantMessage(None, (ToolCall("c1", "calculate_refund", args),)),
            AssistantMessage("340.00 EUR"),
            AssistantMessage("Still 340 EUR."),
        ]
    )
    case = EvalCase(
        id="c",
        turns=("refund CW-1002?", "and tomorrow?"),
        expect_tools=("calculate_refund",),
        must_contain_amounts=(Decimal("340"),),
    )

    result = run_case(case, build_agent(model=model))

    assert result.passed
    assert result.answer == "Still 340 EUR."
    assert result.tool_names == ("calculate_refund",)


def test_run_case_records_llm_error() -> None:
    class Failing:
        def complete(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
            raise LLMError("boom")

    case = EvalCase(id="c", turns=("q",))

    result = run_case(case, build_agent(model=Failing()))

    assert not result.passed
    assert result.reasons == ("LLM error: boom",)


def test_format_report() -> None:
    results = [
        CaseResult("ok_case", ("Q1?",), "A | one", (), ("get_booking",), 1.25),
        CaseResult("bad_case", ("Q2?",), "A two", ("amount missing: 340",), (), 0.5),
    ]
    meta = ReportMeta(
        provider="gemini",
        model="some-model",
        run_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        now=datetime.fromisoformat("2026-06-10T09:00:00+02:00"),
        total_seconds=1.75,
    )

    report = format_report(results, meta)

    assert "**Passed: 1/2**" in report
    assert "some-model" in report
    assert "| ok_case | pass |" in report
    assert "| bad_case | FAIL | amount missing: 340 |" in report
    assert "<details>" in report
    assert "A | one" in report
