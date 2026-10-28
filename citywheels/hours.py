"""Opening hours by date (faq.md#When are you open?), applied in code.

Picking the seasonal rule was left to the model at first, and it picked the winter hours
in June; a date lookup cannot get that wrong.
"""

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

SUMMER_MONTHS = range(4, 11)  # April to October
SUMMER_HOURS = (time(8), time(20))
WINTER_HOURS = (time(9), time(17))
SUNDAY = 6  # date.weekday()
DAYS_PER_WEEK = 7
CLOSED_DAYS = frozenset({(12, 25), (12, 26), (1, 1)})  # (month, day), every year
HOURS_SOURCE = "faq.md#When are you open?"


class InvalidDateError(ValueError):
    """The requested date is not a valid ISO 8601 date."""


@dataclass(frozen=True)
class DayHours:
    day: date
    # None when the shop is closed all day.
    hours: tuple[time, time] | None

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form for tool output."""
        hours = None
        if self.hours is not None:
            opens, closes = self.hours
            hours = f"{opens:%H:%M}–{closes:%H:%M}"
        return {
            "date": self.day.isoformat(),
            "weekday": self.day.strftime("%A"),
            "open": hours is not None,
            "hours": hours,
        }


def hours_on(day: date) -> DayHours:
    if (day.month, day.day) in CLOSED_DAYS:
        return DayHours(day, None)
    if day.month in SUMMER_MONTHS:
        return DayHours(day, SUMMER_HOURS)
    if day.weekday() == SUNDAY:
        return DayHours(day, None)
    return DayHours(day, WINTER_HOURS)


def week_from(start: date) -> list[DayHours]:
    """Seven consecutive days, so "on Saturday" needs no date arithmetic from the model."""
    return [hours_on(start + timedelta(days=offset)) for offset in range(DAYS_PER_WEEK)]


def parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidDateError(f"'{raw}' is not a valid ISO 8601 date, e.g. 2026-12-24.") from exc
