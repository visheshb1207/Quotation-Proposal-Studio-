"""Turn any engine refusal into the same structured shape.

The CLI prints it and the web UI highlights the offending field with it. Both
must say exactly the same thing about the same input -- a refusal that reads
differently in two front ends is a refusal the user cannot act on.

Every refusal carries:
  kind      -- machine-readable category
  summary   -- one sentence for a heading
  findings  -- [{field, message, rule_id, severity}], possibly empty
  fatal     -- True when it indicates a bug in the tool rather than bad input
"""

from __future__ import annotations

import re

from .money import MoneyError
from .place_of_supply import PlaceOfSupplyError
from .recompute import ComputationMismatch
from .registration import RegistrationGateNotAnswered, QUESTIONS
from .render import RenderFailed, TypstNotFound
from .rules import DocumentBlocked
from .verify import DocumentUnverified

# "supplier.gstin: is required" -> field "supplier.gstin", message "is required"
_FIELD_PREFIX = re.compile(r"^([A-Za-z_]+(?:\[\d+\])?(?:\.[A-Za-z_]+)*): (.+)$",
                           re.DOTALL)


def to_refusal(exc: Exception) -> dict:
    """Map an engine exception to the structured refusal shape."""
    if isinstance(exc, DocumentBlocked):
        return {
            "kind": "blocked",
            "summary": (
                f"{len(exc.findings)} field"
                f"{'' if len(exc.findings) == 1 else 's'} must be fixed."
            ),
            "findings": [
                {"field": f.field, "message": f.message,
                 "rule_id": f.rule_id, "severity": f.severity.value}
                for f in exc.findings
            ],
            "fatal": False,
        }

    if isinstance(exc, RegistrationGateNotAnswered):
        wording = dict(QUESTIONS)
        return {
            "kind": "registration_gate",
            "summary": "No tax can be computed until the registration gate is "
                       "answered.",
            "findings": [
                {"field": f"registration.{key}", "message": wording[key],
                 "rule_id": "REG-GATE", "severity": "block"}
                for key in exc.missing
            ],
            "fatal": False,
        }

    if isinstance(exc, PlaceOfSupplyError):
        return {
            "kind": "place_of_supply",
            "summary": "The place of supply needs one more answer.",
            "findings": [{"field": exc.field, "message": str(exc),
                          "rule_id": "POS-ASK", "severity": "block"}],
            "fatal": False,
        }

    if isinstance(exc, (MoneyError, ValueError)):
        return {
            "kind": "invalid_input",
            "summary": "The input could not be read.",
            "findings": [_split_field(str(exc))],
            "fatal": False,
        }

    if isinstance(exc, ComputationMismatch):
        return {
            "kind": "computation_mismatch",
            "summary": "The two independent computations disagree, so nothing "
                       "was produced. This is a bug in the tool, not in your "
                       "input.",
            "findings": [{"field": "", "message": m, "rule_id": "XCHECK",
                          "severity": "block"} for m in exc.mismatches],
            "fatal": True,
        }

    if isinstance(exc, DocumentUnverified):
        return {
            "kind": "unverified",
            "summary": "The rendered PDF did not match the computed figures, "
                       "so it was deleted. This is a bug in the tool, not in "
                       "your input.",
            "findings": [
                {"field": f.what,
                 "message": f"expected {f.expected!r}, the PDF {f.found}",
                 "rule_id": "VERIFY", "severity": "block"}
                for f in exc.failures
            ],
            "fatal": True,
        }

    if isinstance(exc, TypstNotFound):
        return {
            "kind": "typst_missing",
            "summary": "Cannot render: the typst binary was not found.",
            "findings": [{"field": "", "message": str(exc),
                          "rule_id": "ENV", "severity": "block"}],
            "fatal": True,
        }

    if isinstance(exc, RenderFailed):
        return {
            "kind": "render_failed",
            "summary": "The document could not be rendered, so nothing was "
                       "written.",
            "findings": [{"field": "", "message": str(exc),
                          "rule_id": "RENDER", "severity": "block"}],
            "fatal": True,
        }

    raise exc  # not a refusal -- let it surface as a real error


REFUSALS = (
    DocumentBlocked, RegistrationGateNotAnswered, PlaceOfSupplyError,
    MoneyError, ValueError, ComputationMismatch, DocumentUnverified,
    TypstNotFound, RenderFailed,
)


def _split_field(message: str) -> dict:
    match = _FIELD_PREFIX.match(message)
    if match:
        return {"field": match.group(1), "message": match.group(2),
                "rule_id": "INPUT", "severity": "block"}
    return {"field": "", "message": message, "rule_id": "INPUT",
            "severity": "block"}
