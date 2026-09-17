"""Primary computation for a reminder: the calendar and the balance.

Nothing here is generated. Every date is derived from a date the supplier
gave, every figure is arithmetic over amounts the supplier declared, and each
carries the derivation that produced it so the fact table can be printed and
re-checked by someone who does not trust us.

redates.py implements all of it a second time by a deliberately different
method -- day numbers computed from the calendar arithmetic directly, and
money in integer paise over exact rationals. cross_check_reminder() runs both
and refuses to return anything unless they agree to the day and to the paise.

One deliberate conservatism, stated here and printed on the document: interest
is computed on the balance that remains outstanding, from the due date to the
stated date. Where part of the money was paid late, the true entitlement under
most contracts is higher, because a larger principal was outstanding for part
of the period. The tool takes the lower figure. It would rather understate a
debt than overstate one, and the arithmetic stays checkable on a phone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .compute import Fact, compute
from .dates import (
    DateFact, bucket_of, days_between, derive_due_date, format_date,
)
from .model import Document
from .money import ZERO, format_inr, q2
from .receivable import ReminderRequest, ReminderStage
from .words import amount_in_words


@dataclass(frozen=True)
class ComputedReminder:
    request: ReminderRequest
    due_date: date
    due_date_derivation: str
    days_overdue: int
    bucket_label: str
    bucket_why: str
    stage: ReminderStage
    stage_why: str
    amount_due: Decimal
    amount_due_source: str
    payments_total: Decimal
    outstanding: Decimal
    interest: Decimal
    interest_formula: str | None
    total_now: Decimal
    amount_words: str
    facts: list[Fact] = field(default_factory=list)
    date_facts: list[DateFact] = field(default_factory=list)

    @property
    def is_overdue(self) -> bool:
        return self.days_overdue > 0

    @property
    def charges_interest(self) -> bool:
        return self.interest > ZERO


def compute_reminder(req: ReminderRequest) -> ComputedReminder:
    """Compute the whole reminder. Pure; raises ValueError naming the field."""
    amount_due, amount_source = _resolve_amount_due(req)
    due_date, due_derivation = _resolve_due_date(req)

    days_overdue = days_between(due_date, req.as_of)
    bucket_label, bucket_why = bucket_of(days_overdue, req.buckets)
    stage, stage_why = _derive_stage(days_overdue, req.buckets)

    payments_total = q2(sum((p.amount for p in req.payments), ZERO))
    if payments_total > amount_due:
        raise ValueError(
            f"payments: the payments recorded ({format_inr(payments_total)}) "
            f"come to more than the amount due ({format_inr(amount_due)}). "
            f"Nothing is outstanding on these figures, so no reminder is "
            f"produced -- check the amount or the payment list"
        )

    outstanding = q2(amount_due - payments_total)
    if outstanding <= ZERO:
        raise ValueError(
            f"payments: the reference is fully settled on these figures "
            f"({format_inr(payments_total)} received against "
            f"{format_inr(amount_due)} due). This tool does not send a "
            f"reminder for nothing"
        )

    interest, interest_formula = _compute_interest(req, outstanding, days_overdue)
    total_now = q2(outstanding + interest)

    facts = [
        Fact("amount_due", amount_due, amount_source),
        Fact("payments_total", payments_total,
             f"sum of {len(req.payments)} recorded payment"
             f"{'' if len(req.payments) == 1 else 's'}"),
        Fact("outstanding", outstanding, "amount_due - payments_total"),
    ]
    if interest_formula:
        facts.append(Fact("interest", interest, interest_formula))
        facts.append(Fact("total_now", total_now, "outstanding + interest"))

    date_facts = [
        DateFact("reference_date", format_date(req.reference.dated),
                 "declared on the reference"),
        DateFact("due_date", format_date(due_date), due_derivation),
        DateFact("as_of", format_date(req.as_of),
                 "the date this reminder states its position as at"),
        DateFact("days_overdue", str(days_overdue), "as_of - due_date, in calendar days"),
        DateFact("ageing", bucket_label, bucket_why),
        DateFact("stage", stage.value, stage_why),
    ]

    return ComputedReminder(
        request=req,
        due_date=due_date,
        due_date_derivation=due_derivation,
        days_overdue=days_overdue,
        bucket_label=bucket_label,
        bucket_why=bucket_why,
        stage=stage,
        stage_why=stage_why,
        amount_due=amount_due,
        amount_due_source=amount_source,
        payments_total=payments_total,
        outstanding=outstanding,
        interest=interest,
        interest_formula=interest_formula,
        total_now=total_now,
        # Derived from the computed total, never typed. The verifier re-derives
        # this from the figure it extracts out of the rendered PDF.
        amount_words=amount_in_words(total_now),
        facts=facts,
        date_facts=date_facts,
    )


def _resolve_amount_due(req: ReminderRequest) -> tuple[Decimal, str]:
    """What was payable, and where that figure came from.

    When the original document is supplied, the engine recomputes its total
    from scratch rather than trusting a number retyped into the reminder. If
    an amount was ALSO declared, the two must agree exactly -- a reminder that
    chases a different figure from the document it names is the failure mode
    worth blocking hardest.
    """
    declared = req.reference.declared_amount

    if req.source_document is not None:
        if not isinstance(req.source_document, dict):
            raise ValueError("source_document: expected the original document "
                             "as a JSON object")
        original = Document.from_dict(req.source_document)
        recomputed = compute(original).grand_total

        if original.number != req.reference.number:
            raise ValueError(
                f"source_document.number: the document supplied is "
                f"{original.number!r}, but reference.number says "
                f"{req.reference.number!r}. One of the two is wrong"
            )
        if declared is not None and q2(declared) != recomputed:
            raise ValueError(
                f"reference.amount: you declared {format_inr(declared)}, but "
                f"the document supplied computes to {format_inr(recomputed)}. "
                f"A reminder will not chase a figure the document does not say"
            )
        return recomputed, (
            f"recomputed from {original.doc_type.title} {original.number} "
            f"supplied with this reminder"
        )

    if declared is None:
        raise ValueError(
            "reference.amount: is required when the original document is not "
            "supplied. Supply source_document to have the total recomputed, "
            "or declare the amount and the tool will record it as your "
            "declaration"
        )
    if declared <= ZERO:
        raise ValueError(
            f"reference.amount: must be greater than zero, got "
            f"{format_inr(declared)}"
        )
    return declared, "declared by the supplier; not verified by this tool"


def _resolve_due_date(req: ReminderRequest) -> tuple[date, str]:
    """The due date, and the derivation printed beside it.

    When credit terms and a due date are both given they must agree. That is
    not pedantry: the commonest way a reminder goes out on the wrong day is a
    due date carried over from a previous document while the terms changed.
    """
    derived = (
        derive_due_date(req.reference.dated, req.credit_days)
        if req.credit_days is not None else None
    )
    declared = req.declared_due_date

    if derived is not None and declared is not None:
        if derived != declared:
            raise ValueError(
                f"due_date: you declared {declared.isoformat()}, but "
                f"{req.credit_days} credit days from "
                f"{req.reference.dated.isoformat()} is "
                f"{derived.isoformat()}. These contradict each other"
            )
        return derived, (f"{format_date(req.reference.dated)} + "
                         f"{req.credit_days} calendar days")

    if derived is not None:
        return derived, (f"{format_date(req.reference.dated)} + "
                         f"{req.credit_days} calendar days")

    assert declared is not None   # ReminderRequest.from_dict guarantees one
    if declared < req.reference.dated:
        raise ValueError(
            f"due_date: {declared.isoformat()} is before the reference date "
            f"{req.reference.dated.isoformat()}"
        )
    return declared, "declared directly; no credit terms were given"


def _derive_stage(days_overdue: int,
                  buckets: tuple[int, ...]) -> tuple[ReminderStage, str]:
    """The stage is a consequence of the ageing, not a choice.

    This is the same refusal as the place of supply: a dropdown would let a
    final reminder go out on a bill that is not yet due, and the document
    would look entirely correct while doing it.
    """
    last = buckets[-1]
    if days_overdue <= 0:
        return ReminderStage.COURTESY, (
            "the amount is not yet due as at the stated date"
        )
    if days_overdue <= last:
        return ReminderStage.OVERDUE, (
            f"{days_overdue} days overdue, at or within the last declared "
            f"boundary of {last} days"
        )
    return ReminderStage.FINAL, (
        f"{days_overdue} days overdue, past the last declared boundary of "
        f"{last} days"
    )


def _compute_interest(req: ReminderRequest, outstanding: Decimal,
                      days_overdue: int) -> tuple[Decimal, str | None]:
    """Zero unless interest was declared, and then only for days past due."""
    terms = req.interest
    if terms is None:
        return ZERO, None
    if days_overdue <= 0:
        return ZERO, (
            f"no interest: nothing is overdue as at {format_date(req.as_of)}"
        )

    rate = terms.rate_percent_per_annum
    amount = q2(outstanding * rate / Decimal(100)
                * Decimal(days_overdue) / Decimal(terms.day_count_basis))
    formula = (
        f"{format_inr(outstanding)} x {rate.normalize()}% x {days_overdue}/"
        f"{terms.day_count_basis}"
    )
    return amount, formula
