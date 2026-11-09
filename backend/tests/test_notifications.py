"""Order alerts: settings, test button, alerts after a sync (not on the first history import)."""
import json
from datetime import timedelta

import httpx

from app import notifications as alerts
from app.database import SessionLocal
from app.integrations import service
from app.integrations.registry import PROVIDERS
from app.models import Integration, Order, utcnow


def _capture(monkeypatch):
    sent = {"push": [], "twilio": [], "email": []}
    monkeypatch.setattr(alerts, "send_push", lambda cfg, sec, t, b, click="": sent["push"].append((t, b, click)))
    monkeypatch.setattr(alerts, "send_twilio", lambda cfg, sec, s: sent["twilio"].append(s))
    def bad_email(db, cfg, sec, t, s):
        raise ValueError("Text by email: Gmail rejected the app password")
    monkeypatch.setattr(alerts, "send_email", bad_email)
    return sent


def test_settings_secrets_and_test_button(auth, monkeypatch):
    r = auth.get("/api/notifications").json()
    topic = r["config"]["push_topic"]
    assert topic.startswith("funnelhub-") and len(topic) > 15 and r["saved_secrets"] == []
    assert auth.get("/api/notifications").json()["config"]["push_topic"] == topic      # stable
    assert any(c["key"] == "verizon" and c["domain"] == "vtext.com" for c in r["carriers"])
    r = auth.put("/api/notifications", json={"config": {"enabled": True, "push_enabled": True, "twilio_enabled": True,
        "email_enabled": True, "email_carrier": "verizon", "email_number": "+1 (218) 555-0100", "twilio_sid": "AC1",
        "app_url": "http://100.1.2.3:3050/", "bogus": 1}, "secrets": {"twilio_token": "tok", "push_token": ""}}).json()
    assert r["email_target"] == "2185550100@vtext.com" and r["saved_secrets"] == ["twilio_token"]
    assert "bogus" not in r["config"]
    r = auth.put("/api/notifications", json={"config": {}, "secrets": {"twilio_token": ""}}).json()
    assert r["saved_secrets"] == ["twilio_token"]                                       # blank keeps it
    sent = _capture(monkeypatch)
    t = auth.post("/api/notifications/test", json={}).json()
    assert t["results"]["push"] == "ok" and t["results"]["twilio"] == "ok" and "app password" in t["results"]["email"]
    assert not t["ok"] and sent["push"][0][2] == "http://100.1.2.3:3050/orders"
    t = auth.post("/api/notifications/test", json={"channel": "push"}).json()
    assert t["ok"] and list(t["results"]) == ["push"]
    assert len(auth.get("/api/notifications").json()["history"]) == 2
    r = auth.put("/api/notifications", json={"config": {}, "clear_secrets": ["twilio_token"]}).json()
    assert r["saved_secrets"] == []


def test_push_request_and_twilio_errors(monkeypatch):
    seen = {}
    real = httpx.Client
    def client(**kw):
        def h(req):
            seen["url"], seen["body"], seen["auth"] = str(req.url), req.content.decode(), req.headers.get("authorization")
            if "twilio" in str(req.url):
                return httpx.Response(400, json={"message": "Unverified toll-free number", "code": 30032})
            return httpx.Response(200, json={"id": "x"})
        return real(transport=httpx.MockTransport(h), timeout=5)
    monkeypatch.setattr(alerts.httpx, "Client", client)
    alerts.send_push({"push_server": "https://ntfy.sh", "push_topic": "funnelhub-abc"}, {"push_token": "tk"},
                     "New order $5.00 - Square", "Jane – 2× Hat", "http://x/orders")
    assert seen["url"].startswith("https://ntfy.sh/funnelhub-abc?") and "click=" in seen["url"]
    assert seen["body"] == "Jane – 2× Hat" and seen["auth"] == "Bearer tk"
    try:
        alerts.send_twilio({"twilio_sid": "AC1", "twilio_from": "+18005550100", "twilio_to": "+12185550100"},
                           {"twilio_token": "t"}, "hi")
        raise AssertionError("should fail")
    except ValueError as e:
        assert "30032" in str(e) and "toll-free verification" in str(e)
    assert alerts._ascii("2× Hat – Jané…") == "2x Hat - Jane..."


def _fake_square(monkeypatch, batches):
    def sync(ctx):
        for ext, total, days_ago in batches.pop(0):
            ctx.db.add(Order(source="square", external_id=ext, channel_id=ctx.channel.id, total=total, state="COMPLETED",
                             customer_name="Jane Doe", items_summary="2× Hat", reference=ext[-4:].upper(),
                             ordered_at=utcnow() - timedelta(days=days_ago)))
    monkeypatch.setattr(PROVIDERS["square"], "sync", sync)


def test_alerts_after_sync(auth, monkeypatch):
    sent = _capture(monkeypatch)
    auth.put("/api/notifications", json={"config": {"enabled": True, "push_enabled": True, "min_total": 10}})
    _fake_square(monkeypatch, [
        [("hist1", 50, 30), ("hist2", 20, 0)],                       # first sync = history import -> silent
        [("new1", 45.5, 0), ("cheap", 5, 0), ("old", 99, 10)],        # only new1 (cheap < min, old too old)
        [(f"burst{i}", 20, 0) for i in range(5)],                     # burst -> one summary
    ])
    with SessionLocal() as db:
        integ = Integration(provider="square", name="Shop", config="{}")
        db.add(integ)
        db.commit()
        for _ in range(3):
            service.run_sync(db, db.get(Integration, integ.id))
        assert db.get(Integration, integ.id).last_status == "ok"
    titles = [t for t, _, _ in sent["push"]]
    assert titles == ["New order $45.50 - Square", "5 new orders - $100.00"]
    assert "Jane Doe" in sent["push"][0][1] and "Order #NEW1" in sent["push"][0][1]


def test_alert_failure_never_breaks_sync(auth, monkeypatch):
    auth.put("/api/notifications", json={"config": {"enabled": True, "push_enabled": True}})
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(alerts, "send_push", boom)
    _fake_square(monkeypatch, [[], [("n1", 30, 0)]])
    with SessionLocal() as db:
        integ = Integration(provider="square", name="Shop", config="{}")
        db.add(integ)
        db.commit()
        service.run_sync(db, db.get(Integration, integ.id))
        i = service.run_sync(db, db.get(Integration, integ.id))
        assert i.last_status == "ok"
        hist = json.loads(db.scalar(alerts.select(alerts.NotifySettings)).history)
        assert "network down" in hist[0]["results"]["push"]
