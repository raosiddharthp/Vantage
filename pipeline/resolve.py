"""Resolve per-document readings into one value per field, with flags.

Rules: the most authoritative document that states a field wins; a field is
in conflict when another document states a different value once both are
normalised; a value is grounded when it appears in the OCR lines it cites.
"""
import re

from pipeline.normalise import canonical, is_placeholder

AUTHORITY = ("loss_report", "repair_estimate", "fnol_form")
# The loss description is the claimant's own narrative, so the FNOL form leads.
FIELD_AUTHORITY = {"loss_description": ("fnol_form", "loss_report", "repair_estimate")}
# Free-text narratives legitimately differ between documents: never a conflict.
NARRATIVE_FIELDS = {"loss_description"}
FIELDS = (
    "claim_ref", "policy_number", "insured_name", "risk_address",
    "occupancy_type", "date_of_loss", "date_reported", "cause_of_loss",
    "building_damage_estimate", "contents_damage_estimate",
    "business_interruption", "third_party_involved", "third_party_name",
    "reporter_name", "reporter_phone", "loss_description",
)


def _squash(s):
    return re.sub(r"[^0-9a-z]", "", s.casefold())


BOOL_FIELDS = {"business_interruption", "third_party_involved"}


def is_grounded(value, cited_text, field=None):
    """The value appears in the cited lines, or (yes/no fields only) a cited
    sentence means the same thing as the value."""
    v = _squash(value)
    if v and v in _squash(cited_text):
        return True
    if field in BOOL_FIELDS and len(cited_text.split()) >= 6:
        said = canonical(field, cited_text)
        return said is not None and said == canonical(field, value)
    return False


def resolve(readings, line_text):
    """readings: [{field, doc, value, line_ids}]; line_text: {doc: {line_id: text}}."""
    out = {}
    for field in FIELDS:
        rs, stated_missing = [], []
        for r in readings:
            if r["field"] != field or r["value"] is None or not str(r["value"]).strip():
                continue
            if is_placeholder(r["value"]):
                stated_missing.append({"doc": r["doc"], "value": r["value"], "line_ids": r["line_ids"]})
                continue
            cited = " ".join(line_text.get(r["doc"], {}).get(i, "") for i in r["line_ids"])
            rs.append({**r, "canon": canonical(field, r["value"]),
                       "grounded": is_grounded(r["value"], cited, field)})
        order = FIELD_AUTHORITY.get(field, AUTHORITY)
        rs.sort(key=lambda r: order.index(r["doc"]))
        if not rs:
            out[field] = {"field": field, "value": None, "canon": None,
                          "source_doc": None, "line_ids": [], "grounded": None,
                          "status": "missing", "conflicts": [],
                          "stated_missing": stated_missing}
            continue
        authority = rs[0]
        # Authority decides the value. Among readings that agree with it, cite one
        # whose lines really contain the value, so the evidence link is useful.
        best = next((r for r in rs
                     if r["canon"] == authority["canon"] and r["grounded"]), authority)
        conflicts = [{"doc": r["doc"], "value": r["value"], "line_ids": r["line_ids"]}
                     for r in rs[1:] if r["canon"] != best["canon"]]
        if field in NARRATIVE_FIELDS:
            conflicts = []
        if best["canon"] is None:
            status = "unparsed"
        elif conflicts:
            status = "conflict"
        elif not best["grounded"]:
            status = "ungrounded"
        else:
            status = "ok"
        out[field] = {"field": field, "value": best["value"], "canon": best["canon"],
                      "source_doc": best["doc"], "line_ids": best["line_ids"],
                      "grounded": best["grounded"], "status": status,
                      "agreeing_docs": len(rs) - len(conflicts), "conflicts": conflicts}
    return out
