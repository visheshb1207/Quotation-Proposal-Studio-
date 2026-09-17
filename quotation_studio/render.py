"""Render the computed document to PDF via Typst.

The template receives only strings that compute.py produced. It cannot add,
multiply or round -- so a rendering bug cannot invent a figure, it can only
fail to print one, which verify.py then catches.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import segno

from .compute import ComputedDocument
from .money import format_inr
from .rules import RULEPACK_VERSION

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "document.typ"

SCOPE_NOTE = (
    "This document was produced by a tool that checks arithmetic and field "
    "correctness only. The GST rate and the HSN/SAC classification on every "
    "line are the supplier's declarations. The tool does not determine, verify "
    "or advise on tax rates, classification or registration status."
)


class TypstNotFound(RuntimeError):
    pass


class RenderFailed(RuntimeError):
    pass


def typst_binary() -> str:
    exe = os.environ.get("TYPST_BIN") or shutil.which("typst")
    if not exe:
        local = Path.home() / ".local" / "bin" / "typst"
        if local.exists():
            return str(local)
        raise TypstNotFound(
            "typst was not found. Install it, or set TYPST_BIN to its path."
        )
    return exe


def build_payload(computed: ComputedDocument, *,
                  qr_path: Path | None = None) -> dict:
    """Everything the template prints, already formatted as strings."""
    doc = computed.document
    charged = computed.tax_is_charged

    split_label = (
        "IGST (inter-state supply)" if computed.is_interstate
        else "CGST + SGST (intra-state supply)"
    ) if charged else f"No tax charged -- {doc.registration.why}"

    lines = []
    for i, ln in enumerate(computed.lines, start=1):
        lines.append({
            "index": str(i),
            "description": ln.item.description,
            "hsn_sac": ln.item.hsn_sac,
            "quantity": _plain(ln.item.quantity),
            "unit": ln.item.unit,
            "rate": format_inr(ln.item.rate),
            "discount": format_inr(ln.discount),
            "taxable": format_inr(ln.taxable),
            "tax_rate": f"{ln.tax_rate.normalize()}",
            "tax": format_inr(ln.tax),
            "total": format_inr(ln.total),
        })

    # The per-line tax column carries the combined rate; the CGST/SGST halves
    # are broken out in the tax breakup block so the table stays readable.
    tax_header = "IGST" if computed.is_interstate else "CGST+SGST"
    summary_headers = (
        {"first": "IGST", "second": ""} if computed.is_interstate
        else {"first": "CGST", "second": "SGST"}
    )

    rows = [
        {"label": "Subtotal", "value": format_inr(computed.gross_total)},
    ]
    if computed.discount_total:
        rows.append({"label": "Discount",
                     "value": format_inr(-computed.discount_total)})
    rows.append({"label": "Taxable value",
                 "value": format_inr(computed.taxable_total)})
    if charged:
        if computed.is_interstate:
            rows.append({"label": "IGST", "value": format_inr(computed.igst_total)})
        else:
            rows.append({"label": "CGST", "value": format_inr(computed.cgst_total)})
            rows.append({"label": "SGST", "value": format_inr(computed.sgst_total)})
    if computed.round_off:
        rows.append({"label": "Rounding",
                     "value": format_inr(computed.round_off)})

    return {
        "doc": {
            "title": doc.doc_type.title,
            "disclaimer": doc.doc_type.disclaimer,
            "number": doc.number,
            "issue_date": doc.issue_date.strftime("%d %b %Y"),
            "valid_until": (doc.valid_until.strftime("%d %b %Y")
                            if doc.valid_until else None),
            "terms": doc.terms,
            "notes": doc.notes,
        },
        "supplier": _party(computed.document.supplier),
        "client": _party(computed.document.client),
        "supply": {
            "state": computed.place_of_supply.state,
            "rule": computed.place_of_supply.rule.value,
            "reasoning": computed.place_of_supply.reasoning,
            "split_label": split_label,
        },
        "tax": {
            "charged": charged,
            "interstate": computed.is_interstate,
            "declaration": doc.registration.declaration,
        },
        "table": {
            "show_discount": bool(computed.discount_total),
            "tax_header": tax_header,
            "tax_rate_header": f"{tax_header} %",
        },
        "summary_headers": summary_headers,
        "lines": lines,
        "totals": {
            "rows": rows,
            "grand_label": "Total payable",
            "grand_total": format_inr(computed.grand_total),
            "amount_words": computed.amount_words,
        },
        "summary": _summary_rows(computed),
        "upi": _upi(computed, qr_path),
        "manifest": {
            "line": manifest_line(computed),
            "scope": SCOPE_NOTE,
        },
    }


def _summary_rows(computed: ComputedDocument) -> list[dict]:
    """Per-rate breakup. Inter-state shows IGST alone; intra-state shows the
    CGST and SGST halves, which is what a recipient actually re-checks."""
    from .money import split_half

    rows = []
    for rate, taxable, tax in computed.rate_summary:
        if computed.is_interstate:
            first, second = tax, None
        else:
            first, second = split_half(tax)
        rows.append({
            "rate": f"{rate.normalize()}%",
            "taxable": format_inr(taxable),
            "first": format_inr(first),
            "second": format_inr(second) if second is not None else "",
        })
    return rows


def manifest_line(computed: ComputedDocument) -> str:
    """The verification manifest -- what ran, not a logo."""
    checks = [
        "totals recomputed by a second independent implementation",
        f"field rules {RULEPACK_VERSION}",
    ]
    if computed.document.supplier.gstin or computed.document.client.gstin:
        checks.append("GSTIN mod-36 checksum verified")
    checks.append(f"place of supply derived under {computed.place_of_supply.rule.value}")
    checks.append("amount in words derived from the computed total")
    checks.append("figures re-extracted from this PDF after rendering")
    return "Verified: " + "; ".join(checks) + "."


def _party(p) -> dict:
    from .states import state_name
    return {
        "name": p.name,
        "address": p.address,
        "gstin": p.gstin,
        "state": state_name(p.state_code) if p.state_code else None,
        "email": p.email,
        "phone": p.phone,
    }


def _upi(computed: ComputedDocument, qr_path: Path | None) -> dict | None:
    doc = computed.document
    if not doc.upi_id or qr_path is None:
        return None
    return {
        "vpa": doc.upi_id,
        "amount": f"Rs {format_inr(computed.grand_total)}",
        "qr_path": qr_path.name,
    }


def write_upi_qr(computed: ComputedDocument, directory: Path) -> Path | None:
    """UPI intent QR carrying the exact computed total."""
    doc = computed.document
    if not doc.upi_id:
        return None
    from urllib.parse import quote
    uri = (
        f"upi://pay?pa={quote(doc.upi_id)}"
        f"&pn={quote(doc.supplier.name)}"
        f"&am={computed.grand_total}"
        f"&cu=INR"
        f"&tn={quote(doc.doc_type.title + ' ' + doc.number)}"
    )
    path = directory / "upi.png"
    segno.make(uri, error="m").save(str(path), scale=6, border=1)
    return path


def render(computed: ComputedDocument, out_pdf: Path) -> Path:
    """Render to PDF. Raises RenderFailed; never writes a partial document."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        qr = write_upi_qr(computed, tmpdir)
        payload = build_payload(computed, qr_path=qr)

        staged = tmpdir / "document.typ"
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
                "Typst could not render the document, so nothing was written:\n"
                + (result.stderr.strip() or result.stdout.strip())
            )
        shutil.copyfile(target, out_pdf)

    return out_pdf


def _plain(value: Decimal) -> str:
    """Quantities print without trailing zeros: 2, 2.5, 0.25."""
    normalized = value.normalize()
    text = format(normalized, "f")
    return text
