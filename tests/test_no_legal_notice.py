"""A reminder must be structurally unable to become a legal demand.

The document half of this studio is kept from rendering a tax invoice by
tests/test_no_tax_invoice.py. The reminder half needs the same guard for a
different reason: a payment reminder is the document here most likely to be
escalated, one phrase at a time, into something with consequences the tool
cannot reason about -- a notice under section 138, a demand under the MSMED
Act, a threat of recovery proceedings.

None of that language exists in the codebase. This test is the enforcement. It
fails if anyone adds it -- including via a template string, an enum member, or
a tone that a careless change could route to.
"""

import re
from pathlib import Path

import pytest

from quotation_studio.receivable import ReminderStage

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(
    list((ROOT / "quotation_studio").rglob("*.py"))
    + list((ROOT / "templates").rglob("*.typ"))
)

_DEMAND = re.compile(
    r"\blegal notice\b|\bdemand notice\b|\bsection 138\b|\bMSMED\b"
    r"|\blegal action\b|\brecovery proceedings\b|\bwithout prejudice\b"
    r"|\barbitration\b|\bwinding[- ]up\b|\binsolvency\b",
    re.IGNORECASE,
)

# Where the language is allowed: in text that DENIES it, in the guard that
# looks for it, or in a comment explaining this rule.
_PERMITTED = re.compile(
    r"not a legal notice"
    r"|never escalates into a demand"
    r"|Language that turns a reminder into an instrument"
    r"|no legal-demand language"
    r"|checked for legal-demand language",
    re.IGNORECASE,
)

_WINDOW = 220


def test_reminder_stage_has_exactly_three_members():
    assert [s.value for s in ReminderStage] == ["courtesy", "overdue", "final"]


def test_no_stage_title_is_a_notice():
    for stage in ReminderStage:
        assert "NOTICE" not in stage.title.upper()
        assert "DEMAND" not in stage.title.upper()


def test_every_stage_denies_being_a_legal_notice():
    for stage in ReminderStage:
        assert "not a legal notice" in stage.disclaimer
        assert "not a tax invoice" in stage.disclaimer


def test_no_stage_threatens_consequences():
    for stage in ReminderStage:
        assert not _DEMAND.search(stage.opening), (
            f"the {stage.value} opening reads as a legal demand"
        )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_source_file_carries_demand_language(path):
    text = path.read_text()
    for match in _DEMAND.finditer(text):
        window = text[max(0, match.start() - _WINDOW): match.end() + _WINDOW]
        lineno = text.count("\n", 0, match.start()) + 1
        assert _PERMITTED.search(window), (
            f"{path.relative_to(ROOT)}:{lineno} carries the language of a "
            f"legal demand outside a denial or a guard:\n  {window.strip()}\n\n"
            f"A reminder states a position. Turning it into an instrument with "
            f"legal consequences is not a change this tool may make on its own."
        )
