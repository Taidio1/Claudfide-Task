"""Booking records and lookup by (possibly messy) customer-typed id."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from citywheels.money import format_money

# Customers write ids in many ways ("cw1002", "#CW 1002", "1002"); accept them all.
# [0-9] rather than \d: \d also matches non-ASCII digits, which would break the CW-NNNN contract.
_BOOKING_ID_PATTERN = re.compile(r"^[\s#]*(?:CW)?[\s#-]*([0-9]{4})$")

# The refund rules branch on these values, so an unknown one must fail at load time,
# not as a KeyError in the middle of a customer conversation.
BOOKING_STATUSES = frozenset({"confirmed", "in_progress", "completed", "cancelled"})
PAYMENT_METHODS = frozenset({"card", "voucher"})


class BookingDataError(ValueError):
    """A booking record does not match the documented format."""


@dataclass(frozen=True)
class Booking:
    id: str
    status: str
    bike_type: str
    bikes: int
    start: datetime
    end: datetime
    add_ons: tuple[str, ...]
    rental_price_eur: Decimal
    booking_fee_eur: Decimal
    deposit_eur: Decimal
    paid_with: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form for tool output."""
        return {
            "id": self.id,
            "status": self.status,
            "bike_type": self.bike_type,
            "bikes": self.bikes,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "add_ons": list(self.add_ons),
            "rental_price_eur": format_money(self.rental_price_eur),
            "booking_fee_eur": format_money(self.booking_fee_eur),
            "deposit_eur": format_money(self.deposit_eur),
            "paid_with": self.paid_with,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Self:
        _require_known(record, "status", BOOKING_STATUSES)
        _require_known(record, "paid_with", PAYMENT_METHODS)
        # Decimal(str(...)) avoids binary-float artefacts from the JSON numbers.
        return cls(
            id=record["id"],
            status=record["status"],
            bike_type=record["bike_type"],
            bikes=record["bikes"],
            start=datetime.fromisoformat(record["start"]),
            end=datetime.fromisoformat(record["end"]),
            add_ons=tuple(record["add_ons"]),
            rental_price_eur=Decimal(str(record["rental_price_eur"])),
            booking_fee_eur=Decimal(str(record["booking_fee_eur"])),
            deposit_eur=Decimal(str(record["deposit_eur"])),
            paid_with=record["paid_with"],
        )


def _require_known(record: dict[str, Any], field: str, allowed: frozenset[str]) -> None:
    if record[field] not in allowed:
        raise BookingDataError(
            f"Booking {record['id']}: unknown {field} {record[field]!r}, "
            f"expected one of {sorted(allowed)}."
        )


def normalize_booking_id(raw: str) -> str | None:
    """Return the canonical `CW-NNNN` id, or None if `raw` is not a booking id."""
    match = _BOOKING_ID_PATTERN.match(raw.strip().upper())
    return f"CW-{match.group(1)}" if match else None


class BookingRepository:
    """In-memory bookings indexed by id; loaded once, read-only afterwards."""

    def __init__(self, bookings: Iterable[Booking]) -> None:
        self._by_id = {booking.id: booking for booking in bookings}

    @classmethod
    def from_file(cls, path: Path) -> Self:
        records = json.loads(path.read_text(encoding="utf-8"))
        return cls(Booking.from_record(record) for record in records)

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, raw_id: str) -> Booking | None:
        booking_id = normalize_booking_id(raw_id)
        return self._by_id.get(booking_id) if booking_id else None
