"""The four-stage chassis, in the order that makes refusal enforceable.

  Stage 1  parse    -- user input into the model. No inference, no defaults
                       for anything that carries meaning (rate, HSN/SAC).
  Stage 2  compute  -- Decimal arithmetic, then an independent integer-paise
                       recomputation that must agree to the paise.
  Stage 3  rules    -- field pack. A BLOCK finding ends it here with the
                       field named, and no file is written.
  Stage 4  render    -- Typst, then the PDF is read back and every figure on
           + verify    the page is checked against what was computed. A
                       mismatch deletes the file.

The ordering is the point: nothing reaches a renderer that has not already
been computed twice and rule-checked, and nothing reaches the user that has
not been read back off the page.

run() walks a quotation or proforma through those stages. remind() walks a
payment reminder through the identical four, with the calendar in the place
the tax split occupies: the due date is derived rather than typed, the
escalation stage is derived from the ageing rather than chosen, and both are
computed twice before anything renders.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from typing import TYPE_CHECKING

from .compute import ComputedDocument, compute
from .model import Document
from .recompute import Recomputed, cross_check
from .reminder_rules import REMINDER_RULEPACK_VERSION
from .render import manifest_line, render
from .rules import RULEPACK_VERSION, Finding, check
from .verify import verify

if TYPE_CHECKING:                       # imported lazily inside remind()
    from .ageing import ComputedReminder
    from .redates import RecomputedReminder


@dataclass
class Result:
    computed: ComputedDocument
    second: Recomputed
    warnings: list[Finding] = field(default_factory=list)
    pdf_path: Path | None = None
    manifest: str = ""

    @property
    def checks_run(self) -> list[str]:
        ran = [
            "parsed without inference",
            "computed in Decimal",
            "recomputed in integer paise by an independent implementation",
            "the two computations agree to the paise",
            f"field rule pack {RULEPACK_VERSION} passed",
        ]
        if self.pdf_path:
            ran += [
                "rendered to PDF",
                "figures re-extracted from the PDF and matched",
            ]
        return ran


def run(data: dict, *, out_pdf: Path | None = None) -> Result:
    """Take parsed JSON to a verified document, or raise with a named field.

    Exceptions a caller should expect and present:
      ValueError                -- bad input, message names the field
      RegistrationGateNotAnswered -- the three questions were not answered
      PlaceOfSupplyError        -- the questionnaire needs one more answer
      DocumentBlocked           -- rule pack refused; .findings names fields
      ComputationMismatch       -- the two implementations disagree (tool bug)
      DocumentUnverified        -- the PDF does not say what was computed
    """
    document = Document.from_dict(data)          # stage 1
    computed = compute(document)                 # stage 2a
    second = cross_check(computed)               # stage 2b
    warnings = check(computed)                   # stage 3

    result = Result(computed=computed, second=second, warnings=warnings,
                    manifest=manifest_line(computed))

    if out_pdf is not None:                      # stage 4
        path = render(computed, Path(out_pdf))
        verify(computed, path)
        result.pdf_path = path

    return result


def run_file(json_path: Path, *, out_pdf: Path | None = None) -> Result:
    data = json.loads(Path(json_path).read_text())
    return run(data, out_pdf=out_pdf)


@dataclass
class ReminderResult:
    computed: "ComputedReminder"
    second: "RecomputedReminder"
    warnings: list[Finding] = field(default_factory=list)
    pdf_path: Path | None = None
    manifest: str = ""

    @property
    def checks_run(self) -> list[str]:
        ran = [
            "parsed without inference",
            "due date derived from the declared payment terms",
            "balance computed in Decimal",
            "dates and balance recomputed by an independent implementation",
            "the two computations agree to the day and to the paise",
            "escalation stage derived from the ageing, not chosen",
            f"field rule pack {REMINDER_RULEPACK_VERSION} passed",
        ]
        if self.computed.request.source_document is not None:
            ran.insert(1, "amount recomputed from the original document")
        if self.pdf_path:
            ran += [
                "rendered to PDF",
                "figures and dates re-extracted from the PDF and matched",
                "rendered bytes checked for legal-demand language",
            ]
        return ran


def remind(data: dict, *, out_pdf: Path | None = None) -> ReminderResult:
    """Take parsed JSON to a verified reminder, or raise with a named field.

    The same four stages as run(), in the same order and for the same reason:
    nothing reaches a renderer that has not already been computed twice and
    rule-checked, and nothing reaches the user that has not been read back off
    the page.

    Exceptions a caller should expect and present:
      ValueError            -- bad input, message names the field
      DateError             -- a date was not given in ISO form
      DocumentBlocked       -- rule pack refused; .findings names fields
      ComputationMismatch   -- the two implementations disagree (tool bug)
      DocumentUnverified    -- the PDF does not say what was computed
    """
    from .ageing import compute_reminder
    from .receivable import ReminderRequest
    from .redates import cross_check_reminder
    from .reminder_render import manifest_line as reminder_manifest
    from .reminder_render import render_reminder
    from .reminder_rules import check_reminder
    from .reminder_verify import verify_reminder

    request = ReminderRequest.from_dict(data)      # stage 1
    computed = compute_reminder(request)           # stage 2a
    second = cross_check_reminder(computed)        # stage 2b
    warnings = check_reminder(computed)            # stage 3

    result = ReminderResult(computed=computed, second=second,
                            warnings=warnings,
                            manifest=reminder_manifest(computed))

    if out_pdf is not None:                        # stage 4
        path = render_reminder(computed, Path(out_pdf))
        verify_reminder(computed, path)
        result.pdf_path = path

    return result


def remind_file(json_path: Path, *,
                out_pdf: Path | None = None) -> ReminderResult:
    data = json.loads(Path(json_path).read_text())
    return remind(data, out_pdf=out_pdf)
