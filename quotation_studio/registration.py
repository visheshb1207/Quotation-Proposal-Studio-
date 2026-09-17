"""The three-question registration gate.

Skeptic's fix, adopted: no tax may be computed until the supplier's own
registration status is declared. An unregistered supplier who charges GST on a
document is committing an offence; a composition dealer who does so is
committing a different one. The tool must not let a template do that silently.

These are the supplier's declarations about their own business. The tool does
not verify them and does not guess them -- it refuses to compute tax until
they are answered.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaxTreatment(str, Enum):
    """What the answers entitle the document to show."""

    FORWARD_CHARGE = "forward_charge"      # normal: supplier computes and collects
    COMPOSITION = "composition"            # no tax collectible; declaration required
    UNREGISTERED = "unregistered"          # no tax collectible at all
    REVERSE_CHARGE = "reverse_charge"      # recipient pays; supplier shows zero

    @property
    def tax_is_charged(self) -> bool:
        return self is TaxTreatment.FORWARD_CHARGE


# The literal wording put to the user. Kept here so the CLI, any future UI and
# the audit trail all ask the identical question.
QUESTIONS = (
    ("registered",
     "Is your business registered under GST with a valid GSTIN?"),
    ("composition",
     "Are you registered under the Composition Scheme (section 10)?"),
    ("reverse_charge",
     "Is this particular supply taxable under reverse charge, so that the "
     "recipient -- not you -- pays the GST?"),
)

# The mandatory declaration a composition dealer must carry on every bill of
# supply. Quoted from rule 5(1)(f) of the Composition Rules.
COMPOSITION_DECLARATION = (
    "Composition taxable person, not eligible to collect tax on supplies."
)

REVERSE_CHARGE_DECLARATION = (
    "Tax payable on reverse charge basis by the recipient."
)

UNREGISTERED_DECLARATION = (
    "Supplier is not registered under GST. No tax is charged on this document."
)


@dataclass(frozen=True)
class RegistrationStatus:
    registered: bool
    composition: bool
    reverse_charge: bool

    @classmethod
    def from_dict(cls, data: dict) -> "RegistrationStatus":
        missing = [key for key, _ in QUESTIONS if key not in data]
        if missing:
            raise RegistrationGateNotAnswered(missing)
        return cls(
            registered=bool(data["registered"]),
            composition=bool(data["composition"]),
            reverse_charge=bool(data["reverse_charge"]),
        )

    @property
    def treatment(self) -> TaxTreatment:
        # Order matters: unregistered dominates everything, then composition,
        # then reverse charge. Each of these forbids charging tax.
        if not self.registered:
            return TaxTreatment.UNREGISTERED
        if self.composition:
            return TaxTreatment.COMPOSITION
        if self.reverse_charge:
            return TaxTreatment.REVERSE_CHARGE
        return TaxTreatment.FORWARD_CHARGE

    @property
    def declaration(self) -> str | None:
        """The line the document is required to carry, if any."""
        return {
            TaxTreatment.UNREGISTERED: UNREGISTERED_DECLARATION,
            TaxTreatment.COMPOSITION: COMPOSITION_DECLARATION,
            TaxTreatment.REVERSE_CHARGE: REVERSE_CHARGE_DECLARATION,
            TaxTreatment.FORWARD_CHARGE: None,
        }[self.treatment]

    @property
    def why(self) -> str:
        """Plain-English reason shown next to a zero-tax document."""
        return {
            TaxTreatment.UNREGISTERED:
                "you declared that your business is not registered under GST",
            TaxTreatment.COMPOSITION:
                "you declared that you are registered under the Composition "
                "Scheme, which does not permit collecting tax from the recipient",
            TaxTreatment.REVERSE_CHARGE:
                "you declared this supply as reverse charge, so the recipient "
                "pays the tax directly",
            TaxTreatment.FORWARD_CHARGE: "",
        }[self.treatment]


class RegistrationGateNotAnswered(Exception):
    """Raised instead of computing tax against unanswered questions."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        wording = dict(QUESTIONS)
        asked = "; ".join(f"{k} -- {wording[k]}" for k in missing)
        super().__init__(
            "No tax can be computed until the registration gate is answered. "
            f"Unanswered: {asked}"
        )
