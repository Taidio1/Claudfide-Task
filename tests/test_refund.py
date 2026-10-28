from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from citywheels.bookings import Booking, BookingRepository
from citywheels.config import BOOKINGS_PATH, NOW
from citywheels.refund import (
    CancellationTimeError,
    calculate_refund,
    parse_cancel_at,
    to_money,
)

ZERO = Decimal("0.00")


def make_booking(**overrides: Any) -> Booking:
    base = Booking(
        id="CW-0000",
        status="confirmed",
        bike_type="city",
        bikes=1,
        start=NOW + timedelta(hours=72),
        end=NOW + timedelta(hours=96),
        add_ons=(),
        rental_price_eur=Decimal("40"),
        booking_fee_eur=Decimal("2"),
        deposit_eur=Decimal("50"),
        paid_with="card",
    )
    return replace(base, **overrides)


def booking_starting_in(delta: timedelta, **overrides: Any) -> Booking:
    return make_booking(start=NOW + delta, end=NOW + delta + timedelta(hours=24), **overrides)


def test_to_money_rounds_half_up() -> None:
    assert to_money(Decimal("11.525")) == Decimal("11.53")
    assert to_money(Decimal("5")) == Decimal("5.00")


def test_full_refund_48h_or_more() -> None:
    result = calculate_refund(make_booking(), NOW)

    assert result.can_cancel is True
    assert result.refund_percent == 100
    assert result.rental_refund_eur == Decimal("40.00")
    assert result.deposit_refund_eur == Decimal("50.00")
    assert result.total_refund_eur == Decimal("90.00")
    assert result.booking_fee_refund_eur == ZERO
    assert result.hours_before_start == 72.0


def test_exactly_48h_is_full_refund() -> None:
    result = calculate_refund(booking_starting_in(timedelta(hours=48)), NOW)

    assert result.refund_percent == 100


def test_just_under_48h_is_half() -> None:
    result = calculate_refund(booking_starting_in(timedelta(hours=47, minutes=59)), NOW)

    assert result.refund_percent == 50
    assert result.total_refund_eur == Decimal("70.00")


def test_exactly_24h_is_half_refund() -> None:
    result = calculate_refund(booking_starting_in(timedelta(hours=24)), NOW)

    assert result.refund_percent == 50


def test_just_under_24h_is_zero() -> None:
    result = calculate_refund(booking_starting_in(timedelta(hours=23, minutes=59)), NOW)

    assert result.refund_percent == 0
    assert result.rental_refund_eur == ZERO
    assert result.total_refund_eur == Decimal("50.00")


def test_tier_uses_exact_time_not_rounded_hours() -> None:
    # 47h59m59.9s rounds to 48.0 for display but must still fall in the 50% tier.
    start_in = timedelta(hours=48) - timedelta(milliseconds=100)
    result = calculate_refund(booking_starting_in(start_in), NOW)

    assert result.hours_before_start == 48.0
    assert result.refund_percent == 50


@pytest.mark.parametrize("fee", ["2", "0"])
def test_booking_fee_never_refunded(fee: str) -> None:
    result = calculate_refund(make_booking(booking_fee_eur=Decimal(fee)), NOW)

    assert result.booking_fee_eur == Decimal(fee)
    assert result.booking_fee_refund_eur == ZERO


def test_deposit_always_refunded_when_cancellable() -> None:
    result = calculate_refund(booking_starting_in(timedelta(hours=2)), NOW)

    assert result.refund_percent == 0
    assert result.deposit_refund_eur == Decimal("50.00")


@pytest.mark.parametrize("status", ["in_progress", "completed", "cancelled"])
def test_non_cancellable_statuses(status: str) -> None:
    result = calculate_refund(make_booking(status=status), NOW)

    assert result.can_cancel is False
    assert status in result.reason
    assert result.refund_percent == 0
    assert result.rental_refund_eur == ZERO
    assert result.deposit_refund_eur == ZERO
    assert result.total_refund_eur == ZERO
    assert result.refund_method == "card"
    assert result.rental_price_eur == Decimal("40")


