"""Read access to claim records, page images and the live flag.

Results are cached in memory for a short time, so a visitor refreshing the page
repeatedly (or a crowd of them) costs almost no Firestore reads or bandwidth.
"""
import time
from functools import lru_cache

from google.cloud import firestore, storage

from app import settings

_cache = {}


def _cached(key, loader, ttl=60):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


@lru_cache(maxsize=1)
def _db():
    return firestore.Client(project=settings.PROJECT_ID)


@lru_cache(maxsize=1)
def _bucket():
    return storage.Client(project=settings.PROJECT_ID).bucket(settings.INBOX_BUCKET)


def get_claim(claim_id):
    return _cached(("claim", claim_id),
                   lambda: _db().collection("claims").document(claim_id).get().to_dict())


def list_claims():
    return _cached(("claims",),
                   lambda: [d.to_dict() for d in _db().collection("claims").stream()])


def get_live_enabled():
    """Fails closed: a missing flag document means live mode is off."""
    def load():
        doc = _db().collection("config").document("demo").get().to_dict() or {}
        return bool(doc.get("live_enabled", False))
    return _cached(("live",), load, ttl=15)


def get_page_png(claim_id, doc, page):
    def load():
        blob = _bucket().blob(f"{settings.PAGES_PREFIX}{claim_id}/{claim_id}_{doc}_p{page}.png")
        return blob.download_as_bytes() if blob.exists() else None
    return _cached(("png", claim_id, doc, page), load, ttl=3600)
