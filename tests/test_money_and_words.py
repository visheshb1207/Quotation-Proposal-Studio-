"""Rounding policy, Indian digit grouping and amount in words."""

from decimal import Decimal

import pytest

from quotation_studio.money import MoneyError, format_inr, money, q0, q2, split_half
from quotation_studio.words import AmountTooLarge, amount_in_words, integer_to_words


@pytest.mark.parametrize("value,expected", [
    ("0", "0.00"), ("999.5", "999.50"), ("1234.567", "1,234.57"),
    ("123456.78", "1,23,456.78"), ("12345678.9", "1,23,45,678.90"),
    ("1234567890.05", "1,23,45,67,890.05"), ("-1234.5", "-1,234.50"),
])
def test_indian_digit_grouping(value, expected):
    assert format_inr(Decimal(value)) == expected


def test_floats_are_refused_outright():
    with pytest.raises(MoneyError, match="floating-point"):
        money(1234.56, field="rate")


def test_string_with_commas_and_symbol_parses():
    assert money("Rs 1,23,456.78".replace("Rs ", "")) == Decimal("123456.78")
    assert money("₹1,000") == Decimal("1000.00")


@pytest.mark.parametrize("value", ["", "abc", "1.2.3"])
def test_non_numbers_name_the_field(value):
    with pytest.raises(MoneyError, match="rate"):
        money(value, field="rate")


def test_rounding_is_half_up_not_bankers():
    assert q2(Decimal("0.005")) == Decimal("0.01")
    assert q2(Decimal("0.015")) == Decimal("0.02")   # bankers' would give 0.02
    assert q2(Decimal("0.025")) == Decimal("0.03")   # bankers' would give 0.02
    assert q0(Decimal("0.5")) == Decimal("1")
    assert q0(Decimal("1.5")) == Decimal("2")        # bankers' would give 2
    assert q0(Decimal("2.5")) == Decimal("3")        # bankers' would give 2


@pytest.mark.parametrize("total", [
    "0.00", "0.01", "0.05", "18.00", "18.01", "9999.99", "1.23", "7.77",
])
def test_cgst_plus_sgst_always_equals_the_tax(total):
    """The first thing a recipient checks on a phone calculator."""
    tax = Decimal(total)
    cgst, sgst = split_half(tax)
    assert cgst + sgst == tax
    assert abs(cgst - sgst) <= Decimal("0.01")


@pytest.mark.parametrize("n,expected", [
    (0, "Zero"), (7, "Seven"), (15, "Fifteen"), (21, "Twenty One"),
    (100, "One Hundred"), (101, "One Hundred and One"),
    (1000, "One Thousand"), (100000, "One Lakh"),
    (10000000, "One Crore"), (1000000000, "One Hundred Crore"),
])
def test_integer_words_use_the_indian_scale(n, expected):
    assert integer_to_words(n) == expected


def test_lakh_not_hundred_thousand():
    words = amount_in_words(Decimal("123456.78"))
    assert "Lakh" in words
    assert "Hundred Thousand" not in words
    assert words.endswith("Seventy Eight Paise Only")


def test_paise_are_omitted_when_zero():
    assert amount_in_words(Decimal("500.00")) == "Rupees Five Hundred Only"


def test_words_round_trip_against_the_number():
    """Reading the words back must give the same rupees and paise."""
    for value in ["0.00", "1.01", "999.99", "100000.50", "12345678.09"]:
        amount = Decimal(value)
        words = amount_in_words(amount)
        assert words == amount_in_words(amount)  # deterministic
        rupees = int(amount)
        assert integer_to_words(rupees) in words


def test_absurd_amounts_are_refused_rather_than_misnamed():
    with pytest.raises(AmountTooLarge):
        amount_in_words(Decimal("10000000000000000"))


def test_negative_amounts_are_refused():
    with pytest.raises(ValueError):
        amount_in_words(Decimal("-1.00"))
