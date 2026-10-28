"""Command-line interface: one-shot question or an interactive session."""

import argparse
import sys

from dotenv import load_dotenv

from citywheels.agent import Agent
from citywheels.config import NOW, PROVIDERS, ConfigError, load_llm_settings
from citywheels.llm import ChatModel, LLMError, OpenAICompatibleModel
from citywheels.prompts import build_system_prompt
from citywheels.tools import Toolbox

EXIT_COMMANDS = frozenset({"exit", "quit"})


def build_agent(provider: str | None = None, model: ChatModel | None = None) -> Agent:
    if model is None:
        model = OpenAICompatibleModel(load_llm_settings(provider))
    return Agent(model, Toolbox.from_data(), build_system_prompt(NOW))


def _ask_and_print(agent: Agent, question: str, verbose: bool) -> None:
    result = agent.ask(question)
    if verbose:
        # stderr keeps stdout limited to the answer, so it stays pipeable.
        for call in result.tool_calls:
            print(f"→ {call.name}({call.arguments})", file=sys.stderr)
    print(result.answer)


def _interactive(agent: Agent, verbose: bool) -> None:
    print("CityWheels help desk. Type 'exit' or 'quit' to leave.")
    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in EXIT_COMMANDS:
            return
        print("Agent: ", end="")
        _ask_and_print(agent, line, verbose)


def main(argv: list[str] | None = None, model: ChatModel | None = None) -> int:
    # On Windows, redirected output defaults to a legacy code page and mangles non-ASCII answers.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="citywheels", description="CityWheels help-desk agent for bike rental customers."
    )
    parser.add_argument("question", nargs="*", help="a single question; omit for interactive mode")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), help="LLM provider to use")
    parser.add_argument("--verbose", action="store_true", help="print tool calls to stderr")
    args = parser.parse_args(argv)

    try:
        agent = build_agent(args.provider, model)
        if args.question:
            _ask_and_print(agent, " ".join(args.question), args.verbose)
        else:
            _interactive(agent, args.verbose)
    except (ConfigError, LLMError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0
