"""Exact money handling.

Every dollar figure in a demand letter is either an exact decimal or explicitly
unknown. Floats are never used, and the storage type round-trips through strings
so the value is identical on SQLite and PostgreSQL alike.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    """Raised when a value cannot be interpreted as an exact money amount."""


def to_money(value: Any) -> Decimal:
    """Coerce to an exact 2-dp Decimal. Rejects floats outright."""
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.replace(",", "").replace("$", "").strip())
        except InvalidOperation as exc:  # pragma: no cover - defensive
            raise MoneyError(f"not a money value: {value!r}") from exc
    elif isinstance(value, float):
        raise MoneyError(
            "float amounts are not accepted; pass a string or Decimal to preserve exactness"
        )
    else:
        raise MoneyError(f"not a money value: {value!r}")
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def money_sum(values: Iterable[Decimal | None]) -> Decimal:
    """Sum known amounts. ``None`` means *unknown* and is skipped, never zero."""
    total = ZERO
    for value in values:
        if value is None:
            continue
        total += to_money(value)
    return total.quantize(CENTS, rounding=ROUND_HALF_UP)


def format_money(value: Decimal | None) -> str:
    if value is None:
        return "amount pending"
    return f"${to_money(value):,.2f}"


class Money(TypeDecorator):
    """Store Decimal money as a canonical string so no float ever touches it."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: D102 - SQLAlchemy hook
        if value is None:
            return None
        return str(to_money(value))

    def process_result_value(self, value, dialect):  # noqa: D102 - SQLAlchemy hook
        if value is None:
            return None
        return to_money(value)
