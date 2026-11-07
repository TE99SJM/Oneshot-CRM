import json
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.database import SessionLocal
from app.integrations import base, google_analytics as ga
from app.models import Integration


@pytest.fixture()
def service_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return {"type": "service_account", "client_email": "reporter@test.iam.gserviceaccount.com", "private_key": pem,
            "token_uri": "https://untrusted.example/token"}


@pytest.fixture(autouse=True)
def clear_cache():
    ga._cache.clear()
    yield
    ga._cache.clear()


def connect(auth, service_key, name="First site", host="example.com", property_id="12345"):
    r = auth.post("/api/integrations", json={"provider": "google_analytics", "name": name,
        "values": {"hostname": host, "property_id": property_id, "service_account": json.dumps(service_key)}})
    assert r.status_code == 201, r.text
    return r.json()


def mock(monkeypatch, handler):
    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))


def result(visitors=42, visits=60, views=90, **meta):
    return {"metricHeaders": [{"name": m} for m in ga.METRICS], "rowCount": 1,
            "rows": [{"metricValues": [{"value": str(n)} for n in [visitors, visits, views]]}],
            "metadata": {"timeZone": "America/Chicago", **meta}}


def test_two_sites_use_separate_host_filters_and_selected_period(auth, monkeypatch, service_key):
    a = connect(auth, service_key, host="https://www.example.com/")
    b = connect(auth, service_key, "Second site", "second.example.com")
    reports = []

    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            claims = jwt.decode(parse_qs(req.content.decode())["assertion"][0], options={"verify_signature": False})
            assert claims["scope"] == "https://www.googleapis.com/auth/analytics.readonly"
            assert claims["aud"] == ga.TOKEN_URL
            return httpx.Response(200, json={"access_token": "TEST_ACCESS_TOKEN"})
        assert req.url.host == "analyticsdata.googleapis.com"
        assert req.headers["authorization"] == "Bearer TEST_ACCESS_TOKEN"
        data = json.loads(req.content)
        reports.append(data)
        assert data["dateRanges"] == [{"startDate": "2026-10-01", "endDate": "2026-10-31"}]
        assert not data.get("dimensions"), "Do not sum daily unique visitors"
        hosts = data["dimensionFilter"]["filter"]["inListFilter"]["values"]
        assert hosts in [["example.com", "www.example.com"], ["second.example.com", "www.second.example.com"]]
        return httpx.Response(200, json=result(42 if hosts[0] == "example.com" else 7))

    mock(monkeypatch, handler)
    for site, count in [(a, 42), (b, 7)]:
        r = auth.get(f"/api/dashboard/site-visitors/{site['id']}?start=2026-10-01&end=2026-10-31")
        assert r.status_code == 200, r.text
        assert r.json()["visitors"] == count
        assert r.json()["timezone"] == "America/Chicago"
    # Same range reuses the cached totals, without conflating the two sites.
    assert auth.get(f"/api/dashboard/site-visitors/{a['id']}?start=2026-10-01&end=2026-10-31").json()["visitors"] == 42
    assert len(reports) == 2
    assert len(auth.get("/api/dashboard/site-visitors").json()) == 2
    kpis = auth.get("/api/dashboard").json()["kpis"]
    assert kpis["followers"] == 0 and kpis["views"] == 0
    assert auth.get("/api/posts").json() == []
    with SessionLocal() as db:
        stored = db.get(Integration, a["id"]).secrets
        assert "PRIVATE KEY" not in stored
    assert "PRIVATE KEY" not in auth.get("/api/integrations").text


