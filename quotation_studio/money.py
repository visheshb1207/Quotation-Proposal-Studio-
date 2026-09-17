"""Money arithmetic policy.

Every rupee figure in this package is a Decimal quantized to 2 places with
ROUND_HALF_UP. Floats never touch money: parsing goes str -> Decimal directly,
so 0.1 + 0.2 problems cannot arise.

Rounding policy, stated once so both implementations can be held to it:
  * A line's taxable value is rounded to paise BEFORE tax is applied.
  * Tax is computed per line on that rounded taxable value, then rounded.
  * CGST and SGST are each exactly half the line's total tax, with any odd
    paise given to CGST, so CGST + SGST == the total tax to the paise.
  * Totals are the sum of already-rounded line figures -- never a rounded sum
    of unrounded figures. This is what lets a recipient re-add the column on a
    phone calculator and match.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISE = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")


class MoneyError(ValueError):
    """A value that should be a number is not one."""


def to_decimal(value, *, field: str) -> Decimal:
    """Parse user input into an exact Decimal. Floats are rejected outright."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise MoneyError(f"{field}: expected a number, got a boolean")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise MoneyError(
            f"{field}: floating-point numbers are not accepted for money or "
            f"quantities -- supply {value!r} as a string to keep it exact"
        )
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("₹", "")
        if not cleaned:
            raise MoneyError(f"{field}: is empty")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            raise MoneyError(f"{field}: {value!r} is not a number") from None
    raise MoneyError(f"{field}: expected a number, got {type(value).__name__}")


def money(value, *, field: str = "amount") -> Decimal:
    """Parse and quantize to paise."""
    return q2(to_decimal(value, field=field))


def q2(value: Decimal) -> Decimal:
    """Quantize to paise, half-up."""
    return value.quantize(PAISE, rounding=ROUND_HALF_UP)


def q0(value: Decimal) -> Decimal:
    """Quantize to whole rupees, half-up."""
    return value.quantize(RUPEE, rounding=ROUND_HALF_UP)


def split_half(total_tax: Decimal) -> tuple[Decimal, Decimal]:
    """Split a line's tax into CGST and SGST with no paise lost.

    Odd paise go to CGST. The invariant cgst + sgst == total_tax holds
    exactly, which is the thing a recipient checks first.
    """
    total_tax = q2(total_tax)
    cgst = q2(total_tax / 2)
    sgst = q2(total_tax - cgst)
    assert cgst + sgst == total_tax
    return cgst, sgst


def format_inr(value: Decimal) -> str:
    """Indian digit grouping: 12,34,567.89 -- last three, then pairs."""
    value = q2(value)
    sign = "-" if value < 0 else ""
    digits, _, frac = abs(value).__str__().partition(".")
    frac = (frac + "00")[:2]

    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail

    return f"{sign}{grouped}.{frac}"
