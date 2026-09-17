"""GSTIN structural validation and mod-36 check-digit verification.

This is one of the two things the tool can prove. A GSTIN that fails here is
malformed or mistyped -- that is a fact about the string, checkable offline,
independent of any tax opinion. It is NOT a claim that the GSTIN is active,
registered, or belongs to the named party; only the GST portal can say that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .states import is_valid_state_code, retired_reason, state_name

# Positions 1-15:
#   1-2   state code (numeric)
#   3-12  PAN of the registrant (AAAAA9999A)
#   13    entity number of the same PAN holder in the state (1-9, A-Z)
#   14    'Z' by default
#   15    checksum character
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

# PAN 4th character encodes holder type; 5th is the first letter of the
# surname/entity name. We validate the 4th against the known set.
PAN_ENTITY_TYPES = {
    "A": "Association of Persons (AOP)",
    "B": "Body of Individuals (BOI)",
    "C": "Company",
    "F": "Firm / LLP",
    "G": "Government",
    "H": "Hindu Undivided Family (HUF)",
    "J": "Artificial Juridical Person",
    "L": "Local Authority",
    "P": "Individual / Proprietor",
    "T": "Trust",
}

CODEPOINTS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MOD = len(CODEPOINTS)  # 36


def compute_check_digit(first_fourteen: str) -> str:
    """Luhn mod-36 check character over the first 14 GSTIN characters."""
    if len(first_fourteen) != 14:
        raise ValueError("check digit is computed over exactly 14 characters")

    total = 0
    factor = 2
    # Weights alternate 2,1,2,1,... reading right-to-left from position 14.
    for ch in reversed(first_fourteen):
        idx = CODEPOINTS.find(ch)
        if idx < 0:
            raise ValueError(f"character {ch!r} is not in the GSTIN alphabet")
        product = idx * factor
        total += product // _MOD + product % _MOD
        factor = 1 if factor == 2 else 2

    return CODEPOINTS[(_MOD - (total % _MOD)) % _MOD]


@dataclass(frozen=True)
class GstinCheck:
    gstin: str
    ok: bool
    field: str                 # which field to point the user at
    reason: str | None = None  # None when ok
    state_code: str | None = None
    state: str | None = None
    pan: str | None = None
    entity_type: str | None = None
    expected_check_digit: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def validate_gstin(raw: str, *, field: str = "gstin") -> GstinCheck:
    """Validate a GSTIN string. Never raises -- returns a named-field verdict."""
    if raw is None:
        return GstinCheck("", False, field, "GSTIN is missing")

    gstin = raw.strip().upper().replace(" ", "")
    if not gstin:
        return GstinCheck(gstin, False, field, "GSTIN is empty")

    if len(gstin) != 15:
        return GstinCheck(
            gstin, False, field,
            f"GSTIN must be exactly 15 characters; this one has {len(gstin)}",
        )

    if not GSTIN_RE.match(gstin):
        return GstinCheck(gstin, False, field, _explain_format_failure(gstin))

    code = gstin[:2]
    if not is_valid_state_code(code):
        retired = retired_reason(code)
        why = (
            f"state code {code} is no longer issued -- {retired}"
            if retired
            else f"{code} is not a valid GST state code"
        )
        return GstinCheck(gstin, False, field, why, state_code=code)

    pan = gstin[2:12]
    entity = PAN_ENTITY_TYPES.get(pan[3])
    if entity is None:
        return GstinCheck(
            gstin, False, field,
            f"character 6 of the GSTIN ({pan[3]}) is not a valid PAN holder type",
            state_code=code, state=state_name(code), pan=pan,
        )

    expected = compute_check_digit(gstin[:14])
    if gstin[14] != expected:
        return GstinCheck(
            gstin, False, field,
            f"checksum character is {gstin[14]}, but the first 14 characters "
            f"require {expected} -- this GSTIN contains a typo",
            state_code=code, state=state_name(code), pan=pan,
            entity_type=entity, expected_check_digit=expected,
        )

    return GstinCheck(
        gstin, True, field, None,
        state_code=code, state=state_name(code), pan=pan,
        entity_type=entity, expected_check_digit=expected,
    )


def _explain_format_failure(g: str) -> str:
    """Point at the first character group that is wrong, not just 'invalid'."""
    checks = [
        (g[0:2].isdigit(), "characters 1-2 must be the numeric state code"),
        (g[2:7].isalpha() and g[2:7].isupper(), "characters 3-7 must be five letters (start of PAN)"),
        (g[7:11].isdigit(), "characters 8-11 must be four digits (PAN)"),
        (g[11:12].isalpha(), "character 12 must be a letter (PAN check letter)"),
        (g[12:13].isalnum(), "character 13 must be a digit 1-9 or a letter"),
        (g[13:14] == "Z", f"character 14 must be Z, but it is {g[13:14] or '(missing)'}"),
        (g[14:15].isalnum(), "character 15 must be the alphanumeric checksum"),
    ]
    for ok, message in checks:
        if not ok:
            return message
    return "GSTIN does not match the required 15-character pattern"
