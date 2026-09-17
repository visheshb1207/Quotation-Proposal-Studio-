"""Post-render verification for a reminder: read the PDF back.

Everything before this point verifies the computation. This verifies the
LETTER -- the artefact that leaves the building. A due date formatted into the
wrong cell, a balance left over from a previous render, a template that quietly
drops the disclaimer: none of those are visible to ageing.py, and all of them
are visible here.

A failure yields nothing. The PDF is deleted, not handed over with a warning.

There is one check here the document pack does not need. A reminder is the
document in this studio most likely to be escalated into something it is not,
so the rendered bytes are searched for the language of a legal demand, and any
of it outside an explicit denial deletes the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from .ageing import ComputedReminder
from .dates import format_date
from .money import ZERO, format_inr
from .verify import DocumentUnverified, VerificationFailure, extract_text
from .words import amount_in_words

# Language that turns a reminder into an instrument with consequences the tool
# cannot reason about. Permitted only inside a sentence that denies it.
_DEMAND_LANGUAGE = re.compile(
    r"\blegal notice\b|\bdemand notice\b|\bsection 138\b|\bMSMED\b"
    r"|\blegal action\b|\brecovery proceedings\b|\bwithout prejudice\b"
    r"|\barbitration\b|\bwinding[- ]up\b|\binsolvency\b",
    re.IGNORECASE,
)

_DENIAL = re.compile(
    r"is not a legal notice|not a legal notice, a demand notice"
    r"|no legal-demand language",
    re.IGNORECASE,
)

_WINDOW = 200

# Typst may break a line after a slash or a hyphen, and PDF extraction then
# leaves a space where the break was: "AUR/PO/2026/4412" comes back as
# "AUR/ PO/2026/4412". A free-text field that happens to contain a slash would
# otherwise fail verification for a reason that has nothing to do with whether
# the document says the right thing. The tolerance costs nothing, for the same
# reason verify.py's concatenated-cell tolerance does: it only closes a gap
# after a slash or hyphen, and every FIGURE checked here is digits, commas and
# a decimal point, so no wrong number can slip through it.
_SOFT_BREAK = re.compile(r"(?<=[/-])\s+")


def _unbreak(text: str) -> str:
    return _SOFT_BREAK.sub("", text)


def verify_reminder(computed: ComputedReminder, pdf_path: Path) -> str:
    """Re-extract and compare. Raises DocumentUnverified on any mismatch."""
    text = extract_text(Path(pdf_path))
    flat = re.sub(r"\s+", " ", text)

    unbroken = _unbreak(flat)

    failures: list[VerificationFailure] = []
    req = computed.request

    def must_contain(what: str, value: str) -> None:
        if value not in flat and _unbreak(value) not in unbroken:
            failures.append(VerificationFailure(what, value,
                                                "does not contain it"))

    # 1. Every figure a recipient would re-add must appear as printed.
    must_contain("amount due", format_inr(computed.amount_due))
    must_contain("balance outstanding", format_inr(computed.outstanding))
    must_contain("total now payable", format_inr(computed.total_now))
    if computed.payments_total:
        must_contain("payments received", format_inr(computed.payments_total))
    if computed.charges_interest:
        must_contain("interest", format_inr(computed.interest))

    for i, payment in enumerate(req.payments):
        must_contain(f"payments[{i}] amount", format_inr(payment.amount))
        must_contain(f"payments[{i}] date", format_date(payment.received_on))

    # 2. Every date the letter turns on must be on the page. A reminder whose
    #    due date is missing is a reminder the recipient cannot check.
    must_contain("due date", format_date(computed.due_date))
    must_contain("as-at date", format_date(req.as_of))
    must_contain("reference date", format_date(req.reference.dated))
    must_contain("reference number", req.reference.number)
    for i, sent in enumerate(req.history):
        must_contain(f"history[{i}]", format_date(sent))

    # 3. The ageing must be stated in words, so nobody has to subtract dates to
    #    find out whether this is overdue at all.
    from .reminder_render import _status_line
    must_contain("ageing status", _status_line(computed))
    must_contain("ageing bucket", computed.bucket_label)

    # 4. The amount in words must be present AND re-derive to the same number
    #    as the printed total. This catches a words line left over from a
    #    previous render.
    must_contain("amount in words", computed.amount_words)
    re_derived = amount_in_words(computed.total_now)
    if re_derived != computed.amount_words:
        failures.append(VerificationFailure(
            "amount in words", re_derived,
            f"was computed as {computed.amount_words!r}"))

    # 5. The letter must name itself correctly and must carry the disclaimer.
    must_contain("document title", computed.stage.title)
    must_contain("disclaimer", computed.stage.disclaimer)

    # 6. It must NOT claim to be a tax invoice. Checked on the rendered bytes.
    if re.search(r"\btax\s+invoice\b", flat, re.IGNORECASE):
        if "not a tax invoice" not in flat.lower():
            failures.append(VerificationFailure(
                "document type", "no 'Tax Invoice' claim",
                "contains the words 'Tax Invoice'"))

    # 7. It must not read as a legal demand.
    for match in _DEMAND_LANGUAGE.finditer(flat):
        window = flat[max(0, match.start() - _WINDOW): match.end() + _WINDOW]
        if not _DENIAL.search(window):
            failures.append(VerificationFailure(
                "tone", "no legal-demand language",
                f"contains {match.group(0)!r} outside a denial"))

    # 8. Where interest is charged, the rate and where it was agreed must both
    #    be printed. An interest line with no cited source is not checkable.
    if computed.charges_interest:
        assert req.interest is not None
        must_contain("interest rate",
                     f"{req.interest.rate_percent_per_annum.normalize()}%")
        must_contain("interest source", req.interest.declared_in)

    # 9. No stray figure: every rupee-shaped token must be one we computed.
    stray = _stray_figures(flat, computed)
    if stray:
        failures.append(VerificationFailure(
            "figures on the page", "only computed figures",
            f"contains {', '.join(sorted(stray))} which nothing computed"))

    if failures:
        Path(pdf_path).unlink(missing_ok=True)
        raise DocumentUnverified(failures)

    return text


def _stray_figures(flat: str, computed: ComputedReminder) -> set[str]:
    from .verify import _FIGURE_RE, _decomposes

    expected = _expected_figures(computed)
    return {
        token for token in _FIGURE_RE.findall(flat)
        if not _decomposes(token, expected)
    }


def _expected_figures(computed: ComputedReminder) -> set[str]:
    expected: set[str] = {
        format_inr(computed.amount_due),
        format_inr(computed.payments_total),
        format_inr(-computed.payments_total),
        format_inr(computed.outstanding),
        format_inr(computed.interest),
        format_inr(computed.total_now),
        format_inr(ZERO),
    }
    for payment in computed.request.payments:
        expected.add(format_inr(payment.amount))

    # A declared interest rate can itself look like a rupee figure once it is
    # printed (13.25%), so it belongs in the expected set rather than being
    # reported as a number nobody computed.
    if computed.request.interest is not None:
        rate = computed.request.interest.rate_percent_per_annum
        expected.add(f"{rate.normalize()}")
        expected.add(str(rate))

    expected |= {v.lstrip("-") for v in expected}
    return expected
