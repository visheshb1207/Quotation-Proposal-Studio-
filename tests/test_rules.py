"""The rule pack blocks the document and names the field."""

import pytest

from quotation_studio.pipeline import run
from quotation_studio.registration import RegistrationGateNotAnswered
from quotation_studio.rules import DocumentBlocked, Severity


def blocked_fields(doc: dict) -> dict[str, str]:
    with pytest.raises(DocumentBlocked) as exc:
        run(doc)
    return {f.field: f.message for f in exc.value.findings}


def test_the_example_passes_cleanly(base_doc):
    result = run(base_doc)
    assert result.computed.grand_total > 0


def test_a_mistyped_gstin_blocks_and_names_the_character(base_doc):
    base_doc["supplier"]["gstin"] = "27AAPFU0939F1ZX"
    fields = blocked_fields(base_doc)
    assert "supplier.gstin" in fields
    assert "require V" in fields["supplier.gstin"]


def test_a_gstin_from_the_wrong_state_blocks(base_doc):
    """The GSTIN says Maharashtra, the state code says Karnataka."""
    base_doc["supplier"]["state_code"] = "29"
    fields = blocked_fields(base_doc)
    assert "One of the two is wrong" in fields["supplier.gstin"]


def test_a_registered_supplier_without_a_gstin_blocks(base_doc):
    del base_doc["supplier"]["gstin"]
    assert "supplier.gstin" in blocked_fields(base_doc)


def test_declaring_unregistered_while_supplying_a_gstin_blocks(base_doc):
    base_doc["registration"]["registered"] = False
    fields = blocked_fields(base_doc)
    assert "registration.registered" in fields
    assert "contradict" in fields["registration.registered"]


@pytest.mark.parametrize("bad,expect", [
    ("", "required"),
    ("ABC998", "not numeric"),
    ("99829", "5 digits"),
])
def test_hsn_sac_must_be_present_and_well_formed(base_doc, bad, expect):
    base_doc["items"][0]["hsn_sac"] = bad
    fields = blocked_fields(base_doc)
    assert expect in fields["items[0].hsn_sac"]


def test_a_missing_gst_rate_is_refused_not_guessed(base_doc):
    del base_doc["items"][0]["gst_rate"]
    with pytest.raises(ValueError) as exc:
        run(base_doc)
    assert "will not guess it" in str(exc.value)


def test_an_unusual_rate_warns_but_does_not_block(base_doc):
    base_doc["items"][0]["gst_rate"] = "1.8"
    warnings = {w.field: w for w in run(base_doc).warnings}
    assert warnings["items[0].gst_rate"].severity is Severity.WARN


def test_zero_quantity_blocks(base_doc):
    base_doc["items"][0]["quantity"] = "0"
    assert "items[0].quantity" in blocked_fields(base_doc)


def test_a_discount_larger_than_the_line_is_refused(base_doc):
    base_doc["items"][0]["discount_kind"] = "amount"
    base_doc["items"][0]["discount_value"] = "999999"
    with pytest.raises(ValueError, match="larger than the line value"):
        run(base_doc)


def test_validity_before_issue_date_blocks(base_doc):
    base_doc["valid_until"] = "2026-09-01"
    assert "valid_until" in blocked_fields(base_doc)


def test_a_foreign_currency_blocks(base_doc):
    base_doc["currency"] = "USD"
    fields = blocked_fields(base_doc)
    assert "means nothing" in fields["currency"]


def test_the_registration_gate_must_be_answered(base_doc):
    del base_doc["registration"]["composition"]
    with pytest.raises(RegistrationGateNotAnswered, match="composition"):
        run(base_doc)


def test_a_carve_out_that_moves_the_state_raises_a_warning(base_doc):
    """The user should be told the place of supply is not the client's state."""
    base_doc["client"]["state_code"] = "27"
    base_doc["place_of_supply"] = {"nature": "training", "performance_state": "29"}
    warnings = {w.field: w.message for w in run(base_doc).warnings}
    assert "NOT the client's state" in warnings["place_of_supply"]


def test_a_user_declared_place_of_supply_is_flagged_as_unvouched(base_doc):
    base_doc["place_of_supply"] = {"nature": "other", "declared_state": "07"}
    warnings = {w.field: w.message for w in run(base_doc).warnings}
    assert "does not vouch" in warnings["place_of_supply.nature"]


def test_every_blocking_rule_names_a_field(base_doc):
    """No rule may fail with a message the user cannot act on."""
    mutations = [
        ("supplier.gstin", lambda d: d["supplier"].__setitem__("gstin", "BAD")),
        ("items[0].hsn_sac", lambda d: d["items"][0].__setitem__("hsn_sac", "")),
        ("currency", lambda d: d.__setitem__("currency", "EUR")),
    ]
    for _, mutate in mutations:
        import copy
        d = copy.deepcopy(base_doc)
        mutate(d)
        with pytest.raises(DocumentBlocked) as exc:
            run(d)
        for finding in exc.value.findings:
            assert finding.field
            assert finding.message
            assert finding.rule_id
