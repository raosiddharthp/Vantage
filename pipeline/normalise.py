"""Turn printed values into comparable canonical forms (pure functions)."""
import re
from datetime import datetime

DATE_FORMATS = ("%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d")


def norm_text(s):
    return re.sub(r"\s+", " ", s).strip().casefold()


def norm_date(s):
    s = s.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def norm_money(s):
    digits = re.sub(r"[^\d.]", "", s)
    try:
        return int(round(float(digits)))
    except ValueError:
        return None


def norm_bool(s):
    """Yes/No, also when printed as a sentence ('No claim is anticipated.')."""
    v = s.strip().lower()
    if re.match(r"^(yes|y|true)\b", v):
        return True
    if re.match(r"^(no|n|false)\b", v):
        return False
    if re.search(r"\b(no|not|nil|none|without)\b", v):
        return False
    if re.search(r"\b(yes|expected|anticipated|claimed|involved|likely|true)\b", v):
        return True
    return None


def norm_phone(s):
    return re.sub(r"\D", "", s) or None


NORMALISERS = {
    "date_of_loss": norm_date,
    "date_reported": norm_date,
    "building_damage_estimate": norm_money,
    "contents_damage_estimate": norm_money,
    "business_interruption": norm_bool,
    "third_party_involved": norm_bool,
    "reporter_phone": norm_phone,
}


def canonical(field, raw):
    """Comparable form of a printed value; None if missing or unparseable."""
    if raw is None or str(raw).strip() == "":
        return None
    return NORMALISERS.get(field, norm_text)(str(raw))


PLACEHOLDERS = {
    "unknown", "tbc", "tbd", "n/a", "na", "none", "pending", "-", "\u2014",
    "to be confirmed", "to follow", "blank",
}


def is_placeholder(raw):
    """True when a document prints 'not recorded'-style text instead of a value."""
    v = norm_text(str(raw))
    return v in PLACEHOLDERS or v.startswith("not ")
