"""The tool must be structurally unable to render a tax invoice.

From the blueprint: the document type string is hard-coded to Quotation or
Proforma, and the tool physically cannot render "Tax Invoice" until a
practising CA has reviewed the CGST Rule 46 pack and signed the changelog.

This test is the enforcement. It fails if anyone adds the capability without
that review -- including by adding a template string, an enum member, or a
title that a careless change could route to.
"""

import re
from pathlib import Path

import pytest

from quotation_studio.model import DocumentType

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(
    list((ROOT / "quotation_studio").rglob("*.py"))
    + list((ROOT / "templates").rglob("*.typ"))
)

# Where the phrase is allowed: only in text that DENIES being a tax invoice,
# or in a comment explaining this rule. Matched against a window of surrounding
# text rather than a single line, because comments and strings wrap.
_PERMITTED = re.compile(
    r"not a tax invoice"
    r"|not valid for input tax credit"
    r"|cannot (?:produce|render) a tax invoice"
    r"|rather than a tax invoice"
    r"|neither is a tax invoice"
    r"|there is no \"Tax Invoice\" value"
    r"|must NOT claim to be a"
    r"|no 'Tax Invoice' claim"
    r"|contains the words 'Tax Invoice'",
    re.IGNORECASE,
)

_MENTION = re.compile(r"\btax\s+invoice\b", re.IGNORECASE)
_WINDOW = 160


def test_document_type_has_exactly_two_members():
    assert [d.value for d in DocumentType] == ["quotation", "proforma"]


def test_titles_never_say_tax_invoice():
    for d in DocumentType:
        assert "TAX INVOICE" not in d.title.upper()


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_source_file_claims_to_produce_a_tax_invoice(path):
    text = path.read_text()
    for match in _MENTION.finditer(text):
        window = text[max(0, match.start() - _WINDOW): match.end() + _WINDOW]
        lineno = text.count("\n", 0, match.start()) + 1
        assert _PERMITTED.search(window), (
            f"{path.relative_to(ROOT)}:{lineno} mentions a tax invoice "
            f"outside a disclaimer:\n  {window.strip()}\n\n"
            f"Adding this capability requires a practising CA to review the "
            f"CGST Rule 46 pack and sign the changelog."
        )


def test_an_unknown_document_type_is_refused_with_an_explanation():
    from quotation_studio.model import Document
    with pytest.raises(ValueError) as exc:
        Document.from_dict({"doc_type": "tax_invoice"})
    assert "cannot produce a tax invoice" in str(exc.value)


def test_both_document_types_carry_a_disclaimer():
    for d in DocumentType:
        assert "not a tax invoice" in d.disclaimer
