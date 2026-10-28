"""Money rounding and formatting shared by bookings and refunds."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value: Decimal) -> Decimal:
    """Single rounding point for all amounts; half-up matches how shops round cents."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    # A string such as "340.00" rather than a float: the model copies it verbatim
    # instead of rendering 340.0 or re-rounding it.
    return str(to_money(value))
