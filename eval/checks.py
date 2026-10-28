"""Deterministic answer checks for the evaluation suite.

No model-as-judge: every rule is a plain string, number or tool-name comparison,
so a run's verdict depends only on the agent's output, never on a grader's mood.
"""

import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from citywheels.config import STAFF_EMAIL, STAFF_PHONE

# Shop amounts are small (no thousands separators), so a comma is always a decimal comma.
_NUMBER = r"(\d+(?:[.,]\d{1,2})?)"
_CURRENCY = r"(?:€|\beur(?:os?)?\b)"
# Only numbers next to a currency count as money, so "16 years" or "33 hours" cannot
# satisfy an amount check by accident.
_MONEY_RE = re.compile(
    rf"{_CURRENCY}\s*{_NUMBER}|(?<![\d.,]){_NUMBER}\s*{_CURRENCY}", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s+")
# Models mix typographic and plain apostrophes ("can’t" vs "can't").
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'"})


@dataclass(frozen=True)
class EvalCase:
    id: str
    turns: tuple[str, ...]
    expect_tools: tuple[str, ...] = ()
    must_contain_amounts: tuple[Decimal, ...] = ()
    must_contain: tuple[str, ...] = ()
    must_contain_any: tuple[str, ...] = ()
    must_not_contain: tuple[str, ...] = ()
    must_not_call: tuple[str, ...] = ()
    expect_refusal: bool = False


def load_cases(path: Path) -> list[EvalCase]:
    with path.open("rb") as file:
        raw_cases = tomllib.load(file).get("case", [])

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for raw in raw_cases:
        case_id = raw["id"]
        if case_id in seen:
            raise ValueError(f"Duplicate case id: {case_id}")
        seen.add(case_id)
        if ("question" in raw) == ("turns" in raw):
            raise ValueError(f"Case {case_id} needs exactly one of 'question' or 'turns'")
        turns = tuple(raw["turns"]) if "turns" in raw else (raw["question"],)
        cases.append(
            EvalCase(
                id=case_id,
                turns=turns,
                expect_tools=tuple(raw.get("expect_tools", ())),
                # str() first: a TOML float would otherwise drag binary noise into the Decimal.
                must_contain_amounts=tuple(
                    Decimal(str(value)) for value in raw.get("must_contain_amounts", ())
                ),
                must_contain=tuple(raw.get("must_contain", ())),
                must_contain_any=tuple(raw.get("must_contain_any", ())),
                must_not_contain=tuple(raw.get("must_not_contain", ())),
                must_not_call=tuple(raw.get("must_not_call", ())),
                expect_refusal=bool(raw.get("expect_refusal", False)),
            )
        )
    return cases


def extract_amounts(text: str) -> set[Decimal]:
    """Money amounts in the text as Decimals, so 340 EUR, €340.00 and 340,00 € compare equal."""
    return {
        Decimal((before or after).replace(",", ".")) for before, after in _MONEY_RE.findall(text)
    }


def contains_phrase(text: str, phrase: str) -> bool:
    """Case-insensitive whole-word match, so "8:00" does not match inside "18:00"."""
    pattern = rf"(?<!\w){re.escape(phrase.translate(_APOSTROPHES))}(?!\w)"
    return re.search(pattern, text.translate(_APOSTROPHES), re.IGNORECASE) is not None


def _refers_to_staff(answer: str) -> bool:
    # Phone spacing varies between answers, so compare with whitespace removed.
    compact_answer = _WHITESPACE_RE.sub("", answer)
    return STAFF_EMAIL in answer or _WHITESPACE_RE.sub("", STAFF_PHONE) in compact_answer


def check_case(case: EvalCase, answer: str, tool_names: set[str]) -> list[str]:
    """Return failure reasons; an empty list means the case passed."""
    reasons: list[str] = []

    for tool in case.expect_tools:
        if tool not in tool_names:
            reasons.append(f"tool not called: {tool}")

    for tool in case.must_not_call:
        if tool in tool_names:
            reasons.append(f"forbidden tool called: {tool}")

    found = extract_amounts(answer)
    for amount in case.must_contain_amounts:
        if amount not in found:
            reasons.append(f"amount missing: {amount}")

    for phrase in case.must_contain:
        if not contains_phrase(answer, phrase):
            reasons.append(f"phrase missing: {phrase!r}")

    if case.must_contain_any and not any(contains_phrase(answer, p) for p in case.must_contain_any):
        options = ", ".join(repr(p) for p in case.must_contain_any)
        reasons.append(f"none of the phrases present: {options}")

    for phrase in case.must_not_contain:
        if contains_phrase(answer, phrase):
            reasons.append(f"forbidden phrase present: {phrase!r}")

    if case.expect_refusal and not _refers_to_staff(answer):
        reasons.append("no staff contact in answer (expected refusal)")

    return reasons
