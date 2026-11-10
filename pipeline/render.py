"""Render claim PDF pages to PNG so the handler view can draw evidence boxes.

OCR boxes are normalised (0 to 1) against the page, so they line up with a PNG
of any size. Images are cached under pages/ in the inbox bucket.

    python -m pipeline.render                    # whole corpus
    python -m pipeline.render --claim CLM-2026-0015
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import pymupdf
from google.cloud import storage

from pipeline import config

PAGES_PREFIX = "pages/"
ZOOM = 1.6  # about 115 dpi: sharp enough to read, small enough to load fast


def page_name(pdf_name, page_number):
    """CLM-x/CLM-x_fnol_form.pdf -> pages/CLM-x/CLM-x_fnol_form_p1.png"""
    return f"{PAGES_PREFIX}{pdf_name.removesuffix('.pdf')}_p{page_number}.png"


def render_document(bucket, pdf_name):
    """Render every page of one PDF. Returns the number of images created."""
    pdf = pymupdf.open(
        stream=bucket.blob(config.CLAIMS_PREFIX + pdf_name).download_as_bytes(),
        filetype="pdf",
    )
    created = 0
    for number, page in enumerate(pdf, start=1):
        out = bucket.blob(page_name(pdf_name, number))
        if out.exists():
            continue
        png = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).tobytes("png")
        out.upload_from_string(png, content_type="image/png")
        created += 1
    return created


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claim", help="only this claim id")
    args = ap.parse_args()
    bucket = storage.Client(project=config.PROJECT_ID).bucket(config.INBOX_BUCKET)
    manifest = json.loads(bucket.blob(config.CLAIMS_PREFIX + "manifest.json").download_as_text())
    if args.claim:
        manifest = [c for c in manifest if c["claim_id"] == args.claim]
    files = [d["file"] for c in manifest for d in c["documents"]]
    if not files:
        raise SystemExit("No matching claims in the manifest.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        created = sum(pool.map(lambda n: render_document(bucket, n), files))
    print(f"Documents: {len(files)}, page images created: {created} "
          f"({len(files) - created} already existed or had no new pages)")


if __name__ == "__main__":
    main()
