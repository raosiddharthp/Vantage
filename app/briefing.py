"""Assemble the handler briefing from a Claim Intelligence Record.

Every sentence is built from verified fields only and lists the fields it
used, so the handler view can show the evidence behind each statement.
There is no free-text generation: nothing can be invented, and viewing a
briefing costs nothing.

    python -m app.briefing --claim CLM-2026-0015
"""
import argparse
import difflib
from datetime import date

LABELS = {
    "claim_ref": "Claim reference",
    "policy_number": "Policy number",
    "insured_name": "Insured",
    "risk_address": "Risk address",
    "occupancy_type": "Occupancy",
    "date_of_loss": "Date of loss",
    "date_reported": "Date reported",
    "cause_of_loss": "Cause of loss",
    "building_damage_estimate": "Building damage estimate",
    "contents_damage_estimate": "Contents damage estimate",
    "business_interruption": "Business interruption",
    "third_party_involved": "Third party involved",
    "third_party_name": "Third party name",
    "reporter_name": "Reporter",
    "reporter_phone": "Reporter phone",
    "loss_description": "Description of loss",
}
DOC_REFS = {
    "fnol_form": "the FNOL form",
    "loss_report": "the loss report",
    "repair_estimate": "the repair estimate",
}


def _doc(doc, capital=False):
    ref = DOC_REFS.get(doc, doc)
    return ref[0].upper() + ref[1:] if capital else ref


HAS_VALUE = ("ok", "conflict", "ungrounded", "unparsed")
SIMILAR = 0.85  # printed values this alike probably differ by a reading error


def _field(record, name):
    return record["fields"].get(name) or {"status": "missing", "value": None, "canonical": None}


def _has(record, name):
    f = _field(record, name)
    return f["status"] in HAS_VALUE and f.get("value") not in (None, "")


def _text(record, name):
    return _field(record, name)["value"].strip()


def _date(record, name):
    canon = _field(record, name).get("canonical")
    try:
        d = date.fromisoformat(canon)
    except (TypeError, ValueError):
        return None
    return f"{d.day} {d:%B %Y}"


def _money_value(record, name):
    canon = _field(record, name).get("canonical")
    return canon if isinstance(canon, int) and not isinstance(canon, bool) else None


def _days_between(record, first, second):
    try:
        a = date.fromisoformat(_field(record, first)["canonical"])
        b = date.fromisoformat(_field(record, second)["canonical"])
    except (TypeError, ValueError):
        return None
    return (b - a).days


def _sentences(record):
    out = []

    parts = []
    if _has(record, "insured_name"):
        parts.append(_text(record, "insured_name"))
    if _has(record, "occupancy_type"):
        parts.append(_text(record, "occupancy_type").lower())
    policy = _text(record, "policy_number") if _has(record, "policy_number") else None
    text = ", ".join(parts)
    if text:
        text = f"Insured: {text}"
    if policy:
        text = f"{text}; policy {policy}" if text else f"Policy {policy}"
    elif text:
        text += "; policy number not recorded"
    if text:
        out.append({"text": text + ".",
                    "fields": ["insured_name", "occupancy_type", "policy_number"]})

    lost, reported = _date(record, "date_of_loss"), _date(record, "date_reported")
    gap = _days_between(record, "date_of_loss", "date_reported")
    if lost and reported:
        late = f" ({gap} day{'s' if gap != 1 else ''} later)" if gap is not None and gap >= 0 else ""
        out.append({"text": f"The loss occurred on {lost} and was reported on {reported}{late}.",
                    "fields": ["date_of_loss", "date_reported"]})
    elif reported:
        out.append({"text": f"The date of loss is not confirmed. It was reported on {reported}.",
                    "fields": ["date_of_loss", "date_reported"]})
    elif lost:
        out.append({"text": f"The loss occurred on {lost}.", "fields": ["date_of_loss"]})

    if _has(record, "cause_of_loss"):
        cause = _text(record, "cause_of_loss")
        out.append({"text": f"Cause of loss: {cause[0].upper() + cause[1:]}.",
                    "fields": ["cause_of_loss"]})
    if _has(record, "loss_description"):
        out.append({"text": f"Description: {_text(record, 'loss_description')}",
                    "fields": ["loss_description"]})

    building = _money_value(record, "building_damage_estimate")
    contents = _money_value(record, "contents_damage_estimate")
    if building is not None and contents is not None:
        out.append({"text": f"Estimated damage: £{building:,} building and £{contents:,} contents "
                            f"(£{building + contents:,} in total).",
                    "fields": ["building_damage_estimate", "contents_damage_estimate"]})
    elif building is not None:
        out.append({"text": f"Estimated building damage: £{building:,}.",
                    "fields": ["building_damage_estimate"]})
    elif contents is not None:
        out.append({"text": f"Estimated contents damage: £{contents:,}.",
                    "fields": ["contents_damage_estimate"]})

    bi = _field(record, "business_interruption").get("canonical")
    if bi is True:
        out.append({"text": "A business interruption claim is expected.",
                    "fields": ["business_interruption"]})
    elif bi is False:
        out.append({"text": "No business interruption claim is expected.",
                    "fields": ["business_interruption"]})

    third = _field(record, "third_party_involved").get("canonical")
    if third is True:
        who = f": {_text(record, 'third_party_name')}" if _has(record, "third_party_name") else ""
        out.append({"text": f"A third party is involved{who}.",
                    "fields": ["third_party_involved", "third_party_name"]})
    elif third is False:
        out.append({"text": "No third party is involved.", "fields": ["third_party_involved"]})

    if _has(record, "reporter_name"):
        phone = f" ({_text(record, 'reporter_phone')})" if _has(record, "reporter_phone") else ""
        out.append({"text": f"Reported by {_text(record, 'reporter_name')}{phone}.",
                    "fields": ["reporter_name", "reporter_phone"]})
    return out


