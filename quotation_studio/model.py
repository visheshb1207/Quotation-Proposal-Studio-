"""The document model.

Two things here are load-bearing:

1. `DocumentType` has exactly two members. There is no "Tax Invoice" value, so
   the tool is structurally unable to render one -- not by a check that could be
   bypassed, but because the string does not exist in the codebase. Adding it
   requires a practising CA to review the CGST Rule 46 pack and sign the
   changelog. tests/test_no_tax_invoice.py enforces this against the templates.

2. The GST rate and the HSN/SAC code on every line are the USER'S declared
   input. The tool never suggests, defaults or infers them. It only checks that
   they are present and structurally well-formed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from .money import ZERO, money, to_decimal
from .place_of_supply import NatureOfSupply
from .registration import RegistrationStatus


class DocumentType(str, Enum):
    """The only two documents this tool may produce.

    A quotation is an offer. A proforma is a request for advance payment.
    Neither is a tax invoice, neither creates a tax liability, and neither may
    be presented as evidence of a supply having been made.
    """

    QUOTATION = "quotation"
    PROFORMA = "proforma"

    @property
    def title(self) -> str:
        return {"quotation": "QUOTATION", "proforma": "PROFORMA INVOICE"}[self.value]

    @property
    def disclaimer(self) -> str:
        return {
            "quotation":
                "This is a quotation, not a tax invoice. It is an offer only "
                "and does not create a tax liability.",
            "proforma":
                "This is a proforma invoice, not a tax invoice. It is a request "
                "for payment in advance and is not valid for input tax credit.",
        }[self.value]


class DiscountKind(str, Enum):
    NONE = "none"
    PERCENT = "percent"
    AMOUNT = "amount"


@dataclass(frozen=True)
class Party:
    name: str
    state_code: str
    gstin: str | None = None
    address: list[str] = field(default_factory=list)
    email: str | None = None
    phone: str | None = None

    @property
    def is_registered(self) -> bool:
        return bool(self.gstin)

    @classmethod
    def from_dict(cls, data: dict, *, who: str) -> "Party":
        if not isinstance(data, dict):
            raise ValueError(f"{who}: expected an object")
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError(f"{who}.name: is required")
        addr = data.get("address") or []
        if isinstance(addr, str):
            addr = [line.strip() for line in addr.splitlines() if line.strip()]
        return cls(
            name=name,
            state_code=str(data.get("state_code") or "").strip().zfill(2)
            if data.get("state_code") else "",
            gstin=(data.get("gstin") or "").strip().upper() or None,
            address=[str(line) for line in addr],
            email=(data.get("email") or "").strip() or None,
            phone=(data.get("phone") or "").strip() or None,
        )


@dataclass(frozen=True)
class LineItem:
    description: str
    hsn_sac: str
    quantity: Decimal
    unit: str
    rate: Decimal
    gst_rate: Decimal                 # declared by the user, in percent
    discount_kind: DiscountKind = DiscountKind.NONE
    discount_value: Decimal = ZERO

    @classmethod
    def from_dict(cls, data: dict, *, index: int) -> "LineItem":
        where = f"items[{index}]"
        if not isinstance(data, dict):
            raise ValueError(f"{where}: expected an object")

        description = (data.get("description") or "").strip()
        if not description:
            raise ValueError(f"{where}.description: is required")

        kind_raw = (data.get("discount_kind") or "none").strip().lower()
        try:
            kind = DiscountKind(kind_raw)
        except ValueError:
            raise ValueError(
                f"{where}.discount_kind: must be one of "
                f"{', '.join(k.value for k in DiscountKind)}"
            ) from None

        discount = (
            to_decimal(data.get("discount_value", "0"),
                       field=f"{where}.discount_value")
            if kind is not DiscountKind.NONE else ZERO
        )

        if data.get("rate") is None:
            raise ValueError(f"{where}.rate: is required")
        if data.get("gst_rate") is None:
            raise ValueError(
                f"{where}.gst_rate: is required -- the GST rate is your "
                f"declaration, this tool will not guess it"
            )

        return cls(
            description=description,
            hsn_sac=str(data.get("hsn_sac") or "").strip(),
            quantity=to_decimal(data.get("quantity", "1"),
                                field=f"{where}.quantity"),
            unit=(data.get("unit") or "nos").strip(),
            rate=money(data["rate"], field=f"{where}.rate"),
            gst_rate=to_decimal(data["gst_rate"], field=f"{where}.gst_rate"),
            discount_kind=kind,
            discount_value=discount,
        )


@dataclass(frozen=True)
class SupplyQuestionnaire:
    nature: NatureOfSupply
    answers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "SupplyQuestionnaire":
        if not isinstance(data, dict):
            raise ValueError("place_of_supply: expected an object")
        raw = (data.get("nature") or "").strip().lower()
        if not raw:
            raise ValueError(
                "place_of_supply.nature: is required -- answer the nature of "
                "supply question so the place of supply can be derived"
            )
        try:
            nature = NatureOfSupply(raw)
        except ValueError:
            raise ValueError(
                f"place_of_supply.nature: {raw!r} is not one of "
                f"{', '.join(n.value for n in NatureOfSupply)}"
            ) from None
        answers = {
            k: str(v) for k, v in data.items()
            if k != "nature" and v is not None
        }
        return cls(nature=nature, answers=answers)


@dataclass(frozen=True)
class Document:
    doc_type: DocumentType
    number: str
    issue_date: date
    supplier: Party
    client: Party
    items: list[LineItem]
    registration: RegistrationStatus
    supply: SupplyQuestionnaire
    valid_until: date | None = None
    currency: str = "INR"
    round_to_rupee: bool = True
    terms: list[str] = field(default_factory=list)
    notes: str | None = None
    upi_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Document":
        if not isinstance(data, dict):
            raise ValueError("document: expected a JSON object at the top level")

        raw_type = (data.get("doc_type") or "").strip().lower()
        if not raw_type:
            raise ValueError("doc_type: is required (quotation or proforma)")
        try:
            doc_type = DocumentType(raw_type)
        except ValueError:
            raise ValueError(
                f"doc_type: {raw_type!r} is not available. This tool renders "
                f"only 'quotation' and 'proforma'. It cannot produce a tax "
                f"invoice."
            ) from None

        number = str(data.get("number") or "").strip()
        if not number:
            raise ValueError("number: is required")

        items_raw = data.get("items") or []
        if not isinstance(items_raw, list) or not items_raw:
            raise ValueError("items: at least one line item is required")

        return cls(
            doc_type=doc_type,
            number=number,
            issue_date=_parse_date(data.get("issue_date"), field="issue_date",
                                   required=True),
            valid_until=_parse_date(data.get("valid_until"),
                                    field="valid_until", required=False),
            supplier=Party.from_dict(data.get("supplier") or {}, who="supplier"),
            client=Party.from_dict(data.get("client") or {}, who="client"),
            items=[LineItem.from_dict(item, index=i)
                   for i, item in enumerate(items_raw)],
            registration=RegistrationStatus.from_dict(
                data.get("registration") or {}),
            supply=SupplyQuestionnaire.from_dict(data.get("place_of_supply") or {}),
            currency=(data.get("currency") or "INR").strip().upper(),
            round_to_rupee=bool(data.get("round_to_rupee", True)),
            terms=[str(t) for t in (data.get("terms") or [])],
            notes=(data.get("notes") or "").strip() or None,
            upi_id=(data.get("upi_id") or "").strip() or None,
        )


def _parse_date(value, *, field: str, required: bool) -> date | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field}: is required (YYYY-MM-DD)")
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(
            f"{field}: {value!r} is not a date in YYYY-MM-DD form"
        ) from None
