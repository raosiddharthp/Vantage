"""Exercise the API against the real Firestore and bucket, without a server.

    python -m app.smoke
"""
from fastapi.testclient import TestClient

from app.main import app


def main():
    c = TestClient(app)
    print("healthz:", c.get("/healthz").json())
    print("config:", c.get("/api/config").json())
    rows = c.get("/api/claims").json()
    print(f"claims: {len(rows)} listed, {sum(r['review_required'] for r in rows)} need review")
    body = c.get("/api/claims/CLM-2026-0015").json()
    print("detail:", body["briefing"]["headline"], "| attention items:", len(body["briefing"]["attention"]))
    img = c.get("/api/pages/CLM-2026-0015/loss_report/1")
    print(f"page image: {img.status_code} {img.headers.get('content-type')} {len(img.content) // 1024} KB")
    print("unknown claim:", c.get("/api/claims/CLM-2026-9999").status_code)
    print("bad document:", c.get("/api/pages/CLM-2026-0015/secrets/1").status_code)


if __name__ == "__main__":
    main()
