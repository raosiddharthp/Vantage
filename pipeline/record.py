"""Build the Claim Intelligence Record and write it to Firestore.

One document per claim in the `claims` collection. It holds every resolved
field with its evidence (document, page, box and text of the cited OCR
lines), the review flags, and the cost of producing it. The handler view and
the dashboard both read this record.
"""
import argparse
import json
from datetime import datetime, timezone

from google.cloud import firestore, storage

from pipeline import config
from pipeline.extract import DOCS, EXTRACT_PREFIX, load_ocr

COLLECTION = "claims"
SCHEMA_VERSION = 1
DOCAI_USD_PER_PAGE = 0.0015  # list price, Enterprise Document OCR
FLAG_STATUSES = ("missing", "conflict", "ungrounded", "unparsed")


def line_index(ocr):
    return {
        doc: {l["id"]: {"page": p["page"], "box": l["box"], "text": l["text"]}
              for p in o["pages"] for l in p["lines"]}
        for doc, o in ocr.items()
    }


def evidence_for(index, doc, line_ids):
    return [{"line_id": i, **index[doc][i]} for i in line_ids if i in index.get(doc, {})]


def build_record(claim, payload, ocr):
    index = line_index(ocr)
    resolved = payload["fields"]
    no_third_party = resolved["third_party_involved"]["canon"] is False
    fields, flags = {}, []
    for name, f in resolved.items():
        status = f["status"]
        if name == "third_party_name" and no_third_party and status == "missing":
            status = "not_applicable"
        fields[name] = {
            "value": f["value"],
            "canonical": f["canon"],
            "status": status,
            "source_doc": f["source_doc"],
            "grounded": f["grounded"],
            "agreeing_docs": f.get("agreeing_docs", 0),
            "evidence": evidence_for(index, f["source_doc"], f["line_ids"]) if f["source_doc"] else [],
            "conflicts": [
                {**c, "evidence": evidence_for(index, c["doc"], c["line_ids"])}
                for c in f["conflicts"]
            ],
            "stated_missing": f.get("stated_missing", []),
        }
        if status in FLAG_STATUSES:
            flags.append({"field": name, "type": status})
    pages = sum(o["page_count"] for o in ocr.values())
    docai_usd = round(pages * DOCAI_USD_PER_PAGE, 6)
    return {
        "claim_id": claim,
        "schema_version": SCHEMA_VERSION,
        "status": "briefing_ready",
        "processed_at": datetime.now(timezone.utc),
        "model": payload["model"],
        "documents": [
            {"type": d,
             "uri": f"gs://{config.INBOX_BUCKET}/{config.CLAIMS_PREFIX}{claim}/{claim}_{d}.pdf",
             "pages": ocr[d]["page_count"]}
            for d in DOCS
        ],
        "fields": fields,
        "flags": flags,
        "review_required": bool(flags),
        "summary": {
            "fields_total": len(fields),
            "fields_ok": sum(1 for f in fields.values() if f["status"] in ("ok", "not_applicable")),
            "flags": len(flags),
        },
        "cost": {
            "docai_pages": pages,
            "docai_usd": docai_usd,
            "gemini_usd": payload["cost_usd"],
            "tokens_in": payload["usage"]["tokens_in"],
            "tokens_out": payload["usage"]["tokens_out"],
            "total_usd": round(docai_usd + payload["cost_usd"], 6),
        },
        "timings": {},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", nargs="+", required=True)
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    db = firestore.Client(project=config.PROJECT_ID)
    for claim in args.claim:
        payload = json.loads(bucket.blob(f"{EXTRACT_PREFIX}{claim}.json").download_as_text())
        rec = build_record(claim, payload, load_ocr(bucket, claim))
        db.collection(COLLECTION).document(claim).set(rec)
        flagged = ", ".join(f"{f['field']}:{f['type']}" for f in rec["flags"]) or "none"
        print(f"{claim}: written, flags: {flagged}, cost ${rec['cost']['total_usd']:.5f}")


if __name__ == "__main__":
    main()
