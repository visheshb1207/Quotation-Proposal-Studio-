"""Primary computation: Decimal, line by line.

Nothing here is generated. Every figure is arithmetic over the user's declared
quantities, rates and GST percentages, and every figure carries the formula
that produced it so the fact table can be printed and re-checked.

recompute.py implements the same result a second time by a deliberately
different method (integer paise, whole-document aggregation). check() runs both
and refuses to return anything unless they agree to the paise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .model import DiscountKind, Document, LineItem
from .money import ZERO, format_inr, q0, q2, split_half
from .place_of_supply import PlaceOfSupply, derive
from .registration import TaxTreatment
from .words import amount_in_words


@dataclass(frozen=True)
class Fact:
    """One computed figure and the formula that produced it."""

    key: str
    value: Decimal
    formula: str

    def __str__(self) -> str:
        return f"{self.key} = {format_inr(self.value)}  [{self.formula}]"


@dataclass(frozen=True)
class ComputedLine:
    item: LineItem
    gross: Decimal            # quantity x rate
    discount: Decimal
    taxable: Decimal          # gross - discount
    tax_rate: Decimal         # effective rate applied (0 when not charged)
    tax: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    facts: list[Fact] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return q2(self.taxable + self.tax)


@dataclass(frozen=True)
class ComputedDocument:
    document: Document
    place_of_supply: PlaceOfSupply
    is_interstate: bool
    treatment: TaxTreatment
    lines: list[ComputedLine]
    gross_total: Decimal
    discount_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal
    igst_total: Decimal
    tax_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    amount_words: str
    rate_summary: list[tuple[Decimal, Decimal, Decimal]]  # (rate, taxable, tax)
    facts: list[Fact] = field(default_factory=list)

    @property
    def tax_is_charged(self) -> bool:
        return self.treatment.tax_is_charged


def compute(doc: Document) -> ComputedDocument:
    """Compute every figure on the document. Pure; raises only on bad input."""
    pos = derive(
        nature=doc.supply.nature,
        supplier_state_code=doc.supplier.state_code,
        client_state_code=doc.client.state_code or None,
        client_is_registered=doc.client.is_registered,
        answers=doc.supply.answers,
    )

    # Intra-state when the place of supply is the supplier's own state.
    # Everything else is inter-state and attracts IGST instead of CGST+SGST.
    is_interstate = pos.state_code != doc.supplier.state_code

    treatment = doc.registration.treatment
    charging = treatment.tax_is_charged

    lines = [
        _compute_line(item, index=i, is_interstate=is_interstate,
                      charging=charging)
        for i, item in enumerate(doc.items)
    ]

    gross_total = q2(sum((ln.gross for ln in lines), ZERO))
    discount_total = q2(sum((ln.discount for ln in lines), ZERO))
    taxable_total = q2(sum((ln.taxable for ln in lines), ZERO))
    cgst_total = q2(sum((ln.cgst for ln in lines), ZERO))
    sgst_total = q2(sum((ln.sgst for ln in lines), ZERO))
    igst_total = q2(sum((ln.igst for ln in lines), ZERO))
    tax_total = q2(cgst_total + sgst_total + igst_total)

    before_rounding = q2(taxable_total + tax_total)
    if doc.round_to_rupee:
        grand_total = q0(before_rounding)
        round_off = q2(grand_total - before_rounding)
    else:
        grand_total = before_rounding
        round_off = ZERO

    facts = [
        Fact("gross_total", gross_total, "sum of line gross values"),
        Fact("discount_total", discount_total, "sum of line discounts"),
        Fact("taxable_total", taxable_total, "sum of line taxable values"),
        Fact("cgst_total", cgst_total, "sum of line CGST"),
        Fact("sgst_total", sgst_total, "sum of line SGST"),
        Fact("igst_total", igst_total, "sum of line IGST"),
        Fact("tax_total", tax_total, "cgst_total + sgst_total + igst_total"),
        Fact("round_off", round_off,
             "grand_total - (taxable_total + tax_total)"),
        Fact("grand_total", grand_total,
             "taxable_total + tax_total"
             + (" rounded to the nearest rupee" if doc.round_to_rupee else "")),
    ]

    return ComputedDocument(
        document=doc,
        place_of_supply=pos,
        is_interstate=is_interstate,
        treatment=treatment,
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
        # Derived from the computed total, never typed. verify.py re-derives
        # this from the number extracted out of the rendered PDF.
        amount_words=amount_in_words(grand_total),
        rate_summary=_summarise_by_rate(lines),
        facts=facts,
    )


def _compute_line(item: LineItem, *, index: int, is_interstate: bool,
                  charging: bool) -> ComputedLine:
    where = f"items[{index}]"

    gross = q2(item.quantity * item.rate)

    if item.discount_kind is DiscountKind.PERCENT:
        discount = q2(gross * item.discount_value / Decimal(100))
        discount_formula = f"{item.discount_value}% of {gross}"
    elif item.discount_kind is DiscountKind.AMOUNT:
        discount = q2(item.discount_value)
        discount_formula = "flat discount"
    else:
        discount, discount_formula = ZERO, "no discount"

    if discount > gross:
        raise ValueError(
            f"{where}.discount_value: the discount ({format_inr(discount)}) is "
            f"larger than the line value ({format_inr(gross)})"
        )

    taxable = q2(gross - discount)

    # Rate is the user's declaration. When the registration gate says tax is
    # not collectible, the effective rate is zero and the document says why.
    tax_rate = item.gst_rate if charging else ZERO
    tax = q2(taxable * tax_rate / Decimal(100))

    if not charging:
        cgst = sgst = igst = ZERO
    elif is_interstate:
        cgst = sgst = ZERO
        igst = tax
    else:
        cgst, sgst = split_half(tax)
        igst = ZERO

    facts = [
        Fact(f"{where}.gross", gross, f"{item.quantity} x {item.rate}"),
        Fact(f"{where}.discount", discount, discount_formula),
        Fact(f"{where}.taxable", taxable, "gross - discount"),
        Fact(f"{where}.tax", tax, f"{tax_rate}% of {taxable}"),
    ]
    if charging and is_interstate:
        facts.append(Fact(f"{where}.igst", igst, f"IGST {tax_rate}% (inter-state)"))
    elif charging:
        half = tax_rate / Decimal(2)
        facts += [
            Fact(f"{where}.cgst", cgst, f"CGST {half}% (intra-state)"),
            Fact(f"{where}.sgst", sgst, f"SGST {half}% (intra-state)"),
        ]

    return ComputedLine(
        item=item, gross=gross, discount=discount, taxable=taxable,
        tax_rate=tax_rate, tax=tax, cgst=cgst, sgst=sgst, igst=igst,
        facts=facts,
    )


def _summarise_by_rate(
    lines: list[ComputedLine],
) -> list[tuple[Decimal, Decimal, Decimal]]:
    """Taxable value and tax grouped by rate -- the HSN-wise summary block."""
    buckets: dict[Decimal, list[Decimal]] = {}
    for ln in lines:
        taxable, tax = buckets.setdefault(ln.tax_rate, [ZERO, ZERO])
        buckets[ln.tax_rate] = [q2(taxable + ln.taxable), q2(tax + ln.tax)]
    return [(rate, vals[0], vals[1]) for rate, vals in sorted(buckets.items())]
