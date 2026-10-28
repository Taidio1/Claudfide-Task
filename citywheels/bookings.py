"""Booking records and lookup by (possibly messy) customer-typed id."""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

# Customers write ids in many ways ("cw1002", "#CW 1002", "1002"); accept them all.
# [0-9] rather than \d: \d also matches non-ASCII digits, which would break the CW-NNNN contract.
_BOOKING_ID_PATTERN = re.compile(r"^[\s#]*(?:CW)?[\s#-]*([0-9]{4})$")


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
        """JSON-ready form for tool output; money is a plain float (data has <= 2 decimals)."""
        return {
            "id": self.id,
            "status": self.status,
            "bike_type": self.bike_type,
            "bikes": self.bikes,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "add_ons": list(self.add_ons),
            "rental_price_eur": float(self.rental_price_eur),
            "booking_fee_eur": float(self.booking_fee_eur),
            "deposit_eur": float(self.deposit_eur),
            "paid_with": self.paid_with,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> Self:
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
