"""The agent loop: the model picks a tool, we run it, the result goes back."""

from dataclasses import dataclass

from citywheels.config import STAFF_EMAIL, STAFF_PHONE
from citywheels.llm import ChatModel, ToolCall
from citywheels.tools import TOOL_SCHEMAS, Toolbox

# Caps model calls so a confused model cannot loop (and bill) forever.
MAX_STEPS = 6

FALLBACK_ANSWER = (
    f"I'm sorry, I can't answer that reliably. "
    f"Please contact our staff at {STAFF_EMAIL} or {STAFF_PHONE}."
)


@dataclass(frozen=True)
class AgentResult:
    answer: str
    tool_calls: tuple[ToolCall, ...]
    hit_step_limit: bool = False


class Agent:
    def __init__(
        self, model: ChatModel, toolbox: Toolbox, system_prompt: str, max_steps: int = MAX_STEPS
    ) -> None:
        self._model = model
        self._toolbox = toolbox
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._messages: list[dict] = []
        self.reset()

    def reset(self) -> None:
        self._messages = [{"role": "system", "content": self._system_prompt}]

    def ask(self, question: str) -> AgentResult:
        # History (incl. tool results) is kept so follow-ups know the booking number.
        turn_start = len(self._messages)
        self._messages.append({"role": "user", "content": question})
        try:
            return self._run_turn()
        except Exception:
            # A half-finished turn (e.g. tool calls without results) would make the
            # provider reject every later request, so the failed turn is dropped.
            del self._messages[turn_start:]
            raise

    def _run_turn(self) -> AgentResult:
        trace: list[ToolCall] = []

        for _ in range(self._max_steps):
            reply = self._model.complete(self._messages, TOOL_SCHEMAS)
            self._messages.append(reply.to_message())

            if not reply.tool_calls:
                answer = (reply.content or "").strip() or FALLBACK_ANSWER
                return AgentResult(answer, tuple(trace))

            for call in reply.tool_calls:
                trace.append(call)
                result = self._toolbox.execute(call.name, call.arguments)
                self._messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        # Close the turn so the next ask() does not follow orphan tool messages.
        self._messages.append({"role": "assistant", "content": FALLBACK_ANSWER})
        return AgentResult(FALLBACK_ANSWER, tuple(trace), hit_step_limit=True)
