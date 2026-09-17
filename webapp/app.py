"""Local web UI for the Quotation Studio.

The browser never computes anything. Every figure on screen came from the same
engine the CLI uses, and every refusal is the engine's own, carrying the field
name it named. The form itself is built from the engine's questionnaires at
runtime (/api/schema), so the UI cannot drift out of step with the rules.

Run:  python3 -m webapp        (or: uvicorn webapp.app:app --reload)
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from quotation_studio.compute import compute
from quotation_studio.dates import DEFAULT_BUCKETS, format_date
from quotation_studio.errors import REFUSALS, to_refusal
from quotation_studio.gstin import validate_gstin
from quotation_studio.model import Document, DocumentType
from quotation_studio.money import format_inr
from quotation_studio.pipeline import remind, run
from quotation_studio.place_of_supply import (
    FOLLOW_UP, NATURE_OPTIONS, NATURE_QUESTION,
)
from quotation_studio.receivable import (
    InterestBasis, ReferenceKind, ReminderStage,
)
from quotation_studio.registration import QUESTIONS as REG_QUESTIONS
from quotation_studio.reminder_render import REMINDER_SCOPE_NOTE, _status_line
from quotation_studio.reminder_rules import REMINDER_RULEPACK_VERSION
from quotation_studio.render import SCOPE_NOTE, typst_binary
from quotation_studio.render import TypstNotFound
from quotation_studio.rules import RULEPACK_VERSION, _DECLARABLE_RATES
from quotation_studio.states import STATE_CODES

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
EXAMPLES = ROOT.parent / "examples"

app = FastAPI(title="Quotation Studio", docs_url="/api/docs")


@app.get("/api/schema")
def schema() -> dict:
    """Everything the form needs, taken from the engine rather than restated."""
    return {
        "doc_types": [
            {"value": d.value, "title": d.title, "disclaimer": d.disclaimer}
            for d in DocumentType
        ],
        "registration_questions": [
            {"key": key, "question": question} for key, question in REG_QUESTIONS
        ],
        "nature_question": NATURE_QUESTION,
        "natures": [
            {
                "value": nature.value,
                "label": text,
                "follow_up": (
                    {"field": FOLLOW_UP[nature][0],
                     "question": FOLLOW_UP[nature][1]}
                    if FOLLOW_UP[nature] else None
                ),
            }
            for nature, text in NATURE_OPTIONS.items()
        ],
        "states": [
            {"code": code, "name": name}
            for code, name in sorted(STATE_CODES.items(),
                                     key=lambda kv: kv[1])
        ],
        "common_rates": sorted(str(r.normalize()) for r in _DECLARABLE_RATES),
        "rulepack": RULEPACK_VERSION,
        "scope_note": SCOPE_NOTE,
        "typst": _typst_status(),
        "reminder": _reminder_schema(),
    }


def _reminder_schema() -> dict:
    """The reminder half, also taken from the engine rather than restated.

    The stage list is sent so the UI can SHOW what each stage means, never so
    it can offer one. There is no stage input anywhere in the browser, because
    there is no stage input in the engine -- it is derived from the ageing.
    """
    return {
        "reference_kinds": [
            {"value": k.value, "label": k.label, "provenance": k.provenance}
            for k in ReferenceKind
        ],
        "stages": [
            {"value": s.value, "title": s.title, "opening": s.opening,
             "disclaimer": s.disclaimer}
            for s in ReminderStage
        ],
        "interest_bases": [
            {"value": b.value, "description": b.description}
            for b in InterestBasis
        ],
        "default_buckets": list(DEFAULT_BUCKETS),
        "rulepack": REMINDER_RULEPACK_VERSION,
        "scope_note": REMINDER_SCOPE_NOTE,
    }


@app.get("/api/examples")
def examples() -> dict:
    """Both kinds, tagged, so the UI can offer the right ones per mode.

    The tag is read off the payload rather than the filename: a reminder is the
    thing that names a reference, a document is the thing that names a type.
    """
    out = []
    for path in sorted(EXAMPLES.glob("*.json")):
        payload = json.loads(path.read_text())
        out.append({
            "name": path.stem,
            "kind": "reminder" if "reference" in payload else "document",
            "payload": payload,
        })
    return {"examples": out}


@app.get("/api/gstin")
def check_gstin(value: str = "") -> dict:
    """Live validation as the user types."""
    if not value.strip():
        return {"state": "empty"}
    v = validate_gstin(value)
    return {
        "state": "valid" if v.ok else "invalid",
        "gstin": v.gstin,
        "reason": v.reason,
        "state_name": v.state,
        "state_code": v.state_code,
        "pan": v.pan,
        "entity_type": v.entity_type,
        "expected_check_digit": v.expected_check_digit,
    }


@app.post("/api/compute")
def api_compute(payload: dict) -> JSONResponse:
    """Stages 1-3. No render, so this is safe to call on every keystroke."""
    try:
        result = run(payload)
    except REFUSALS as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "refusal": to_refusal(exc)},
        )
    return JSONResponse({"ok": True, **_view(result)})


@app.post("/api/render")
def api_render(payload: dict) -> JSONResponse:
    """All four stages. Returns the verified PDF inline as base64."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "document.pdf"
        try:
            result = run(payload, out_pdf=out)
        except REFUSALS as exc:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "refusal": to_refusal(exc)},
            )
        pdf = base64.b64encode(out.read_bytes()).decode("ascii")

    return JSONResponse({
        "ok": True,
        **_view(result),
        "pdf_base64": pdf,
        "filename": f"{result.computed.document.number}.pdf",
    })


