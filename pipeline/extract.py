"""Read claim fields per document with Gemini, then resolve them in code.

Gemini only reads: for each document it reports the fields that document
states, copied as printed, with the OCR line ids that contain them. All
judgement (normalising, authority order, conflicts, grounding) is in
pipeline/resolve.py, so results are deterministic and testable.
"""
import argparse
import json
import statistics
from typing import Literal, Optional

from google import genai
from google.cloud import storage
from google.genai import types
from pydantic import BaseModel

from pipeline import config
from pipeline.resolve import FIELDS, resolve

EXTRACT_PREFIX = "extract/"
DOCS = ("fnol_form", "loss_report", "repair_estimate")
PRICE_IN, PRICE_OUT = 0.25, 1.50  # USD per 1M tokens, gemini-3.1-flash-lite

DocName = Literal["fnol_form", "loss_report", "repair_estimate"]
FieldName = Literal[FIELDS]

SYSTEM = ("""You read the three documents of one commercial property insurance \
claim: fnol_form, loss_report and repair_estimate. Each document is given as \
rows of OCR lines. A row looks like:
[p1-l7] Label  |  [p1-l12] Value
Return exactly 48 entries: for each of the three documents, one entry for each \
of the 16 fields, in the order of the field list.
Rules:
- value: copy it exactly as printed. Do not reformat dates, amounts or names.
  If the document does not state the field, value is null and line_ids is [].
- line_ids: the OCR line ids in that same document that contain the value.
- Do not compare documents or resolve disagreements: report each document as printed.
- Never guess or infer a value that is not printed.
Printed labels differ from field names. For example: Insured is insured_name,
Occupancy is occupancy_type, Reported by is reporter_name, Contact telephone is
reporter_phone, Business interruption expected is business_interruption.
reporter_name and reporter_phone are the person who reported the loss.
third_party_involved is Yes or No as printed. loss_description is the short
narrative as printed.
""" + "Field list: " + ", ".join(FIELDS))


class Reading(BaseModel):
    field: FieldName
    doc: DocName
    value: Optional[str]
    line_ids: list[str]


class Readings(BaseModel):
    readings: list[Reading]


def rows_text(ocr):
    """Group OCR lines that share a baseline into rows, left to right."""
    out = []
    for page in ocr["pages"]:
        lines = page["lines"]
        if not lines:
            continue
        tol = 0.6 * statistics.median(l["box"][3] - l["box"][1] for l in lines)
        rows = []
        for l in sorted(lines, key=lambda l: l["box"][1] + l["box"][3]):
            yc = (l["box"][1] + l["box"][3]) / 2
            if rows and abs(yc - rows[-1][0]) <= tol:
                rows[-1][1].append(l)
                rows[-1][0] = statistics.mean(
                    (m["box"][1] + m["box"][3]) / 2 for m in rows[-1][1]
                )
            else:
                rows.append([yc, [l]])
        for _, items in rows:
            items.sort(key=lambda l: l["box"][0])
            out.append("  |  ".join(f"[{l['id']}] {l['text']}" for l in items))
    return "\n".join(out)


def load_ocr(bucket, claim):
    return {
        doc: json.loads(bucket.blob(
            f"{config.OCR_PREFIX}{claim}/{claim}_{doc}.json").download_as_text())
        for doc in DOCS
    }


def extract_claim(bucket, client, claim):
    ocr = load_ocr(bucket, claim)
    prompt = "\n\n".join(
        f"=== DOCUMENT: {doc} ===\n{rows_text(ocr[doc])}" for doc in DOCS
    )
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Readings,
        ),
    )
    readings = [r.model_dump() for r in Readings.model_validate_json(resp.text).readings]
    line_text = {
        doc: {l["id"]: l["text"] for p in o["pages"] for l in p["lines"]}
        for doc, o in ocr.items()
    }
    u = resp.usage_metadata
    tokens_in = u.prompt_token_count or 0
    tokens_out = (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", None) or 0)
    payload = {
        "claim_ref": claim,
        "model": config.GEMINI_MODEL,
        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
        "cost_usd": round((tokens_in * PRICE_IN + tokens_out * PRICE_OUT) / 1e6, 6),
        "readings": readings,
        "fields": resolve(readings, line_text),
    }
    bucket.blob(f"{EXTRACT_PREFIX}{claim}.json").upload_from_string(
        json.dumps(payload, indent=2), content_type="application/json"
    )
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", nargs="+", default=["CLM-2026-0001"])
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    client = genai.Client(
        vertexai=True, project=config.PROJECT_ID, location=config.GEMINI_LOCATION
    )
    total = 0.0
    for claim in args.claim:
        p = extract_claim(bucket, client, claim)
        total += p["cost_usd"]
        flagged = [f for f in p["fields"].values() if f["status"] != "ok"]
        stated = sum(1 for r in p["readings"] if r["value"])
        print(f"{claim}: {len(p['readings'])} entries ({stated} stated), "
              f"{len(flagged)} fields not ok, ${p['cost_usd']:.5f}")
        for f in flagged:
            extra = "; ".join(f"{c['doc']}={c['value']}" for c in f["conflicts"])
            print(f"    {f['field']:<26} {f['status']:<10} {str(f['value'])[:30]:<30} {extra}")
    print(f"total cost: ${total:.5f}")


if __name__ == "__main__":
    main()
