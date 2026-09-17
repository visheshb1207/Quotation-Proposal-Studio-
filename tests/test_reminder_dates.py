"""The calendar, cross-checked between two implementations that share no code.

dates.py/ageing.py work in datetime with timedelta. redates.py works in serial
day numbers computed from the civil date by hand. A leap-year bug, a month
boundary off by one, or a comparison written with the wrong inequality would
have to be present in both to survive this file.
"""

import random
from datetime import date, timedelta

import pytest

from quotation_studio.dates import (
    DEFAULT_BUCKETS, DateError, add_days, bucket_of, days_between,
    derive_due_date, parse_buckets, to_date,
)
from quotation_studio.receivable import ReminderStage
from quotation_studio.recompute import ComputationMismatch
from quotation_studio.redates import (
    _bucket, _civil_from_days, _days_from_civil, _stage,
)

EPOCH = date(1970, 1, 1)


# ---------------------------------------------------------------- day numbers

@pytest.mark.parametrize("d", [
    date(1970, 1, 1), date(2000, 2, 29), date(1900, 3, 1), date(2024, 2, 29),
    date(2100, 3, 1), date(2026, 12, 31), date(1999, 12, 31),
])
def test_day_number_round_trips_at_the_awkward_boundaries(d):
    n = _days_from_civil(d.year, d.month, d.day)
    assert n == (d - EPOCH).days
    assert _civil_from_days(n) == (d.year, d.month, d.day)


def test_day_number_agrees_with_the_calendar_over_random_dates():
    rng = random.Random(20260917)
    for _ in range(5000):
        d = EPOCH + timedelta(days=rng.randint(-40000, 40000))
        n = _days_from_civil(d.year, d.month, d.day)
        assert n == (d - EPOCH).days, d
        assert _civil_from_days(n) == (d.year, d.month, d.day), d


def test_due_date_agrees_between_the_two_implementations():
    rng = random.Random(4412)
    for _ in range(5000):
        start = EPOCH + timedelta(days=rng.randint(0, 30000))
        credit = rng.randint(0, 400)
        primary = derive_due_date(start, credit)
        other = _days_from_civil(start.year, start.month, start.day) + credit
        assert _civil_from_days(other) == (primary.year, primary.month,
                                           primary.day)


def test_day_counts_agree_across_leap_years():
    # 2024 is a leap year, 2100 is not. Both spans are exactly one year of
    # calendar days and the two implementations must agree on how many.
    for start, expected in ((date(2024, 1, 1), 366), (date(2100, 1, 1), 365)):
        end = date(start.year + 1, 1, 1)
        assert days_between(start, end) == expected
        assert (_days_from_civil(end.year, end.month, end.day)
                - _days_from_civil(start.year, start.month, start.day)
                ) == expected


# --------------------------------------------------------- buckets and stages

@pytest.mark.parametrize("days,label", [
    (-5, "Not yet due"), (0, "Not yet due"),
    (1, "1-30 days"), (30, "1-30 days"),
    (31, "31-60 days"), (60, "31-60 days"),
    (61, "61-90 days"), (90, "61-90 days"),
    (91, "Over 90 days"), (4000, "Over 90 days"),
])
def test_bucket_boundaries_are_where_they_are_claimed(days, label):
    assert bucket_of(days, DEFAULT_BUCKETS)[0] == label


def test_bucket_agrees_between_the_two_implementations():
    for buckets in (DEFAULT_BUCKETS, (7,), (15, 45), (10, 20, 30, 60)):
        for days in range(-10, 400):
            assert bucket_of(days, buckets)[0] == _bucket(days, buckets), (
                buckets, days)


def test_stage_agrees_between_the_two_implementations():
    from quotation_studio.ageing import _derive_stage
    for buckets in (DEFAULT_BUCKETS, (7,), (15, 45), (10, 20, 30, 60)):
        for days in range(-10, 400):
            assert _derive_stage(days, buckets)[0] is _stage(days, buckets)


def test_a_courtesy_reminder_cannot_be_final():
    from quotation_studio.ageing import _derive_stage
    assert _derive_stage(0, DEFAULT_BUCKETS)[0] is ReminderStage.COURTESY
    assert _derive_stage(-1, DEFAULT_BUCKETS)[0] is ReminderStage.COURTESY
    assert _derive_stage(1, DEFAULT_BUCKETS)[0] is ReminderStage.OVERDUE
    assert _derive_stage(91, DEFAULT_BUCKETS)[0] is ReminderStage.FINAL


# ------------------------------------------------------------------- refusals

@pytest.mark.parametrize("bad", ["03/04/2026", "4 March 2026", "2026-13-01",
                                 "", "next tuesday"])
def test_a_date_that_is_not_iso_is_refused_by_name(bad):
    with pytest.raises(DateError) as exc:
        to_date(bad, field="as_of")
    assert "as_of" in str(exc.value)


def test_a_float_date_is_refused_rather_than_coerced():
    with pytest.raises(DateError):
        to_date(20260917, field="as_of")


@pytest.mark.parametrize("bad", [[60, 30], [30, 30], [0], [-5]])
def test_buckets_that_do_not_ascend_are_refused(bad):
    with pytest.raises(DateError):
        parse_buckets(bad, field="ageing_buckets")


def test_absent_buckets_fall_back_to_the_standard_convention():
    assert parse_buckets(None, field="ageing_buckets") == DEFAULT_BUCKETS


# ------------------------------------------------ the cross-check itself bites

def test_a_tampered_due_date_is_caught_by_the_cross_check(base_reminder):
    from dataclasses import replace

    from quotation_studio.ageing import compute_reminder
    from quotation_studio.receivable import ReminderRequest
    from quotation_studio.redates import cross_check_reminder

    computed = compute_reminder(ReminderRequest.from_dict(base_reminder))
    cross_check_reminder(computed)          # the honest one passes

    tampered = replace(computed, due_date=add_days(computed.due_date, 1))
    with pytest.raises(ComputationMismatch) as exc:
        cross_check_reminder(tampered)
    assert "due_date" in str(exc.value)
