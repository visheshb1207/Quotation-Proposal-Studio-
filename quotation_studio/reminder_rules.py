"""The reminder rule pack: field checks that block the letter.

Scope, stated as honestly as the document pack states its own: these rules
check DATE AND FIELD CORRECTNESS. They do not and cannot check whether the
money is actually owed, whether the underlying supply was made, whether the
recipient disputes it, or whether chasing it is wise. Those are matters of
fact and judgement outside anything the tool can see.

What it can see, and refuses on, is a reminder that contradicts itself: one
that states its position as at a date before the document it chases, one that
counts a payment received after that date, or one that escalates to a final
demand on money that is not yet due.

A BLOCK produces no document -- not a watermarked one, not a partial one --
plus the name of the field to fix. A WARN is printed and does not stop it.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from .dates import format_date
from .gstin import validate_gstin
from .money import format_inr
from .receivable import ReferenceKind, ReminderStage
from .rules import DocumentBlocked, Finding, Severity
from .states import is_valid_state_code, state_name

REMINDER_RULEPACK_VERSION = "reminder-fields-1.0.0"

# Above this, an annual rate is more likely to be a typo (a monthly rate typed
# into an annual field) than a term anybody agreed. The tool still computes it.
_IMPLAUSIBLE_ANNUAL_RATE = Decimal("36")

# Below this, the postage costs more than the debt. Said once, as a warning.
_TRIVIAL_BALANCE = Decimal("100")


def check_reminder(computed) -> list[Finding]:
    """Run the pack. Returns warnings; raises DocumentBlocked on failure."""
    findings: list[Finding] = []

    findings += _check_calendar(computed)
    findings += _check_payments(computed)
    findings += _check_parties(computed)
    findings += _check_reference(computed)
    findings += _check_escalation(computed)
    findings += _check_interest(computed)

    blocking = [f for f in findings if f.severity is Severity.BLOCK]
    if blocking:
        raise DocumentBlocked(blocking)
    return [f for f in findings if f.severity is Severity.WARN]


def _check_calendar(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []

    if req.as_of < req.reference.dated:
        out.append(Finding(
            "REM-001", Severity.BLOCK, "as_of",
            f"this reminder states its position as at "
            f"{format_date(req.as_of)}, which is before the document it "
            f"chases was raised ({format_date(req.reference.dated)})"))

    if req.as_of > date.today() + timedelta(days=1):
        out.append(Finding(
            "REM-002", Severity.WARN, "as_of",
            f"{format_date(req.as_of)} is in the future, so this reminder "
            f"states a position that has not happened yet"))

    for i, sent in enumerate(req.history):
        if sent > req.as_of:
            out.append(Finding(
                "REM-003", Severity.BLOCK, f"history[{i}]",
                f"a previous reminder is recorded as sent on "
                f"{format_date(sent)}, after the date this one states its "
                f"position as at ({format_date(req.as_of)})"))
        elif sent < req.reference.dated:
            out.append(Finding(
                "REM-004", Severity.WARN, f"history[{i}]",
                f"a previous reminder is recorded as sent on "
                f"{format_date(sent)}, before the document it chases was "
                f"raised"))

    return out


def _check_payments(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []

    for i, payment in enumerate(req.payments):
        where = f"payments[{i}]"
        if payment.received_on > req.as_of:
            out.append(Finding(
                "PAY-001", Severity.BLOCK, f"{where}.received_on",
                f"this payment is dated {format_date(payment.received_on)}, "
                f"after the date this reminder states its position as at "
                f"({format_date(req.as_of)}). A reminder cannot account for "
                f"money it was not yet told about"))
        elif payment.received_on < req.reference.dated:
            out.append(Finding(
                "PAY-002", Severity.WARN, f"{where}.received_on",
                f"this payment is dated {format_date(payment.received_on)}, "
                f"before the document it is set against was raised. It may be "
                f"an advance against something else"))

        if not payment.reference:
            out.append(Finding(
                "PAY-003", Severity.WARN, f"{where}.reference",
                "no payment reference given; the recipient's accounts team "
                "cannot match this receipt without one"))

    if computed.outstanding < _TRIVIAL_BALANCE:
        out.append(Finding(
            "PAY-004", Severity.WARN, "payments",
            f"the balance outstanding is {format_inr(computed.outstanding)}. "
            f"Chasing it may cost more than it recovers"))

    return out


def _check_parties(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []

    for who, party in (("supplier", req.supplier), ("client", req.client)):
        if party.state_code and not is_valid_state_code(party.state_code):
            out.append(Finding(
                "PTY-002", Severity.BLOCK, f"{who}.state_code",
                f"{party.state_code!r} is not a valid GST state code"))

        if party.gstin:
            verdict = validate_gstin(party.gstin, field=f"{who}.gstin")
            if not verdict.ok:
                out.append(Finding("PTY-003", Severity.BLOCK,
                                   f"{who}.gstin", verdict.reason or "invalid"))
            elif party.state_code and verdict.state_code != party.state_code:
                out.append(Finding(
                    "PTY-004", Severity.BLOCK, f"{who}.gstin",
                    f"the GSTIN begins with {verdict.state_code} "
                    f"({verdict.state}), but {who}.state_code says "
                    f"{party.state_code} ({state_name(party.state_code)}). "
                    f"One of the two is wrong"))

    if not (req.client.email or req.client.phone):
        out.append(Finding(
            "PTY-007", Severity.WARN, "client",
            "no email address or phone number for the client, so there is no "
            "recorded route by which this reminder reaches anybody"))

    if not req.supplier.email and not req.supplier.phone:
        out.append(Finding(
            "PTY-008", Severity.WARN, "supplier",
            "no contact details for the supplier; a recipient who wants to "
            "query or settle this has nowhere to reply"))

    return out


def _check_reference(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []

    if len(req.reference.number) > 16:
        out.append(Finding(
            "REF-001", Severity.WARN, "reference.number",
            f"the reference is {len(req.reference.number)} characters; "
            f"document series are capped at 16, so this may not match what "
            f"the recipient has on file"))

    if (req.reference.kind is ReferenceKind.PROFORMA
            and req.source_document is None):
        out.append(Finding(
            "REF-002", Severity.WARN, "source_document",
            "you declared this as a proforma but did not supply the original "
            "document, so the amount chased is your declaration and was not "
            "recomputed. Supply source_document to have it checked"))

    if len(req.number) > 16:
        out.append(Finding(
            "REF-003", Severity.WARN, "number",
            f"this reminder's own reference is {len(req.number)} characters"))

    return out


def _check_escalation(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []

    if computed.stage is ReminderStage.FINAL and not req.history:
        out.append(Finding(
            "ESC-001", Severity.WARN, "history",
            f"this is a final reminder at {computed.days_overdue} days "
            f"overdue, but no earlier reminder is recorded. If earlier ones "
            f"were sent, list them in history so the document says so"))

    if computed.stage is ReminderStage.COURTESY and req.history:
        out.append(Finding(
            "ESC-002", Severity.WARN, "history",
            f"{len(req.history)} earlier reminder(s) are recorded, but nothing "
            f"is overdue as at {format_date(req.as_of)}. Check the due date"))

    if len(req.history) >= 4:
        out.append(Finding(
            "ESC-003", Severity.WARN, "history",
            f"{len(req.history)} reminders have already gone out. Another "
            f"letter is unlikely to be what changes this"))

    return out


def _check_interest(computed) -> list[Finding]:
    req = computed.request
    out: list[Finding] = []
    terms = req.interest

    if terms is None:
        return out

    if terms.rate_percent_per_annum > _IMPLAUSIBLE_ANNUAL_RATE:
        out.append(Finding(
            "INT-001", Severity.WARN, "interest.rate_percent_per_annum",
            f"{terms.rate_percent_per_annum.normalize()}% per annum is high "
            f"enough to look like a monthly rate typed into an annual field. "
            f"The tool computes what you declared and has no view on whether "
            f"it is enforceable"))

    if computed.interest > computed.outstanding:
        out.append(Finding(
            "INT-002", Severity.BLOCK, "interest",
            f"the interest computed ({format_inr(computed.interest)}) exceeds "
            f"the principal outstanding ({format_inr(computed.outstanding)}). "
            f"Check the rate and the due date before this goes anywhere"))

    return out
