"""Indian-system amount in words, derived from the computed total.

The blueprint's rule: the words are generated FROM the number and compared
against it, never typed by a user and never written by a model. This module is
the generator; verify.py does the comparison after render.

Scale is the Indian one -- thousand, lakh, crore, arab, kharab -- so 1,00,000
reads "One Lakh" and not "One Hundred Thousand".
"""

from __future__ import annotations

from decimal import Decimal

from .money import q2

_UNITS = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
    "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
    "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
    "Eighty", "Ninety",
]

# Indian groups, largest first. After the first group of three, each group is
# a pair of digits: thousand (2), lakh (2), crore (2), arab (2), kharab (2).
_SCALES = [
    (Decimal(10) ** 12, "Kharab"),
    (Decimal(10) ** 10, "Arab"),
    (Decimal(10) ** 7, "Crore"),
    (Decimal(10) ** 5, "Lakh"),
    (Decimal(10) ** 3, "Thousand"),
]

MAX_SUPPORTED = 10 ** 14 - 1  # up to 99,99,99,99,99,999


class AmountTooLarge(ValueError):
    """Beyond the scale names this module is willing to vouch for."""


def _under_thousand(n: int) -> list[str]:
    """0-999 as words. Returns [] for 0 so callers can skip empty groups."""
    out: list[str] = []
    if n >= 100:
        out += [_UNITS[n // 100], "Hundred"]
        n %= 100
        if n:
            out.append("and")
    if n >= 20:
        out.append(_TENS[n // 10])
        n %= 10
        if n:
            out.append(_UNITS[n])
    elif n > 0:
        out.append(_UNITS[n])
    return out


def integer_to_words(n: int) -> str:
    """Whole number to Indian-system words. 0 -> 'Zero'."""
    if n < 0:
        raise ValueError("negative amounts are not written in words")
    if n > MAX_SUPPORTED:
        raise AmountTooLarge(
            f"{n} exceeds the largest amount this routine will name "
            f"({MAX_SUPPORTED})"
        )
    if n == 0:
        return "Zero"

    words: list[str] = []
    for value, name in _SCALES:
        divisor = int(value)
        if n >= divisor:
            count = n // divisor
            n %= divisor
            words += _under_thousand(count) + [name]
    if n:
        words += _under_thousand(n)

    return " ".join(words)


def amount_in_words(amount: Decimal, *, currency: str = "Rupees",
                    subunit: str = "Paise") -> str:
    """Render a rupee amount as the line printed on the document.

    >>> amount_in_words(Decimal("123456.78"))
    'Rupees One Lakh Twenty Three Thousand Four Hundred and Fifty Six and Seventy Eight Paise Only'
    """
    amount = q2(amount)
    if amount < 0:
        raise ValueError("negative amounts are not written in words")

    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    parts = [currency, integer_to_words(rupees)]
    if paise:
        parts += ["and", integer_to_words(paise), subunit]
    parts.append("Only")
    return " ".join(parts)
