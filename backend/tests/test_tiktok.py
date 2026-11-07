"""TikTok (sign-in, stats, posting) and TikTok Shop (orders, chats, shipping) against mock TikTok APIs."""
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx

from app.database import SessionLocal
from app.integrations import base, tiktok_shop
from app.models import Conversation, Order
from app.publishing import common, runner, tiktok as ttpub

NOW = int(time.time())
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 7000


class FakeTikTok:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.uploaded = b""
        self.refreshes = 0
        self.init_body: dict = {}
        self.sent: list[dict] = []
        self.packages: list[dict] = []
        self.signs_ok = True
        self.cs_approved = True
        self.cs_calls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        host, path = req.url.host, req.url.path
        # ---------------- TikTok (open.tiktokapis.com)
        if host == "open.tiktokapis.com":
            if path == "/v2/oauth/token/":
                f = dict(httpx.QueryParams(req.read().decode()))
                assert f["client_key"] == "ck" and f["client_secret"] == "cs"
                if f["grant_type"] == "authorization_code":
                    assert f["code"] == "TTCODE" and f["redirect_uri"].endswith("/api/oauth/tiktok/callback")
                    return httpx.Response(200, json={"access_token": "TAT", "refresh_token": "TRT", "expires_in": 86400,
                                                     "open_id": "OID", "scope": "user.info.basic,video.list,video.publish"})
                self.refreshes += 1
                assert f["refresh_token"] == "TRT"
                return httpx.Response(200, json={"access_token": "TAT2", "refresh_token": "TRT", "expires_in": 86400})
            assert req.headers["authorization"].startswith("Bearer TAT")
            ok = {"error": {"code": "ok", "message": ""}}
            if path == "/v2/user/info/":
                return httpx.Response(200, json={**ok, "data": {"user": {
                    "open_id": "OID", "display_name": "Gaming Outdoorsmen", "username": "gamingoutdoorsmen",
                    "profile_deep_link": "https://www.tiktok.com/@gamingoutdoorsmen", "follower_count": 1234,
                    "following_count": 50, "likes_count": 9000, "video_count": 2}}})
            if path == "/v2/video/list/":
                body = json.loads(req.read())
                if not body.get("cursor"):
                    return httpx.Response(200, json={**ok, "data": {"has_more": True, "cursor": 111, "videos": [
                        {"id": "v1", "title": "Duck hunt", "create_time": NOW - 86400, "share_url": "https://t/v1",
                         "view_count": 5000, "like_count": 300, "comment_count": 12, "share_count": 4}]}})
                return httpx.Response(200, json={**ok, "data": {"has_more": False, "videos": [
                    {"id": "v2", "video_description": "Deer camp\nmore", "create_time": NOW - 3600,
                     "view_count": 700, "like_count": 20}]}})
            if path == "/v2/post/publish/creator_info/query/":
                return httpx.Response(200, json={**ok, "data": {
                    "creator_nickname": "Gaming Outdoorsmen", "creator_username": "gamingoutdoorsmen",
                    "privacy_level_options": ["SELF_ONLY"], "comment_disabled": False, "duet_disabled": True,
                    "stitch_disabled": False, "max_video_post_duration_sec": 600}})
            if path == "/v2/post/publish/video/init/":
                self.init_body = json.loads(req.read())
                return httpx.Response(200, json={**ok, "data": {"publish_id": "p1",
                                                                "upload_url": "https://open-upload.tiktokapis.com/up/1"}})
            if path == "/v2/post/publish/status/fetch/":
                return httpx.Response(200, json={**ok, "data": {"status": "PUBLISH_COMPLETE",
                                                                "publicaly_available_post_id": [7300000000001]}})
        if host == "open-upload.tiktokapis.com":
            rng = req.headers["content-range"]
            assert rng == f"bytes 0-{len(VIDEO) - 1}/{len(VIDEO)}"
            self.uploaded += req.read()
            return httpx.Response(201)
        # ---------------- TikTok Shop
        if host == "auth.tiktok-shops.com":
            q = req.url.params
            assert q["app_key"] == "ak" and q["app_secret"] == "as"
            if path == "/api/v2/token/get":
                assert q["auth_code"] == "SHOPCODE" and q["grant_type"] == "authorized_code"
            return httpx.Response(200, json={"code": 0, "data": {"access_token": "SAT", "refresh_token": "SRT",
                                                                 "access_token_expire_in": NOW + 7 * 86400,
                                                                 "seller_name": "The Forge"}})
        if host == "open-api.tiktokglobalshop.com":
            q = dict(req.url.params)
            raw = req.read()
            assert q["sign"] == tiktok_shop.sign(path, q, raw, "as"), "bad signature"
            assert req.headers["x-tts-access-token"] == "SAT"
            if path == "/authorization/202309/shops":
                return httpx.Response(200, json={"code": 0, "data": {"shops": [
                    {"id": "7001", "name": "The Forge Shop", "region": "US", "cipher": "CIPHER1"}]}})
            assert q.get("shop_cipher") == "CIPHER1"
            if path.startswith("/customer_service/"):
                self.cs_calls += 1
                if not self.cs_approved:
                    return httpx.Response(200, json={"code": 105005, "message": "Access denied: scope not authorized"})
            if path == "/order/202309/orders/search":
                return httpx.Response(200, json={"code": 0, "data": {"orders": [
                    {"id": "576001", "status": "AWAITING_SHIPMENT", "user_id": "buyer9", "create_time": NOW - 7200,
                     "update_time": NOW - 3600, "buyer_email": "x1@scs.tiktokw.us", "shipping_type": "SELLER",
                     "delivery_option_id": "DO1", "fulfillment_type": "FULFILLMENT_BY_SELLER",
                     "payment": {"currency": "USD", "total_amount": "45.50", "sub_total": "40.00", "shipping_fee": "5.50"},
                     "recipient_address": {"name": "Jane Hunter", "phone_number": "(+1)555-0100"},
                     "line_items": [{"id": "L1", "product_name": "Forge Knife", "sku_name": "Black", "sale_price": "20.00", "sku_id": "S1"},
                                    {"id": "L2", "product_name": "Forge Knife", "sku_name": "Black", "sale_price": "20.00", "sku_id": "S1"}]},
                    {"id": "576002", "status": "CANCELLED", "user_id": "buyer8", "create_time": NOW - 9000,
                     "payment": {"currency": "USD", "total_amount": "10.00"},
                     "recipient_address": {"name": "Bob"}, "line_items": [{"id": "L3", "product_name": "Sticker"}]},
                ]}})
            if path == "/product/202309/products/search":
                return httpx.Response(200, json={"code": 0, "data": {"products": [{"status": "ACTIVATE"},
                                                                                  {"status": "DRAFT"}]}})
            if path == "/customer_service/202309/conversations":
                return httpx.Response(200, json={"code": 0, "data": {"conversations": [
                    {"id": "C1", "unread_count": 1, "can_send_message": True,
                     "participants": [{"role": "BUYER", "nickname": "Jane H", "user_id": "buyer9"},
                                      {"role": "SHOP", "nickname": "The Forge Shop"}],
                     "latest_message": {"create_time": NOW - 60}}]}})
            if path == "/customer_service/202309/conversations/C1/messages" and req.method == "GET":
                return httpx.Response(200, json={"code": 0, "data": {"messages": [
                    {"id": "M2", "type": "TEXT", "content": json.dumps({"content": "When will it ship?"}),
                     "create_time": NOW - 60, "sender": {"role": "BUYER", "nickname": "Jane H"}},
                    {"id": "M1", "type": "ORDER_CARD", "content": json.dumps({"order_id": "576001"}),
                     "create_time": NOW - 120, "sender": {"role": "BUYER", "nickname": "Jane H"}}]}})
            if path == "/customer_service/202309/conversations/C1/messages" and req.method == "POST":
                body = json.loads(raw)
                self.sent.append(body)
                return httpx.Response(200, json={"code": 0, "data": {"message_id": "M3"}})
            if path == "/customer_service/202309/conversations/C1/messages/read":
                return httpx.Response(200, json={"code": 0, "data": {}})
            if path == "/logistics/202309/delivery_options/DO1/shipping_providers":
                return httpx.Response(200, json={"code": 0, "data": {"shipping_providers": [
                    {"id": "SP_USPS", "name": "USPS"}, {"id": "SP_UPS", "name": "UPS"}]}})
            if path == "/fulfillment/202309/orders/576001/packages":
                self.packages.append(json.loads(raw))
                return httpx.Response(200, json={"code": 0, "data": {"package_id": "PK1"}})
        return httpx.Response(404, json={"error": f"unexpected {req.method} {req.url}"})


