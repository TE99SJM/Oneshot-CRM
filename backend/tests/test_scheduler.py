"""Automatic syncing: stats every 6 hours, sales/messages every 15 minutes, separate lanes, status endpoint."""
import json
from datetime import timedelta

import httpx

from app.database import SessionLocal
from app.integrations import scheduler
from app.models import Integration, utcnow
from test_integrations import connect, mock


def _yt(n):
    def handler(req):
        n["c"] += 1
        if req.url.path.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": "UC" + "a" * 22, "snippet": {"title": "Me"},
                "statistics": {"subscriberCount": str(1000 + n["c"]), "viewCount": str(5000 + n["c"])},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        return httpx.Response(200, json={"items": []})
    return handler


def _age(iid, **delta):
    with SessionLocal() as db:
        i = db.get(Integration, iid)
        i.last_sync_at = utcnow() - timedelta(**delta)
        db.commit()


def test_defaults_and_youtube_auto_sync(auth, monkeypatch):
    scheduler._last_attempt.clear()
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    sq = connect(auth, "square", {"access_token": "T"}, enabled=False)
    assert yt["sync_interval_minutes"] == 360 and sq["sync_interval_minutes"] == 15
    provs = {p["key"]: p["default_interval"] for p in auth.get("/api/integrations/providers").json()}
    assert provs["youtube"] == 360 and provs["square"] == provs["ebay"] == provs["tiktok_shop"] == provs["gmail"] == 15
    assert scheduler.lane_of("youtube") == "stats" and scheduler.lane_of("ebay") == "sales"

    # never synced -> picked up on the first tick of the stats lane
    scheduler._run_due("sales")
    assert n["c"] == 0                                   # YouTube isn't in the sales lane
    scheduler._run_due("stats")
    first = auth.get(f"/api/integrations/{yt['id']}").json()
    assert first["last_status"] == "ok" and first["last_sync_at"]
    assert [c for c in auth.get("/api/channels").json() if c["platform"] == "youtube"][0]["followers"] > 1000
    calls = n["c"]

    # 5 hours later: not due yet. 6 hours later: syncs again by itself.
    _age(yt["id"], hours=5)
    scheduler._last_attempt.clear()
    scheduler._run_due()
    assert n["c"] == calls
    nxt = auth.get(f"/api/integrations/{yt['id']}").json()["next_sync_at"]
    assert nxt and nxt > utcnow().isoformat()
    _age(yt["id"], hours=6, minutes=1)
    scheduler._run_due()
    assert n["c"] > calls
    assert auth.get(f"/api/integrations/{yt['id']}").json()["last_status"] == "ok"

    st = auth.get("/api/integrations/scheduler").json()
    assert st["lanes"]["stats"]["last_tick"] and st["lanes"]["sales"]["last_tick"] and st["lanes"]["stats"]["running_id"] is None


def test_one_failure_doesnt_stop_others(auth, monkeypatch):
    scheduler._last_attempt.clear()
    n = {"c": 0}
    good = _yt(n)

    def handler(req):
        if req.url.params.get("key") == "BAD":
            raise httpx.ConnectError("boom")
        return good(req)
    mock(monkeypatch, handler)
    bad = connect(auth, "youtube", {"channel": "x", "api_key": "BAD"})
    ok = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    scheduler._run_due("stats")
    assert auth.get(f"/api/integrations/{bad['id']}").json()["last_status"] == "error"
    assert auth.get(f"/api/integrations/{ok['id']}").json()["last_status"] == "ok"


def test_old_six_hour_sales_connections_move_to_15_min(auth):
    from app.main import _apply_interval_defaults
    sq = connect(auth, "square", {"access_token": "T"}, sync_interval_minutes=360, enabled=False)
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"}, enabled=False)
    with SessionLocal() as db:     # simulate a connection made before this version (no marker)
        i = db.get(Integration, sq["id"]); cfg = json.loads(i.config); cfg.pop("interval_defaults_v2", None)
        i.config = json.dumps(cfg); db.commit()
    _apply_interval_defaults()
    assert auth.get(f"/api/integrations/{sq['id']}").json()["sync_interval_minutes"] == 15
    assert auth.get(f"/api/integrations/{yt['id']}").json()["sync_interval_minutes"] == 360
    # the user sets Square back to 6 hours: it stays that way after restarts
    auth.patch(f"/api/integrations/{sq['id']}", json={"sync_interval_minutes": 360})
    _apply_interval_defaults()
    assert auth.get(f"/api/integrations/{sq['id']}").json()["sync_interval_minutes"] == 360
