"""Vantage API: claim records, handler briefings and page images."""
import re
from pathlib import Path as FilePath

from fastapi import FastAPI, HTTPException, Path, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import data
from app.briefing import build_briefing

app = FastAPI(title="Vantage", version="0.1.0")

CLAIM_ID = re.compile(r"^CLM-2026-\d{4}$")
DOCS = ("fnol_form", "loss_report", "repair_estimate")
STATIC = FilePath(__file__).parent / "static"


def _value(record, name, key="value"):
    return (record.get("fields", {}).get(name) or {}).get(key)


def summarise(record):
    return {
        "claim_id": record["claim_id"],
        "insured": _value(record, "insured_name"),
        "cause": _value(record, "cause_of_loss"),
        "date_of_loss": _value(record, "date_of_loss", "canonical"),
        "building_damage": _value(record, "building_damage_estimate", "canonical"),
        "contents_damage": _value(record, "contents_damage_estimate", "canonical"),
        "flags": record.get("flags", []),
        "review_required": record.get("review_required", False),
        "cost_usd": (record.get("cost") or {}).get("total_usd"),
        "pipeline_seconds": (record.get("timings") or {}).get("total_seconds"),
        "status": record.get("status"),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {"live_enabled": data.get_live_enabled()}


@app.get("/api/claims")
def claims():
    return sorted((summarise(r) for r in data.list_claims()), key=lambda c: c["claim_id"])


@app.get("/api/claims/{claim_id}")
def claim(claim_id: str):
    record = data.get_claim(claim_id) if CLAIM_ID.match(claim_id) else None
    if record is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return {"record": record, "briefing": build_briefing(record)}


@app.get("/api/pages/{claim_id}/{doc}/{page}")
def page_image(claim_id: str, doc: str, page: int = Path(ge=1, le=9)):
    png = data.get_page_png(claim_id, doc, page) if CLAIM_ID.match(claim_id) and doc in DOCS else None
    if png is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "launch.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def allow_design_doc_embed(request, call_next):
    """Only the design doc site may frame the app."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://raosiddharthp.github.io"
    return response


# Per-visitor limit on API calls. One instance serves the demo, so a simple in-memory count is enough.
import time
from collections import defaultdict, deque

from fastapi.responses import JSONResponse

RATE_LIMIT = 240      # requests
RATE_WINDOW = 60.0    # seconds
_hits = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request, call_next):
    if request.url.path.startswith("/api/"):
        # Cloud Run appends the caller's address last in X-Forwarded-For.
        forwarded = request.headers.get("x-forwarded-for", "")
        who = forwarded.split(",")[-1].strip() or (request.client.host if request.client else "unknown")
        now = time.monotonic()
        window = _hits[who]
        while window and now - window[0] > RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_LIMIT:
            return JSONResponse({"detail": "Too many requests. Wait a minute and try again."},
                                status_code=429, headers={"Retry-After": "60"})
        window.append(now)
        if len(_hits) > 5000:
            for key in [k for k, v in _hits.items() if not v]:
                del _hits[key]
    return await call_next(request)
