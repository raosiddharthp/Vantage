"""Document AI OCR step.

Turns each claim PDF into numbered lines with confidence and page coordinates,
and caches the result in the inbox bucket under ocr/ so a document is only ever
OCR-ed (and billed) once.

    python -m pipeline.ocr --limit 3            # first 3 claims
    python -m pipeline.ocr --claim CLM-2026-0002
    python -m pipeline.ocr                      # whole corpus
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from google.api_core import exceptions as gexc
from google.api_core.client_options import ClientOptions
from google.cloud import documentai, storage

from pipeline import config

LIST_PRICE_PER_PAGE = 1.50 / 1000  # USD, Enterprise Document OCR (first 1,000 pages/month may be free)
RETRYABLE = (gexc.ServiceUnavailable, gexc.DeadlineExceeded, gexc.ResourceExhausted,
             gexc.InternalServerError)


def make_docai_client():
    endpoint = f"{config.DOCAI_LOCATION}-documentai.googleapis.com"
    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=endpoint))


def processor_name():
    return (f"projects/{config.PROJECT_ID}/locations/{config.DOCAI_LOCATION}"
            f"/processors/{config.DOCAI_PROCESSOR_ID}")


def _segments_text(text, anchor):
    parts = [text[int(s.start_index):int(s.end_index)] for s in anchor.text_segments]
    return " ".join("".join(parts).split())


def _box(poly):
    xs = [v.x for v in poly.normalized_vertices]
    ys = [v.y for v in poly.normalized_vertices]
    if not xs:
        return None
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


def document_to_lines(document):
    """Normalise a Document AI result into numbered lines per page."""
    pages = []
    for page in document.pages:
        number = int(page.page_number) or len(pages) + 1
        lines = []
        for index, line in enumerate(page.lines, start=1):
            text = _segments_text(document.text, line.layout.text_anchor)
            if not text:
                continue
            lines.append({
                "id": f"p{number}-l{index}",
                "text": text,
                "confidence": round(float(line.layout.confidence), 4),
                "box": _box(line.layout.bounding_poly),
            })
        pages.append({"page": number,
                      "width": page.dimension.width or None,
                      "height": page.dimension.height or None,
                      "lines": lines})
    return {"page_count": len(pages), "pages": pages}


def ocr_pdf(client, pdf_bytes):
    request = documentai.ProcessRequest(
        name=processor_name(),
        raw_document=documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf"))
    for attempt in range(4):
        try:
            return document_to_lines(client.process_document(request=request).document)
        except RETRYABLE:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def cache_name(pdf_name):
    """claims-relative PDF path -> cache object name under ocr/."""
    return config.OCR_PREFIX + pdf_name.removesuffix(".pdf") + ".json"


def process_document(bucket, client, pdf_name):
    """OCR one document unless a cached result exists. Returns pages billed (0 if cached)."""
    out = bucket.blob(cache_name(pdf_name))
    if out.exists():
        return 0
    pdf_bytes = bucket.blob(config.CLAIMS_PREFIX + pdf_name).download_as_bytes()
    result = ocr_pdf(client, pdf_bytes)
    result["source"] = pdf_name
    out.upload_from_string(json.dumps(result), content_type="application/json")
    return result["page_count"]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only the first N claims")
    parser.add_argument("--claim", help="only this claim id, e.g. CLM-2026-0002")
    args = parser.parse_args()

    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    manifest = json.loads(bucket.blob(config.CLAIMS_PREFIX + "manifest.json").download_as_text())
    if args.claim:
        manifest = [c for c in manifest if c["claim_id"] == args.claim]
    if args.limit:
        manifest = manifest[:args.limit]
    files = [d["file"] for c in manifest for d in c["documents"]]
    if not files:
        raise SystemExit("No matching claims in the manifest.")

    client = make_docai_client()
    with ThreadPoolExecutor(max_workers=4) as pool:
        billed = list(pool.map(lambda name: process_document(bucket, client, name), files))

    pages = sum(billed)
    cached = sum(1 for b in billed if b == 0)
    print(f"Documents: {len(files)} ({len(files) - cached} OCR-ed, {cached} already cached)")
    print(f"Pages sent to Document AI this run: {pages}")
    print(f"Estimated list-price cost: ${pages * LIST_PRICE_PER_PAGE:.4f} "
          "(the first 1,000 pages per month may be free)")


if __name__ == "__main__":
    main()
