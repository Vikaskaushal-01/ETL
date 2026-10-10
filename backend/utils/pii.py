"""
Sensitive data (PII) detection and masking.

Card numbers are confirmed with the Luhn checksum, Aadhaar numbers with Verhoeff and IBANs with
mod-97, so ordinary numbers are not mistaken for identifiers. Contact details (emails, phone
numbers, IP addresses) are personal data too, but expected in contact columns; identifiers and
secrets are sensitive wherever they appear.
"""
import hashlib
import hmac
import re
from typing import Optional

import pandas as pd

SAMPLE_VALUES = 2000
# Share of a column's values that must be of one kind for the column to hold that kind of data
COLUMN_SHARE = 0.5


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
               [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
               [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
               [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
               [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
               [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def _iban(value: str) -> bool:
    s = value.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    try:
        return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1
    except ValueError:
        return False


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


_DATEISH = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}")
_YEAR_RANGE = re.compile(r"^[12]\d{3}\s*[-/]\s*[12]\d{3}$")
_PHONE_CHARS = re.compile(r"\+?[\d\s().-]+")


def _phone(match: str) -> bool:
    # In free text only full numbers count: dates, year ranges, decimals and IP addresses have the
    # same shape as short local numbers
    digits = len(_digits(match))
    if digits > 15 or _DATEISH.match(match) or _YEAR_RANGE.match(match.strip()):
        return False
    if match.startswith("+"):
        return digits >= 8
    return digits >= 10 and "." not in match


def _local_phone(text: str) -> bool:
    """A whole value that is a phone number of any length (for columns named as phone numbers)."""
    text = text.strip()
    return (bool(_PHONE_CHARS.fullmatch(text)) and 7 <= len(_digits(text)) <= 15
            and not _DATEISH.match(text) and not _YEAR_RANGE.match(text))


# key: (label, pattern, check on the matched text, sensitive identifier?, column-name hint)
KINDS = {
    "card": ("card numbers", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"),
             lambda m: 13 <= len(_digits(m)) <= 19 and not _DATEISH.match(m) and _luhn(_digits(m)), True, ("card", "ccnum", "pan_number")),
    "aadhaar": ("Aadhaar numbers", re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
                lambda m: not _DATEISH.match(m) and _verhoeff(_digits(m)), True, ("aadhaar", "aadhar", "uid")),
    "pan": ("PAN numbers", re.compile(r"(?<![A-Z0-9])[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z](?![A-Z0-9])"),
            lambda m: True, True, ("pan",)),
    "ssn": ("US social security numbers", re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"),
            lambda m: True, True, ("ssn", "social_security")),
    "iban": ("IBANs", re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?(?![A-Z0-9])"),
             _iban, True, ("iban",)),
    "email": ("email addresses", re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])"),
              lambda m: True, False, ("email", "mail")),
    "phone": ("phone numbers", re.compile(r"(?<![\w+])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,5}\)[ .-]?)?\d{2,5}(?:[ .-]\d{2,5}){1,3}(?![\w-])|(?<![\w+])\+\d{8,14}(?!\w)"),
              _phone, False, ("phone", "mobile", "contact", "tel", "whatsapp")),
    "ip": ("IP addresses", re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"),
           lambda m: True, False, ("ip",)),
}
# About one in ten random numbers passes a checksum (and version numbers look like IP addresses), so
# a column is only taken for these when (almost) every value matches, or its name says what it holds
CHECKSUM_KINDS = ("card", "aadhaar", "ip")
CHECKSUM_COLUMN_SHARE = 0.9
SECRET_NAMES = re.compile(r"(^|_)(password|passwd|pwd|secret|api_?key|access_?token|auth_?token|private_?key)(_|$)")


def label(kind: str) -> str:
    return "secrets (passwords, keys or tokens)" if kind == "secret" else KINDS[kind][0]


def is_sensitive(kind: str) -> bool:
    return kind == "secret" or KINDS[kind][3]


def name_suggests(kind: str, column: str) -> bool:
    name = str(column).lower()
    return kind != "secret" and any(hint in name for hint in KINDS[kind][4])


def _matches(kind: str, text: str, lenient: bool = False) -> list:
    """Matches of the kind in the text; lenient accepts a whole value that is a short local phone number."""
    if kind == "phone" and lenient and _local_phone(text):
        return [re.fullmatch(r"\s*(.*?)\s*", text, re.S)]
    pattern, check = KINDS[kind][1], KINDS[kind][2]
    return [m for m in pattern.finditer(text) if check(m.group(0))]


def contains(kind: str, text: str, lenient: bool = False) -> bool:
    return bool(_matches(kind, text, lenient))


def lenient_for(kind: str, column: str) -> bool:
    """Short local phone numbers only count in a column named as phone numbers."""
    return kind == "phone" and name_suggests("phone", column)


# Cheap tests that rule values out before the patterns run
_MIN_DIGITS = {"card": 13, "aadhaar": 12, "ssn": 9, "iban": 2, "phone": 7, "ip": 4, "pan": 4}


def _filled_text(series: pd.Series) -> pd.Series:
    values = series.dropna().astype(str).str.strip()
    return values[values != ""]


def scan_column(series: pd.Series, column: str) -> list:
    """
    Kinds of sensitive data in a column: [{"kind", "share", "count", "whole_values", "examples"}], where
    whole_values says the values are the data itself (an email column) rather than text containing it.
    """
    if pd.api.types.is_bool_dtype(series):
        return []
    values = _filled_text(series)
    if values.empty:
        return []
    sample = values.sample(SAMPLE_VALUES, random_state=0) if len(values) > SAMPLE_VALUES else values
    found = []
    if SECRET_NAMES.search(str(column).lower()):
        found.append({"kind": "secret", "share": 1.0, "count": int(len(values)), "whole_values": True, "examples": []})
        return found
    numeric = pd.api.types.is_numeric_dtype(series)
    digit_counts = sample.str.count(r"\d")
    has_at = sample.str.contains("@", regex=False)
    for kind in KINDS:
        if numeric and kind not in ("card", "aadhaar"):
            continue
        candidates = sample[has_at] if kind == "email" else sample[digit_counts >= _MIN_DIGITS[kind]]
        lenient = lenient_for(kind, column)
        hits = candidates[candidates.map(lambda v: contains(kind, v, lenient))]
        if hits.empty:
            continue
        whole_values = bool(hits.map(lambda v: any(m.group(0).strip() == v for m in _matches(kind, v, lenient))).mean() >= COLUMN_SHARE)
        share = len(hits) / len(sample)
        named = name_suggests(kind, column)
        # Free text only counts with several values, or the column's name says what it holds
        if len(hits) < 2 and not named:
            continue
        if kind in CHECKSUM_KINDS and whole_values and share < CHECKSUM_COLUMN_SHARE and not named:
            continue
        found.append({
            "kind": kind, "share": share, "count": int(round(share * len(values))),
            "whole_values": whole_values,
            "examples": [mask_text(kind, v, lenient) for v in hits.head(3)],
        })
    # A column of card numbers also matches as phone numbers: keep the most specific kind
    kinds = {f["kind"] for f in found}
    if kinds & {"card", "aadhaar", "ssn", "iban"}:
        found = [f for f in found if f["kind"] not in ("phone",)]
    return found


# ---------- masking ----------

def _mask_token(kind: str, token: str) -> str:
    if kind == "email":
        local, _, domain = token.partition("@")
        return (local[:1] + "***@" + domain) if domain else "***"
    if kind == "ip":
        return ".".join(token.split(".")[:2] + ["x", "x"])
    # Keep the last four characters (as on receipts), hide the rest but keep separators
    keep = 4
    chars = [c for c in token if c.isalnum()]
    hide = max(0, len(chars) - keep)
    out = []
    for c in token:
        if c.isalnum() and hide > 0:
            out.append("*")
            hide -= 1
        else:
            out.append(c)
    return "".join(out)


def mask_text(kind: str, text: str, lenient: bool = False) -> str:
    """The text with every match of the kind masked (the whole value for secrets)."""
    if kind == "secret":
        return "********" if str(text).strip() else str(text)
    out, last = [], 0
    for m in _matches(kind, text, lenient):
        out.append(text[last:m.start()])
        out.append(_mask_token(kind, m.group(0)))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def pseudonym(value: str, key: bytes) -> str:
    """A stable stand-in for a value: the same input always gives the same token, so joins still work."""
    return "anon_" + hmac.new(key, value.strip().encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def pseudonymize_text(kind: str, text: str, key: bytes, lenient: bool = False) -> str:
    if kind == "secret":
        return pseudonym(text, key) if str(text).strip() else str(text)
    out, last = [], 0
    for m in _matches(kind, text, lenient):
        out.append(text[last:m.start()])
        out.append(pseudonym(m.group(0), key))
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def row_mask(series: pd.Series, kind: str, lenient: bool = False) -> pd.Series:
    """Rows whose value contains the kind of data (any filled value for secrets)."""
    text = series.astype(str)
    if kind == "secret":
        return series.notna() & (text.str.strip() != "")
    return series.notna() & text.map(lambda v: contains(kind, v, lenient))


def known_kind(kind: Optional[str]) -> bool:
    return kind == "secret" or kind in KINDS