def test_zero_is_distinct_from_unavailable_and_errors_are_safe(auth, monkeypatch, service_key):
    site = connect(auth, service_key)
    state = {"error": False}

    def handler(req):
        if state["error"]:
            return httpx.Response(403, json={"error": {"message": service_key["private_key"]}})
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "T"})
        return httpx.Response(200, json={"metricHeaders": [{"name": m} for m in ga.METRICS], "rowCount": 0})

    mock(monkeypatch, handler)
    url = f"/api/dashboard/site-visitors/{site['id']}?start=2026-10-01&end=2026-10-31"
    r = auth.get(url).json()
    assert r["visitors"] == 0 and not r["stale"]
    state["error"] = True
    r = auth.get(url + "&refresh=true")
    assert r.json()["stale"] and r.json()["error"]
    assert "PRIVATE KEY" not in r.text
    # No cached result for a different period: error, never invented zero totals.
    r = auth.get(f"/api/dashboard/site-visitors/{site['id']}?start=2026-09-01&end=2026-09-30")
    assert r.status_code == 502 and "visitors" not in r.json()


def test_changing_site_configuration_does_not_reuse_old_totals(auth, monkeypatch, service_key):
    site = connect(auth, service_key)
    def handler(req):
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "T"})
        return httpx.Response(200, json=result(100 if "/12345:" in req.url.path else 5))
    mock(monkeypatch, handler)
    url = f"/api/dashboard/site-visitors/{site['id']}"
    assert auth.get(url).json()["visitors"] == 100
    assert auth.patch(f"/api/integrations/{site['id']}", json={"values": {"property_id": "56789", "service_account": ""}}).status_code == 200
    assert auth.get(url).json()["visitors"] == 5
    auth.patch(f"/api/integrations/{site['id']}", json={"enabled": False})
    assert auth.get(url).status_code == 409
    assert auth.get("/api/dashboard/site-visitors").json()[0]["enabled"] is False
    auth.delete(f"/api/integrations/{site['id']}")
    assert auth.get("/api/dashboard/site-visitors").json() == []
    assert auth.get(url).status_code == 404


@pytest.mark.parametrize("values", [
    {"property_id": "G-TRACKING"}, {"hostname": "example.com/a-page"}, {"hostname": "https://me:secret@example.com"},
    {"hostname": "example.com:123"}, {"service_account": '{"installed": {"client_secret": "SECRET"}}'},
    {"service_account": "invalid JSON SECRET"},
])
def test_validation(auth, service_key, values):
    r = auth.post("/api/integrations", json={"provider": "google_analytics", "values": {
        "hostname": "example.com", "property_id": "12345", "service_account": json.dumps(service_key), **values}})
    assert r.status_code == 422
    assert "SECRET" not in r.text and "PRIVATE KEY" not in r.text


def test_auth_range_validation_and_unrelated_integrations(client, auth, service_key):
    site = connect(auth, service_key)
    url = f"/api/dashboard/site-visitors/{site['id']}"
    assert auth.get(url + "?start=2026-10-02&end=2026-10-01").status_code == 422
    assert auth.get(url + "?start=garbage").status_code == 422
    square = auth.post("/api/integrations", json={"provider": "square", "values": {"access_token": "TOKEN"}}).json()
    assert auth.get(f"/api/dashboard/site-visitors/{square['id']}").status_code == 404
    assert len(auth.get("/api/dashboard/site-visitors").json()) == 1
    client.headers.pop("Authorization")
    assert client.get("/api/dashboard/site-visitors").status_code == 401
    assert client.get(url).status_code == 401


def test_sync_and_metadata_warning(auth, monkeypatch, service_key):
    site = connect(auth, service_key)
    def handler(req):
        return httpx.Response(200, json={"access_token": "T"} if req.url.host == "oauth2.googleapis.com"
                              else result(subjectToThresholding=True))
    mock(monkeypatch, handler)
    assert auth.post(f"/api/integrations/{site['id']}/test").json()["ok"]
    r = auth.post(f"/api/integrations/{site['id']}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["site_visitors_30d"] == 42
    assert r["last_result"]["warnings"]


def test_malformed_google_response_is_not_reported_as_zero(auth, monkeypatch, service_key):
    site = connect(auth, service_key)
    mock(monkeypatch, lambda req: httpx.Response(200, json={"access_token": "T"} if req.url.host == "oauth2.googleapis.com" else {}))
    r = auth.get(f"/api/dashboard/site-visitors/{site['id']}")
    assert r.status_code == 502
