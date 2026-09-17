"""Render a computed reminder to PDF via Typst.

The template receives only strings that ageing.py produced. It cannot add,
subtract or round -- so a rendering bug cannot invent a figure or a date, it
can only fail to print one, which reminder_verify.py then catches.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import segno

from .ageing import ComputedReminder
from .dates import format_date
from .money import format_inr
from .receivable import ReminderStage
from .reminder_rules import REMINDER_RULEPACK_VERSION
from .render import RenderFailed, _party, typst_binary

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "reminder.typ"

REMINDER_SCOPE_NOTE = (
    "This reminder was produced by a tool that checks date and balance "
    "arithmetic only. The amount claimed, the payment terms and any interest "
    "rate are the supplier's declarations. The tool has no connection to any "
    "bank account, does not know whether this sum is owed or disputed, and "
    "does not advise on recovery."
)


def build_payload(computed: ComputedReminder, *,
                  qr_path: Path | None = None) -> dict:
    """Everything the template prints, already formatted as strings."""
    req = computed.request

    rows = [
        {"label": f"{req.reference.kind.label} amount",
         "value": format_inr(computed.amount_due)},
    ]
    if computed.payments_total:
        rows.append({"label": "Less payments received",
                     "value": format_inr(-computed.payments_total)})
    rows.append({"label": "Balance outstanding",
                 "value": format_inr(computed.outstanding)})
    if computed.charges_interest:
        rows.append({"label": "Interest", "value": format_inr(computed.interest)})

    return {
        "doc": {
            "title": computed.stage.title,
            "number": req.number,
            "as_of": format_date(req.as_of),
            "opening": computed.stage.opening,
            "disclaimer": computed.stage.disclaimer,
            "terms": req.terms,
            "notes": req.notes,
        },
        "supplier": _party(req.supplier),
        "client": _party(req.client),
        "reference": {
            "label": req.reference.kind.label,
            "number": req.reference.number,
            "dated": format_date(req.reference.dated),
            "provenance": req.reference.kind.provenance,
            "amount_source": computed.amount_due_source,
        },
        "ageing": {
            "due_date": format_date(computed.due_date),
            "derivation": computed.due_date_derivation,
            "status": _status_line(computed),
            "bucket": computed.bucket_label,
            "bucket_why": computed.bucket_why,
            "stage_why": computed.stage_why,
            "boundaries": _boundaries_text(req.buckets),
            "is_final": computed.stage is ReminderStage.FINAL,
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
        "history": [format_date(h) for h in req.history],
        "interest": (
            {
                "rate": f"{req.interest.rate_percent_per_annum.normalize()}%",
                "basis": req.interest.basis.description,
                "declared_in": req.interest.declared_in,
                "day_count": str(req.interest.day_count_basis),
                "formula": computed.interest_formula or "",
            }
            if req.interest is not None else None
        ),
        "totals": {
            "rows": rows,
            "grand_label": ("Total now payable" if computed.charges_interest
                            else "Amount now payable"),
            "grand_total": format_inr(computed.total_now),
            "amount_words": computed.amount_words,
        },
        "upi": _upi(computed, qr_path),
        "manifest": {
            "line": manifest_line(computed),
            "scope": REMINDER_SCOPE_NOTE,
        },
    }


def _status_line(computed: ComputedReminder) -> str:
    """The one phrase a reader looks for. Never a bare negative number."""
    days = computed.days_overdue
    if days > 0:
        return f"{days} day{'' if days == 1 else 's'} overdue"
    if days == 0:
        return "Due today"
    return f"Not yet due -- {-days} day{'' if days == -1 else 's'} to go"


def _boundaries_text(buckets: tuple[int, ...]) -> str:
    return ", ".join(f"{b} days" for b in buckets)


def manifest_line(computed: ComputedReminder) -> str:
    """The verification manifest -- what ran, not a logo."""
    checks = [
        "balance and due date recomputed by a second independent implementation",
        f"field rules {REMINDER_RULEPACK_VERSION}",
    ]
    if computed.request.supplier.gstin or computed.request.client.gstin:
        checks.append("GSTIN mod-36 checksum verified")
    checks.append("due date derived from the stated payment terms")
    checks.append("escalation stage derived from the ageing, not chosen")
    if computed.request.source_document is not None:
        checks.append("amount recomputed from the original document")
    checks.append("amount in words derived from the computed total")
    checks.append("figures re-extracted from this PDF after rendering")
    return "Verified: " + "; ".join(checks) + "."


def _upi(computed: ComputedReminder, qr_path: Path | None) -> dict | None:
    if not computed.request.upi_id or qr_path is None:
        return None
    return {
        "vpa": computed.request.upi_id,
        "amount": f"Rs {format_inr(computed.total_now)}",
        "qr_path": qr_path.name,
    }


def write_upi_qr(computed: ComputedReminder, directory: Path) -> Path | None:
    """UPI intent QR carrying the exact amount now payable."""
    req = computed.request
    if not req.upi_id:
        return None
    uri = (
        f"upi://pay?pa={quote(req.upi_id)}"
        f"&pn={quote(req.supplier.name)}"
        f"&am={computed.total_now}"
        f"&cu=INR"
        f"&tn={quote(req.reference.kind.label + ' ' + req.reference.number)}"
    )
    path = directory / "upi.png"
    segno.make(uri, error="m").save(str(path), scale=6, border=1)
    return path


def render_reminder(computed: ComputedReminder, out_pdf: Path) -> Path:
    """Render to PDF. Raises RenderFailed; never writes a partial document."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        qr = write_upi_qr(computed, tmpdir)
        payload = build_payload(computed, qr_path=qr)

        staged = tmpdir / "reminder.typ"
        staged.write_text(TEMPLATE.read_text())
        target = tmpdir / "out.pdf"

        result = subprocess.run(
            [typst_binary(), "compile",
             "--root", str(tmpdir),
             "--input", "payload=" + json.dumps(payload, ensure_ascii=False),
             str(staged), str(target)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not target.exists():
            raise RenderFailed(
                "Typst could not render the reminder, so nothing was written:\n"
                + (result.stderr.strip() or result.stdout.strip())
            )
        shutil.copyfile(target, out_pdf)

    return out_pdf
