"""The reminder model: what is owed, against what, and what has been paid.

Three things here are load-bearing.

1. `ReminderStage` has exactly three members and none of them is a legal
   notice. A reminder escalates in tone; it never escalates into a demand
   under section 138 or the MSMED Act, because those are legal instruments
   whose consequences this tool cannot reason about. The strings do not exist
   in the codebase, and tests/test_no_legal_notice.py fails the build if
   anyone adds them.

2. The stage is DERIVED from how overdue the money is, not chosen. A dropdown
   would let a final reminder go out on a bill that is not yet due, which is
   the single most expensive mistake in this whole workflow. The boundary that
   produced the stage is printed on the document.

3. The reference this chases is the SUPPLIER'S DECLARATION, exactly like a GST
   rate. This tool is structurally unable to produce a document that creates a
   receivable -- DocumentType has two members and neither is one. So when you
   chase an invoice you raised elsewhere, the tool records the number, date and
   amount you state, prints them as your declaration, and vouches for none of
   it. What it does vouch for is the arithmetic and the calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from .dates import (
    DEFAULT_BUCKETS, parse_buckets, to_date, to_days, to_optional_date,
)
from .model import Party
from .money import ZERO, money, to_decimal


class ReferenceKind(str, Enum):
    """What the money is owed against.

    PROFORMA -- a proforma this tool produced. Its total can be recomputed
                from the original document, and when that document is supplied
                the engine does exactly that and refuses any declared amount
                that disagrees with it.
    INVOICE  -- a document raised outside this tool. Number, date and amount
                are the supplier's declaration and nothing about them is
                verified. This is not a tax invoice produced by this tool and
                the document says so.
    """

    PROFORMA = "proforma"
    INVOICE = "invoice"

    @property
    def label(self) -> str:
        return {"proforma": "Proforma", "invoice": "Invoice"}[self.value]

    @property
    def provenance(self) -> str:
        """Printed under the reference so a reader knows what stands behind it."""
        return {
            "proforma":
                "Produced by this tool. Its total was recomputed from the "
                "original document before this reminder was rendered.",
            "invoice":
                "Raised outside this tool. The number, date and amount above "
                "are the supplier's declaration and are not verified here.",
        }[self.value]


class ReminderStage(str, Enum):
    """The only three stages. Derived from the ageing, never chosen."""

    COURTESY = "courtesy"     # not yet due, or due today
    OVERDUE = "overdue"       # past due, within the declared boundaries
    FINAL = "final"           # past the last declared boundary

    @property
    def title(self) -> str:
        return {
            "courtesy": "PAYMENT REMINDER",
            "overdue": "PAYMENT REMINDER",
            "final": "FINAL PAYMENT REMINDER",
        }[self.value]

    @property
    def opening(self) -> str:
        """The one sentence that sets the tone. Fixed text, never generated."""
        return {
            "courtesy":
                "This is a courtesy reminder that the amount below falls due "
                "shortly. If payment is already on its way, please treat this "
                "as a record of the position and ignore it.",
            "overdue":
                "The amount below is shown as outstanding in our records as at "
                "the date of this reminder. If it has been settled since, "
                "please let us know the payment date and reference.",
            "final":
                "The amount below remains outstanding in our records and is "
                "now past the last of the payment boundaries set out on this "
                "document. We would like to settle it by agreement.",
        }[self.value]

    @property
    def disclaimer(self) -> str:
        """Carried on every reminder, whatever the stage."""
        return (
            "This is a payment reminder. It is a statement of the position in "
            "the supplier's own records, it is not a tax invoice, and it is "
            "not a legal notice, a demand notice or a filing of any kind. It "
            "creates no liability and confers no right of recovery. The "
            "supplier has no connection to any bank account here, so a payment "
            "made and not yet recorded is not reflected in these figures."
        )


class InterestBasis(str, Enum):
    """Only one basis is implemented, and the document names it.

    Simple interest, per annum, on the outstanding principal, from the due
    date to the stated date, on a declared day-count basis. Compounding is not
    offered: compounding intervals are a contractual term with more variants
    than the tool can hold, and getting one wrong overstates a debt.
    """

    SIMPLE_PER_ANNUM = "simple_per_annum"

    @property
    def description(self) -> str:
        return ("simple interest per annum on the outstanding principal, "
                "from the due date to the date of this reminder")


@dataclass(frozen=True)
class InterestTerms:
    """Interest is computed only when it is declared, with its source named.

    Whether interest is chargeable at all, and at what rate, is a term of your
    contract or a matter of statute. The tool has no view on either. It will
    do the arithmetic once you state the rate AND state where you agreed it,
    and it prints that source on the document so the recipient can look it up.
    """

    rate_percent_per_annum: Decimal
    basis: InterestBasis
    declared_in: str
    day_count_basis: int

    @classmethod
    def from_dict(cls, data: dict | None) -> "InterestTerms | None":
        if data in (None, {}):
            return None
        if not isinstance(data, dict):
            raise ValueError("interest: expected an object")

        if data.get("rate_percent_per_annum") is None:
            raise ValueError(
                "interest.rate_percent_per_annum: is required once an interest "
                "block is present. This tool does not know whether interest is "
                "chargeable on your contract, or at what rate, and will not "
                "supply a figure"
            )
        rate = to_decimal(data["rate_percent_per_annum"],
                          field="interest.rate_percent_per_annum")
        if rate < 0:
            raise ValueError(
                "interest.rate_percent_per_annum: cannot be negative")

        declared_in = str(data.get("declared_in") or "").strip()
        if not declared_in:
            raise ValueError(
                "interest.declared_in: is required -- state where this rate "
                "was agreed (a clause, a purchase order, a signed term sheet). "
                "It is printed on the reminder so the recipient can check it"
            )

        raw_basis = (data.get("basis") or InterestBasis.SIMPLE_PER_ANNUM.value)
        try:
            basis = InterestBasis(str(raw_basis).strip().lower())
        except ValueError:
            raise ValueError(
                f"interest.basis: {raw_basis!r} is not available. This tool "
                f"computes only "
                f"{', '.join(b.value for b in InterestBasis)}"
            ) from None

        day_count = to_days(data.get("day_count_basis", 365),
                            field="interest.day_count_basis")
        if day_count not in (360, 365, 366):
            raise ValueError(
                f"interest.day_count_basis: {day_count} is not a day-count "
                f"basis this tool recognises (360, 365 or 366)"
            )

        return cls(rate_percent_per_annum=rate, basis=basis,
                   declared_in=declared_in, day_count_basis=day_count)


@dataclass(frozen=True)
class Reference:
    """The document the money is owed against."""

    kind: ReferenceKind
    number: str
    dated: date
    declared_amount: Decimal | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Reference":
        if not isinstance(data, dict):
            raise ValueError("reference: expected an object")

        raw_kind = (data.get("kind") or "").strip().lower()
        if not raw_kind:
            raise ValueError(
                "reference.kind: is required (proforma or invoice)")
        try:
            kind = ReferenceKind(raw_kind)
        except ValueError:
            raise ValueError(
                f"reference.kind: {raw_kind!r} is not one of "
                f"{', '.join(k.value for k in ReferenceKind)}"
            ) from None

        number = str(data.get("number") or "").strip()
        if not number:
            raise ValueError(
                "reference.number: is required -- a reminder that does not "
                "name the document it chases cannot be reconciled by the "
                "recipient's accounts team"
            )

        amount = data.get("amount")
        return cls(
            kind=kind,
            number=number,
            dated=to_date(data.get("dated"), field="reference.dated"),
            declared_amount=(money(amount, field="reference.amount")
                             if amount is not None else None),
        )


@dataclass(frozen=True)
class Payment:
    """A payment the supplier says they received. Declared, never detected."""

    received_on: date
    amount: Decimal
    method: str | None = None
    reference: str | None = None

    @classmethod
    def from_dict(cls, data: dict, *, index: int) -> "Payment":
        where = f"payments[{index}]"
        if not isinstance(data, dict):
            raise ValueError(f"{where}: expected an object")
        if data.get("amount") is None:
            raise ValueError(f"{where}.amount: is required")
        amount = money(data["amount"], field=f"{where}.amount")
        if amount <= ZERO:
            raise ValueError(
                f"{where}.amount: must be greater than zero. A credit note or "
                f"a reversal is not a payment and this tool does not net them"
            )
        return cls(
            received_on=to_date(data.get("received_on"),
                                field=f"{where}.received_on"),
            amount=amount,
            method=(data.get("method") or "").strip() or None,
            reference=(data.get("reference") or "").strip() or None,
        )


@dataclass(frozen=True)
class ReminderRequest:
    """Everything a reminder is computed from. No state is carried anywhere.

    The whole reminder is a pure function of this object. There is no client
    register, no stored receivable and no database: what was sent before is
    supplied in `history`, which means the same JSON produces the same
    document forever, and the tool holds nobody's contact details after the
    process exits.
    """

    number: str
    as_of: date
    supplier: Party
    client: Party
    reference: Reference
    payments: list[Payment]
    credit_days: int | None = None
    declared_due_date: date | None = None
    interest: InterestTerms | None = None
    buckets: tuple[int, ...] = DEFAULT_BUCKETS
    history: list[date] = field(default_factory=list)
    source_document: dict | None = None
    terms: list[str] = field(default_factory=list)
    notes: str | None = None
    upi_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ReminderRequest":
        if not isinstance(data, dict):
            raise ValueError("reminder: expected a JSON object at the top level")

        number = str(data.get("number") or "").strip()
        if not number:
            raise ValueError("number: is required -- the reminder's own reference")

        credit_days = (
            to_days(data["credit_days"], field="credit_days")
            if data.get("credit_days") is not None else None
        )
        declared_due = to_optional_date(data.get("due_date"), field="due_date")

        if credit_days is None and declared_due is None:
            raise ValueError(
                "credit_days: is required, or supply due_date directly. The "
                "due date decides everything on this document and the tool "
                "will not assume payment terms it was not told"
            )

        payments_raw = data.get("payments") or []
        if not isinstance(payments_raw, list):
            raise ValueError("payments: expected a list")

        history_raw = data.get("history") or []
        if not isinstance(history_raw, list):
            raise ValueError("history: expected a list of dates")

        return cls(
            number=number,
            as_of=to_date(data.get("as_of"), field="as_of"),
            supplier=Party.from_dict(data.get("supplier") or {}, who="supplier"),
            client=Party.from_dict(data.get("client") or {}, who="client"),
            reference=Reference.from_dict(data.get("reference") or {}),
            payments=[Payment.from_dict(p, index=i)
                      for i, p in enumerate(payments_raw)],
            credit_days=credit_days,
            declared_due_date=declared_due,
            interest=InterestTerms.from_dict(data.get("interest")),
            buckets=parse_buckets(data.get("ageing_buckets"),
                                  field="ageing_buckets"),
            history=[to_date(h, field=f"history[{i}]")
                     for i, h in enumerate(history_raw)],
            source_document=data.get("source_document"),
            terms=[str(t) for t in (data.get("terms") or [])],
            notes=(data.get("notes") or "").strip() or None,
            upi_id=(data.get("upi_id") or "").strip() or None,
        )
