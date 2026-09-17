"""Command-line interface.

    quotation-studio render  input.json -o out.pdf
    quotation-studio check   input.json          # rules only, no render
    quotation-studio facts   input.json          # the fact table
    quotation-studio remind  reminder.json -o out.pdf
    quotation-studio ageing  reminder.json       # the ageing, no render
    quotation-studio gstin   27AAPFU0939F1ZV
    quotation-studio ask                         # the questionnaires, printed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .gstin import validate_gstin
from .money import format_inr
from .place_of_supply import FOLLOW_UP, NATURE_OPTIONS, NATURE_QUESTION
from .pipeline import remind_file, run_file
from .recompute import ComputationMismatch
from .registration import QUESTIONS as REG_QUESTIONS
from .registration import RegistrationGateNotAnswered
from .receivable import ReferenceKind, ReminderStage
from .rules import DocumentBlocked, Severity
from .render import RenderFailed, TypstNotFound
from .dates import format_date
from .verify import DocumentUnverified

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
)


def _plain() -> bool:
    return not sys.stdout.isatty()


def c(text: str, colour: str) -> str:
    return text if _plain() else f"{colour}{text}{RESET}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quotation-studio",
        description=(
            "Quotation and proforma documents with the tax split derived from "
            "place of supply, every figure computed twice, and the PDF read "
            "back before it is handed over."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render", help="produce a verified PDF")
    p_render.add_argument("input", type=Path)
    p_render.add_argument("-o", "--out", type=Path, required=True)

    p_check = sub.add_parser("check", help="run the rules without rendering")
    p_check.add_argument("input", type=Path)

    p_facts = sub.add_parser("facts", help="print every figure and its formula")
    p_facts.add_argument("input", type=Path)
    p_facts.add_argument("--json", action="store_true")

    p_remind = sub.add_parser(
        "remind", help="produce a verified payment reminder")
    p_remind.add_argument("input", type=Path)
    p_remind.add_argument("-o", "--out", type=Path, required=True)

    p_ageing = sub.add_parser(
        "ageing", help="the ageing and the balance, without rendering")
    p_ageing.add_argument("input", type=Path)
    p_ageing.add_argument("--json", action="store_true")

    p_gstin = sub.add_parser("gstin", help="validate a GSTIN")
    p_gstin.add_argument("gstin")

    sub.add_parser("ask", help="print the questions the tool asks and why")

    args = parser.parse_args(argv)

    if args.command == "gstin":
        return _cmd_gstin(args.gstin)
    if args.command == "ask":
        return _cmd_ask()
    if args.command in ("remind", "ageing"):
        return _cmd_reminder(args)
    return _cmd_document(args)


def _cmd_document(args) -> int:
    out = getattr(args, "out", None)
    try:
        result = run_file(args.input, out_pdf=out)
    except DocumentBlocked as exc:
        print(c(f"\nRefused. {len(exc.findings)} field(s) must be fixed:\n",
                RED + BOLD))
        for f in exc.findings:
            print(f"  {c(f.field, BOLD)}")
            print(f"    {f.message}")
            print(f"    {c(f.rule_id, DIM)}\n")
        print(c("No document was produced.", DIM))
        return 2
    except (RegistrationGateNotAnswered, ValueError) as exc:
        print(c("\nRefused.\n", RED + BOLD))
        print(f"  {exc}\n")
        print(c("No document was produced.", DIM))
        return 2
    except ComputationMismatch as exc:
        print(c("\nInternal check failed.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except DocumentUnverified as exc:
        print(c("\nRendered document failed verification.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except RenderFailed as exc:
        print(c("\nRender failed, so nothing was written.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except TypstNotFound as exc:
        print(c("\nCannot render.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 4

    if args.command == "facts":
        return _print_facts(result, as_json=args.json)

    _print_summary(result)
    return 0


def _print_summary(result) -> None:
    cd = result.computed
    doc = cd.document

    print()
    print(c(f"{doc.doc_type.title} {doc.number}", BOLD))
    print(f"  {doc.supplier.name}  ->  {doc.client.name}")
    print()
    print(f"  Place of supply   {c(cd.place_of_supply.state, BOLD)} "
          f"{c('(' + cd.place_of_supply.rule.value + ')', DIM)}")
    print(f"                    {c(cd.place_of_supply.reasoning, DIM)}")

    if cd.tax_is_charged:
        split = "IGST" if cd.is_interstate else "CGST + SGST"
        kind = "inter-state" if cd.is_interstate else "intra-state"
        print(f"  Tax split         {c(split, BOLD)} ({kind})")
    else:
        print(f"  Tax               {c('not charged', YELLOW)} -- "
              f"{doc.registration.why}")

    print()
    print(f"  Taxable value     {format_inr(cd.taxable_total):>16}")
    if cd.tax_is_charged:
        if cd.is_interstate:
            print(f"  IGST              {format_inr(cd.igst_total):>16}")
        else:
            print(f"  CGST              {format_inr(cd.cgst_total):>16}")
            print(f"  SGST              {format_inr(cd.sgst_total):>16}")
    if cd.round_off:
        print(f"  Rounding          {format_inr(cd.round_off):>16}")
    print(f"  {c('Total payable', BOLD)}     {c(format_inr(cd.grand_total).rjust(16), BOLD)}")
    print(f"  {c(cd.amount_words, DIM)}")

    if result.warnings:
        print()
        print(c(f"  {len(result.warnings)} warning(s):", YELLOW))
        for w in result.warnings:
            print(f"    {w.field}: {w.message}")

    print()
    print(c("  Checks run:", BOLD))
    for line in result.checks_run:
        print(f"    {c('ok', GREEN)}  {line}")

    if result.pdf_path:
        print()
        print(f"  Written to {c(str(result.pdf_path), BOLD)}")
    print()


def _print_facts(result, *, as_json: bool) -> int:
    cd = result.computed
    facts = [f for ln in cd.lines for f in ln.facts] + cd.facts

    if as_json:
        print(json.dumps({
            "place_of_supply": {
                "state": cd.place_of_supply.state,
                "rule": cd.place_of_supply.rule.value,
                "reasoning": cd.place_of_supply.reasoning,
            },
            "interstate": cd.is_interstate,
            "tax_charged": cd.tax_is_charged,
            "facts": [
                {"key": f.key, "value": str(f.value), "formula": f.formula}
                for f in facts
            ],
            "amount_in_words": cd.amount_words,
            "manifest": result.manifest,
        }, indent=2))
        return 0

    print()
    width = max(len(f.key) for f in facts)
    for f in facts:
        print(f"  {f.key:<{width}}  {format_inr(f.value):>14}   "
              f"{c(f.formula, DIM)}")
    print()
    print(f"  {c('amount in words', BOLD)}  {cd.amount_words}")
    print()
    return 0


def _cmd_reminder(args) -> int:
    """`remind` and `ageing` share every stage but the render."""
    out = getattr(args, "out", None)
    try:
        result = remind_file(args.input, out_pdf=out)
    except DocumentBlocked as exc:
        print(c(f"\nRefused. {len(exc.findings)} field(s) must be fixed:\n",
                RED + BOLD))
        for f in exc.findings:
            print(f"  {c(f.field, BOLD)}")
            print(f"    {f.message}")
            print(f"    {c(f.rule_id, DIM)}\n")
        print(c("No reminder was produced.", DIM))
        return 2
    except ValueError as exc:
        print(c("\nRefused.\n", RED + BOLD))
        print(f"  {exc}\n")
        print(c("No reminder was produced.", DIM))
        return 2
    except ComputationMismatch as exc:
        print(c("\nInternal check failed.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except DocumentUnverified as exc:
        print(c("\nRendered reminder failed verification.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except RenderFailed as exc:
        print(c("\nRender failed, so nothing was written.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 3
    except TypstNotFound as exc:
        print(c("\nCannot render.\n", RED + BOLD))
        print(f"  {exc}\n")
        return 4

    if args.command == "ageing":
        return _print_ageing(result, as_json=args.json)

    _print_reminder(result)
    return 0


def _print_reminder(result) -> None:
    cr = result.computed
    req = cr.request

    print()
    print(c(f"{cr.stage.title} {req.number}", BOLD))
    print(f"  {req.supplier.name}  ->  {req.client.name}")
    print(f"  against {req.reference.kind.label} {req.reference.number} "
          f"dated {format_date(req.reference.dated)}")
    print()
    print(f"  Due               {c(format_date(cr.due_date), BOLD)} "
          f"{c('(' + cr.due_date_derivation + ')', DIM)}")

    status = (
        c(f"{cr.days_overdue} day(s) overdue", RED) if cr.days_overdue > 0
        else c("not yet due", GREEN)
    )
    print(f"  As at             {format_date(req.as_of)}  ->  {status}")
    print(f"  Ageing            {c(cr.bucket_label, BOLD)} "
          f"{c('(' + cr.bucket_why + ')', DIM)}")
    print(f"  Stage             {c(cr.stage.value, BOLD)} "
          f"{c('-- derived, not chosen', DIM)}")
    print(f"                    {c(cr.stage_why, DIM)}")

    print()
    print(f"  Amount due        {format_inr(cr.amount_due):>16}")
    print(f"                    {c(cr.amount_due_source, DIM)}")
    if cr.payments_total:
        print(f"  Payments received {format_inr(-cr.payments_total):>16}")
    print(f"  Outstanding       {format_inr(cr.outstanding):>16}")
    if cr.charges_interest:
        print(f"  Interest          {format_inr(cr.interest):>16}")
        print(f"                    {c(cr.interest_formula or '', DIM)}")
    label = "Total now payable" if cr.charges_interest else "Amount now payable"
    print(f"  {c(label, BOLD)} {c(format_inr(cr.total_now).rjust(16), BOLD)}")
    print(f"  {c(cr.amount_words, DIM)}")

    if result.warnings:
        print()
        print(c(f"  {len(result.warnings)} warning(s):", YELLOW))
        for w in result.warnings:
            print(f"    {w.field}: {w.message}")

    print()
    print(c("  Checks run:", BOLD))
    for line in result.checks_run:
        print(f"    {c('ok', GREEN)}  {line}")

    if result.pdf_path:
        print()
        print(f"  Written to {c(str(result.pdf_path), BOLD)}")
    print()


def _print_ageing(result, *, as_json: bool) -> int:
    cr = result.computed

    if as_json:
        print(json.dumps({
            "stage": cr.stage.value,
            "stage_why": cr.stage_why,
            "due_date": cr.due_date.isoformat(),
            "due_date_derivation": cr.due_date_derivation,
            "as_of": cr.request.as_of.isoformat(),
            "days_overdue": cr.days_overdue,
            "ageing_bucket": cr.bucket_label,
            "ageing_why": cr.bucket_why,
            "money": [
                {"key": f.key, "value": str(f.value), "formula": f.formula}
                for f in cr.facts
            ],
            "dates": [
                {"key": d.key, "value": d.value, "derivation": d.formula}
                for d in cr.date_facts
            ],
            "amount_in_words": cr.amount_words,
            "manifest": result.manifest,
        }, indent=2))
        return 0

    print()
    width = max(len(d.key) for d in cr.date_facts)
    for d in cr.date_facts:
        print(f"  {d.key:<{width}}  {d.value:>14}   {c(d.formula, DIM)}")
    print()
    width = max(len(f.key) for f in cr.facts)
    for f in cr.facts:
        print(f"  {f.key:<{width}}  {format_inr(f.value):>14}   "
              f"{c(f.formula, DIM)}")
    print()
    print(f"  {c('amount in words', BOLD)}  {cr.amount_words}")
    print()
    return 0


def _cmd_gstin(value: str) -> int:
    v = validate_gstin(value)
    print()
    if v.ok:
        print(f"  {c('valid', GREEN)}  {c(v.gstin, BOLD)}")
        print(f"         state       {v.state} ({v.state_code})")
        print(f"         PAN         {v.pan}")
        print(f"         entity      {v.entity_type}")
        print(f"         check digit {v.expected_check_digit}")
        print()
        print(c("  This confirms the GSTIN is well-formed and its checksum is\n"
                "  correct. It does not confirm the registration is active or\n"
                "  that it belongs to any particular business.", DIM))
    else:
        print(f"  {c('invalid', RED)}  {v.gstin or value}")
        print(f"           {v.reason}")
    print()
    return 0 if v.ok else 1


def _cmd_ask() -> int:
    print()
    print(c("Registration gate", BOLD))
    print(c("  Asked before any tax is computed. Your answers decide whether "
            "tax may\n  be charged at all.", DIM))
    print()
    for key, question in REG_QUESTIONS:
        print(f"  {c(key, BOLD)}")
        print(f"    {question}")
    print()
    print(c("Place of supply", BOLD))
    print(c("  Replaces a state dropdown, because the place of supply is not\n"
            "  always the client's state. These carve-outs are the ones these\n"
            "  users actually hit.", DIM))
    print()
    print(f"  {NATURE_QUESTION}")
    for nature, text in NATURE_OPTIONS.items():
        print(f"    {c(nature.value, BOLD)}")
        print(f"      {text}")
        follow = FOLLOW_UP[nature]
        if follow:
            print(f"      {c('then: ' + follow[1], DIM)}")
    print()
    print(c("Payment reminders", BOLD))
    print(c("  A reminder asks for no tone and offers no dropdown. Everything\n"
            "  that decides how it reads is derived from what you declare.", DIM))
    print()
    print(f"  {c('reference.kind', BOLD)}")
    print("    What is the money owed against?")
    for kind in ReferenceKind:
        print(f"      {c(kind.value, BOLD)}  {kind.provenance}")
    print()
    print(f"  {c('credit_days or due_date', BOLD)}")
    print("    The due date is reference date + credit days, in calendar days.")
    print(c("    Working days would need a holiday calendar the tool does not\n"
            "    have and will not guess. Declare both and they must agree.", DIM))
    print()
    print(f"  {c('as_of', BOLD)}")
    print("    The date the reminder states its position as at.")
    print(c("    Always explicit. The engine never reads the clock, so the same\n"
            "    input produces the same reminder next year -- which is the only\n"
            "    way anyone can check the one you sent last year.", DIM))
    print()
    print(f"  {c('stage', BOLD)}  {c('-- derived, never asked', DIM)}")
    for stage in ReminderStage:
        print(f"      {c(stage.value, BOLD)}  {_stage_rule(stage)}")
    print(c("    A dropdown here would let a final reminder go out on a bill\n"
            "    that is not yet due, and the document would look correct doing\n"
            "    it. None of these is a demand under any statute.", DIM))
    print()
    print(f"  {c('interest', BOLD)}  {c('-- optional, and never assumed', DIM)}")
    print("    Declare a rate AND where you agreed it, or no interest is shown.")
    print(c("    Whether interest is chargeable at all is a matter of your\n"
            "    contract or of statute. The tool has no view on either.", DIM))
    print()
    return 0


def _stage_rule(stage) -> str:
    return {
        ReminderStage.COURTESY: "nothing is overdue as at the stated date",
        ReminderStage.OVERDUE:
            "overdue, at or within the last declared ageing boundary",
        ReminderStage.FINAL: "overdue past the last declared ageing boundary",
    }[stage]


if __name__ == "__main__":
    sys.exit(main())