def _attention(record):
    items = []
    for flag in record.get("flags", []):
        name, kind = flag["field"], flag["type"]
        f = _field(record, name)
        label = LABELS.get(name, name)
        if kind == "conflict":
            c = f["conflicts"][0]
            src = _doc(f.get("source_doc"), capital=True)
            text = (f"{label}: the documents disagree. {src} says {f['value']}; "
                    f"{_doc(c['doc'])} says {c['value']}. "
                    f"{src} is used because it is the more authoritative source.")
            if difflib.SequenceMatcher(None, f["value"].casefold(), c["value"].casefold()).ratio() >= SIMILAR:
                text += " The wording differs only slightly, which can mean a scan was misread: check the page image."
        elif kind == "missing":
            said = f.get("stated_missing") or []
            if said:
                where = "; ".join(f"{_doc(s['doc'])} says \"{s['value']}\"" for s in said)
                text = f"{label}: not recorded ({where})."
            else:
                text = f"{label}: not found in any document."
        elif kind == "ungrounded":
            text = f"{label}: the cited text could not be matched to the value. Check the page image before relying on it."
        else:
            text = f"{label}: the printed value \"{f.get('value')}\" could not be interpreted. Check the page image."
        items.append({"field": name, "type": kind, "text": text})
    return items


def build_briefing(record):
    place = _text(record, "risk_address") if _has(record, "risk_address") else None
    cause = _text(record, "cause_of_loss") if _has(record, "cause_of_loss") else None
    what = (cause[0].upper() + cause[1:]) if cause else "Loss"
    headline = f"{what} at {place}" if place else what
    flagged = {f["field"] for f in record.get("flags", [])}
    sentences = _sentences(record)
    for sentence in sentences:
        # A sentence that rests on a flagged field must not read as settled.
        sentence["flagged"] = any(name in flagged for name in sentence["fields"])
    return {
        "claim_id": record["claim_id"],
        "headline": headline,
        "headline_flagged": bool(flagged & {"cause_of_loss", "risk_address"}),
        "sentences": sentences,
        "attention": _attention(record),
        "review_required": bool(flagged),
    }


def main():
    from google.cloud import firestore

    from app import settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", required=True)
    args = ap.parse_args()
    record = firestore.Client(project=settings.PROJECT_ID).collection("claims").document(args.claim).get().to_dict()
    if record is None:
        raise SystemExit(f"No record for {args.claim}")
    b = build_briefing(record)
    print(f"{b['claim_id']}  {b['headline']}")
    for s in b["sentences"]:
        print(f"  - {s['text']}")
    print("Needs review:" if b["attention"] else "No review flags.")
    for a in b["attention"]:
        print(f"  ! {a['text']}")


if __name__ == "__main__":
    main()
