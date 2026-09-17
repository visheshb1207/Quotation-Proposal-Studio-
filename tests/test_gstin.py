"""GSTIN structure and mod-36 checksum."""

import pytest

from quotation_studio.gstin import (
    CODEPOINTS, compute_check_digit, validate_gstin,
)

VALID = "27AAPFU0939F1ZV"


def test_known_valid_gstin_passes():
    v = validate_gstin(VALID)
    assert v.ok
    assert v.state == "Maharashtra"
    assert v.pan == "AAPFU0939F"
    assert v.entity_type == "Firm / LLP"


def test_check_digit_is_reproducible():
    assert compute_check_digit(VALID[:14]) == VALID[14]


@pytest.mark.parametrize("wrong", [c for c in CODEPOINTS if c != VALID[14]])
def test_every_other_check_digit_is_rejected(wrong):
    """Only one of the 36 possible final characters may pass."""
    v = validate_gstin(VALID[:14] + wrong)
    assert not v.ok
    assert v.expected_check_digit == VALID[14]
    assert "typo" in v.reason


def test_single_character_corruption_is_caught_anywhere():
    """Mutating any one of the first 14 characters must break the checksum
    or the format. This is the property that makes the check worth running."""
    escaped = 0
    for i in range(14):
        for repl in CODEPOINTS:
            if repl == VALID[i]:
                continue
            candidate = VALID[:i] + repl + VALID[i + 1:]
            if validate_gstin(candidate).ok:
                escaped += 1
    assert escaped == 0


@pytest.mark.parametrize("bad,expect", [
    ("", "empty"),
    ("27AAPFU0939F1Z", "15 characters"),
    ("27AAPFU0939F1ZVV", "15 characters"),
    ("2AAAPFU0939F1ZV", "state code"),
    ("27AAPFU0939F1AV", "character 14 must be Z"),
    ("99AAPFU0939F1ZV", "not a valid GST state code"),
])
def test_malformed_gstins_name_the_problem(bad, expect):
    v = validate_gstin(bad)
    assert not v.ok
    assert expect in v.reason


def test_retired_state_code_explains_itself():
    v = validate_gstin("25AAPFU0939F1ZV")
    assert not v.ok
    assert "no longer issued" in v.reason


def test_invalid_pan_entity_character_is_named():
    v = validate_gstin("27AAPXU0939F1ZV")
    assert not v.ok
    assert "PAN holder type" in v.reason


def test_whitespace_and_case_are_tolerated():
    assert validate_gstin("  27aapfu0939f1zv  ").ok
