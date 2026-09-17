import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

EXAMPLE = ROOT / "examples" / "training-karnataka.json"
REMINDER = ROOT / "examples" / "reminder-auriga.json"
REMINDER_PROFORMA = ROOT / "examples" / "reminder-clinic.json"


@pytest.fixture
def base_doc() -> dict:
    """A fresh copy of the example document for each test."""
    return json.loads(EXAMPLE.read_text())


@pytest.fixture
def base_reminder() -> dict:
    """A fresh copy of the example reminder for each test.

    It chases a declared invoice, carries one part payment, declares interest
    and records one earlier reminder -- so most rules have something to bite on.
    """
    return json.loads(REMINDER.read_text())


@pytest.fixture
def proforma_reminder() -> dict:
    """A reminder that carries the original proforma, so the amount is
    recomputed by the engine rather than taken from a declaration."""
    return json.loads(REMINDER_PROFORMA.read_text())


@pytest.fixture
def typst_available() -> bool:
    from quotation_studio.render import TypstNotFound, typst_binary
    try:
        typst_binary()
        return True
    except TypstNotFound:
        return False
