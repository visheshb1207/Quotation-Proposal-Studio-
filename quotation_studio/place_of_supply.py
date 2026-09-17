"""Place of supply as a questionnaire, not a dropdown.

Skeptic's fix, adopted: place of supply is NOT "the client's state". Section 12
carries carve-outs that these exact personas hit -- training delivered at a
venue, work on immovable property, events, restaurant and health services. A
state dropdown quietly gets those wrong, and the error is invisible because the
document still looks right.

So the user answers a short questionnaire about the nature of the supply, and
the place of supply is DERIVED from the answers by the rule the answers select.
The derivation and the rule that produced it are recorded, printed on the
document, and carried in the manifest -- so the user can check the reasoning
rather than trust it.

Scope and limits, stated plainly:
  * Domestic supplies only, both parties in India (section 10 for goods,
    section 12 for services). Cross-border (section 13) is out of scope and
    is refused, not guessed.
  * The rules implemented here are the ones the target personas actually hit.
    Anything else routes to MANUAL, where the user states the place of supply
    themselves and the document records that they did.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .states import is_valid_state_code, state_name


class SupplyKind(str, Enum):
    GOODS = "goods"
    SERVICES = "services"


class PosRule(str, Enum):
    """The specific provision that decided the place of supply."""

    GOODS_MOVEMENT = "10(1)(a)"
    GOODS_BILL_TO_SHIP_TO = "10(1)(b)"
    GOODS_NO_MOVEMENT = "10(1)(c)"
    SERVICES_DEFAULT = "12(2)"
    SERVICES_IMMOVABLE_PROPERTY = "12(3)"
    SERVICES_PERFORMANCE_BASED = "12(4)"
    SERVICES_TRAINING = "12(5)"
    SERVICES_EVENT_ADMISSION = "12(6)"
    SERVICES_EVENT_ORGANISING = "12(7)"
    MANUAL = "user-declared"

    @property
    def text(self) -> str:
        return _RULE_TEXT[self]


_RULE_TEXT = {
    PosRule.GOODS_MOVEMENT:
        "Section 10(1)(a) -- supply involves movement of goods: place of supply "
        "is where the movement terminates for delivery to the recipient.",
    PosRule.GOODS_BILL_TO_SHIP_TO:
        "Section 10(1)(b) -- goods delivered to a third person on the buyer's "
        "direction: place of supply is the buyer's principal place of business.",
    PosRule.GOODS_NO_MOVEMENT:
        "Section 10(1)(c) -- no movement of goods: place of supply is where the "
        "goods are located at the time of delivery.",
    PosRule.SERVICES_DEFAULT:
        "Section 12(2) -- general rule: place of supply is the registered "
        "recipient's location, or for an unregistered recipient the address on "
        "record, failing which the supplier's location.",
    PosRule.SERVICES_IMMOVABLE_PROPERTY:
        "Section 12(3) -- services relating to immovable property, including "
        "architects, surveyors, accommodation and related work: place of supply "
        "is where the property is located.",
    PosRule.SERVICES_PERFORMANCE_BASED:
        "Section 12(4) -- restaurant, catering, personal grooming, fitness, "
        "beauty treatment and health services: place of supply is where the "
        "service is actually performed.",
    PosRule.SERVICES_TRAINING:
        "Section 12(5) -- training and performance appraisal: for a registered "
        "recipient the recipient's location; for an unregistered recipient the "
        "place where the training is actually performed.",
    PosRule.SERVICES_EVENT_ADMISSION:
        "Section 12(6) -- admission to an event or amusement park: place of "
        "supply is where the event is actually held.",
    PosRule.SERVICES_EVENT_ORGANISING:
        "Section 12(7) -- organising an event: for a registered recipient the "
        "recipient's location; for an unregistered recipient where the event "
        "is held.",
    PosRule.MANUAL:
        "Place of supply was stated by the user. This tool did not derive it "
        "and does not vouch for it.",
}


class NatureOfSupply(str, Enum):
    """The questionnaire's first answer. Each value selects one rule."""

    GOODS_SHIPPED = "goods_shipped"
    GOODS_BILL_TO_SHIP_TO = "goods_bill_to_ship_to"
    GOODS_COLLECTED = "goods_collected"
    GENERAL_SERVICE = "general_service"
    IMMOVABLE_PROPERTY = "immovable_property"
    PERFORMANCE_BASED = "performance_based"
    TRAINING = "training"
    EVENT_ADMISSION = "event_admission"
    EVENT_ORGANISING = "event_organising"
    OTHER = "other"


