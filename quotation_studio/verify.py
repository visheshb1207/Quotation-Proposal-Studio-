"""Post-render verification: read the PDF back and check what it actually says.

Everything before this point verifies the computation. This verifies the
DOCUMENT -- the artefact that leaves the building. A template bug, a column
that silently overflows, a figure formatted into the wrong cell: none of those
are visible to compute.py, and all of them are visible here.

The rule from the blueprint: pdfplumber extracts the text and the document
totals must equal the computed totals. A failure yields nothing -- the PDF is
deleted, not handed over with a warning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pdfplumber

from .compute import ComputedDocument
from .money import format_inr
from .words import amount_in_words


@dataclass(frozen=True)
class VerificationFailure:
    what: str
    expected: str
    found: str


class DocumentUnverified(Exception):
    """The rendered PDF does not say what was computed. Nothing is released."""

    def __init__(self, failures: list[VerificationFailure]):
        self.failures = failures
        detail = "\n  ".join(
            f"{f.what}: expected {f.expected!r}, the PDF {f.found}"
            for f in failures
        )
        super().__init__(
            "The rendered PDF does not match the computed figures, so it was "
            "deleted rather than handed over. This is a bug in the tool, not "
            "in your input.\n  " + detail
        )


def extract_text(pdf_path: Path) -> str:
    with pdfplumber.open(str(pdf_path)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def verify(computed: ComputedDocument, pdf_path: Path) -> str:
    """Re-extract and compare. Raises DocumentUnverified on any mismatch."""
    text = extract_text(Path(pdf_path))
    # PDF extraction can split on odd boundaries; normalise whitespace so the
    # comparison is about the figures, not about layout.
    flat = re.sub(r"\s+", " ", text)

    failures: list[VerificationFailure] = []

    def must_contain(what: str, value: str) -> None:
        if value not in flat:
            failures.append(VerificationFailure(what, value, "does not contain it"))

    # 1. Every total that a recipient would re-add must appear as printed.
    must_contain("taxable total", format_inr(computed.taxable_total))
    must_contain("grand total", format_inr(computed.grand_total))
    if computed.tax_is_charged:
        if computed.is_interstate:
            must_contain("IGST total", format_inr(computed.igst_total))
        else:
            must_contain("CGST total", format_inr(computed.cgst_total))
            must_contain("SGST total", format_inr(computed.sgst_total))

    # 2. Every line's taxable value and amount must appear.
    for i, ln in enumerate(computed.lines):
        must_contain(f"items[{i}] taxable", format_inr(ln.taxable))
        must_contain(f"items[{i}] amount", format_inr(ln.total))

    # 3. The amount in words must be present AND must re-derive to the same
    #    number as the printed grand total. This is the check that catches a
    #    words line left over from a previous render.
    must_contain("amount in words", computed.amount_words)
    re_derived = amount_in_words(computed.grand_total)
    if re_derived != computed.amount_words:
        failures.append(VerificationFailure(
            "amount in words", re_derived,
            f"was computed as {computed.amount_words!r}"))

    # 4. The document must name itself correctly, and must NOT claim to be a
    #    tax invoice. This is checked on the rendered bytes, not the model.
    must_contain("document title", computed.document.doc_type.title)
    if re.search(r"\btax\s+invoice\b", flat, re.IGNORECASE):
        if "not a tax invoice" not in flat.lower():
            failures.append(VerificationFailure(
                "document type", "no 'Tax Invoice' claim",
                "contains the words 'Tax Invoice'"))

    # 5. The statutory declaration, when one is required, must be on the page.
    declaration = computed.document.registration.declaration
    if declaration:
        must_contain("statutory declaration", declaration)

    # 6. The place of supply and the rule that derived it must be visible, so
    #    the recipient can check the reasoning rather than trust it.
    must_contain("place of supply", computed.place_of_supply.state)
    must_contain("place-of-supply rule", computed.place_of_supply.rule.value)

    # 7. No stray figure: every rupee-shaped token in the PDF must be one we
    #    computed. This is what catches a template printing a number nobody
    #    asked for.
    stray = _stray_figures(flat, computed)
    if stray:
        failures.append(VerificationFailure(
            "figures on the page", "only computed figures",
            f"contains {', '.join(sorted(stray))} which nothing computed"))

    if failures:
        Path(pdf_path).unlink(missing_ok=True)
        raise DocumentUnverified(failures)

    return text


_FIGURE_RE = re.compile(r"\d{1,3}(?:,\d{2})*(?:,\d{3})?\.\d{2}|\d+\.\d{2}")


def _stray_figures(flat: str, computed: ComputedDocument) -> set[str]:
    """Rupee-formatted tokens on the page that no computation produced.

    PDF text extraction can run two adjacent table cells together, so a token
    may legitimately be several expected figures concatenated. A token is
    therefore stray only if it cannot be decomposed into a sequence of figures
    we computed. That tolerance costs nothing: an invented figure still fails,
    because it is not in the expected set and neither are its pieces.
    """
    expected = _expected_figures(computed)
    return {
        token for token in _FIGURE_RE.findall(flat)
        if not _decomposes(token, expected)
    }


def _expected_figures(computed: ComputedDocument) -> set[str]:
    from .money import split_half

    expected: set[str] = {
        format_inr(computed.gross_total),
        format_inr(computed.discount_total),
        format_inr(computed.taxable_total),
        format_inr(computed.cgst_total),
        format_inr(computed.sgst_total),
        format_inr(computed.igst_total),
        format_inr(computed.tax_total),
        format_inr(computed.round_off),
        format_inr(computed.grand_total),
        format_inr(-computed.discount_total),
    }
    for ln in computed.lines:
        expected |= {
            format_inr(ln.item.rate), format_inr(ln.gross),
            format_inr(ln.discount), format_inr(ln.taxable),
            format_inr(ln.tax), format_inr(ln.cgst), format_inr(ln.sgst),
            format_inr(ln.igst), format_inr(ln.total),
        }
    for _, taxable, tax in computed.rate_summary:
        expected |= {format_inr(taxable), format_inr(tax)}
        cgst, sgst = split_half(tax)
        expected |= {format_inr(cgst), format_inr(sgst)}
    # A leading minus may be dropped or rendered as a different glyph.
    expected |= {v.lstrip("-") for v in expected}
    return expected


def _decomposes(token: str, expected: set[str]) -> bool:
    """Can `token` be read as one or more expected figures, end to end?"""
    if token in expected:
        return True
    n = len(token)
    reachable = [False] * (n + 1)
    reachable[0] = True
    for i in range(n):
        if not reachable[i]:
            continue
        for candidate in expected:
            j = i + len(candidate)
            if j <= n and token.startswith(candidate, i):
                reachable[j] = True
    return reachable[n]
