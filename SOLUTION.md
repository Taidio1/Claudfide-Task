# CityWheels Help Desk Agent — Solution

A command-line agent that answers CityWheels customer questions from the shop's policy
documents and bookings. The model decides which tool to call; refund amounts are always
computed by code.

## Install and run

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # then set GEMINI_API_KEY (and XAI_API_KEY for Grok)
```

| Task | Command |
| --- | --- |
| Ask one question | `python -m citywheels "I want to cancel booking CW-1002. How much will I get back?"` |
| Interactive session (with memory, `/reset`, `exit`) | `python -m citywheels` |
| Show tool calls | add `--verbose` |
| Use Grok instead of Gemini | add `--provider grok` |
| Tests (no network, no key) | `pytest` |
| Lint | `ruff check .` and `ruff format --check .` |
| Evaluation | `python -m eval.run_eval` (writes `eval/results.md`) |
| Evaluation on Grok | `python -m eval.run_eval --provider grok --out eval/results-grok.md` |

Environment variables (`.env.example`): `LLM_PROVIDER` (`gemini` or `grok`),
`GEMINI_API_KEY`, `XAI_API_KEY`, and optional model overrides `GEMINI_MODEL`, `XAI_MODEL`.

The current time is fixed at `2026-06-10T09:00:00+02:00` (`citywheels/config.py`) and
passed explicitly wherever it is needed; the system clock is never used for business logic.

## Model and provider

- **Gemini** (default) — free tier, which the task explicitly allows. Default model
  `gemini-3.8-flash`; the committed evaluation ran on `gemini-3.5-flash-lite`, which has more
  generous free limits. (`gemini-2.5-flash` is no longer offered to new API users.)
- **Grok** (`grok-4.20-0309-non-reasoning`) — used for the model comparison. A
  non-reasoning model is enough for short tool-calling turns and is cheaper.

Both providers expose an **OpenAI-compatible** chat completions endpoint, so one small client
(`citywheels/llm.py`, using the `openai` package purely as an HTTP client) serves both; the
provider is a configuration choice, not a code change. I did not use an agent framework: the
loop is about fifteen lines, and owning it makes the behaviour easy to explain, test with a
fake model and change.

## How it works

```
cli.py ──> Agent.ask()  ── messages + TOOL_SCHEMAS ──>  ChatModel (Gemini / Grok / fake)
               ^                                              │
               └──── tool result JSON <── Toolbox.execute <───┘ tool calls
```

**Agent loop** (`citywheels/agent.py`). The conversation starts with the system prompt. For
each question: append the user message, call the model, and if it asks for tools, run each
one and append its JSON result as a `tool` message; repeat until the model answers without
tool calls. The loop is capped at `MAX_STEPS = 6`; at the cap, or on an empty answer, the
agent returns a fixed fallback that points to the staff. History is kept between questions,
which gives conversation memory ("and what if I cancel tomorrow instead?"). The model's own
turn is sent back verbatim, because Gemini 3 attaches provider-specific fields to tool calls.
If the API fails in the middle of a turn, that turn is removed from the history (a tool call
without its result would make the provider reject every later request), and the interactive
session prints the error and keeps going.

**Tools** (`citywheels/tools.py`, domain logic in separate modules):

| Tool | What it does |
| --- | --- |
| `search_policies(query)` | Policy Markdown files are split into `##` sections once at start-up and ranked with a small BM25 implementation (`policies.py`); the top 3 sections are returned with their source, e.g. `faq.md#Are there age limits?`. |
| `get_booking(booking_id)` | Bookings are loaded once into a dict. IDs are normalised (`cw1002`, `#CW-1002`, `1002` → `CW-1002`); unknown IDs return `{"found": false, ...}` instead of failing. |
| `calculate_refund(booking_id, cancel_at?)` | Applies the cancellation rules in `refund.py`: 100% at ≥ 48 h, 50% at ≥ 24 h, 0% below (boundaries belong to the higher tier, compared on exact `timedelta`), booking fee never refunded, deposit always refunded, only `confirmed` bookings can be cancelled, card vs voucher refund method. Money uses `Decimal` with one rounding point. `cancel_at` supports hypothetical times for follow-ups. |
| `get_opening_hours(start_date?)` | Extra tool. Returns the hours for 7 days in a row from today (or a given date), with the season (April–October vs November–March), winter Sundays and holidays already applied in `hours.py`. A week rather than one day, so "on Saturday" needs no date arithmetic from the model. Added after the model kept choosing the wrong season (see Evaluation). |

