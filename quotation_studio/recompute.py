"""Independent second implementation of every figure on the document.

This is not a copy of compute.py with the names changed. It shares no helper,
imports nothing from money.py, and uses a different numeric representation:
exact rational arithmetic (fractions.Fraction) reduced to INTEGER PAISE, with
rounding written out by hand rather than delegated to Decimal's rounding modes.

The point is that a bug in one implementation is unlikely to be present in the
other. If Decimal's quantize is misused, or a rounding mode is wrong, or a
total is taken over unrounded values, the two implementations disagree and
cross_check() refuses the document instead of rendering a wrong one.

Everything below is in integer paise. There are no floats and no Decimals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .model import DiscountKind, Document


def _half_up(value: Fraction) -> int:
    """Round a non-negative rational to the nearest integer, halves upward."""
    return math.floor(value + Fraction(1, 2))


def _paise(value: Decimal) -> int:
    """A quantized Decimal rupee amount as exact integer paise."""
    return int((value * 100).to_integral_value())


@dataclass(frozen=True)
class RecomputedLine:
    gross: int
    discount: int
    taxable: int
    tax: int
    cgst: int
    sgst: int
    igst: int


@dataclass(frozen=True)
class Recomputed:
    lines: list[RecomputedLine]
    gross_total: int
    discount_total: int
    taxable_total: int
    cgst_total: int
    sgst_total: int
    igst_total: int
    tax_total: int
    round_off: int
    grand_total: int


def recompute(doc: Document, *, is_interstate: bool, charging: bool) -> Recomputed:
    """Recompute the whole document in integer paise."""
    lines: list[RecomputedLine] = []

    for item in doc.items:
        rate_paise = Fraction(item.rate) * 100
        gross = _half_up(Fraction(item.quantity) * rate_paise)

        if item.discount_kind is DiscountKind.PERCENT:
            discount = _half_up(
                Fraction(gross) * Fraction(item.discount_value) / 100
            )
        elif item.discount_kind is DiscountKind.AMOUNT:
            discount = _half_up(Fraction(item.discount_value) * 100)
        else:
            discount = 0

        taxable = gross - discount

        effective_rate = Fraction(item.gst_rate) if charging else Fraction(0)
        tax = _half_up(Fraction(taxable) * effective_rate / 100)

        if not charging:
            cgst = sgst = igst = 0
        elif is_interstate:
            cgst = sgst = 0
            igst = tax
        else:
            cgst = _half_up(Fraction(tax, 2))
            sgst = tax - cgst
            igst = 0

        lines.append(RecomputedLine(gross, discount, taxable, tax,
                                    cgst, sgst, igst))

    gross_total = sum(ln.gross for ln in lines)
    discount_total = sum(ln.discount for ln in lines)
    taxable_total = sum(ln.taxable for ln in lines)
    cgst_total = sum(ln.cgst for ln in lines)
    sgst_total = sum(ln.sgst for ln in lines)
    igst_total = sum(ln.igst for ln in lines)
    tax_total = cgst_total + sgst_total + igst_total

    before = taxable_total + tax_total
    if doc.round_to_rupee:
        grand_total = _half_up(Fraction(before, 100)) * 100
        round_off = grand_total - before
    else:
        grand_total = before
        round_off = 0

    return Recomputed(
        lines=lines,
        gross_total=gross_total,
        discount_total=discount_total,
        taxable_total=taxable_total,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        tax_total=tax_total,
        round_off=round_off,
        grand_total=grand_total,
    )


class ComputationMismatch(Exception):
    """The two implementations disagree. Nothing may be rendered."""

    def __init__(self, mismatches: list[str]):
        self.mismatches = mismatches
        super().__init__(
            "The two independent computations disagree, so no document was "
            "produced. This is a bug in the tool, not in your input. "
            "Disagreements:\n  " + "\n  ".join(mismatches)
        )


def cross_check(computed) -> Recomputed:
    """Recompute and compare. Raises ComputationMismatch on any difference.

    Returns the recomputation so callers can record that it ran.
    """
    doc = computed.document
    second = recompute(
        doc,
        is_interstate=computed.is_interstate,
        charging=computed.tax_is_charged,
    )

    mismatches: list[str] = []

    def compare(label: str, primary: Decimal, other: int) -> None:
        got = _paise(primary)
        if got != other:
            mismatches.append(
                f"{label}: Decimal path says {got} paise, "
                f"integer path says {other} paise"
            )

    if len(computed.lines) != len(second.lines):
        raise ComputationMismatch(
            [f"line count: {len(computed.lines)} vs {len(second.lines)}"]
        )

    for i, (a, b) in enumerate(zip(computed.lines, second.lines)):
        compare(f"items[{i}].gross", a.gross, b.gross)
        compare(f"items[{i}].discount", a.discount, b.discount)
        compare(f"items[{i}].taxable", a.taxable, b.taxable)
        compare(f"items[{i}].tax", a.tax, b.tax)
        compare(f"items[{i}].cgst", a.cgst, b.cgst)
        compare(f"items[{i}].sgst", a.sgst, b.sgst)
        compare(f"items[{i}].igst", a.igst, b.igst)

    compare("gross_total", computed.gross_total, second.gross_total)
    compare("discount_total", computed.discount_total, second.discount_total)
    compare("taxable_total", computed.taxable_total, second.taxable_total)
    compare("cgst_total", computed.cgst_total, second.cgst_total)
    compare("sgst_total", computed.sgst_total, second.sgst_total)
    compare("igst_total", computed.igst_total, second.igst_total)
    compare("tax_total", computed.tax_total, second.tax_total)
    compare("round_off", computed.round_off, second.round_off)
    compare("grand_total", computed.grand_total, second.grand_total)

    # Invariants that must hold regardless of which path computed them.
    if computed.tax_is_charged:
        if computed.is_interstate and (second.cgst_total or second.sgst_total):
            mismatches.append(
                "inter-state supply carries CGST/SGST, which is impossible"
            )
        if not computed.is_interstate and second.igst_total:
            mismatches.append(
                "intra-state supply carries IGST, which is impossible"
            )
    elif second.tax_total:
        mismatches.append(
            "tax was computed even though the registration gate forbids "
            "collecting it"
        )

    if second.taxable_total + second.tax_total + second.round_off != second.grand_total:
        mismatches.append(
            "taxable + tax + round_off does not equal the grand total"
        )

    if mismatches:
        raise ComputationMismatch(mismatches)

    return second
