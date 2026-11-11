"""Browser launch refreshes, custom intervals, and shared scheduler/manual-sync safety."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest

from app.database import SessionLocal
from app.integrations import scheduler
from app.integrations.service import run_sync
from app.models import Integration, utcnow
from test_integrations import connect, mock
from test_scheduler import _age, _yt


@pytest.fixture(autouse=True)
def clear_attempts():
    scheduler._last_attempt.clear()
    yield
    scheduler._last_attempt.clear()


def test_launch_refresh_and_repeat_tabs_share_cooldown(auth, monkeypatch):
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    _age(yt["id"], minutes=2)  # not due for another six hours
    monkeypatch.setenv("SYNC_SCHEDULER", "true")
    response = auth.post("/api/integrations/browser-open")
    assert response.status_code == 202 and response.json()["queued"]
    assert n["c"] > 0
    calls = n["c"]
    assert auth.get(f"/api/integrations/{yt['id']}").json()["last_status"] == "ok"
    auth.post("/api/integrations/browser-open")
    assert n["c"] == calls
    # Another launch later can refresh even before the regular interval elapses.
    _age(yt["id"], minutes=2)
    scheduler._last_attempt[yt["id"]] = utcnow() - timedelta(minutes=2)
    auth.post("/api/integrations/browser-open")
    assert n["c"] > calls


def test_launch_respects_paused_manual_and_opt_out(auth, monkeypatch):
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    for options in ({"enabled": False}, {"sync_interval_minutes": 0}, {"sync_on_open": False}):
        connect(auth, "youtube", {"channel": "me", "api_key": "K"}, **options)
    scheduler._run_due(on_open=True)
    assert n["c"] == 0
    scheduler._run_due("stats")  # launch opt-out does not disable scheduled syncing
    assert n["c"] > 0


def test_preferences_persist_and_old_connections_default_on(auth):
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"}, sync_interval_minutes=7)
    assert yt["sync_on_open"] is True
    result = auth.patch(f"/api/integrations/{yt['id']}", json={
        "sync_on_open": False, "sync_interval_minutes": 13, "values": {"channel": "@changed"}})
    assert result.status_code == 200
    saved = auth.get(f"/api/integrations/{yt['id']}").json()
    assert saved["sync_on_open"] is False and saved["sync_interval_minutes"] == 13
    assert saved["config"]["channel"] == "@changed" and saved["saved_secrets"] == ["api_key"]
    with SessionLocal() as db:
        item = db.get(Integration, yt["id"])
        config = json.loads(item.config)
        del config["sync_on_open"]
        item.config = json.dumps(config)
        db.commit()
    assert auth.get(f"/api/integrations/{yt['id']}").json()["sync_on_open"] is True


@pytest.mark.parametrize("minutes", [-1, 1.5, 10081])
def test_reject_invalid_interval(auth, minutes):
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    assert auth.patch(f"/api/integrations/{yt['id']}", json={"sync_interval_minutes": minutes}).status_code == 422


def test_custom_interval_runs_without_any_browser(auth, monkeypatch):
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"}, sync_interval_minutes=7)
    _age(yt["id"], minutes=6)
    scheduler._run_due("stats")
    assert n["c"] == 0
    _age(yt["id"], minutes=8)
    scheduler._run_due("stats")
    assert n["c"] > 0
    calls = n["c"]
    scheduler._run_due("stats")
    assert n["c"] == calls


def test_launch_failures_back_off_and_do_not_block_other_connections(auth, monkeypatch):
    n = {"c": 0}
    good = _yt(n)
    def handler(req):
        if req.url.params.get("key") == "BAD":
            return httpx.Response(403, json={"error": {"message": "quota exceeded"}})
        return good(req)
    calls = mock(monkeypatch, handler)
    bad = connect(auth, "youtube", {"channel": "bad", "api_key": "BAD"}, sync_interval_minutes=7)
    good_item = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    scheduler._run_due(on_open=True)
    assert auth.get(f"/api/integrations/{bad['id']}").json()["last_status"] == "error"
    assert auth.get(f"/api/integrations/{good_item['id']}").json()["last_status"] == "ok"
    total = len(calls)
    scheduler._last_attempt[bad["id"]] = utcnow() - timedelta(minutes=2)
    scheduler._run_due(on_open=True)
    assert len(calls) == total
    scheduler._last_attempt[bad["id"]] = utcnow() - timedelta(minutes=8)
    scheduler._run_due(on_open=True)
    assert len(calls) > total


def test_concurrent_launch_and_scheduler_only_sync_once(auth, monkeypatch):
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(scheduler._run_due, "stats", launch) for launch in (True, False, True)]
        for job in jobs:
            job.result(timeout=10)
    # _yt makes two API requests for a single sync (channel + empty upload playlist).
    assert n["c"] == 2


def test_automatic_rechecks_after_manual_sync(auth, monkeypatch):
    n = {"c": 0}
    mock(monkeypatch, _yt(n))
    yt = connect(auth, "youtube", {"channel": "me", "api_key": "K"})
    with SessionLocal() as stale_db:
        stale = stale_db.get(Integration, yt["id"])
        assert stale.last_sync_at is None
        auth.post(f"/api/integrations/{yt['id']}/sync")
        calls = n["c"]
        run_sync(stale_db, stale, should_sync=lambda fresh: scheduler._claim(fresh, True))
        assert n["c"] == calls


def test_launch_requires_auth_and_respects_global_switch(client, auth, monkeypatch):
    assert auth.post("/api/integrations/browser-open").json() == {"queued": False}
    monkeypatch.setenv("SYNC_SCHEDULER", "true")
    token = client.headers.pop("Authorization")
    assert client.post("/api/integrations/browser-open").status_code == 401
    client.headers["Authorization"] = token
    assert scheduler.request_browser_sync() is True
    assert scheduler.request_browser_sync() is False
    asyncio.run(scheduler.run_browser_sync())
    assert not scheduler._browser_lock.locked()
