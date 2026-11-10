import pytest
from fastapi.testclient import TestClient

from app import data, main
from app.tests.test_briefing import f, record

client = TestClient(main.app)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def fake_data(monkeypatch):
    rec = record()
    rec.update({"review_required": False, "cost": {"total_usd": 0.0079},
                "timings": {"total_seconds": 17.5}, "status": "briefing_ready"})
    flagged = record(building_damage_estimate=f("£141,250", 141250, status="conflict",
                     conflicts=[{"doc": "fnol_form", "value": "£180,600", "line_ids": []}]))
    flagged.update({"claim_id": "CLM-2026-0015", "review_required": True})
    store = {"CLM-2026-0001": rec, "CLM-2026-0015": flagged}
    monkeypatch.setattr(data, "get_claim", lambda cid: store.get(cid))
    monkeypatch.setattr(data, "list_claims", lambda: list(store.values()))
    monkeypatch.setattr(data, "get_live_enabled", lambda: True)
    monkeypatch.setattr(data, "get_page_png",
                        lambda cid, doc, page: PNG if (cid, doc, page) == ("CLM-2026-0001", "fnol_form", 1) else None)


def test_health():
    assert client.get("/healthz").json() == {"status": "ok"}


def test_config_reports_the_live_flag():
    assert client.get("/api/config").json() == {"live_enabled": True}


def test_claim_list_is_sorted_and_summarised():
    rows = client.get("/api/claims").json()
    assert [r["claim_id"] for r in rows] == ["CLM-2026-0001", "CLM-2026-0015"]
    assert rows[0]["insured"] == "Thornbury Electrical Supplies Limited"
    assert rows[0]["building_damage"] == 235000 and rows[0]["pipeline_seconds"] == 17.5
    assert rows[1]["review_required"] is True and rows[1]["flags"][0]["field"] == "building_damage_estimate"


def test_claim_detail_returns_record_and_briefing():
    body = client.get("/api/claims/CLM-2026-0015").json()
    assert body["record"]["claim_id"] == "CLM-2026-0015"
    assert body["briefing"]["review_required"] is True and body["briefing"]["attention"]


@pytest.mark.parametrize("claim_id", ["CLM-2026-9999", "nonsense", "CLM-2026-00011"])
def test_unknown_or_malformed_claim_is_404(claim_id):
    assert client.get(f"/api/claims/{claim_id}").status_code == 404


def test_page_image_is_served_as_png_with_caching():
    r = client.get("/api/pages/CLM-2026-0001/fnol_form/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers["cache-control"] and r.content == PNG


@pytest.mark.parametrize("path", [
    "/api/pages/CLM-2026-0001/fnol_form/2",
    "/api/pages/CLM-2026-0001/secrets/1",
    "/api/pages/CLM-2026-0001/fnol_form/0",
    "/api/pages/../etc/passwd/loss_report/1",
])
def test_bad_page_requests_are_rejected(path):
    assert client.get(path).status_code in (404, 422)


def test_launch_page_and_assets_are_served():
    home = client.get("/")
    assert home.status_code == 200 and "text/html" in home.headers["content-type"]
    assert "Vantage" in home.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert "raosiddharthp.github.io" in home.headers["content-security-policy"]


def test_rate_limit_returns_429_after_the_limit(monkeypatch):
    from app import main
    main._hits.clear()
    monkeypatch.setattr(main, "RATE_LIMIT", 3)
    headers = {"x-forwarded-for": "203.0.113.9"}
    codes = [client.get("/healthz", headers=headers).status_code for _ in range(2)]
    codes += [client.get("/api/config", headers=headers).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]          # non-API paths are not counted
    assert codes[2:5] == [200, 200, 200] and codes[5] == 429
    other = client.get("/api/config", headers={"x-forwarded-for": "198.51.100.4"})
    assert other.status_code == 200          # a different visitor is unaffected
    main._hits.clear()
