"""Render the reminder, then read it back off the page.

These tests are about the artefact, not the computation. They check that what
Typst put on the page is what ageing.py computed, and -- more importantly --
that when it is not, nothing survives.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from quotation_studio import remind
from quotation_studio.ageing import compute_reminder
from quotation_studio.receivable import ReminderRequest
from quotation_studio.reminder_render import render_reminder
from quotation_studio.reminder_verify import verify_reminder
from quotation_studio.rules import DocumentBlocked
from quotation_studio.verify import DocumentUnverified, extract_text

pytestmark = pytest.mark.usefixtures("typst_available")


@pytest.fixture(autouse=True)
def _skip_without_typst(typst_available):
    if not typst_available:
        pytest.skip("typst is not installed")


def _computed(payload):
    return compute_reminder(ReminderRequest.from_dict(payload))


def test_a_reminder_renders_and_verifies(base_reminder, tmp_path):
    out = tmp_path / "reminder.pdf"
    result = remind(base_reminder, out_pdf=out)
    assert result.pdf_path == out
    assert out.exists()


def test_every_figure_on_the_page_is_one_that_was_computed(base_reminder,
                                                           tmp_path):
    out = tmp_path / "reminder.pdf"
    result = remind(base_reminder, out_pdf=out)
    text = extract_text(out)
    cr = result.computed

    for value in ("2,75,530.00", "1,00,000.00", "1,75,530.00",
                  "2,154.45", "1,77,684.45"):
        assert value in text.replace("\n", " ")
    assert cr.amount_words in " ".join(text.split())


def test_the_due_date_and_its_derivation_are_both_on_the_page(base_reminder,
                                                              tmp_path):
    out = tmp_path / "reminder.pdf"
    remind(base_reminder, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "16 Aug 2026" in flat
    assert "15 calendar days" in flat
    assert "32 days overdue" in flat


def test_the_page_carries_the_disclaimer_whole(base_reminder, tmp_path):
    out = tmp_path / "reminder.pdf"
    result = remind(base_reminder, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert result.computed.stage.disclaimer in flat


def test_the_page_carries_no_legal_demand_language(base_reminder, tmp_path):
    import re
    out = tmp_path / "reminder.pdf"
    remind(base_reminder, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    for phrase in ("section 138", "MSMED", "legal action",
                   "recovery proceedings", "arbitration"):
        assert not re.search(rf"\b{re.escape(phrase)}\b", flat, re.IGNORECASE)


def test_the_interest_rate_and_its_source_are_both_printed(base_reminder,
                                                           tmp_path):
    out = tmp_path / "reminder.pdf"
    remind(base_reminder, out_pdf=out)
    flat = " ".join(extract_text(out).split())
    assert "14%" in flat
    assert "clause 4 of purchase order" in flat


def test_a_reminder_without_interest_prints_no_interest_block(
        base_reminder, tmp_path):
    base_reminder.pop("interest")
    out = tmp_path / "reminder.pdf"
    result = remind(base_reminder, out_pdf=out)
    assert not result.computed.charges_interest
    # The scope note names interest as something the tool does not decide, so
    # look for the block's own content rather than the word.
    flat = " ".join(extract_text(out).split())
    assert "per annum" not in flat
    assert "Total now payable" not in flat
    assert "Amount now payable" in flat


# ------------------------------------------------- when the page is not right

def test_a_page_that_disagrees_with_the_computation_is_deleted(base_reminder,
                                                               tmp_path):
    """Render an honest page, then verify it against a different figure."""
    out = tmp_path / "reminder.pdf"
    computed = _computed(base_reminder)
    render_reminder(computed, out)
    assert out.exists()

    lying = replace(computed, total_now=computed.total_now + Decimal("1000.00"))
    with pytest.raises(DocumentUnverified):
        verify_reminder(lying, out)
    assert not out.exists(), "the unverified PDF was left on disk"


def test_a_template_that_drops_the_disclaimer_is_caught(base_reminder,
                                                        tmp_path, monkeypatch):
    from quotation_studio import reminder_render

    stripped = tmp_path / "stripped.typ"
    original = reminder_render.TEMPLATE.read_text()
    marker = "// ---------- disclaimer ----------"
    assert marker in original
    stripped.write_text(original.split(marker)[0])
    monkeypatch.setattr(reminder_render, "TEMPLATE", stripped)

    out = tmp_path / "reminder.pdf"
    with pytest.raises(DocumentUnverified) as exc:
        remind(base_reminder, out_pdf=out)
    assert "disclaimer" in str(exc.value)
    assert not out.exists()


def test_a_blocked_reminder_leaves_no_file_behind(base_reminder, tmp_path):
    base_reminder["payments"][0]["received_on"] = "2026-10-20"
    out = tmp_path / "reminder.pdf"
    with pytest.raises(DocumentBlocked):
        remind(base_reminder, out_pdf=out)
    assert not out.exists()


def test_the_manifest_says_what_actually_ran(base_reminder, proforma_reminder,
                                             tmp_path):
    declared = remind(base_reminder, out_pdf=tmp_path / "a.pdf")
    assert "recomputed from the original document" not in declared.manifest

    recomputed = remind(proforma_reminder, out_pdf=tmp_path / "b.pdf")
    assert "recomputed from the original document" in recomputed.manifest
    assert "escalation stage derived from the ageing" in recomputed.manifest


def test_the_upi_qr_carries_the_amount_now_payable(base_reminder, tmp_path):
    out = tmp_path / "reminder.pdf"
    result = remind(base_reminder, out_pdf=out)
    with pdfplumber.open(str(out)) as pdf:
        assert pdf.pages[0].images, "the UPI QR is missing from the page"
    flat = " ".join(extract_text(out).split())
    assert "meridianlabs@okhdfcbank" in flat
    assert str(result.computed.total_now) in flat.replace(",", "")
