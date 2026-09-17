"""End to end: render, then read the PDF back and check what it says.

These are the tests that cover the artefact rather than the computation. They
need the typst binary; they skip cleanly without it.
"""

import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

from quotation_studio.compute import compute
from quotation_studio.model import Document
from quotation_studio.money import format_inr
from quotation_studio.pipeline import run
from quotation_studio.render import manifest_line, render
from quotation_studio.verify import DocumentUnverified, extract_text, verify

pytestmark = pytest.mark.usefixtures("typst_available")


@pytest.fixture(autouse=True)
def _require_typst(typst_available):
    if not typst_available:
        pytest.skip("typst binary not available")


def test_renders_and_verifies(base_doc, tmp_path):
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    assert out.exists() and out.stat().st_size > 1000
    assert result.pdf_path == out


def test_every_printed_total_matches_the_computation(base_doc, tmp_path):
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    text = extract_text(out)
    c = result.computed
    for value in (c.taxable_total, c.igst_total, c.grand_total):
        assert format_inr(value) in " ".join(text.split())


def test_the_amount_in_words_is_on_the_page(base_doc, tmp_path):
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert result.computed.amount_words in flat
    assert "Lakh" in flat


def test_the_manifest_footer_names_the_checks(base_doc, tmp_path):
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "recomputed by a second independent implementation" in flat
    assert "mod-36 checksum verified" in flat
    assert result.computed.place_of_supply.rule.value in flat


def test_the_place_of_supply_reasoning_is_printed(base_doc, tmp_path):
    """A recipient must be able to check the reasoning, not just trust it."""
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert result.computed.place_of_supply.state in flat
    assert "12(5)" in flat


def test_the_scope_disclaimer_is_printed(base_doc, tmp_path):
    out = tmp_path / "q.pdf"
    run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "not a tax invoice" in flat.lower()
    assert "supplier's declarations" in flat


def test_a_composition_declaration_reaches_the_page(base_doc, tmp_path):
    base_doc["registration"]["composition"] = True
    out = tmp_path / "q.pdf"
    run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "not eligible to collect tax on supplies" in flat


def test_an_intrastate_document_prints_cgst_and_sgst(base_doc, tmp_path):
    base_doc["client"]["state_code"] = "27"
    base_doc["place_of_supply"] = {"nature": "general_service"}
    out = tmp_path / "q.pdf"
    result = run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "CGST" in flat and "SGST" in flat and "IGST" not in flat
    assert result.computed.cgst_total + result.computed.sgst_total == \
        result.computed.tax_total


def test_verification_catches_a_total_that_does_not_match(base_doc, tmp_path):
    """Render honestly, then claim a different total. The PDF must be rejected
    and deleted -- this is what protects against a template bug."""
    doc = Document.from_dict(base_doc)
    computed = compute(doc)
    out = tmp_path / "q.pdf"
    render(computed, out)
    assert out.exists()

    tampered = dataclasses.replace(
        computed, grand_total=computed.grand_total + Decimal("1000.00")
    )
    with pytest.raises(DocumentUnverified, match="grand total"):
        verify(tampered, out)
    assert not out.exists(), "an unverified PDF must not survive"


def test_verification_catches_a_stale_amount_in_words(base_doc, tmp_path):
    doc = Document.from_dict(base_doc)
    computed = compute(doc)
    out = tmp_path / "q.pdf"
    render(computed, out)

    stale = dataclasses.replace(computed, amount_words="Rupees One Only")
    with pytest.raises(DocumentUnverified, match="amount in words"):
        verify(stale, out)
    assert not out.exists()


def test_nothing_is_written_when_a_rule_blocks(base_doc, tmp_path):
    from quotation_studio.rules import DocumentBlocked
    base_doc["items"][0]["hsn_sac"] = ""
    out = tmp_path / "q.pdf"
    with pytest.raises(DocumentBlocked):
        run(base_doc, out_pdf=out)
    assert not out.exists(), "a blocked document must leave no file behind"


def test_the_proforma_renders_with_its_own_title(base_doc, tmp_path):
    base_doc["doc_type"] = "proforma"
    out = tmp_path / "p.pdf"
    run(base_doc, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "PROFORMA INVOICE" in flat
    assert "not valid for input tax credit" in flat


def test_manifest_line_is_stable_for_the_same_document(base_doc):
    a = manifest_line(compute(Document.from_dict(base_doc)))
    b = manifest_line(compute(Document.from_dict(base_doc)))
    assert a == b