# The literal question text, kept beside the values so every front end asks the
# same thing in the same words.
NATURE_QUESTION = "Which of these best describes what you are supplying?"

NATURE_OPTIONS: dict[NatureOfSupply, str] = {
    NatureOfSupply.GOODS_SHIPPED:
        "Goods that you ship or deliver to the client",
    NatureOfSupply.GOODS_BILL_TO_SHIP_TO:
        "Goods billed to the client but delivered to someone else on their "
        "instruction (bill-to / ship-to)",
    NatureOfSupply.GOODS_COLLECTED:
        "Goods the client collects, or that do not move at all",
    NatureOfSupply.GENERAL_SERVICE:
        "A service delivered remotely or from your own premises -- consulting, "
        "design, software, retainers, agency work",
    NatureOfSupply.IMMOVABLE_PROPERTY:
        "Work relating to a specific building, site or property -- architecture, "
        "interiors, surveying, site supervision, accommodation",
    NatureOfSupply.PERFORMANCE_BASED:
        "Restaurant, catering, grooming, fitness, beauty or health services "
        "performed in person",
    NatureOfSupply.TRAINING:
        "Training, coaching, a workshop, or performance appraisal",
    NatureOfSupply.EVENT_ADMISSION:
        "Admission or tickets to an event or venue",
    NatureOfSupply.EVENT_ORGANISING:
        "Organising or managing an event",
    NatureOfSupply.OTHER:
        "None of these -- I will state the place of supply myself",
}

# Follow-up question per nature, and which field it fills.
FOLLOW_UP: dict[NatureOfSupply, tuple[str, str] | None] = {
    NatureOfSupply.GOODS_SHIPPED:
        ("delivery_state", "In which state does delivery to the recipient end?"),
    NatureOfSupply.GOODS_BILL_TO_SHIP_TO:
        ("buyer_state", "In which state is the buyer's principal place of business?"),
    NatureOfSupply.GOODS_COLLECTED:
        ("goods_location_state", "In which state are the goods at the time of delivery?"),
    NatureOfSupply.GENERAL_SERVICE: None,
    NatureOfSupply.IMMOVABLE_PROPERTY:
        ("property_state", "In which state is the property or site located?"),
    NatureOfSupply.PERFORMANCE_BASED:
        ("performance_state", "In which state is the service physically performed?"),
    NatureOfSupply.TRAINING:
        ("performance_state", "In which state is the training actually delivered? "
         "(Used only if the client is unregistered.)"),
    NatureOfSupply.EVENT_ADMISSION:
        ("event_state", "In which state is the event held?"),
    NatureOfSupply.EVENT_ORGANISING:
        ("event_state", "In which state is the event held? "
         "(Used only if the client is unregistered.)"),
    NatureOfSupply.OTHER:
        ("declared_state", "Which state is the place of supply?"),
}


@dataclass(frozen=True)
class PlaceOfSupply:
    state_code: str
    state: str
    rule: PosRule
    reasoning: str  # the sentence printed on the document

    @property
    def is_user_declared(self) -> bool:
        return self.rule is PosRule.MANUAL


