"""Deterministic refund calculation; the language model never computes money."""

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Any

from citywheels.bookings import Booking
from citywheels.money import format_money, to_money

FULL_REFUND_HOURS = 48
HALF_REFUND_HOURS = 24
FULL_REFUND_PERCENT = 100
HALF_REFUND_PERCENT = 50
NO_REFUND_PERCENT = 0
PERCENT_DIVISOR = Decimal(100)
SECONDS_PER_HOUR = 3600

CANCELLABLE_STATUSES = frozenset({"confirmed"})

REFUND_NOTES = {
    "card": "Refunded to the same card within 5 working days.",
    "voucher": (
        "Refunded as a new voucher of the same value, not as money. "
        "The deposit is refunded the same way it was paid."
    ),
}
NOT_CANCELLABLE_NOTE = "Nothing is refunded."
ALREADY_STARTED_REASON = "The rental has already started."


class CancellationTimeError(ValueError):
    """The requested cancellation time is unusable (in the past or malformed)."""


@dataclass(frozen=True)
class RefundResult:
    booking_id: str
    status: str
    can_cancel: bool
    reason: str
    cancel_at: datetime
    hours_before_start: float
    refund_percent: int
    rental_price_eur: Decimal
    rental_refund_eur: Decimal
    booking_fee_eur: Decimal
    booking_fee_refund_eur: Decimal
    deposit_refund_eur: Decimal
    total_refund_eur: Decimal
    refund_method: str
    refund_note: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form for tool output."""
        return {
            "booking_id": self.booking_id,
            "status": self.status,
            "can_cancel": self.can_cancel,
            "reason": self.reason,
            "cancel_at": self.cancel_at.isoformat(),
            "hours_before_start": self.hours_before_start,
            "refund_percent": self.refund_percent,
            "rental_price_eur": format_money(self.rental_price_eur),
            "rental_refund_eur": format_money(self.rental_refund_eur),
            "booking_fee_eur": format_money(self.booking_fee_eur),
            "booking_fee_refund_eur": format_money(self.booking_fee_refund_eur),
            "deposit_refund_eur": format_money(self.deposit_refund_eur),
            "total_refund_eur": format_money(self.total_refund_eur),
            "refund_method": self.refund_method,
            "refund_note": self.refund_note,
        }


def _refund_percent(time_to_start: timedelta) -> int:
    # Exact timedelta comparison, so a boundary belongs to the higher tier
    # and a rounded display value can never push a booking into the wrong one.
    if time_to_start >= timedelta(hours=FULL_REFUND_HOURS):
        return FULL_REFUND_PERCENT
    if time_to_start >= timedelta(hours=HALF_REFUND_HOURS):
        return HALF_REFUND_PERCENT
    return NO_REFUND_PERCENT


def calculate_refund(
    booking: Booking, now: datetime, cancel_at: datetime | None = None
) -> RefundResult:
    """Refund for cancelling `booking` at `cancel_at` (default: `now`).

    Raises CancellationTimeError if `cancel_at` is before `now`: the past cannot be changed.
    """
    cancel_at = now if cancel_at is None else cancel_at
    if cancel_at < now:
        raise CancellationTimeError("The cancellation time cannot be in the past.")

    time_to_start = booking.start - cancel_at
    hours_before_start = round(time_to_start.total_seconds() / SECONDS_PER_HOUR, 2)

    if booking.status not in CANCELLABLE_STATUSES:
        reason = f"Bookings with status '{booking.status}' cannot be cancelled."
    elif time_to_start <= timedelta(0):
        reason = ALREADY_STARTED_REASON
    else:
        return _cancellable_result(booking, cancel_at, hours_before_start, time_to_start)

    zero = to_money(Decimal(0))
    return RefundResult(
        booking_id=booking.id,
        status=booking.status,
        can_cancel=False,
        reason=reason,
        cancel_at=cancel_at,
        hours_before_start=hours_before_start,
        refund_percent=NO_REFUND_PERCENT,
        rental_price_eur=booking.rental_price_eur,
        rental_refund_eur=zero,
        booking_fee_eur=booking.booking_fee_eur,
        booking_fee_refund_eur=zero,
        deposit_refund_eur=zero,
        total_refund_eur=zero,
        refund_method=booking.paid_with,
        refund_note=NOT_CANCELLABLE_NOTE,
    )


def _cancellable_result(
    booking: Booking, cancel_at: datetime, hours_before_start: float, time_to_start: timedelta
) -> RefundResult:
    percent = _refund_percent(time_to_start)
    rental_refund = to_money(booking.rental_price_eur * percent / PERCENT_DIVISOR)
    deposit_refund = to_money(booking.deposit_eur)
    return RefundResult(
        booking_id=booking.id,
        status=booking.status,
        can_cancel=True,
        reason=f"Cancelling {hours_before_start} hours before the start: {percent}% of the "
        "rental price is refunded.",
        cancel_at=cancel_at,
        hours_before_start=hours_before_start,
        refund_percent=percent,
        rental_price_eur=booking.rental_price_eur,
        rental_refund_eur=rental_refund,
        booking_fee_eur=booking.booking_fee_eur,
        # Policy: the booking fee is never refunded.
        booking_fee_refund_eur=to_money(Decimal(0)),
        deposit_refund_eur=deposit_refund,
        total_refund_eur=rental_refund + deposit_refund,
        refund_method=booking.paid_with,
        refund_note=REFUND_NOTES[booking.paid_with],
    )


def parse_cancel_at(raw: str, tz: tzinfo) -> datetime:
    """Parse an ISO 8601 time; a value without offset is read as shop-local time in `tz`."""
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CancellationTimeError(
            f"'{raw}' is not a valid ISO 8601 date and time, e.g. 2026-06-11T09:00:00+02:00."
        ) from exc
    return parsed.replace(tzinfo=tz) if parsed.tzinfo is None else parsed
