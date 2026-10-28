"""Tools exposed to the language model and the dispatcher that runs them."""

import inspect
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Self

from citywheels.bookings import BookingRepository
from citywheels.config import BOOKINGS_PATH, NOW, POLICIES_DIR
from citywheels.policies import PolicyIndex
from citywheels.refund import CancellationTimeError, calculate_refund, parse_cancel_at

# Fixed so the model cannot request huge outputs; a few sections cover any single question.
POLICY_RESULTS = 3
SCORE_DECIMALS = 3
NO_BOOKING_MESSAGE = "No booking with this number."
NO_POLICY_MESSAGE = "No matching policy sections."

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_policies",
            "description": (
                "Search the CityWheels policy documents. Use it for any question about rules, "
                "prices, opening hours, deposits, cancellations, damage, age limits or other "
                "shop policies. Write the query in English, whatever language the customer uses."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Short English search query, e.g. 'late return fee'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking",
            "description": (
                "Get booking details by booking number like CW-1001. Use it whenever the "
                "customer mentions a booking and you need its dates, price, status or payment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "string",
                        "description": "Booking number as the customer wrote it, e.g. CW-1001.",
                    }
                },
                "required": ["booking_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_refund",
            "description": (
                "Calculate the refund for cancelling a booking. This is the ONLY source of "
                "refund amounts: never compute or estimate refunds yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {
                        "type": "string",
                        "description": "Booking number as the customer wrote it, e.g. CW-1001.",
                    },
                    "cancel_at": {
                        "type": "string",
                        "description": (
                            "Optional ISO 8601 date-time with offset, e.g. "
                            "2026-06-11T09:00:00+02:00. Omit to cancel now."
                        ),
                    },
                },
                "required": ["booking_id"],
            },
        },
    },
]


class Toolbox:
    """Runs model-requested tools against injected data, so tests can supply their own."""

    def __init__(self, bookings: BookingRepository, policies: PolicyIndex, now: datetime) -> None:
        self._bookings = bookings
        self._policies = policies
        self._now = now
        # Single source of truth for dispatch; TOOL_SCHEMAS must list exactly these names.
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "search_policies": self.search_policies,
            "get_booking": self.get_booking,
            "calculate_refund": self.calculate_refund,
        }

    @classmethod
    def from_data(cls, now: datetime = NOW) -> Self:
        return cls(
            BookingRepository.from_file(BOOKINGS_PATH), PolicyIndex.from_dir(POLICIES_DIR), now
        )

    def search_policies(self, query: str) -> dict[str, Any]:
        hits = self._policies.search(query, top_k=POLICY_RESULTS)
        if not hits:
            return {"results": [], "message": NO_POLICY_MESSAGE}
        return {
            "results": [
                {
                    "source": section.source,
                    "text": section.text,
                    "score": round(score, SCORE_DECIMALS),
                }
                for section, score in hits
            ]
        }

    def get_booking(self, booking_id: str) -> dict[str, Any]:
        booking = self._bookings.get(booking_id)
        if booking is None:
            return _booking_not_found(booking_id)
        return {"found": True, "booking": booking.to_dict()}

    def calculate_refund(self, booking_id: str, cancel_at: str | None = None) -> dict[str, Any]:
        booking = self._bookings.get(booking_id)
        if booking is None:
            return _booking_not_found(booking_id)
        parsed = None if cancel_at is None else parse_cancel_at(cancel_at, self._now.tzinfo)
        return {"found": True, **calculate_refund(booking, self._now, parsed).to_dict()}

    def execute(self, name: str, arguments: str) -> str:
        """Run a tool and return a JSON string; model mistakes become `{"error": ...}`.

        Only errors the model can fix by retrying are caught; anything else is a bug
        and must stay visible.
        """
        handler = self._handlers.get(name)
        if handler is None:
            return _dump({"error": f"Unknown tool '{name}'."})
        try:
            # Some providers send "" for calls without arguments.
            kwargs = json.loads(arguments) if arguments.strip() else {}
            if not isinstance(kwargs, dict):
                return _dump({"error": "Tool arguments must be a JSON object."})
            # Binding validates names up front, so a TypeError raised inside the handler
            # later is a real bug and is not mistaken for a model mistake.
            bound = inspect.signature(handler).bind(**kwargs)
        except json.JSONDecodeError as exc:
            return _dump({"error": f"Arguments are not valid JSON: {exc}."})
        except TypeError as exc:
            return _dump({"error": f"Invalid arguments for '{name}': {exc}."})
        # Models sometimes send numbers for ids; every tool argument is a string.
        parameters = inspect.signature(handler).parameters
        for arg_name, value in bound.arguments.items():
            optional_none = value is None and parameters[arg_name].default is None
            if not isinstance(value, str) and not optional_none:
                return _dump({"error": f"Argument '{arg_name}' must be a string."})
        try:
            return _dump(handler(*bound.args, **bound.kwargs))
        except CancellationTimeError as exc:
            return _dump({"error": str(exc)})


def _booking_not_found(booking_id: str) -> dict[str, Any]:
    return {"found": False, "booking_id": booking_id, "message": NO_BOOKING_MESSAGE}


def _dump(payload: dict[str, Any]) -> str:
    # ensure_ascii=False keeps non-ASCII text readable (and cheaper in tokens).
    return json.dumps(payload, ensure_ascii=False)
