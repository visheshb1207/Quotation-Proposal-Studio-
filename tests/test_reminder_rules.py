"""What the reminder pack refuses, and what it merely warns about.

The distinction is the whole design. A BLOCK is for a reminder that
contradicts itself -- one that counts money it could not have known about, or
escalates against a bill that is not due. A WARN is for a reminder that is
arithmetically sound but that a careful person would want to look at twice.
"""

import pytest

from quotation_studio import remind
from quotation_studio.receivable import ReminderStage
from quotation_studio.rules import DocumentBlocked, Severity


def _blocked(payload) -> DocumentBlocked:
    with pytest.raises(DocumentBlocked) as exc:
        remind(payload)
    return exc.value


def _rule_ids(result) -> set[str]:
    return {w.rule_id for w in result.warnings}


# ---------------------------------------------------------------- it computes

def test_the_example_reminder_computes_and_warns_about_nothing(base_reminder):
    result = remind(base_reminder)
    assert result.warnings == []
    assert result.computed.stage is ReminderStage.OVERDUE
    assert result.computed.days_overdue == 32
    assert str(result.computed.outstanding) == "175530.00"


def test_a_proforma_reminder_recomputes_the_amount_from_the_document(
        proforma_reminder):
    result = remind(proforma_reminder)
    assert "recomputed from" in result.computed.amount_due_source
    assert "REF-002" not in _rule_ids(result)


# ------------------------------------------------------------------ it blocks

def test_a_payment_dated_after_the_as_at_date_is_blocked(base_reminder):
    base_reminder["payments"][0]["received_on"] = "2026-10-20"
    blocked = _blocked(base_reminder)
    assert [f.rule_id for f in blocked.findings] == ["PAY-001"]
    assert blocked.findings[0].field == "payments[0].received_on"


def test_an_earlier_reminder_dated_after_the_as_at_date_is_blocked(
        base_reminder):
    base_reminder["history"] = ["2026-11-01"]
    assert "REM-003" in {f.rule_id for f in _blocked(base_reminder).findings}


def test_stating_a_position_before_the_reference_was_raised_is_blocked(
        base_reminder):
    base_reminder["as_of"] = "2026-07-01"
    base_reminder["payments"] = []
    base_reminder["history"] = []
    assert "REM-001" in {f.rule_id for f in _blocked(base_reminder).findings}


def test_interest_larger_than_the_principal_is_blocked(base_reminder):
    base_reminder["interest"]["rate_percent_per_annum"] = "5000"
    assert "INT-002" in {f.rule_id for f in _blocked(base_reminder).findings}


def test_an_invalid_gstin_blocks_the_reminder(base_reminder):
    base_reminder["supplier"]["gstin"] = "27AAPFU0939F1ZX"
    assert "PTY-003" in {f.rule_id for f in _blocked(base_reminder).findings}


def test_a_blocked_reminder_names_every_field_at_once(base_reminder):
    base_reminder["payments"][0]["received_on"] = "2026-10-20"
    base_reminder["history"] = ["2026-11-01"]
    fields = {f.field for f in _blocked(base_reminder).findings}
    assert fields == {"payments[0].received_on", "history[0]"}


# ---------------------------------------------------- it refuses before rules

@pytest.mark.parametrize("mutate,fragment", [
    (lambda d: d["payments"].append(
        {"received_on": "2026-09-01", "amount": "300000"}),
     "more than the amount due"),
    (lambda d: d["payments"][0].update({"amount": "275530.00"}),
     "fully settled"),
    (lambda d: d.update({"due_date": "2026-08-20"}),
     "contradict each other"),
    (lambda d: d["reference"].update({"amount": None}) or d.pop("credit_days"),
     "is required"),
    (lambda d: d["interest"].pop("declared_in"),
     "state where this rate was agreed"),
    (lambda d: d["interest"].pop("rate_percent_per_annum"),
     "will not supply a figure"),
    (lambda d: d["reference"].update({"dated": "01/08/2026"}),
     "two different days"),
])
def test_an_impossible_reminder_is_refused_with_the_reason(
        base_reminder, mutate, fragment):
    mutate(base_reminder)
    with pytest.raises(ValueError) as exc:
        remind(base_reminder)
    assert fragment in " ".join(str(exc.value).split())


def test_a_declared_amount_that_contradicts_the_document_is_refused(
        proforma_reminder):
    proforma_reminder["reference"]["amount"] = "50000.00"
    with pytest.raises(ValueError) as exc:
        remind(proforma_reminder)
    assert "will not chase a figure the document does not say" in str(exc.value)


def test_a_document_whose_number_does_not_match_is_refused(proforma_reminder):
    proforma_reminder["reference"]["number"] = "PF-9999"
    with pytest.raises(ValueError) as exc:
        remind(proforma_reminder)
    assert "One of the two is wrong" in str(exc.value)


# ------------------------------------------------------------------- it warns

def test_a_proforma_without_its_document_warns_that_nothing_was_recomputed(
        base_reminder):
    base_reminder["reference"]["kind"] = "proforma"
    assert "REF-002" in _rule_ids(remind(base_reminder))


def test_a_final_reminder_with_no_history_warns(base_reminder):
    base_reminder["as_of"] = "2026-12-01"
    base_reminder["history"] = []
    result = remind(base_reminder)
    assert result.computed.stage is ReminderStage.FINAL
    assert "ESC-001" in _rule_ids(result)


def test_a_client_with_no_contact_details_warns(base_reminder):
    base_reminder["client"].pop("email")
    assert "PTY-007" in _rule_ids(remind(base_reminder))


def test_an_unreferenced_payment_warns(base_reminder):
    base_reminder["payments"][0].pop("reference")
    assert "PAY-003" in _rule_ids(remind(base_reminder))


def test_a_rate_that_looks_like_a_monthly_one_warns_without_blocking(
        base_reminder):
    base_reminder["interest"]["rate_percent_per_annum"] = "36.5"
    result = remind(base_reminder)
    assert "INT-001" in _rule_ids(result)
    assert result.computed.charges_interest


def test_a_balance_too_small_to_chase_warns(base_reminder):
    base_reminder["payments"][0]["amount"] = "275480.00"
    result = remind(base_reminder)
    assert "PAY-004" in _rule_ids(result)


def test_every_warning_is_a_warning_and_not_a_block(base_reminder):
    base_reminder["client"].pop("email")
    base_reminder["payments"][0].pop("reference")
    result = remind(base_reminder)
    assert result.warnings
    assert all(w.severity is Severity.WARN for w in result.warnings)


# ---------------------------------------------------------- stage is derived

def test_the_stage_follows_the_calendar_and_not_a_choice(base_reminder):
    base_reminder["payments"] = []
    base_reminder["history"] = []
    base_reminder.pop("interest")

    for as_of, expected in (
        ("2026-08-10", ReminderStage.COURTESY),
        ("2026-08-16", ReminderStage.COURTESY),
        ("2026-08-17", ReminderStage.OVERDUE),
        ("2026-11-14", ReminderStage.OVERDUE),
        ("2026-11-15", ReminderStage.FINAL),
    ):
        base_reminder["as_of"] = as_of
        assert remind(base_reminder).computed.stage is expected, as_of


def test_there_is_no_way_to_ask_for_a_stage(base_reminder):
    """A stage supplied in the JSON is ignored, not honoured."""
    base_reminder["stage"] = "final"
    assert remind(base_reminder).computed.stage is ReminderStage.OVERDUE
