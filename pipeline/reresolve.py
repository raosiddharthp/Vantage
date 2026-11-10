"""Re-apply the resolution rules to cached readings (no Gemini call, no cost)."""
import argparse
import json

from google.cloud import storage

from pipeline import config
from pipeline.extract import EXTRACT_PREFIX, load_ocr
from pipeline.resolve import resolve


def reresolve(bucket, claim):
    blob = bucket.blob(f"{EXTRACT_PREFIX}{claim}.json")
    payload = json.loads(blob.download_as_text())
    line_text = {
        doc: {l["id"]: l["text"] for p in o["pages"] for l in p["lines"]}
        for doc, o in load_ocr(bucket, claim).items()
    }
    payload["fields"] = resolve(payload["readings"], line_text)
    blob.upload_from_string(json.dumps(payload, indent=2), content_type="application/json")
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", nargs="+", required=True)
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    for claim in args.claim:
        p = reresolve(bucket, claim)
        flagged = sum(1 for f in p["fields"].values() if f["status"] != "ok")
        print(f"{claim}: re-resolved, {flagged} fields not ok")


if __name__ == "__main__":
    main()
