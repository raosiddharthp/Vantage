"""Run one claim end to end, timing every stage.

    python -m pipeline.run --claim CLM-2026-0001            # use cached OCR
    python -m pipeline.run --claim CLM-2026-0001 --force    # re-OCR for real timings

Stages: OCR (Document AI), extract (Gemini reads, code resolves), record
(Claim Intelligence Record in Firestore). The timings are stored on the record
and are what the dashboard reports as pipeline time.
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from google import genai
from google.cloud import firestore, storage

from pipeline import config
from pipeline.extract import DOCS, extract_claim, load_ocr
from pipeline.ocr import cache_name, make_docai_client, process_document
from pipeline.record import COLLECTION, build_record


def run_claim(bucket, docai, gemini, db, claim, force=False):
    files = [f"{claim}/{claim}_{d}.pdf" for d in DOCS]

    if force:
        for name in files:
            blob = bucket.blob(cache_name(name))
            if blob.exists():
                blob.delete()

    # The clock starts after the optional cache cleanup: that step is a testing
    # aid, not part of the real flow.
    started = datetime.now(timezone.utc)
    t_start = time.perf_counter()
    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(files)) as pool:
        billed = list(pool.map(lambda n: process_document(bucket, docai, n), files))
    ocr_s = time.perf_counter() - t

    t = time.perf_counter()
    payload = extract_claim(bucket, gemini, claim)
    extract_s = time.perf_counter() - t

    t = time.perf_counter()
    record = build_record(claim, payload, load_ocr(bucket, claim))
    record["started_at"] = started
    ref = db.collection(COLLECTION).document(claim)
    ref.set(record)
    record_s = time.perf_counter() - t

    timings = {
        "ocr_seconds": round(ocr_s, 2),
        "extract_seconds": round(extract_s, 2),
        "record_seconds": round(record_s, 2),
        "total_seconds": round(time.perf_counter() - t_start, 2),
        "ocr_from_cache": sum(billed) == 0,
    }
    ref.update({"timings": timings, "finished_at": datetime.now(timezone.utc)})
    record["timings"] = timings
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", required=True)
    ap.add_argument("--force", action="store_true", help="discard cached OCR first")
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    gemini = genai.Client(
        vertexai=True, project=config.PROJECT_ID, location=config.GEMINI_LOCATION
    )
    rec = run_claim(bucket, make_docai_client(), gemini,
                    firestore.Client(project=config.PROJECT_ID), args.claim, args.force)
    tm = rec["timings"]
    flagged = ", ".join(f"{f['field']}:{f['type']}" for f in rec["flags"]) or "none"
    print(f"{args.claim}: briefing_ready in {tm['total_seconds']}s "
          f"(ocr {tm['ocr_seconds']}s{' cached' if tm['ocr_from_cache'] else ''}, "
          f"extract {tm['extract_seconds']}s, record {tm['record_seconds']}s)")
    print(f"flags: {flagged} | cost ${rec['cost']['total_usd']:.5f}")


if __name__ == "__main__":
    main()
