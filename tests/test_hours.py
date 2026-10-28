from datetime import date, timedelta

import pytest

from citywheels.hours import InvalidDateError, hours_on, parse_date, week_from


def hours_text(day: date) -> str | None:
    return hours_on(day).to_dict()["hours"]


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 4, 1),  # first summer day
        date(2026, 6, 13),  # Saturday
        date(2026, 6, 14),  # Sunday: open in summer
        date(2026, 10, 31),  # last summer day
    ],
)
def test_summer_every_day_8_to_20(day: date) -> None:
    assert hours_text(day) == "08:00–20:00"


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 3, 31),  # last winter day (Tuesday)
        date(2026, 11, 2),  # first winter Monday
        date(2026, 11, 7),  # Saturday
    ],
)
def test_winter_monday_to_saturday_9_to_17(day: date) -> None:
    assert hours_text(day) == "09:00–17:00"


def test_winter_sunday_closed() -> None:
    result = hours_on(date(2026, 11, 1)).to_dict()  # Sunday
    assert result["open"] is False
    assert result["hours"] is None


@pytest.mark.parametrize("day", [date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1)])
def test_holidays_closed(day: date) -> None:
    assert hours_on(day).to_dict()["open"] is False


def test_to_dict_names_weekday() -> None:
    assert hours_on(date(2026, 6, 13)).to_dict() == {
        "date": "2026-06-13",
        "weekday": "Saturday",
        "open": True,
        "hours": "08:00–20:00",
    }


def test_week_from_returns_seven_consecutive_days() -> None:
    week = week_from(date(2026, 6, 10))
    assert [d.day for d in week] == [date(2026, 6, 10) + timedelta(days=i) for i in range(7)]


def test_parse_date_rejects_garbage() -> None:
    with pytest.raises(InvalidDateError):
        parse_date("next saturday")


def test_parse_date_accepts_iso() -> None:
    assert parse_date("2026-12-25") == date(2026, 12, 25)
