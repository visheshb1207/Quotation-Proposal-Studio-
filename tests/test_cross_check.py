"""The two implementations must agree on arbitrary inputs.

compute.py uses Decimal with quantize; recompute.py uses exact rationals
reduced to integer paise with hand-written rounding. They share no helper.
If they agree across thousands of randomised documents, the arithmetic is
almost certainly right -- and if they ever disagree, nothing renders.
"""

import random
from decimal import Decimal

import pytest

from quotation_studio.compute import compute
from quotation_studio.model import Document
from quotation_studio.recompute import ComputationMismatch, cross_check


def make_doc(rng: random.Random) -> dict:
    n_items = rng.randint(1, 8)
    items = []
    for _ in range(n_items):
        kind = rng.choice(["none", "none", "percent", "amount"])
        rate = Decimal(rng.randint(1, 5_000_00)) / 100      # up to 5,000.00
        qty = Decimal(rng.choice(
            ["1", "2", "3", "40", "0.5", "2.25", "0.333", "17"]))
        item = {
            "description": "Line",
            "hsn_sac": rng.choice(["998314", "999293", "8471", "99843100"]),
            "quantity": str(qty),
            "unit": "nos",
            "rate": str(rate),
            "gst_rate": rng.choice(["0", "5", "12", "18", "28", "1.5", "0.25"]),
            "discount_kind": kind,
        }
        if kind == "percent":
            item["discount_value"] = str(rng.choice(["5", "10", "12.5", "33", "100"]))
        elif kind == "amount":
            # A flat discount may not exceed the line value, so cap it against
            # quantity x rate rather than against the rate alone.
            gross = (qty * rate).quantize(Decimal("0.01"))
            item["discount_value"] = str(
                min(Decimal(rng.randint(0, 20000)), gross))
        items.append(item)

    registered = rng.random() > 0.2
    supplier_state = rng.choice(["27", "29", "07", "33", "19"])
    return {
        "doc_type": rng.choice(["quotation", "proforma"]),
        "number": "QT-1",
        "issue_date": "2026-09-16",
        "round_to_rupee": rng.random() > 0.5,
        "registration": {
            "registered": registered,
            "composition": registered and rng.random() < 0.15,
            "reverse_charge": registered and rng.random() < 0.15,
        },
        "supplier": {
            "name": "S", "state_code": supplier_state,
            **({"gstin": {"27": "27AAPFU0939F1ZV"}.get(supplier_state)}
               if registered and supplier_state == "27" else {}),
        },
        "client": {"name": "C",
                   "state_code": rng.choice(["27", "29", "07", "33", "19"])},
        "place_of_supply": {"nature": "general_service"},
        "items": items,
    }


@pytest.mark.parametrize("seed", range(400))
def test_both_implementations_agree(seed):
    rng = random.Random(seed)
    doc = Document.from_dict(make_doc(rng))
    computed = compute(doc)
    cross_check(computed)  # raises on any disagreement


def test_totals_reconcile_to_the_grand_total():
    """taxable + tax + rounding == grand total, on every randomised document."""
    for seed in range(400):
        doc = Document.from_dict(make_doc(random.Random(seed)))
        c = compute(doc)
        assert c.taxable_total + c.tax_total + c.round_off == c.grand_total


def test_line_totals_sum_to_the_taxable_and_tax_totals():
    """A recipient re-adding the column must land on the printed subtotal."""
    for seed in range(400):
        doc = Document.from_dict(make_doc(random.Random(seed)))
        c = compute(doc)
        assert sum(ln.taxable for ln in c.lines) == c.taxable_total
        assert sum(ln.tax for ln in c.lines) == c.tax_total
        assert sum(ln.cgst for ln in c.lines) == c.cgst_total
        assert sum(ln.sgst for ln in c.lines) == c.sgst_total
        assert sum(ln.igst for ln in c.lines) == c.igst_total


def test_cgst_and_sgst_never_coexist_with_igst():
    for seed in range(400):
        doc = Document.from_dict(make_doc(random.Random(seed)))
        c = compute(doc)
        assert not (c.igst_total and (c.cgst_total or c.sgst_total))


def test_a_deliberate_bug_is_caught():
    """Sanity: if the Decimal path were wrong, cross_check must notice."""
    import dataclasses

    doc = Document.from_dict(make_doc(random.Random(1)))
    computed = compute(doc)
    broken = dataclasses.replace(
        computed, grand_total=computed.grand_total + Decimal("0.01")
    )
    with pytest.raises(ComputationMismatch, match="grand_total"):
        cross_check(broken)