def _mock(monkeypatch, fake):
    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(common, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "start", runner.run_job)          # run synchronously in tests


def _signin(auth, integ_id, slug, code, param="code"):
    r = auth.put(f"/api/integrations/{integ_id}/oauth/redirect",
                 json={"redirect_uri": f"https://mserver.tail1234.ts.net/api/oauth/{slug}/callback"})
    assert r.status_code == 200, r.text
    r = auth.get(f"/api/integrations/{integ_id}/oauth/authorize", params={"return_to": "http://192.168.50.199:3050"})
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
    r = auth.get(f"/api/oauth/{slug}/callback", params={param: code, "state": state}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert r.headers["location"].startswith("http://192.168.50.199:3050/integrations?")
    return r.headers["location"]


def test_tiktok_signin_sync_and_post(auth, monkeypatch):
    fake = FakeTikTok()
    _mock(monkeypatch, fake)
    r = auth.post("/api/integrations", json={"provider": "tiktok", "values": {"client_key": "ck", "client_secret": "cs"}})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    r = auth.get(f"/api/integrations/{iid}/oauth/authorize")
    assert r.status_code == 422                                  # needs return address first
    loc = _signin(auth, iid, "tiktok", "TTCODE")
    assert "tiktok_signin=connected" in loc and "Gaming+Outdoorsmen" in loc
    info = auth.get(f"/api/integrations/{iid}/oauth").json()
    assert info["signed_in"] and info["account"] == "Gaming Outdoorsmen"
    assert "video.upload" in info["missing_scopes"]

    r = auth.post(f"/api/integrations/{iid}/sync")
    assert r.status_code == 200, r.text
    ch = auth.get("/api/channels").json()
    tt = next(c for c in ch if c["platform"] == "tiktok")
    assert tt["followers"] == 1234
    posts = auth.get("/api/posts").json()
    posts = posts.get("items", posts) if isinstance(posts, dict) else posts
    views = {p["external_id"]: p["views"] for p in posts if p.get("external_source") == "tiktok"}
    assert views == {"v1": 5000, "v2": 700}

    # expired token is refreshed and saved
    from app.integrations.crypto import decrypt_secrets, encrypt_secrets
    from app.models import Integration
    with SessionLocal() as db:
        i = db.get(Integration, iid)
        s = decrypt_secrets(i.secrets)
        s["token_expires"] = "1"
        i.secrets = encrypt_secrets(s)
        db.commit()

    # posting
    targets = auth.get("/api/publish/targets").json()
    t = next(x for x in targets if x["platform"] == "tiktok")
    assert t["ready"] and t["account"] == "Gaming Outdoorsmen"
    ci = auth.get(f"/api/publish/tiktok/{iid}/creator-info").json()
    assert ci["privacy_level_options"] == ["SELF_ONLY"]
    assert fake.refreshes == 1
    m = auth.post("/api/publish/media", files=[("files", ("clip.mp4", VIDEO, "video/mp4"))])
    assert m.status_code == 201, m.text
    mid = m.json()[0]["id"]
    bad = auth.post("/api/publish", json={"text": "Elk!", "media_ids": [mid],
                                          "targets": [{"integration_id": iid, "options": {}}]})
    assert bad.status_code == 422 and "who can view" in bad.text.lower()
    r = auth.post("/api/publish", json={"text": "Elk camp #hunting", "media_ids": [mid],
                                        "targets": [{"integration_id": iid, "options": {
                                            "privacy_level": "SELF_ONLY", "consent": True, "allow_comment": True,
                                            "allow_duet": True}}]})
    assert r.status_code in (200, 201), r.text
    job_id = r.json()["id"]
    job = auth.get(f"/api/publish/{job_id}").json()
    tgt = job["targets"][0]
    assert tgt["status"] == "posted", tgt
    assert tgt["url"] == "https://www.tiktok.com/@gamingoutdoorsmen/video/7300000000001"
    assert fake.uploaded == VIDEO
    pi = fake.init_body["post_info"]
    assert pi["privacy_level"] == "SELF_ONLY" and pi["title"].startswith("Elk camp")
    assert pi["disable_comment"] is False and pi["disable_duet"] is True      # duet off in creator settings
    assert fake.init_body["source_info"]["total_chunk_count"] == 1


def test_chunk_plan():
    assert ttpub.chunk_plan(1000) == (1000, 1)
    assert ttpub.chunk_plan(25 * 1024 * 1024) == (25 * 1024 * 1024, 1)
    assert ttpub.chunk_plan(105 * 1024 * 1024) == (10 * 1024 * 1024, 10)       # last chunk takes the remainder
    assert ttpub.chunk_plan(9 * 1024 * 1024)[1] == 1


def test_tiktok_shop_orders_messages_and_shipping(auth, monkeypatch):
    fake = FakeTikTok()
    _mock(monkeypatch, fake)
    r = auth.post("/api/integrations", json={"provider": "tiktok_shop", "values": {
        "app_key": "ak", "app_secret": "as", "service_id": "123", "region": "US"}})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    url = auth.put(f"/api/integrations/{iid}/oauth/redirect",
                   json={"redirect_uri": "https://mserver.tail1234.ts.net/api/oauth/tiktok-shop/callback"})
    assert url.status_code == 200
    auth_url = auth.get(f"/api/integrations/{iid}/oauth/authorize").json()["url"]
    assert auth_url.startswith("https://services.us.tiktokshop.com/open/authorize?service_id=123")
    # paste fallback
    r = auth.post(f"/api/integrations/{iid}/oauth/connect",
                  json={"pasted": "https://mserver.tail1234.ts.net/api/oauth/tiktok-shop/callback?code=SHOPCODE&state=x"})
    assert r.status_code == 200, r.text
    assert r.json()["oauth"]["account"] == "The Forge Shop"

    r = auth.post(f"/api/integrations/{iid}/sync")
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        o = db.query(Order).filter_by(source="tiktok_shop", external_id="576001").one()
        assert o.total == 45.5 and o.items_summary == "Forge Knife (Black) ×2" and o.customer_name == "Jane Hunter"
        assert o.fulfillment_state == "NEEDS_SHIPPING"
        c = db.query(Order).filter_by(external_id="576002").one()
        assert c.state == "CANCELED" and c.net == 0
        oid = o.id
        conv = db.query(Conversation).one()
        assert conv.title == "Jane H" and conv.unread == 1 and conv.contact_id
        assert conv.last_message == "When will it ship?"
        conv_id = conv.id

    inbox = auth.get("/api/messages").json()
    assert inbox["unread_total"] == 1 and inbox["conversations"][0]["source"] == "tiktok_shop"
    detail = auth.get(f"/api/messages/{conv_id}").json()
    assert [m["body"] for m in detail["messages"]] == ["[Order Card] 576001", "When will it ship?"]
    r = auth.post(f"/api/messages/{conv_id}/reply", json={"text": "Shipping tomorrow, thanks!"})
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "out"
    assert json.loads(fake.sent[0]["content"]) == {"content": "Shipping tomorrow, thanks!"}
    after = auth.get(f"/api/messages/{conv_id}").json()
    assert after["unread"] == 0 and after["messages"][-1]["body"] == "Shipping tomorrow, thanks!"

    provs = auth.get(f"/api/orders/{oid}/shipping-providers")
    assert provs.status_code == 200, provs.text
    assert provs.json()[0] == {"id": "SP_USPS", "name": "USPS"}
    r = auth.post(f"/api/orders/{oid}/ship", json={"tracking_number": "9400100000000000000000",
                                                   "shipping_provider_id": "SP_USPS"})
    assert r.status_code == 200, r.text
    assert fake.packages[0] == {"tracking_number": "9400100000000000000000", "shipping_provider_id": "SP_USPS",
                                "order_line_item_ids": ["L1", "L2"]}


def test_tiktok_shop_messages_wait_for_approval_then_turn_on(auth, monkeypatch):
    """Before TikTok approves Customer service: orders still sync, Messages explains what to do and checks
    hourly. After approval + signing in again, chats come in on the next background check."""
    from datetime import timedelta
    from app.integrations import scheduler
    from app.models import Integration, utcnow
    fake = FakeTikTok()
    fake.cs_approved = False
    _mock(monkeypatch, fake)
    iid = auth.post("/api/integrations", json={"provider": "tiktok_shop", "values": {
        "app_key": "ak", "app_secret": "as", "service_id": "123", "region": "US"}}).json()["id"]
    st = auth.get("/api/messages/status").json()
    assert st[0]["status"] == "not_signed_in" and st[0]["every_minutes"] == 5
    pasted = "https://mserver.tail1234.ts.net/api/oauth/tiktok-shop/callback?code=SHOPCODE&state=x"
    assert auth.post(f"/api/integrations/{iid}/oauth/connect", json={"pasted": pasted}).status_code == 200

    r = auth.post(f"/api/integrations/{iid}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["orders_synced"] == 2       # orders unaffected
    assert any("waiting for TikTok to approve" in w for w in r["last_result"]["warnings"])
    st = auth.get("/api/messages/status").json()[0]
    assert st["status"] == "waiting_approval" and st["recheck_minutes"] == 60 and "scope" in st["error"]

    # background check doesn't hammer TikTok while waiting: next look is an hour later
    calls = fake.cs_calls
    scheduler.run_message_checks()
    assert fake.cs_calls == calls
    with SessionLocal() as db:
        i = db.get(Integration, iid)
        cfg = json.loads(i.config)
        cfg["messages_checked_at"] = (utcnow() - timedelta(minutes=61)).isoformat()
        i.config = json.dumps(cfg)
        db.commit()
    scheduler.run_message_checks()
    assert fake.cs_calls == calls + 1                      # looked again, still waiting
    assert auth.get("/api/messages/status").json()[0]["status"] == "waiting_approval"

    # TikTok approves; the user signs in again -> next background check (within a minute) pulls chats
    fake.cs_approved = True
    assert auth.post(f"/api/integrations/{iid}/oauth/connect", json={"pasted": pasted}).status_code == 200
    assert auth.get("/api/messages/status").json()[0]["status"] == "unknown"
    scheduler.run_message_checks()
    st = auth.get("/api/messages/status").json()[0]
    assert st["status"] == "active" and st["error"] == ""
    inbox = auth.get("/api/messages").json()
    assert inbox["conversations"][0]["title"] == "Jane H" and inbox["unread_total"] == 1

    # active: checked every 5 minutes, not every minute
    calls = fake.cs_calls
    scheduler.run_message_checks()
    assert fake.cs_calls == calls
    # "Check now" button
    out = auth.post("/api/messages/check").json()
    assert out[0]["status"] == "active" and out[0]["result"]["conversations"] == 1


def test_message_check_schedule():
    from datetime import datetime, timedelta
    now = datetime(2026, 11, 7, 12, 0)
    due = tiktok_shop.message_check_due
    assert due({}, now)
    assert not due({"messages_status": "active", "messages_checked_at": (now - timedelta(minutes=3)).isoformat()}, now)
    assert due({"messages_status": "active", "messages_checked_at": (now - timedelta(minutes=5)).isoformat()}, now)
    assert not due({"messages_status": "active", "messages_every_minutes": "0"}, now)
    assert not due({"messages_status": "waiting_approval", "messages_checked_at": (now - timedelta(minutes=30)).isoformat()}, now)
    assert due({"messages_status": "error", "messages_checked_at": (now - timedelta(minutes=15)).isoformat()}, now)
    assert not due({"messages_status": "not_signed_in"}, now)
