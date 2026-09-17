"""GST state / UT codes.

The first two characters of a GSTIN are the state code. This table is the
authority for validating them and for deciding intra- vs inter-state supply.
It is data, not judgement: nothing here infers a place of supply.
"""

STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "96": "Foreign Country",
    "97": "Other Territory",
}

# 25 (Daman & Diu) and 28 (old Andhra Pradesh) were merged away and are no
# longer issued. They are listed so a stale GSTIN gets a useful message rather
# than "unknown state code".
RETIRED_STATE_CODES: dict[str, str] = {
    "25": "Daman and Diu (merged into 26 on 26 Jan 2020)",
    "28": "Andhra Pradesh (old; split into 37 Andhra Pradesh and 36 Telangana)",
}


def state_name(code: str) -> str | None:
    return STATE_CODES.get(code)


def is_valid_state_code(code: str) -> bool:
    return code in STATE_CODES


def retired_reason(code: str) -> str | None:
    return RETIRED_STATE_CODES.get(code)


def name_to_code(name: str) -> str | None:
    """Reverse lookup, case- and punctuation-insensitive."""
    def norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    target = norm(name)
    for code, nm in STATE_CODES.items():
        if norm(nm) == target:
            return code
    return None
