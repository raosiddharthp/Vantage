"""Synthetic Commercial Property claim generator for the Vantage POC.

Produces 30 fictional claim packs (FNOL form, loss adjuster report, repair
estimate) plus an exact answer key for each. Everything is invented. The
output is deterministic: the same seed always yields the same claims and labels.

    python data/generate_claims.py

Writes:
    data/claims/<claim_id>/*.pdf        claim documents (not committed to git)
    data/ground_truth/<claim_id>.json   answer key per claim
    data/ground_truth/manifest.json     index of all claims

Authority order when documents disagree: loss report > repair estimate > FNOL form.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

import pymupdf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SEED = 1110
HERE = Path(__file__).resolve().parent
CLAIMS_DIR = HERE / "claims"
TRUTH_DIR = HERE / "ground_truth"

TIERS = ["clean"] * 18 + ["scanned"] * 9 + ["problem"] * 3
PROBLEMS = ["missing_date", "missing_ids", "conflict"]

SCORED_FIELDS = [
    "claim_ref", "policy_number", "insured_name", "risk_address", "occupancy_type",
    "date_of_loss", "date_reported", "cause_of_loss", "building_damage_estimate",
    "contents_damage_estimate", "business_interruption", "third_party_involved",
    "third_party_name", "reporter_name", "reporter_phone",
]
UNSCORED_FIELDS = ["loss_description"]

STEMS = ["Harlow", "Brightwater", "Ashford", "Kestrel", "Marlow", "Thornbury", "Calder",
         "Redfern", "Stanton", "Pennine", "Westbrook", "Alder", "Corbridge", "Danbury",
         "Elmstead", "Fairlight", "Granton", "Hexham", "Ironbridge", "Kingsley"]
TRADES = ["Logistics", "Foods", "Engineering", "Textiles", "Print Works", "Storage",
          "Joinery", "Packaging", "Plastics", "Wholesale", "Bakeries", "Fabrications",
          "Electrical Supplies", "Furniture", "Components"]
TOWNS = [("Wakefield", "WF"), ("Leeds", "LS"), ("Bradford", "BD"), ("Sheffield", "S"),
         ("Derby", "DE"), ("Nottingham", "NG"), ("Leicester", "LE"), ("Bristol", "BS"),
         ("Reading", "RG"), ("Norwich", "NR"), ("Cardiff", "CF"), ("Glasgow", "G"),
         ("Newcastle", "NE"), ("Swindon", "SN")]
ESTATES = ["Calder Industrial Estate", "Riverside Trading Park", "Meadow Lane Business Park",
           "Foundry Road", "Canal Street Works", "Northgate Enterprise Park", "Station Yard",
           "Millbrook Way"]
OCCUPANCY = ["Warehouse and storage", "Light manufacturing", "Retail premises",
             "Food production", "Office building", "Workshop"]
AREAS = ["main production area", "rear storage bay", "loading dock", "first-floor office",
         "goods-in area", "workshop floor", "retail floor", "plant room"]
FIRST = ["Dana", "Priya", "Tom", "Helen", "Marcus", "Aisha", "Callum", "Fiona", "Owen",
         "Grace", "Rahul", "Nadia", "Stuart", "Imogen", "Declan"]
LAST = ["Whitcombe", "Adeyemi", "Chandra", "Okonkwo", "Marsh", "Kim", "Mehta", "Clarke",
        "Hargreaves", "Linton", "Barrow", "Quill", "Ferris", "Nolan", "Pearce"]
THIRD_PARTIES = ["Redline Haulage Ltd", "Okafor Print Ltd", "Brightside Electrical Services",
                 "Penrose Roofing Ltd", "Tallis Mechanical Ltd", "Greenway Couriers Ltd",
                 "Aldous Joinery Ltd", "Norbury Cleaning Services"]
CONTRACTORS = ["Hartwell Building Services", "Kingsmead Construction Ltd",
               "Ridgeway Reinstatement Ltd", "Oakley Property Repairs"]
ADJUSTERS = ["Marlowe and Finch Loss Adjusters", "Calloway Reid Claims Consultants",
             "Strand and Vale Adjusting"]
POSTCODE_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"

CAUSES = ["Fire", "Escape of water", "Storm damage", "Theft / burglary",
          "Malicious damage", "Impact by vehicle"]

LINE_ITEMS = {
    "Fire": ["Smoke damage clean and decontamination", "Roof deck repair",
             "Electrical rewire (affected circuits)", "Redecoration of affected areas",
             "Replacement fixtures and fittings", "Skip hire and debris removal"],
    "Escape of water": ["Water extraction and drying", "Replacement flooring",
                        "Plasterboard and skim", "Electrical testing and repairs",
                        "Redecoration", "Pipework repair"],
    "Storm damage": ["Roof sheeting replacement", "Scaffold hire", "Internal ceiling repairs",
                     "Gutter and fascia repairs", "Water damage drying", "Redecoration"],
    "Theft / burglary": ["Roller shutter replacement", "Door and frame repairs",
                         "Alarm panel replacement", "Lock changes", "Redecoration",
                         "Temporary security hire"],
    "Malicious damage": ["Window replacement", "Door and frame repairs", "Graffiti removal",
                         "Replacement fixtures", "Redecoration", "Temporary boarding"],
    "Impact by vehicle": ["Structural wall repair", "Door frame replacement",
                          "Racking replacement", "Steel lintel repair", "Redecoration",
                          "Temporary propping"],
}


# ----------------------------------------------------------------- formatting
def d_slash(d):
    return d.strftime("%d/%m/%Y")


def d_long(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def d_abbr(d):
    return f"{d.day:02d}-{d.strftime('%b-%Y')}"


def money(n):
    return f"£{n:,}"


def yes_no(b):
    return "Yes" if b else "No"


def split_amount(rng, total, parts):
    """Split an integer total into `parts` positive integers that sum exactly."""
    weights = [rng.uniform(0.5, 2.0) for _ in range(parts)]
    scale = total / sum(weights)
    amounts = [max(50, int(round(w * scale, -1))) for w in weights]
    amounts[-1] = total - sum(amounts[:-1])
    if amounts[-1] < 50:  # extremely unlikely; rebalance deterministically
        amounts = [total // parts] * parts
        amounts[-1] = total - sum(amounts[:-1])
    return amounts


# --------------------------------------------------------------- claim model
def make_claim(rng, number, tier, problem, used_names):
    claim_id = f"CLM-2026-{number:04d}"

    while True:
        stem, trade = rng.choice(STEMS), rng.choice(TRADES)
        insured = f"{stem} {trade} {rng.choice(['Ltd', 'Limited'])}"
        if insured not in used_names:
            used_names.add(insured)
            break

    town, area_code = rng.choice(TOWNS)
    postcode = (f"{area_code}{rng.randint(1, 19)} {rng.randint(1, 9)}"
                f"{rng.choice(POSTCODE_LETTERS)}{rng.choice(POSTCODE_LETTERS)}")
    address = f"Unit {rng.randint(1, 40)}, {rng.choice(ESTATES)}, {town}, {postcode}"

    loss_date = date(2026, 1, 5) + timedelta(days=rng.randint(0, 260))
    reported = loss_date + timedelta(days=rng.randint(0, 6))
    cause = rng.choice(CAUSES)
    area = rng.choice(AREAS)
    time_str = f"{rng.randint(0, 23):02d}:{rng.choice(['00', '15', '30', '45'])}"

    third_party = None
    if cause == "Impact by vehicle":
        third_party = rng.choice(THIRD_PARTIES)
    elif cause == "Escape of water" and rng.random() < 0.4:
        third_party = rng.choice(THIRD_PARTIES)
    elif cause == "Fire" and rng.random() < 0.3:
        third_party = rng.choice(THIRD_PARTIES)

    building = rng.randrange(8000, 260000, 250)
    contents = 0 if rng.random() < 0.25 else rng.randrange(2000, 90000, 250)
    bi_chance = 0.15 if cause == "Theft / burglary" else 0.4
    business_interruption = rng.random() < bi_chance

    first, last = rng.choice(FIRST), rng.choice(LAST)
    phone = f"07700 900{rng.randint(100, 999)}"
    email = f"{first.lower()}.{last.lower()}@{stem.lower()}{trade.split()[0].lower()}.example"

    description = describe_loss(cause, area, time_str, third_party)

    truth = {
        "claim_ref": claim_id,
        "policy_number": f"BGI-CP-{rng.randint(1000000, 9999999)}",
        "insured_name": insured,
        "risk_address": address,
        "occupancy_type": rng.choice(OCCUPANCY),
        "date_of_loss": loss_date.isoformat(),
        "date_reported": reported.isoformat(),
        "cause_of_loss": cause,
        "loss_description": description,
        "building_damage_estimate": building,
        "contents_damage_estimate": contents,
        "business_interruption": business_interruption,
        "third_party_involved": third_party is not None,
        "third_party_name": third_party,
        "reporter_name": f"{first} {last}",
        "reporter_phone": phone,
    }

    claim = {
        "claim_id": claim_id,
        "tier": tier,
        "problem_type": problem,
        "truth": truth,
        "email": email,
        "area": area,
        "time": time_str,
        "loss_date": loss_date,
        "reported": reported,
        "contractor": rng.choice(CONTRACTORS),
        "adjuster": rng.choice(ADJUSTERS),
        "form_building": building,
        "show_date_of_loss": True,
        "show_policy": True,
        "show_phone": True,
        "flags": {"missing": [], "conflicting": []},
    }

    if problem == "missing_date":
        truth["date_of_loss"] = None
        claim["show_date_of_loss"] = False
        claim["flags"]["missing"].append("date_of_loss")
    elif problem == "missing_ids":
        truth["policy_number"] = None
        truth["reporter_phone"] = None
        claim["show_policy"] = False
        claim["show_phone"] = False
        claim["flags"]["missing"] += ["policy_number", "reporter_phone"]
    elif problem == "conflict":
        inflated = int(round(building * rng.uniform(1.25, 1.45), -2))
        claim["form_building"] = inflated if inflated != building else building + 5000
        claim["flags"]["conflicting"].append("building_damage_estimate")

    return claim


def describe_loss(cause, area, time_str, third_party):
    if cause == "Fire":
        text = (f"A fire started in the {area} at approximately {time_str}. It was contained "
                "by the fire service, leaving heat, smoke and water damage to stock, fixtures "
                "and the roof structure.")
        if third_party:
            text += f" The fire is believed to have started during hot works by {third_party}."
    elif cause == "Escape of water":
        text = (f"A supply pipe failed in the {area} and the leak was discovered at {time_str}. "
                "Water affected flooring, plasterboard and stock stored at low level.")
        if third_party:
            text += f" The water is believed to have come from premises occupied by {third_party}."
    elif cause == "Storm damage":
        text = (f"High winds lifted roof sheeting above the {area} and rain entered the building. "
                f"The damage was discovered at {time_str}.")
    elif cause == "Theft / burglary":
        text = (f"Forced entry was made through the {area} shutter overnight. Stock and equipment "
                f"were taken and the shutter and alarm panel were damaged. Discovered at {time_str}; "
                "the police have been informed.")
    elif cause == "Malicious damage":
        text = (f"Vandalism to the {area}: windows were broken and fixtures damaged. "
                f"Discovered at {time_str}.")
    else:
        text = (f"A vehicle reversed into the {area} wall at approximately {time_str}, damaging the "
                f"wall, door frame and internal racking. The driver, employed by {third_party}, "
                "left contact details.")
    return text


# ------------------------------------------------------------------- PDF build
_ss = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=_ss["Title"], fontSize=16, spaceAfter=2)
SUB = ParagraphStyle("s", parent=_ss["Normal"], fontSize=11, textColor=colors.HexColor("#444444"),
                     alignment=1, spaceAfter=8)
BODY = ParagraphStyle("b", parent=_ss["Normal"], fontSize=10, leading=14)
CELL = ParagraphStyle("c", parent=_ss["Normal"], fontSize=9.5, leading=12)
CELLB = ParagraphStyle("cb", parent=CELL, fontName="Helvetica-Bold")
HEAD = ParagraphStyle("h", parent=_ss["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=3)


def P(text, style=BODY):
    return Paragraph(escape(text), style)


def kv_table(rows):
    data = [[P(k, CELLB), P(v or "", CELL)] for k, v in rows]
    table = Table(data, colWidths=[55 * mm, 115 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEEEEE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def build_pdf(path, story, title):
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=title,
                            author="Vantage synthetic data", invariant=1)
    doc.build(story)


def build_fnol(path, c):
    t = c["truth"]
    rows = [
        ("Claim reference", t["claim_ref"]),
        ("Policy number", t["policy_number"] if c["show_policy"] else ""),
        ("Insured", t["insured_name"]),
        ("Risk address", t["risk_address"]),
        ("Occupancy", t["occupancy_type"]),
        ("Date of loss", d_slash(c["loss_date"]) if c["show_date_of_loss"] else ""),
        ("Date reported", d_slash(c["reported"])),
        ("Cause of loss", t["cause_of_loss"]),
        ("Estimated building damage", money(c["form_building"])),
        ("Estimated contents damage", money(t["contents_damage_estimate"])),
        ("Business interruption expected", yes_no(t["business_interruption"])),
        ("Third party involved", yes_no(t["third_party_involved"])),
        ("Third party name", t["third_party_name"] or ""),
        ("Reported by", t["reporter_name"]),
        ("Contact telephone", t["reporter_phone"] if c["show_phone"] else ""),
        ("Contact email", c["email"]),
    ]
    story = [P("BISHOPSGATE GENERAL INSURANCE", TITLE),
             P("First Notification of Loss: Commercial Property", SUB),
             kv_table(rows),
             Paragraph("Description of loss", HEAD),
             P(t["loss_description"]),
             Spacer(1, 8 * mm),
             P("I declare that the information given above is true to the best of my knowledge."),
             Spacer(1, 6 * mm),
             P(f"Signed: {t['reporter_name']}        Date: {d_slash(c['reported'])}")]
    build_pdf(path, story, f"FNOL {t['claim_ref']}")


def build_report(path, c):
    t = c["truth"]
    inspection = c["reported"] + timedelta(days=1 + (c["loss_date"].day % 4))
    cause = t["cause_of_loss"].lower()
    header = [
        ("Claim reference", t["claim_ref"]),
        ("Policy number", t["policy_number"] if c["show_policy"] else "Not recorded"),
        ("Insured", t["insured_name"]),
        ("Risk address", t["risk_address"]),
        ("Date of loss", d_long(c["loss_date"]) if c["show_date_of_loss"] else "Not yet confirmed"),
        ("Date of inspection", d_long(inspection)),
    ]
    circumstances = (f"The reported cause of loss is {cause}, affecting the {c['area']} of the "
                     f"{t['occupancy_type'].lower()} at the risk address. The incident was "
                     f"reported to the insurer on {d_long(c['reported'])}.")
    if not c["show_date_of_loss"]:
        circumstances += " The insured has not yet confirmed the date on which the loss occurred."
    damage = ("On inspection we observed damage consistent with the reported cause. "
              "A schedule of building repair works has been obtained from the insured's contractor.")
    if t["third_party_involved"]:
        third = (f"Enquiries indicate that {t['third_party_name']} may be connected to the incident. "
                 "No position on responsibility has been reached and the evidence is still being collected.")
    else:
        third = "No third-party involvement has been identified at this stage."
    if t["business_interruption"]:
        bi = ("The insured reports that trading has been interrupted since the loss and "
              "expects to make a business interruption claim.")
    else:
        bi = "The premises remain operational. No business interruption claim is anticipated."
    reserve = [("Building", money(t["building_damage_estimate"])),
               ("Contents", money(t["contents_damage_estimate"]))]

    story = [P(c["adjuster"].upper(), TITLE), P("Preliminary Loss Report", SUB),
             kv_table(header),
             Paragraph("1. Circumstances", HEAD), P(circumstances),
             Paragraph("2. Damage observed", HEAD), P(damage),
             Paragraph("3. Third party position", HEAD), P(third),
             Paragraph("4. Business interruption", HEAD), P(bi),
             Paragraph("5. Recommended reserve", HEAD), kv_table(reserve),
             Spacer(1, 6 * mm),
             P(f"Prepared by {c['adjuster']} on behalf of Bishopsgate General Insurance.")]
    build_pdf(path, story, f"Loss report {t['claim_ref']}")


def build_estimate(path, c, rng):
    t = c["truth"]
    items = rng.sample(LINE_ITEMS[t["cause_of_loss"]], rng.randint(4, 6))
    amounts = split_amount(rng, t["building_damage_estimate"], len(items))
    quote_date = c["reported"] + timedelta(days=5 + (c["loss_date"].day % 5))
    head = [
        ("Quotation reference", f"Q-{rng.randint(10000, 99999)}"),
        ("Quotation date", d_abbr(quote_date)),
        ("Client", t["insured_name"]),
        ("Works address", t["risk_address"]),
        ("Our claim reference", t["claim_ref"]),
    ]
    rows = [[P("Item", CELLB), P("Amount (GBP)", CELLB)]]
    rows += [[P(i, CELL), P(money(a), CELL)] for i, a in zip(items, amounts)]
    rows.append([P("TOTAL ESTIMATE", CELLB), P(money(t["building_damage_estimate"]), CELLB)])
    table = Table(rows, colWidths=[125 * mm, 45 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story = [P(c["contractor"].upper(), TITLE), P("Schedule of Repair Works", SUB),
             kv_table(head), Spacer(1, 6 * mm), table, Spacer(1, 6 * mm),
             P("This estimate is valid for 30 days. Works subject to access and final inspection.")]
    build_pdf(path, story, f"Estimate {t['claim_ref']}")


# ----------------------------------------------------------- scanned appearance
def scanify(path, seed_text):
    """Replace a digital PDF with an image-only, slightly skewed and noisy copy."""
    rng = random.Random(seed_text)
    pages = []
    with pymupdf.open(str(path)) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=130)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
            img = img.rotate(rng.uniform(-1.8, 1.8), resample=Image.BICUBIC, fillcolor=238)
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.0)))
            img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.82, 0.93))
            img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.94, 1.0))
            draw = ImageDraw.Draw(img)
            w, h = img.size
            for _ in range(rng.randint(150, 400)):
                x, y, r = rng.randrange(w), rng.randrange(h), rng.choice([0, 0, 1])
                draw.ellipse([x - r, y - r, x + r, y + r], fill=rng.randint(120, 200))
            for _ in range(rng.randint(1, 2)):
                y = rng.randrange(h)
                draw.line([(0, y), (w, y)], fill=rng.randint(205, 225), width=2)
            pages.append(img)
    pages[0].save(str(path), "PDF", resolution=130.0, save_all=True, append_images=pages[1:])


# --------------------------------------------------------------------- main
def main():
    rng = random.Random(SEED)
    tiers = TIERS[:]
    rng.shuffle(tiers)
    problem_queue = PROBLEMS[:]
    used_names = set()
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []

    for number, tier in enumerate(tiers, start=1):
        problem = problem_queue.pop(0) if tier == "problem" else None
        claim = make_claim(rng, number, tier, problem, used_names)
        cid = claim["claim_id"]
        folder = CLAIMS_DIR / cid
        folder.mkdir(parents=True, exist_ok=True)

        files = {
            "fnol_form": folder / f"{cid}_fnol_form.pdf",
            "loss_report": folder / f"{cid}_loss_report.pdf",
            "repair_estimate": folder / f"{cid}_repair_estimate.pdf",
        }
        build_fnol(files["fnol_form"], claim)
        build_report(files["loss_report"], claim)
        build_estimate(files["repair_estimate"], claim, rng)

        documents = []
        for doc_type, path in files.items():
            if tier == "scanned":
                scanify(path, f"{SEED}-{cid}-{doc_type}")
            with pymupdf.open(str(path)) as d:
                pages = len(d)
            documents.append({"type": doc_type, "file": f"{cid}/{path.name}", "pages": pages})

        answer_key = {
            "claim_id": cid,
            "tier": tier,
            "problem_type": problem,
            "fields": claim["truth"],
            "expected_flags": claim["flags"],
            "scored_fields": SCORED_FIELDS,
            "unscored_fields": UNSCORED_FIELDS,
            "documents": documents,
        }
        (TRUTH_DIR / f"{cid}.json").write_text(json.dumps(answer_key, indent=2) + "\n")
        manifest.append({"claim_id": cid, "tier": tier, "problem_type": problem,
                         "documents": documents})

    (TRUTH_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    counts = {t: tiers.count(t) for t in ("clean", "scanned", "problem")}
    print(f"Generated {len(tiers)} claims {counts}")
    print(f"Documents:    {CLAIMS_DIR}")
    print(f"Ground truth: {TRUTH_DIR}")


if __name__ == "__main__":
    main()
