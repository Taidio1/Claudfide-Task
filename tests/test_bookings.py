from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from citywheels.bookings import (
    Booking,
    BookingDataError,
    BookingRepository,
    normalize_booking_id,
)
from citywheels.config import BOOKINGS_PATH


@pytest.fixture(scope="module")
def repo() -> BookingRepository:
    return BookingRepository.from_file(BOOKINGS_PATH)


def test_get_existing_booking(repo: BookingRepository) -> None:
    booking = repo.get("CW-1002")

    assert booking is not None
    assert booking.bikes == 2
    assert booking.rental_price_eur == Decimal("80")


def test_unknown_booking_returns_none(repo: BookingRepository) -> None:
    assert repo.get("CW-9999") is None


@pytest.mark.parametrize("raw", ["cw1002", "CW 1002", "cw-1002", "#CW-1002", "1002", " CW-1002 "])
def test_normalizes_ids(raw: str) -> None:
    assert normalize_booking_id(raw) == "CW-1002"


@pytest.mark.parametrize("raw", ["hello", "CW-12", "CW-10021", ""])
def test_rejects_garbage_ids(raw: str, repo: BookingRepository) -> None:
    assert normalize_booking_id(raw) is None
    assert repo.get(raw) is None


def test_get_accepts_messy_id(repo: BookingRepository) -> None:
    booking = repo.get(" cw 1002 ")

    assert booking is not None
    assert booking.id == "CW-1002"


def test_loads_all_bookings_from_data(repo: BookingRepository) -> None:
    assert len(repo) == 10


def test_to_dict_is_json_ready() -> None:
    booking = Booking(
        id="CW-1004",
        status="confirmed",
        bike_type="city",
        bikes=1,
        start=datetime.fromisoformat("2026-06-20T09:00:00+02:00"),
        end=datetime.fromisoformat("2026-06-21T09:00:00+02:00"),
        add_ons=("child_seat",),
        rental_price_eur=Decimal("23.0"),
        booking_fee_eur=Decimal("2.0"),
        deposit_eur=Decimal("50.0"),
        paid_with="voucher",
    )

    assert booking.to_dict() == {
        "id": "CW-1004",
        "status": "confirmed",
        "bike_type": "city",
        "bikes": 1,
        "start": "2026-06-20T09:00:00+02:00",
        "end": "2026-06-21T09:00:00+02:00",
        "add_ons": ["child_seat"],
        "rental_price_eur": "23.00",
        "booking_fee_eur": "2.00",
        "deposit_eur": "50.00",
        "paid_with": "voucher",
    }


def test_from_record_parses_amounts_exactly_via_str() -> None:
    record = {
        "id": "CW-1",
        "status": "confirmed",
        "bike_type": "city",
        "bikes": 1,
        "start": "2026-06-20T09:00:00+02:00",
        "end": "2026-06-21T09:00:00+02:00",
        "add_ons": ["child_seat"],
        "rental_price_eur": 23.1,
        "booking_fee_eur": 0.1,
        "deposit_eur": 50,
        "paid_with": "card",
    }

    booking = Booking.from_record(record)

    assert booking.rental_price_eur == Decimal(
        "23.1"
    )  # Decimal(23.1) would be 23.100000000000001...
    assert booking.booking_fee_eur == Decimal("0.1")
    assert booking.start.utcoffset() == timedelta(hours=2)
    assert booking.add_ons == ("child_seat",)


def test_normalize_rejects_non_ascii_digits() -> None:
    assert normalize_booking_id("١٠٠٢") is None


@pytest.mark.parametrize(("field", "value"), [("status", "pending"), ("paid_with", "cash")])
def test_from_record_rejects_unknown_values(field: str, value: str) -> None:
    record = {
        "id": "CW-1",
        "status": "confirmed",
        "bike_type": "city",
        "bikes": 1,
        "start": "2026-06-20T09:00:00+02:00",
        "end": "2026-06-21T09:00:00+02:00",
        "add_ons": [],
        "rental_price_eur": 20,
        "booking_fee_eur": 2,
        "deposit_eur": 50,
        "paid_with": "card",
        field: value,
    }

    with pytest.raises(BookingDataError, match=f"CW-1: unknown {field} '{value}'"):
        Booking.from_record(record)
