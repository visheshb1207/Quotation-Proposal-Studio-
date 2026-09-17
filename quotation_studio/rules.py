"""The rule pack: mandatory-field checks that block the document.

Scope, stated honestly and repeated in the manifest: these rules check
ARITHMETIC AND FIELD CORRECTNESS. They do not and cannot check tax law. The
tool does not know whether 18% is the right rate for your service, whether
998314 is the right SAC, or whether your registration status is what you
declared. Those are your inputs; these rules only confirm they are present and
structurally well-formed.

A failure at BLOCK severity produces no document. Not a watermarked one, not a
partial one -- nothing, plus the name of the field to fix. A WARN is printed
but does not stop the render.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from .gstin import validate_gstin
from .model import Document, DocumentType
from .money import format_inr
from .place_of_supply import PosRule
from .registration import TaxTreatment
from .states import is_valid_state_code, state_name

RULEPACK_VERSION = "quotation-fields-1.0.0"


class Severity(str, Enum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: Severity
    field: str
    message: str

    def __str__(self) -> str:
        mark = "BLOCK" if self.severity is Severity.BLOCK else "warn "
        return f"[{mark}] {self.field}: {self.message}  ({self.rule_id})"


class DocumentBlocked(Exception):
    """One or more BLOCK findings. No document is produced."""

    def __init__(self, findings: list[Finding]):
        self.findings = findings
        lines = "\n  ".join(f"{f.field} -- {f.message}" for f in findings)
        super().__init__(
            f"{len(findings)} field(s) must be fixed before this document can "
            f"be produced:\n  {lines}"
        )


def check(computed) -> list[Finding]:
    """Run the rule pack. Returns warnings; raises DocumentBlocked on failure."""
    doc: Document = computed.document
    findings: list[Finding] = []

    findings += _check_identity(doc)
    findings += _check_parties(doc)
    findings += _check_place_of_supply(doc, computed)
    findings += _check_items(doc, computed)
    findings += _check_treatment(doc, computed)

    blocking = [f for f in findings if f.severity is Severity.BLOCK]
    if blocking:
        raise DocumentBlocked(blocking)
    return [f for f in findings if f.severity is Severity.WARN]


def _check_identity(doc: Document) -> list[Finding]:
    out: list[Finding] = []

    if not doc.number.strip():
        out.append(Finding("DOC-001", Severity.BLOCK, "number",
                           "a document number is required"))
    elif len(doc.number) > 16:
        out.append(Finding(
            "DOC-002", Severity.WARN, "number",
            f"the number is {len(doc.number)} characters; invoice series are "
            f"capped at 16, so a matching invoice later will not be able to "
            f"reuse it"))

    if doc.valid_until and doc.valid_until < doc.issue_date:
        out.append(Finding(
            "DOC-003", Severity.BLOCK, "valid_until",
            f"the validity date ({doc.valid_until}) is before the issue date "
            f"({doc.issue_date})"))

    if doc.issue_date > date.today() + timedelta(days=1):
        out.append(Finding(
            "DOC-004", Severity.WARN, "issue_date",
            f"{doc.issue_date} is in the future"))

    if doc.currency != "INR":
        out.append(Finding(
            "DOC-005", Severity.BLOCK, "currency",
            f"this tool computes GST in rupees only; {doc.currency} is not "
            f"supported and would produce a tax split that means nothing"))

    return out


def _check_parties(doc: Document) -> list[Finding]:
    out: list[Finding] = []

    for who, party, required_gstin in (
        ("supplier", doc.supplier, doc.registration.registered),
        ("client", doc.client, False),
    ):
        if not party.state_code:
            severity = Severity.BLOCK if who == "supplier" else Severity.WARN
            out.append(Finding(
                "PTY-001", severity, f"{who}.state_code",
                "a two-digit GST state code is required"
                if who == "supplier" else
                "no state code given; the place of supply may fall back to the "
                "supplier's state under section 12(2)(b)"))
        elif not is_valid_state_code(party.state_code):
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
        elif required_gstin:
            out.append(Finding(
                "PTY-005", Severity.BLOCK, f"{who}.gstin",
                "you declared the business as GST-registered, so its GSTIN "
                "must appear on the document"))

        if not party.address:
            out.append(Finding("PTY-006", Severity.WARN, f"{who}.address",
                               "no address given"))

    return out


def _check_place_of_supply(doc: Document, computed) -> list[Finding]:
    pos = computed.place_of_supply
    out: list[Finding] = []

    if pos.rule is PosRule.MANUAL:
        out.append(Finding(
            "POS-001", Severity.WARN, "place_of_supply.nature",
            f"you stated the place of supply as {pos.state} yourself. This "
            f"tool did not derive it and does not vouch for it"))

    # The carve-out cases are where a state dropdown silently gets it wrong.
    # Say so on the document rather than letting it pass unremarked.
    carve_outs = {
        PosRule.SERVICES_TRAINING, PosRule.SERVICES_IMMOVABLE_PROPERTY,
        PosRule.SERVICES_PERFORMANCE_BASED, PosRule.SERVICES_EVENT_ADMISSION,
        PosRule.SERVICES_EVENT_ORGANISING,
    }
    if (pos.rule in carve_outs and doc.client.state_code
            and pos.state_code != doc.client.state_code):
        out.append(Finding(
            "POS-002", Severity.WARN, "place_of_supply",
            f"the place of supply is {pos.state}, NOT the client's state "
            f"({state_name(doc.client.state_code)}), because {pos.rule.value} "
            f"applies. Check this is what you intended"))

    return out


def _check_items(doc: Document, computed) -> list[Finding]:
    out: list[Finding] = []
    charging = computed.tax_is_charged

    for i, (item, line) in enumerate(zip(doc.items, computed.lines)):
        where = f"items[{i}]"

        if not item.hsn_sac:
            out.append(Finding(
                "ITM-001", Severity.BLOCK, f"{where}.hsn_sac",
                "an HSN (goods) or SAC (services) code is required. This is "
                "your classification -- the tool will not choose one for you"))
        elif not item.hsn_sac.isdigit():
            out.append(Finding(
                "ITM-002", Severity.BLOCK, f"{where}.hsn_sac",
                f"{item.hsn_sac!r} is not numeric; HSN and SAC codes are digits"))
        elif len(item.hsn_sac) not in (4, 6, 8):
            out.append(Finding(
                "ITM-003", Severity.BLOCK, f"{where}.hsn_sac",
                f"{item.hsn_sac!r} is {len(item.hsn_sac)} digits; HSN and SAC "
                f"codes are 4, 6 or 8 digits"))

        if item.quantity <= 0:
            out.append(Finding("ITM-004", Severity.BLOCK, f"{where}.quantity",
                               f"must be greater than zero, got {item.quantity}"))
        if item.rate < 0:
            out.append(Finding("ITM-005", Severity.BLOCK, f"{where}.rate",
                               f"cannot be negative, got {format_inr(item.rate)}"))

        if charging and item.gst_rate not in _DECLARABLE_RATES:
            out.append(Finding(
                "ITM-006", Severity.WARN, f"{where}.gst_rate",
                f"{item.gst_rate}% is not one of the common GST rates "
                f"({_rates_text()}). The tool accepts your declaration but "
                f"cannot tell you whether it is right"))

        if line.taxable < 0:
            out.append(Finding("ITM-007", Severity.BLOCK, f"{where}.discount_value",
                               "the discount makes this line negative"))

    return out


def _check_treatment(doc: Document, computed) -> list[Finding]:
    """Cross-checks between the registration gate and what was computed."""
    out: list[Finding] = []
    treatment = computed.treatment

    if treatment is TaxTreatment.UNREGISTERED and doc.supplier.gstin:
        out.append(Finding(
            "REG-001", Severity.BLOCK, "registration.registered",
            "you answered that the business is not GST-registered, but a "
            "supplier GSTIN was supplied. These contradict each other"))

    if not treatment.tax_is_charged and computed.tax_total:
        out.append(Finding(
            "REG-002", Severity.BLOCK, "registration",
            f"tax of {format_inr(computed.tax_total)} was computed even though "
            f"{computed.document.registration.why}. This is a bug in the tool"))

    if treatment is TaxTreatment.COMPOSITION and doc.doc_type is DocumentType.PROFORMA:
        out.append(Finding(
            "REG-003", Severity.WARN, "doc_type",
            "a composition dealer issues a bill of supply rather than a tax "
            "invoice; this proforma carries the required declaration but "
            "check it suits your purpose"))

    return out


# The rates currently in force. This list exists ONLY so an obvious typo
# (1.8 instead of 18) raises a warning. It is never used to pick a rate.
_DECLARABLE_RATES = {
    Decimal(r)
    for r in ("0", "0.1", "0.25", "1", "1.5", "3", "5", "6", "12", "18", "28")
}


def _rates_text() -> str:
    return ", ".join(
        f"{r.normalize()}%" for r in sorted(_DECLARABLE_RATES)
    )
