import json
import sqlite3

import httpx
import pytest

from app.integrations import base
from app.integrations.rumble import parse_count


def mock(monkeypatch, handler):
    calls = []

    def wrapped(request: httpx.Request):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(wrapped)))
    return calls


def connect(auth, provider, values, **extra):
    r = auth.post("/api/integrations", json={"provider": provider, "values": values, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_providers_and_secret_masking(auth):
    keys = [p["key"] for p in auth.get("/api/integrations/providers").json()]
    assert keys == ["youtube", "facebook", "instagram", "tiktok", "square", "ebay", "tiktok_shop", "gmail", "rumble", "twitch", "google_analytics"]
    assert auth.post("/api/integrations", json={"provider": "youtube", "values": {"channel": "@x"}}).status_code == 422
    assert auth.post("/api/integrations", json={"provider": "nope", "values": {}}).status_code == 422
    i = connect(auth, "youtube", {"channel": "@x", "api_key": "SECRET123"})
    assert i["saved_secrets"] == ["api_key"] and i["config"]["max_videos"] == "100"
    assert "SECRET123" not in json.dumps(auth.get("/api/integrations").json())
    assert i["channel_id"] and auth.get("/api/channels").json()[0]["platform"] == "youtube"
    # empty secret on edit keeps the old one
    r = auth.patch(f"/api/integrations/{i['id']}", json={"values": {"api_key": "", "channel": "@y"}}).json()
    assert r["saved_secrets"] == ["api_key"] and r["config"]["channel"] == "@y"
    assert auth.delete(f"/api/integrations/{i['id']}").status_code == 204
    assert auth.get("/api/channels").json(), "channel is kept after disconnect"


def test_youtube_sync(auth, monkeypatch):
    def handler(req):
        p = req.url.path
        assert req.url.params["key"] == "K"
        if p.endswith("/channels"):
            assert req.url.params["forHandle"] == "@me"
            return httpx.Response(200, json={"items": [{"id": "UC" + "a" * 22, "snippet": {"title": "Me", "customUrl": "@me"},
                "statistics": {"subscriberCount": "1500", "viewCount": "99"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        if p.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": v}} for v in ("v1", "v2")]})
        if p.endswith("/videos"):
            return httpx.Response(200, json={"items": [
                {"id": v, "snippet": {"title": f"Video {v}", "publishedAt": "2026-10-01T12:00:00Z"},
                 "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "1"}} for v in ("v1", "v2")]})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    assert auth.post(f"/api/integrations/{i['id']}/test").json() == {"ok": True, "message": "Connected to Me (1500 subscribers)"}
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    assert r["last_result"]["posts_created"] == 2
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_result"]["posts_updated"] == 2
    posts = auth.get("/api/posts").json()
    posts = posts["items"] if isinstance(posts, dict) else posts
    assert len(posts) == 2 and posts[0]["external_source"] == "youtube" and posts[0]["views"] == 10
    assert auth.get("/api/channels").json()[0]["followers"] == 1500


def test_youtube_bad_key(auth, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(400, json={"error": {"message": "API key not valid."}}))
    i = connect(auth, "youtube", {"channel": "@me", "api_key": "bad"})
    t = auth.post(f"/api/integrations/{i['id']}/test").json()
    assert t["ok"] is False and "API key not valid" in t["message"]
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "error" and "API key not valid" in r["last_error"]


def test_facebook_sync_without_insights(auth, monkeypatch):
    def handler(req):
        p = req.url.path
        assert p.startswith("/v27.0/")
        if p == "/v27.0/42":
            return httpx.Response(200, json={"id": "42", "name": "My Page", "followers_count": 321, "link": "https://fb.com/p"})
        if p == "/v27.0/42/posts":
            return httpx.Response(200, json={"data": [{"id": "42_1", "message": "Hello\nworld",
                "created_time": "2026-10-02T10:00:00+0000", "permalink_url": "https://fb.com/1", "shares": {"count": 3},
                "reactions": {"summary": {"total_count": 7}}, "comments": {"summary": {"total_count": 2}}}]})
        if p.endswith("/insights"):
            return httpx.Response(403, json={"error": {"message": "(#10) requires read_insights"}})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "facebook", {"page_id": "42", "page_token": "T"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    assert r["last_result"]["followers"] == 321 and r["last_result"]["warnings"]
    posts = auth.get("/api/posts").json()
    posts = posts["items"] if isinstance(posts, dict) else posts
    assert posts[0]["title"] == "Hello" and posts[0]["likes"] == 7 and posts[0]["shares"] == 3


def test_square_sync(auth, monkeypatch):
    def handler(req):
        assert req.headers["Authorization"] == "Bearer SQ" and req.headers["Square-Version"]
        p = req.url.path
        if p == "/v2/locations":
            return httpx.Response(200, json={"locations": [{"id": "L1", "name": "Shop", "status": "ACTIVE"}]})
        if p == "/v2/customers":
            return httpx.Response(200, json={"customers": [{"id": "C1", "given_name": "Ann", "family_name": "Lee",
                                                              "email_address": "ann@x.com"}]})
        if p == "/v2/payments":
            return httpx.Response(200, json={"payments": [{"id": "P1", "order_id": "O1", "source_type": "CARD",
                "card_details": {"card": {"card_brand": "VISA", "last_4": "4242"}},
                "processing_fee": [{"amount_money": {"amount": 105}}], "receipt_url": "https://squareup.com/receipt/P1"}]})
        if p == "/v2/orders/search":
            body = json.loads(req.content)
            assert body["location_ids"] == ["L1"]
            assert "OPEN" in body["query"]["filter"]["state_filter"]["states"]
            return httpx.Response(200, json={"orders": [
                {"id": "O1", "location_id": "L1", "customer_id": "C1", "created_at": "2026-10-03T14:00:00Z",
                 "updated_at": "2026-10-03T15:00:00Z", "closed_at": "2026-10-03T15:00:00Z", "state": "COMPLETED",
                 "source": {"name": "Square Online"},
                 "total_money": {"amount": 2599, "currency": "USD"}, "total_tax_money": {"amount": 199},
                 "line_items": [{"name": "Hat", "variation_name": "Black", "quantity": "2",
                                 "gross_sales_money": {"amount": 2400}}],
                 "fulfillments": [{"type": "SHIPMENT", "state": "COMPLETED", "shipment_details": {"recipient": {
                     "display_name": "Ann Lee", "email_address": "ann@x.com",
                     "address": {"address_line_1": "1 Main St", "locality": "Wadena"}}, "tracking_number": "1Z", "carrier": "UPS"}}]},
                {"id": "O2", "location_id": "L1", "created_at": "2026-10-04T15:00:00Z", "state": "COMPLETED",
                 "closed_at": "2026-10-04T15:00:00Z", "total_money": {"amount": 1000},
                 "return_amounts": {"total_money": {"amount": 1000}}, "line_items": [{"name": "Mug", "quantity": "1"}]},
                {"id": "O3", "location_id": "L1", "created_at": "2026-10-05T15:00:00Z", "state": "OPEN",
                 "total_money": {"amount": 500}, "line_items": [{"name": "Sticker", "quantity": "1"}],
                 "fulfillments": [{"type": "PICKUP", "state": "PROPOSED", "pickup_details": {"recipient": {
                     "display_name": "Bob Ray", "email_address": "bob@x.com"}}}]},
            ]})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "square", {"access_token": "SQ"})
    assert auth.post(f"/api/integrations/{i['id']}/test").json()["ok"] is True
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    assert r["last_result"]["revenue_synced"] == 30.99 and r["last_result"]["orders_created"] == 3
    auth.post(f"/api/integrations/{i['id']}/sync")
    deals = auth.get("/api/deals").json()
    deals = deals["items"] if isinstance(deals, dict) else deals
    assert len(deals) == 3
    by = {d["external_id"]: d for d in deals}
    assert by["O1"]["status"] == "won" and by["O1"]["value"] == 25.99 and by["O1"]["contact_id"]
    assert by["O2"]["status"] == "lost" and by["O3"]["status"] == "open"
    assert any(f["name"] == "Square Sales" for f in auth.get("/api/funnels").json())
    contacts = {c["email"]: c for c in auth.get("/api/contacts").json()["items"]}
    assert contacts["ann@x.com"]["external_source"] == "square" and "bob@x.com" in contacts  # online buyer became a contact

    orders = auth.get("/api/orders").json()
    assert orders["total"] == 3 and orders["summary"]["refunded"] == 10.0 and orders["summary"]["fees"] == 1.05
    o1 = next(o for o in orders["items"] if o["external_id"] == "O1")
    assert o1["payment_summary"] == "Visa ••4242" and o1["fulfillment_type"] == "SHIPMENT"
    assert o1["customer_name"] == "Ann Lee" and o1["items_summary"] == "Hat (Black) ×2" and o1["tax_total"] == 1.99
    assert o1["source_name"] == "Square Online" and o1["location_name"] == "Shop"
    d = auth.get(f"/api/orders/{o1['id']}").json()
    assert d["raw"]["fulfillments"][0]["shipment_details"]["tracking_number"] == "1Z" and d["payments"][0]["id"] == "P1"
    assert auth.get("/api/orders", params={"state": "open"}).json()["total"] == 1
    assert auth.get("/api/orders", params={"q": "sticker"}).json()["items"][0]["external_id"] == "O3"
    assert auth.get("/api/orders/export.csv").text.startswith("id,source,external_id")


def test_rumble_api_and_page_fallback(auth, monkeypatch):
    def handler(req):
        if req.url.path == "/-livestream-api/get-data":
            return httpx.Response(200, json={"username": "me", "followers": {"num_followers": 50, "num_followers_total": 60},
                "subscribers": {"num_subscribers": 4}, "livestreams": [{"id": "abc", "title": "Live!",
                "created_on": "2026-10-05T01:00:00+00:00", "likes": 5, "watching_now": 9}]})
        if req.url.path == "/c/Me":
            return httpx.Response(200, text="<div><span>3.67M Followers</span></div>")
        return httpx.Response(404)

    mock(monkeypatch, handler)
    a = connect(auth, "rumble", {"api_url": "https://rumble.com/-livestream-api/get-data?key=k"})
    r = auth.post(f"/api/integrations/{a['id']}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["followers"] == 60 and r["last_result"]["subscribers"] == 4
    b = connect(auth, "rumble", {"channel_url": "https://rumble.com/c/Me"}, name="Rumble page")
    r = auth.post(f"/api/integrations/{b['id']}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["followers"] == 3_670_000
    assert parse_count("1,234") == 1234 and parse_count("12.5K") == 12500


def test_rumble_blocked(auth, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(403, text="cf"))
    i = connect(auth, "rumble", {"channel_url": "https://rumble.com/c/Me"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "error" and "Send to CRM" in r["last_error"]


def test_migration_adds_columns(tmp_path):
    from sqlalchemy import create_engine, inspect

    from app.migrate import run_migrations
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE contacts (id INTEGER PRIMARY KEY, first_name VARCHAR(80))")
    con.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title VARCHAR(200))")
    con.execute("INSERT INTO contacts (first_name) VALUES ('Old')")
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{db}")
    run_migrations(eng)
    run_migrations(eng)  # idempotent
    cols = {c["name"] for c in inspect(eng).get_columns("contacts")}
    assert {"external_source", "external_id"} <= cols
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT external_source FROM contacts").scalar() == ""


def test_instagram_sync(auth, monkeypatch):
    def handler(req):
        p = req.url.path
        if p == "/v27.0/42":
            return httpx.Response(200, json={"id": "42", "instagram_business_account": {"id": "1784"}})
        if p == "/v27.0/1784":
            return httpx.Response(200, json={"id": "1784", "username": "theforge_sports", "followers_count": 812})
        if p == "/v27.0/1784/media":
            if "view_count" in req.url.params["fields"]:
                return httpx.Response(400, json={"error": {"message": "nonexisting field view_count"}})
            return httpx.Response(200, json={"data": [{"id": "m1", "caption": "Reel!", "media_type": "VIDEO",
                "permalink": "https://instagram.com/p/x", "timestamp": "2026-10-06T10:00:00+0000",
                "like_count": 30, "comments_count": 4}]})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "instagram", {"page_id": "42", "page_token": "T"})
    assert "@theforge_sports" in auth.post(f"/api/integrations/{i['id']}/test").json()["message"]
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    assert r["last_result"]["followers"] == 812 and r["last_result"]["posts_created"] == 1


def test_instagram_not_linked(auth, monkeypatch):
    mock(monkeypatch, lambda req: httpx.Response(200, json={"id": "42"}))
    i = connect(auth, "instagram", {"page_id": "42", "page_token": "T"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "error" and "professional Instagram" in r["last_error"]


def test_twitch_sync(auth, monkeypatch):
    def handler(req):
        if req.url.host == "id.twitch.tv":
            assert b"client_credentials" in req.content
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 5000})
        assert req.headers["Client-Id"] == "CID" and req.headers["Authorization"] == "Bearer APP"
        p = req.url.path
        if p == "/helix/users":
            assert req.url.params["login"] == "theforge_sports"
            return httpx.Response(200, json={"data": [{"id": "99", "login": "theforge_sports", "display_name": "TheForge"}]})
        if p == "/helix/channels/followers":
            return httpx.Response(200, json={"total": 250, "data": []})
        if p == "/helix/streams":
            return httpx.Response(200, json={"data": [{"viewer_count": 17}]})
        if p == "/helix/videos":
            return httpx.Response(200, json={"data": [{"id": "v9", "title": "Stream", "url": "https://twitch.tv/videos/v9",
                "published_at": "2026-10-07T00:00:00Z", "view_count": 88}], "pagination": {}})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "twitch", {"login": "https://www.twitch.tv/TheForge_sports", "client_id": "CID", "client_secret": "S"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    assert r["last_result"]["followers"] == 250 and r["last_result"]["live_viewers"] == 17
    assert r["last_result"]["posts_created"] == 1