Money is returned to the model as strings with two decimals (`"340.00"`, see `money.py`),
so there is no float for it to re-round or print as `340.0`. Bookings are validated when they
are loaded: an unknown status or payment method stops start-up with a clear error instead of
failing later inside a refund.

`Toolbox.execute` validates arguments before calling a tool. Invalid JSON, unknown tools,
missing or non-string arguments, invalid dates and cancellation times in the past come back to
the model as
`{"error": ...}` so it can correct itself. Real bugs are not caught and stay visible.

**Instructions to the model** (`citywheels/prompts.py`). The system prompt injects the current
time (with weekday and month) and sets these rules: answer only from tool results; search
the policies before answering about rules; take opening hours from `get_opening_hours`; look up
bookings and never invent details; get every amount from `calculate_refund` and copy it
exactly; only inform, never offer to cancel; for out-of-scope questions say so and give the
staff contact; reply in the language of the customer's latest message.

**Tests** (`tests/`, 164 tests, `pytest`). Every refund rule is covered, including exact and
±1 minute boundaries, every non-cancellable status, voucher vs card, zero booking fee,
rounding, and all sample bookings. Tests also cover booking lookup and normalisation, policy
ranking, opening hours (season boundaries, winter Sunday, holidays), booking data validation,
tool dispatch errors, the evaluation checks, and the agent loop and CLI with a scripted
`FakeChatModel`
(tool call → result fed back → final answer, step limit, memory, reset, API errors and
recovery from them). No test uses the network.

## Evaluation

`eval/questions.toml` holds 21 cases: policies, opening hours today and on a holiday, seven
refund calculations (100%, 50% and 0% tiers, the exact 24 h boundary of CW-1010, a voucher
booking, a booking id typed as `cw1001`, and a two-turn follow-up), an unknown, a completed and
an in-progress booking, a refund question without a booking number, a question in Polish, and
four requests the agent must refuse or hand over to the staff (one of them a prompt
injection). The checks in `eval/checks.py` are deterministic and do not use a model as a judge:

- expected tool calls, and tools that must not be called (no booking number, no lookup),
- amounts next to a currency (`EUR`, `euro`, `€`), compared as `Decimal` (`340 EUR` equals
  `€340,00`), so an age or a number of hours cannot satisfy an amount check,
- required and forbidden phrases, matched as whole words (`8:00` does not match `18:00`),
- the staff contact present when a refusal is expected,
- a case fails if the agent hits its step limit, because the fallback answer names the staff
  and would otherwise pass a refusal check.

Latest runs (committed):

| Report | Model | Result | Time | Tool calls |
| --- | --- | --- | --- | --- |
| `eval/results.md` | gemini-3.5-flash-lite | **21/21** | 273 s | 19 |
| `eval/results-grok.md` | grok-4.20-0309-non-reasoning | **21/21** | 45 s | 26 |

The Gemini run used `--delay 10`: without it the free tier answered 11 of 21 cases with
HTTP 429. Those were rate limits, not agent errors, and the runner records them as failed
cases instead of stopping. Earlier, on 15 cases, both models scored 15/15.

Earlier runs, on 14 cases: Gemini 13/14, then 14/14 after a checker fix. Grok 14/14 on the
first version of the suite, then 12/14 and 13/14 once I made it stricter, then 15/15 after
the opening-hours tool (see below). Gemini's time varies a lot with free-tier rate limits
(148–584 s for the same suite).

**What failed, and what I changed:**

- **Grok, `opening_hours_saturday` (fixed in code).** The question is taken word for word
  from the task's README: "What time do you open on Saturday?". Grok answered "09:00
  (November to March schedule applies in June)": it applied the winter rule although the
  prompt gives the date. My first version of the case said "It's June" in the question,
  which hid the problem. Spelling out the month in the prompt and telling the model to apply
  date-dependent rules to the current date fixed Gemini but not Grok. Prompting could not
  make this reliable, so I moved the rule into code, as refunds already were: the
  `get_opening_hours` tool returns the hours valid on each day, and the model only reads
  them. I also added `christmas_closed`, which needs a date outside the current week.
- **Checker too strict on opening hours.** After the fix Grok answered "We open at 08:00 on
  Saturday", which the case failed because it also required "20:00". The question asks only
  when the shop opens, so I dropped that requirement and instead forbid the winter "09:00".
- **The agent offered to cancel.** A manual run showed "Would you like me to proceed with
  the cancellation?". The agent cannot cancel bookings, so this is a false promise. The
  prompt now says it only gives information and the customer contacts staff to cancel, and
  `refund_cw1002` forbids offer phrases. My first forbidden phrase was too broad: it also
  rejected the correct "To proceed with the cancellation, please contact our staff", so I
  narrowed it.