class PlaceOfSupplyError(ValueError):
    """The questionnaire cannot be answered from what was supplied."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


def derive(
    *,
    nature: NatureOfSupply,
    supplier_state_code: str,
    client_state_code: str | None,
    client_is_registered: bool,
    answers: dict[str, str] | None = None,
) -> PlaceOfSupply:
    """Derive the place of supply from the questionnaire answers.

    `answers` holds the follow-up answer keyed by the field name in FOLLOW_UP,
    each a two-digit state code.
    """
    answers = answers or {}

    def follow_up() -> str:
        spec = FOLLOW_UP[nature]
        assert spec is not None
        field, question = spec
        value = answers.get(field)
        if not value:
            raise PlaceOfSupplyError(
                f"place_of_supply.{field}",
                f"This supply needs one more answer: {question}",
            )
        return _check_state(value, f"place_of_supply.{field}")

    def recipient_location() -> str:
        if client_state_code:
            return _check_state(client_state_code, "client.state_code")
        # Section 12(2)(b): no address on record -> supplier's location.
        return _check_state(supplier_state_code, "supplier.state_code")

    if nature is NatureOfSupply.GOODS_SHIPPED:
        code, rule = follow_up(), PosRule.GOODS_MOVEMENT
    elif nature is NatureOfSupply.GOODS_BILL_TO_SHIP_TO:
        code, rule = follow_up(), PosRule.GOODS_BILL_TO_SHIP_TO
    elif nature is NatureOfSupply.GOODS_COLLECTED:
        code, rule = follow_up(), PosRule.GOODS_NO_MOVEMENT
    elif nature is NatureOfSupply.GENERAL_SERVICE:
        code, rule = recipient_location(), PosRule.SERVICES_DEFAULT
    elif nature is NatureOfSupply.IMMOVABLE_PROPERTY:
        code, rule = follow_up(), PosRule.SERVICES_IMMOVABLE_PROPERTY
    elif nature is NatureOfSupply.PERFORMANCE_BASED:
        code, rule = follow_up(), PosRule.SERVICES_PERFORMANCE_BASED
    elif nature is NatureOfSupply.TRAINING:
        rule = PosRule.SERVICES_TRAINING
        code = recipient_location() if client_is_registered else follow_up()
    elif nature is NatureOfSupply.EVENT_ADMISSION:
        code, rule = follow_up(), PosRule.SERVICES_EVENT_ADMISSION
    elif nature is NatureOfSupply.EVENT_ORGANISING:
        rule = PosRule.SERVICES_EVENT_ORGANISING
        code = recipient_location() if client_is_registered else follow_up()
    elif nature is NatureOfSupply.OTHER:
        code, rule = follow_up(), PosRule.MANUAL
    else:
        raise PlaceOfSupplyError("place_of_supply.nature",
                                 f"unknown nature of supply {nature!r}")

    return PlaceOfSupply(
        state_code=code,
        state=state_name(code) or code,
        rule=rule,
        reasoning=_reasoning(rule, code, client_is_registered, nature),
    )


def _reasoning(rule: PosRule, code: str, client_registered: bool,
               nature: NatureOfSupply) -> str:
    where = state_name(code) or code
    if rule in (PosRule.SERVICES_TRAINING, PosRule.SERVICES_EVENT_ORGANISING):
        status = "registered" if client_registered else "unregistered"
        basis = ("the client's location" if client_registered
                 else "where it is actually performed")
        return (f"{rule.value}: the client is {status}, so the place of supply "
                f"is {basis} -- {where}.")
    if rule is PosRule.MANUAL:
        return (f"Place of supply stated by you as {where}. This tool did not "
                f"derive it.")
    return f"{rule.value}: place of supply is {where}."


def _check_state(code: str, field: str) -> str:
    code = (code or "").strip()
    if len(code) == 1:
        code = "0" + code
    if not is_valid_state_code(code):
        raise PlaceOfSupplyError(
            field, f"{code!r} is not a valid GST state code"
        )
    return code
