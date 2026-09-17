"""Independent second implementation of every date and figure on a reminder.

This is not a copy of dates.py and ageing.py with the names changed. It shares
no helper with them and uses a different representation throughout:

  * Calendar arithmetic goes through a serial DAY NUMBER computed from the
    civil date by hand -- the days-from-civil algorithm, with its own leap-year
    handling -- rather than through datetime's timedelta. A due date is
    obtained by adding an integer to a day number and converting back. If
    timedelta were misused, or a month boundary were mishandled, the two paths
    would land on different days and cross_check_reminder() would refuse.
  * Money is in INTEGER PAISE over exact rationals (fractions.Fraction), with
    rounding written out rather than delegated to Decimal's rounding modes.
  * The ageing bucket and the escalation stage are re-derived from the day
    number independently, so a boundary applied with the wrong comparison in
    one path shows up as a disagreement rather than as a wrongly-toned letter.

Everything below is integers and rationals. There are no Decimals and no
datetime arithmetic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from .receivable import ReminderRequest, ReminderStage


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Serial day number for a proleptic Gregorian date, era-based.

    Day 0 is 1970-01-01. Written out rather than imported so that a leap-year
    or month-length bug in one implementation cannot be present in both.
    """
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400                                   # [0, 399]
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1   # [0, 365]
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy         # [0, 146096]
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    """Inverse of _days_from_civil, also written out by hand."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097                                # [0, 146096]
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365   # [0, 399]
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)       # [0, 365]
    mp = (5 * doy + 2) // 153                             # [0, 11]
    d = doy - (153 * mp + 2) // 5 + 1                     # [1, 31]
    m = mp + (3 if mp < 10 else -9)                       # [1, 12]
    return y + (1 if m <= 2 else 0), m, d


def _half_up(value: Fraction) -> int:
    """Round a rational to the nearest integer, halves away from zero."""
    if value < 0:
        return -math.floor(-value + Fraction(1, 2))
    return math.floor(value + Fraction(1, 2))


def _paise(value: Decimal) -> int:
    """A quantized Decimal rupee amount as exact integer paise."""
    return int((value * 100).to_integral_value())


@dataclass(frozen=True)
class RecomputedReminder:
    due_day_number: int
    days_overdue: int
    bucket_label: str
    stage: ReminderStage
    amount_due: int          # paise
    payments_total: int      # paise
    outstanding: int         # paise
    interest: int            # paise
    total_now: int           # paise


def recompute_reminder(req: ReminderRequest, *,
                       amount_due: Decimal) -> RecomputedReminder:
    """Recompute the whole reminder from the request, in the other language."""
    ref_day = _days_from_civil(req.reference.dated.year,
                               req.reference.dated.month,
                               req.reference.dated.day)
    as_of_day = _days_from_civil(req.as_of.year, req.as_of.month, req.as_of.day)

    if req.credit_days is not None:
        due_day = ref_day + req.credit_days
    else:
        assert req.declared_due_date is not None
        due_day = _days_from_civil(req.declared_due_date.year,
                                   req.declared_due_date.month,
                                   req.declared_due_date.day)

    days_overdue = as_of_day - due_day

    due_paise = _paise(amount_due)
    paid_paise = sum(_paise(p.amount) for p in req.payments)
    outstanding_paise = due_paise - paid_paise

    if req.interest is None or days_overdue <= 0:
        interest_paise = 0
    else:
        # Fraction(Decimal) is an exact conversion, so a rate with more
        # decimal places than the Decimal path happens to carry cannot be
        # silently truncated here.
        rate = Fraction(req.interest.rate_percent_per_annum) / 100
        interest_paise = _half_up(
            Fraction(outstanding_paise)
            * rate
            * Fraction(days_overdue, req.interest.day_count_basis)
        )

    return RecomputedReminder(
        due_day_number=due_day,
        days_overdue=days_overdue,
        bucket_label=_bucket(days_overdue, req.buckets),
        stage=_stage(days_overdue, req.buckets),
        amount_due=due_paise,
        payments_total=paid_paise,
        outstanding=outstanding_paise,
        interest=interest_paise,
        total_now=outstanding_paise + interest_paise,
    )


def _bucket(days_overdue: int, buckets: tuple[int, ...]) -> str:
    """Re-derived by walking the boundaries in the opposite direction."""
    if days_overdue < 1:
        return "Not yet due"
    for i in range(len(buckets) - 1, -1, -1):
        if days_overdue > buckets[i]:
            if i == len(buckets) - 1:
                return f"Over {buckets[i]} days"
            return f"{buckets[i] + 1}-{buckets[i + 1]} days"
    return f"1-{buckets[0]} days"


def _stage(days_overdue: int, buckets: tuple[int, ...]) -> ReminderStage:
    if days_overdue < 1:
        return ReminderStage.COURTESY
    if days_overdue - buckets[-1] > 0:
        return ReminderStage.FINAL
    return ReminderStage.OVERDUE


def cross_check_reminder(computed) -> RecomputedReminder:
    """Recompute and compare. Raises ComputationMismatch on any difference.

    Returns the recomputation so callers can record that it ran.
    """
    from .recompute import ComputationMismatch

    second = recompute_reminder(computed.request, amount_due=computed.amount_due)
    mismatches: list[str] = []

    def compare_money(label: str, primary: Decimal, other: int) -> None:
        got = _paise(primary)
        if got != other:
            mismatches.append(
                f"{label}: Decimal path says {got} paise, "
                f"integer path says {other} paise"
            )

    # The due date is compared as a day number, so an off-by-one at a month or
    # leap-year boundary cannot hide behind a formatted string.
    primary_due_day = _days_from_civil(computed.due_date.year,
                                       computed.due_date.month,
                                       computed.due_date.day)
    if primary_due_day != second.due_day_number:
        y, m, d = _civil_from_days(second.due_day_number)
        mismatches.append(
            f"due_date: calendar path says {computed.due_date.isoformat()}, "
            f"day-number path says {date(y, m, d).isoformat()}"
        )

    if computed.days_overdue != second.days_overdue:
        mismatches.append(
            f"days_overdue: calendar path says {computed.days_overdue}, "
            f"day-number path says {second.days_overdue}"
        )

    if computed.bucket_label != second.bucket_label:
        mismatches.append(
            f"ageing bucket: {computed.bucket_label!r} vs "
            f"{second.bucket_label!r}"
        )

    if computed.stage is not second.stage:
        mismatches.append(
            f"stage: {computed.stage.value!r} vs {second.stage.value!r}"
        )

    compare_money("amount_due", computed.amount_due, second.amount_due)
    compare_money("payments_total", computed.payments_total, second.payments_total)
    compare_money("outstanding", computed.outstanding, second.outstanding)
    compare_money("interest", computed.interest, second.interest)
    compare_money("total_now", computed.total_now, second.total_now)

    # Invariants that must hold regardless of which path computed them.
    if second.outstanding <= 0:
        mismatches.append(
            "the outstanding balance is not positive, so no reminder is due"
        )
    if second.amount_due - second.payments_total != second.outstanding:
        mismatches.append(
            "amount_due - payments_total does not equal the outstanding balance"
        )
    if second.outstanding + second.interest != second.total_now:
        mismatches.append(
            "outstanding + interest does not equal the total now claimed"
        )
    if second.interest and second.days_overdue <= 0:
        mismatches.append(
            "interest was computed on an amount that is not yet due"
        )
    if computed.request.interest is None and second.interest:
        mismatches.append(
            "interest was computed although no interest terms were declared"
        )

    if mismatches:
        raise ComputationMismatch(mismatches)

    return second