- **Run 1, `unknown_booking`.** The agent's answer was correct ("booking CW-9999 could not
  be found"), but the checker's list of accepted phrases did not include "could not be
  found". This was a false negative in the evaluation, not an agent error. I added the
  missing phrasings and left a comment in the case. Lesson: phrase matching is brittle; a
  better check would read `found: false` from the tool result.
- **Manual smoke test before the evaluation.** An English question about the CW-1002
  refund got a correct answer in Polish. The prompt said "reply in the customer's language",
  and the model seemed to infer Polish from the context (+48 phone number, Warsaw time).
  Changing the rule to "the language of the customer's latest message (an English question
  gets an English answer)" fixed it.
- **Checks that were too loose.** A review of the checker found three ways a wrong answer
  could pass: any number counted as an amount (so "16 years" satisfied an amount of 16),
  phrases matched inside other words (`8:00` inside `18:00`), and a run that hit the step
  limit could pass a refusal case through the fallback text. All three are fixed and tested;
  both models still pass every case under the stricter rules.
- **Model arithmetic slips through.** For CW-1003, Grok wrote "total paid €64", a sum it
  made itself from the booking (12 + 2 + 50). The number is right, but it is exactly what the
  prompt forbids, and no check catches it because it is not a required amount. This is the
  limitation below about grounding, seen in practice.
- **Weak refusal check.** Both models often add the staff contact even to normal answers,
  so "contact present" says little about a real refusal. `capital_australia` is also
  guarded by `must_not_contain = ["Canberra"]`; `poem_off_topic` has no such guard and would
  still pass if the model wrote the poem.

**Model comparison.** Before the opening-hours tool, Gemini was ahead on quality: it applied
the season correctly from the prompt and Grok did not. With the rule in code both pass every
case, which is the point: the less the answer depends on the model's reasoning, the less the
choice of model matters. Other differences:

- **Latency.** Grok was about 20× faster. The Gemini free tier spends most of its time on
  rate limiting and retries (429/503 errors are common at peak times).
- **Tool use.** Grok always calls `get_booking` before `calculate_refund`, which is
  redundant because the refund result already includes status and "not found". Gemini goes
  straight to the refund tool.
- **Formatting.** Grok answers in Markdown, which shows up as raw `**` in a terminal.

## Use of AI coding assistants

I used Claude Code as a coding assistant. It helped me compare options, write boilerplate and
repetitive tests, and get a second opinion on my code. I made the design decisions, wrote the
specifications and tests the code had to meet, and checked each suggestion before keeping it.
Examples where its output was wrong:

- **A regex that failed its own test.** A suggested booking-ID pattern,
  `^(?:CW)?[\s#-]*(\d{4})$`, does not match `#CW-1002`, which my test required. Writing the
  tests first caught it: the test stayed red until I fixed the pattern.
- **Errors swallowed in the tool dispatcher.** A suggested version of `Toolbox.execute`
  caught every `TypeError` around the tool call. That hid real bugs inside tools, and a
  numeric booking id (`{"booking_id": 1002}`) still crashed the loop. I found both in code
  review. The dispatcher now validates arguments before the call and catches nothing else.
- **Outdated model knowledge.** The suggested default model (`gemini-2.5-flash`) is no longer
  available to new API users. I noticed while checking the provider's current documentation.

## Limitations

- Policy search is lexical (BM25 with light stemming). A paraphrase with no shared words can
  miss the right section, and the documents are English only. The model is told to write
  queries in English, which works in practice but is not guaranteed.
- The time zone is a fixed `+02:00` offset. That is correct for the June data, but would be
  wrong in winter; `zoneinfo` would fix it.
- The agent only informs. It does not cancel or change bookings, and it has no
  authentication, so anyone who knows a booking number can see that booking.
- Grounding relies on the prompt: nothing in the code stops the model from adding a fact
  that is not in the tool results. Amounts are safe only as long as the model copies them.
- The evaluation is small (21 cases, one run per model) and refusal detection is weak.
- Opening hours exist twice: in `faq.md` and as constants in `hours.py`. A change to the
  policy has to be made in both places; tests pin the current rules.

## Next steps

- Harder evaluation cases:
  - mixed questions that need several tools,
  - more prompt-injection variants (e.g. inside a fake booking number),
  - a hypothetical cancellation after the rental start,
  - several runs per case to measure variance.
- A stronger check that each amount in the answer matches the amounts the tools returned.
- Show refunds in a fixed template built in code, so the model cannot misquote money.
- Semantic or hybrid search for policies, and a real `Europe/Warsaw` time zone.
- Plain-text output mode for Markdown-heavy models in the terminal.
