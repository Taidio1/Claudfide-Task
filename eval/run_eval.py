"""Run the agent on every evaluation case and write a markdown report.

Usage: python -m eval.run_eval [--provider P] [--out PATH] [--delay SECONDS]
"""

import argparse
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from citywheels.agent import Agent
from citywheels.cli import build_agent
from citywheels.config import NOW, PROVIDERS, ConfigError, load_llm_settings
from citywheels.llm import LLMError
from eval.checks import EvalCase, check_case, load_cases

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_QUESTIONS = EVAL_DIR / "questions.toml"
DEFAULT_OUT = EVAL_DIR / "results.md"


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    turns: tuple[str, ...]
    answer: str
    reasons: tuple[str, ...]
    tool_names: tuple[str, ...]  # full trace in call order, duplicates kept
    seconds: float

    @property
    def passed(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class ReportMeta:
    provider: str
    model: str
    run_at: datetime
    now: datetime
    total_seconds: float


def run_case(case: EvalCase, agent: Agent) -> CaseResult:
    started = time.perf_counter()
    tool_names: list[str] = []
    answer = ""
    try:
        for question in case.turns:
            result = agent.ask(question)
            answer = result.answer
            tool_names.extend(call.name for call in result.tool_calls)
    except LLMError as exc:
        # A provider failure is a failed case, not a reason to abort the whole run.
        reasons: tuple[str, ...] = (f"LLM error: {exc}",)
    else:
        reasons = tuple(check_case(case, answer, set(tool_names)))
    return CaseResult(
        case.id, case.turns, answer, reasons, tuple(tool_names), time.perf_counter() - started
    )


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _fence(text: str) -> str:
    # A fence longer than any backtick run in the text cannot be closed by the text itself.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{text}\n{ticks}"


def format_report(results: list[CaseResult], meta: ReportMeta) -> str:
    passed = sum(result.passed for result in results)
    lines = [
        "# Evaluation results",
        "",
        f"- Provider: {meta.provider}",
        f"- Model: {meta.model}",
        f"- Run at (UTC): {meta.run_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Agent clock (`NOW`): {meta.now.isoformat()}",
        f"- Total time: {meta.total_seconds:.1f} s",
        "",
        f"**Passed: {passed}/{len(results)}**",
        "",
        "| id | result | failure reasons | tools called | time (s) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {'pass' if result.passed else 'FAIL'} "
            f"| {_cell('; '.join(result.reasons))} | {_cell(', '.join(result.tool_names))} "
            f"| {result.seconds:.1f} |"
        )

    lines += ["", "## Answers", ""]
    for result in results:
        status = "pass" if result.passed else "FAIL"
        lines += [f"<details><summary>{result.case_id} ({status})</summary>", ""]
        lines += [f"**Question {i}:** {text}" for i, text in enumerate(result.turns, 1)]
        lines += ["", "**Answer:**", "", _fence(result.answer), "", "</details>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    # On Windows, redirected output defaults to a legacy code page and mangles non-ASCII text.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    load_dotenv()

    parser = argparse.ArgumentParser(prog="eval.run_eval", description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), help="LLM provider to use")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="markdown report path")
    parser.add_argument(
        "--delay", type=float, default=0.0, help="seconds to pause between cases (rate limits)"
    )
    args = parser.parse_args(argv)

    try:
        settings = load_llm_settings(args.provider)
        cases = load_cases(DEFAULT_QUESTIONS)
    except (ConfigError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    run_started = time.perf_counter()
    results: list[CaseResult] = []
    for index, case in enumerate(cases):
        if index and args.delay > 0:
            time.sleep(args.delay)
        # Fresh agent per case so one case's history cannot leak into the next.
        result = run_case(case, build_agent(args.provider))
        results.append(result)
        print(f"{'pass' if result.passed else 'FAIL'}  {case.id}", file=sys.stderr)

    meta = ReportMeta(
        provider=settings.provider,
        model=settings.model,
        # Real clock on purpose: this is run metadata, not the shop's business time (NOW).
        run_at=datetime.now(UTC),
        now=NOW,
        total_seconds=time.perf_counter() - run_started,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(format_report(results, meta), encoding="utf-8")

    passed = sum(result.passed for result in results)
    print(f"Passed {passed}/{len(results)} ({settings.provider}/{settings.model}) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