def test_voucher_refund_method() -> None:
    result = calculate_refund(make_booking(paid_with="voucher"), NOW)

    assert result.refund_method == "voucher"
    assert "voucher" in result.refund_note


def test_card_refund_method() -> None:
    result = calculate_refund(make_booking(), NOW)

    assert result.refund_method == "card"
    assert "5 working days" in result.refund_note


def test_half_refund_rounds_to_cents() -> None:
    booking = booking_starting_in(timedelta(hours=30), rental_price_eur=Decimal("23.05"))

    assert calculate_refund(booking, NOW).rental_refund_eur == Decimal("11.53")


def test_cancel_at_in_future_changes_tier() -> None:
    result = calculate_refund(make_booking(), NOW, NOW + timedelta(hours=42))

    assert result.refund_percent == 50
    assert result.cancel_at == NOW + timedelta(hours=42)
    assert result.hours_before_start == 30.0


def test_cancel_at_in_past_raises() -> None:
    with pytest.raises(CancellationTimeError):
        calculate_refund(make_booking(), NOW, NOW - timedelta(minutes=1))


def test_cancel_after_start_cannot_cancel() -> None:
    result = calculate_refund(make_booking(), NOW, NOW + timedelta(hours=72))

    assert result.can_cancel is False
    assert result.reason == "The rental has already started."
    assert result.total_refund_eur == ZERO


def test_cancel_at_defaults_to_now() -> None:
    assert calculate_refund(make_booking(), NOW).cancel_at == NOW


def test_to_dict_is_json_ready() -> None:
    data = calculate_refund(make_booking(), NOW).to_dict()

    assert data["cancel_at"] == NOW.isoformat()
    assert data["total_refund_eur"] == 90.0
    assert isinstance(data["total_refund_eur"], float)
    assert data["can_cancel"] is True


def test_parse_cancel_at_utc() -> None:
    parsed = parse_cancel_at("2026-06-11T07:00:00Z", NOW.tzinfo)  # type: ignore[arg-type]

    assert parsed == datetime.fromisoformat("2026-06-11T09:00:00+02:00")


def test_parse_cancel_at_naive_uses_tz() -> None:
    tz = timezone(timedelta(hours=2))

    parsed = parse_cancel_at("2026-06-11T09:00:00", tz)

    assert parsed == datetime(2026, 6, 11, 9, 0, tzinfo=tz)


def test_parse_cancel_at_invalid_raises() -> None:
    with pytest.raises(CancellationTimeError):
        parse_cancel_at("tomorrow", UTC)


@pytest.fixture(scope="module")
def repo() -> BookingRepository:
    return BookingRepository.from_file(BOOKINGS_PATH)


@pytest.mark.parametrize(
    ("booking_id", "total", "percent", "method"),
    [
        ("CW-1001", "90.00", 100, "card"),
        ("CW-1002", "340.00", 50, "card"),
        ("CW-1003", "50.00", 0, "card"),
        ("CW-1004", "73.00", 100, "voucher"),
        ("CW-1007", "186.00", 100, "card"),
        ("CW-1009", "169.00", 100, "card"),
        ("CW-1010", "170.00", 50, "card"),
    ],
)
def test_real_bookings(
    repo: BookingRepository, booking_id: str, total: str, percent: int, method: str
) -> None:
    booking = repo.get(booking_id)
    assert booking is not None

    result = calculate_refund(booking, NOW)

    assert result.can_cancel is True
    assert result.total_refund_eur == Decimal(total)
    assert result.refund_percent == percent
    assert result.refund_method == method


@pytest.mark.parametrize("booking_id", ["CW-1005", "CW-1006", "CW-1008"])
def test_real_non_cancellable_bookings(repo: BookingRepository, booking_id: str) -> None:
    booking = repo.get(booking_id)
    assert booking is not None

    result = calculate_refund(booking, NOW)

    assert result.can_cancel is False
    assert result.total_refund_eur == ZERO
