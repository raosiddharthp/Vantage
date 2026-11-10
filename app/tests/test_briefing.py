from app.briefing import LABELS, build_briefing


def f(value=None, canon=None, status="ok", source_doc="loss_report", conflicts=None, stated_missing=None):
    return {"value": value, "canonical": canon, "status": status,
            "source_doc": source_doc if value else None,
            "conflicts": conflicts or [], "stated_missing": stated_missing or [],
            "evidence": [], "grounded": True, "agreeing_docs": 2}


def record(**overrides):
    fields = {
        "claim_ref": f("CLM-2026-0001", "clm-2026-0001"),
        "policy_number": f("BGI-CP-3249648", "bgi-cp-3249648"),
        "insured_name": f("Thornbury Electrical Supplies Limited", "x"),
        "risk_address": f("Unit 36, Riverside Trading Park, Wakefield, WF2 6LE", "x"),
        "occupancy_type": f("Retail premises", "x", source_doc="fnol_form"),
        "date_of_loss": f("29 August 2026", "2026-08-29"),
        "date_reported": f("2 September 2026", "2026-09-02"),
        "cause_of_loss": f("Fire", "fire"),
        "loss_description": f("A fire started in the workshop.", "x", source_doc="fnol_form"),
        "building_damage_estimate": f("£235,000", 235000),
        "contents_damage_estimate": f("£82,250", 82250),
        "business_interruption": f("Yes", True, source_doc="fnol_form"),
        "third_party_involved": f("No", False),
        "third_party_name": f(None, None, status="not_applicable"),
        "reporter_name": f("Rahul Kim", "rahul kim", source_doc="fnol_form"),
        "reporter_phone": f("07700 900449", "07700900449", source_doc="fnol_form"),
    }
    flags = []
    for name, value in overrides.items():
        fields[name] = value
        if value["status"] in ("missing", "conflict", "ungrounded", "unparsed"):
            flags.append({"field": name, "type": value["status"]})
    return {"claim_id": "CLM-2026-0001", "fields": fields, "flags": flags}


def texts(b):
    return [s["text"] for s in b["sentences"]]


def test_clean_claim_reads_well_and_needs_no_review():
    b = build_briefing(record())
    assert b["headline"] == "Fire at Unit 36, Riverside Trading Park, Wakefield, WF2 6LE"
    assert "The loss occurred on 29 August 2026 and was reported on 2 September 2026 (4 days later)." in texts(b)
    assert "Estimated damage: £235,000 building and £82,250 contents (£317,250 in total)." in texts(b)
    assert "A business interruption claim is expected." in texts(b)
    assert "No third party is involved." in texts(b)
    assert "Reported by Rahul Kim (07700 900449)." in texts(b)
    assert b["attention"] == [] and b["review_required"] is False


def test_conflict_names_both_values_and_the_source_used():
    r = record(building_damage_estimate=f("£141,250", 141250, status="conflict",
               conflicts=[{"doc": "fnol_form", "value": "£180,600", "line_ids": ["p1-l20"]}]))
    (a,) = build_briefing(r)["attention"]
    assert a["field"] == "building_damage_estimate" and a["type"] == "conflict"
    assert "£141,250" in a["text"] and "£180,600" in a["text"] and "more authoritative" in a["text"]
    assert "scan was misread" not in a["text"]


def test_near_identical_conflict_hints_at_a_scan_error():
    r = record(cause_of_loss=f("theft / burgiary", "x", status="conflict",
               conflicts=[{"doc": "fnol_form", "value": "Theft / burglary", "line_ids": []}]))
    (a,) = build_briefing(r)["attention"]
    assert "scan was misread" in a["text"]


def test_missing_date_is_said_plainly_and_cites_the_placeholder():
    r = record(date_of_loss=f(None, None, status="missing",
               stated_missing=[{"doc": "fnol_form", "value": "Not yet confirmed"}]))
    b = build_briefing(r)
    assert "The date of loss is not confirmed. It was reported on 2 September 2026." in texts(b)
    (a,) = b["attention"]
    assert 'the FNOL form says "Not yet confirmed"' in a["text"]


def test_missing_policy_number_is_called_out_in_the_text():
    r = record(policy_number=f(None, None, status="missing",
               stated_missing=[{"doc": "fnol_form", "value": "Not recorded"}]))
    b = build_briefing(r)
    assert any("policy number not recorded" in t for t in texts(b))
    assert b["review_required"] is True


def test_third_party_with_name():
    r = record(third_party_involved=f("Yes", True), third_party_name=f("Brightside Electrical Services", "x"))
    assert "A third party is involved: Brightside Electrical Services." in texts(build_briefing(r))


def test_every_sentence_cites_only_real_fields():
    b = build_briefing(record())
    for s in b["sentences"]:
        assert s["fields"] and all(name in LABELS for name in s["fields"])


def test_cause_is_capitalised_in_the_sentence():
    r = record(cause_of_loss=f("fire", "fire"))
    assert "Cause of loss: Fire." in texts(build_briefing(r))


def test_sentences_resting_on_flagged_fields_are_marked():
    r = record(cause_of_loss=f("theft / burgiary", "x", status="conflict",
               conflicts=[{"doc": "fnol_form", "value": "Theft / burglary", "line_ids": []}]))
    b = build_briefing(r)
    marked = {s["text"]: s["flagged"] for s in b["sentences"]}
    assert marked["Cause of loss: Theft / burgiary."] is True
    assert marked["No third party is involved."] is False
    assert b["headline_flagged"] is True


def test_clean_claim_has_nothing_marked():
    b = build_briefing(record())
    assert not any(s["flagged"] for s in b["sentences"]) and b["headline_flagged"] is False