@app.post("/api/reminder/compute")
def api_reminder_compute(payload: dict) -> JSONResponse:
    """Stages 1-3 for a reminder. No render, so it is safe on every keystroke."""
    try:
        result = remind(payload)
    except REFUSALS as exc:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "refusal": to_refusal(exc)},
        )
    return JSONResponse({"ok": True, **_reminder_view(result)})


@app.post("/api/reminder/render")
def api_reminder_render(payload: dict) -> JSONResponse:
    """All four stages. Returns the verified PDF inline as base64."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reminder.pdf"
        try:
            result = remind(payload, out_pdf=out)
        except REFUSALS as exc:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "refusal": to_refusal(exc)},
            )
        pdf = base64.b64encode(out.read_bytes()).decode("ascii")

    return JSONResponse({
        "ok": True,
        **_reminder_view(result),
        "pdf_base64": pdf,
        "filename": f"{result.computed.request.number}.pdf",
    })


def _reminder_view(result) -> dict:
    """The computed reminder as the browser displays it.

    Strings only, for the same reason as _view(): the browser is never handed a
    number it might reformat or re-round. `days_overdue` is the one integer,
    and it is sent alongside the phrase the engine wrote for it so the UI can
    style the badge without ever deciding what the number means.
    """
    c = result.computed
    req = c.request

    return {
        "doc": {
            "title": c.stage.title,
            "number": req.number,
            "stage": c.stage.value,
            "stage_why": c.stage_why,
            "opening": c.stage.opening,
            "disclaimer": c.stage.disclaimer,
        },
        "ageing": {
            "due_date": format_date(c.due_date),
            "derivation": c.due_date_derivation,
            "as_of": format_date(req.as_of),
            "days_overdue": c.days_overdue,
            "status": _status_line(c),
            "bucket": c.bucket_label,
            "bucket_why": c.bucket_why,
            "boundaries": list(req.buckets),
        },
        "reference": {
            "kind": req.reference.kind.value,
            "label": req.reference.kind.label,
            "number": req.reference.number,
            "dated": format_date(req.reference.dated),
            "provenance": req.reference.kind.provenance,
            "amount_source": c.amount_due_source,
            "recomputed": req.source_document is not None,
        },
        "payments": [
            {
                "received_on": format_date(p.received_on),
                "amount": format_inr(p.amount),
                "method": p.method or "",
                "reference": p.reference or "",
            }
            for p in req.payments
        ],
        "interest": (
            {
                "rate": f"{req.interest.rate_percent_per_annum.normalize()}%",
                "basis": req.interest.basis.description,
                "declared_in": req.interest.declared_in,
                "day_count": str(req.interest.day_count_basis),
                "formula": c.interest_formula or "",
            }
            if req.interest is not None else None
        ),
        "totals": {
            "amount_due": format_inr(c.amount_due),
            "payments": format_inr(c.payments_total),
            "outstanding": format_inr(c.outstanding),
            "interest": format_inr(c.interest),
            "grand": format_inr(c.total_now),
            "charges_interest": c.charges_interest,
            "grand_label": ("Total now payable" if c.charges_interest
                            else "Amount now payable"),
            "words": c.amount_words,
        },
        "facts": [
            {"key": f.key, "value": format_inr(f.value), "formula": f.formula}
            for f in c.facts
        ],
        "date_facts": [
            {"key": d.key, "value": d.value, "formula": d.formula}
            for d in c.date_facts
        ],
        "warnings": [
            {"field": w.field, "message": w.message, "rule_id": w.rule_id}
            for w in result.warnings
        ],
        "checks_run": result.checks_run,
        "manifest": result.manifest,
    }


def _view(result) -> dict:
    """The computed document as the browser displays it. Strings only -- the
    browser is never handed a number it might reformat or re-round."""
    c = result.computed
    doc = c.document

    return {
        "doc": {
            "title": doc.doc_type.title,
            "number": doc.number,
            "disclaimer": doc.doc_type.disclaimer,
        },
        "place_of_supply": {
            "state": c.place_of_supply.state,
            "state_code": c.place_of_supply.state_code,
            "rule": c.place_of_supply.rule.value,
            "rule_text": c.place_of_supply.rule.text,
            "reasoning": c.place_of_supply.reasoning,
            "user_declared": c.place_of_supply.is_user_declared,
        },
        "tax": {
            "charged": c.tax_is_charged,
            "interstate": c.is_interstate,
            "split": ("IGST" if c.is_interstate else "CGST + SGST")
                     if c.tax_is_charged else "No tax",
            "treatment": c.treatment.value,
            "why_not": doc.registration.why if not c.tax_is_charged else "",
            "declaration": doc.registration.declaration,
        },
        "lines": [
            {
                "description": ln.item.description,
                "hsn_sac": ln.item.hsn_sac,
                "taxable": format_inr(ln.taxable),
                "tax_rate": str(ln.tax_rate.normalize()),
                "tax": format_inr(ln.tax),
                "cgst": format_inr(ln.cgst),
                "sgst": format_inr(ln.sgst),
                "igst": format_inr(ln.igst),
                "total": format_inr(ln.total),
            }
            for ln in c.lines
        ],
        "totals": {
            "gross": format_inr(c.gross_total),
            "discount": format_inr(c.discount_total),
            "taxable": format_inr(c.taxable_total),
            "cgst": format_inr(c.cgst_total),
            "sgst": format_inr(c.sgst_total),
            "igst": format_inr(c.igst_total),
            "tax": format_inr(c.tax_total),
            "round_off": format_inr(c.round_off),
            "grand": format_inr(c.grand_total),
            "words": c.amount_words,
        },
        "facts": [
            {"key": f.key, "value": format_inr(f.value), "formula": f.formula}
            for ln in c.lines for f in ln.facts
        ] + [
            {"key": f.key, "value": format_inr(f.value), "formula": f.formula}
            for f in c.facts
        ],
        "warnings": [
            {"field": w.field, "message": w.message, "rule_id": w.rule_id}
            for w in result.warnings
        ],
        "checks_run": result.checks_run,
        "manifest": result.manifest,
    }


def _typst_status() -> dict:
    try:
        return {"available": True, "path": typst_binary()}
    except TypstNotFound as exc:
        return {"available": False, "path": None, "reason": str(exc)}


class RevalidatingStatic(StaticFiles):
    """Static files that the browser must revalidate before reusing.

    Starlette sends an ETag and a Last-Modified but no Cache-Control. With no
    explicit policy a browser falls back to HEURISTIC caching -- it guesses a
    freshness lifetime from how long ago the file changed and serves its copy
    WITHOUT asking the server at all. An edit to app.js then does not reach the
    page, and the only symptom is a UI that is quietly a version behind.

    `no-cache` does not mean "do not store"; it means "ask me first". The
    conditional request still answers 304 from the ETag, so nothing is
    re-downloaded that has not changed -- the browser just never assumes.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/", RevalidatingStatic(directory=str(STATIC), html=True),
          name="static")
