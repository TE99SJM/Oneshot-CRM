"""Views: Rumble videos page, Twitch clips, lifetime totals, daily history and views gained."""
import json
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.database import SessionLocal
from app.integrations import rumble
from app.models import StatSnapshot
from app.stats_history import views_gained
from tests.test_integrations import connect, mock

PAGE = (Path(__file__).parent / "rumble_videos_page.html").read_text()


def test_parse_rumble_page():
    videos, followers = rumble.parse_videos_page(PAGE)
    assert len(videos) == 3 and followers and followers > 1000
    v = videos[0]
    assert v["key"].startswith("v") and v["views"] > 0 and v["url"].startswith("https://rumble.com/")
    assert rumble.channel_base("rumble.com/c/Me/videos?page=2") == "https://rumble.com/c/Me"
    assert rumble.channel_base("Me") == "https://rumble.com/c/Me"


def test_rumble_sync_reads_video_views(auth, monkeypatch):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        if req.url.path == "/c/Me/videos":
            if req.url.params.get("page") == "2":
                return httpx.Response(200, text='<rum-videos-grid><script type="application/json">{"items":[{"object_type":"video",'
                                      '"permalink_id":"vold1","title":"Old one","url":"https://rumble.com/vold1-old.html",'
                                      '"upload_date":"2025-01-01T00:00:00+00:00","views":500,"rumble_votes":{"num_votes_up":3},'
                                      '"comments":{"count":2}}]}</script></rum-videos-grid>')
            return httpx.Response(200, text=PAGE)
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "rumble", {"channel_url": "https://rumble.com/c/Me"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok", r
    expected = sum(v["views"] for v in rumble.parse_videos_page(PAGE)[0]) + 500
    assert r["last_result"]["videos_read"] == 4 and r["last_result"]["total_views"] == expected
    assert any("page=2" in u for u in seen)
    ch = auth.get("/api/channels").json()[0]
    assert ch["total_views"] == expected and ch["views"] == expected and ch["followers"] > 1000
    d = auth.get(f"/api/dashboard?start={date.today() - timedelta(days=29)}&end={date.today()}").json()
    assert d["kpis"]["views_lifetime"] == expected
    # first day of history: nothing from before the period yet
    assert d["kpis"]["views_gained"] is None and d["kpis"]["views_history_since"] == date.today().isoformat()
    a = auth.get("/api/dashboard").json()
    assert a["kpis"]["views_gained"] == expected


def test_rumble_blocked_points_to_bookmark(auth, monkeypatch):
    def handler(req):
        if req.url.path == "/-livestream-api/get-data":
            return httpx.Response(200, json={"followers": {"num_followers_total": 7}})
        return httpx.Response(403, text="<title>Just a moment...</title>")

    mock(monkeypatch, handler)
    i = connect(auth, "rumble", {"api_url": "https://rumble.com/-livestream-api/get-data?key=k", "channel_url": "https://rumble.com/c/Me"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["followers"] == 7
    assert any("Send to CRM" in w for w in r["last_result"]["warnings"])


def test_rumble_bookmark_import(auth):
    i = connect(auth, "rumble", {"channel_url": "https://rumble.com/c/Me"})
    body = {"channel_url": "https://rumble.com/c/me", "followers": 321, "videos": [
        {"permalink_id": "vA1", "url": "https://rumble.com/vA1-x.html", "title": "A", "upload_date": "2026-10-30T10:00:00+00:00",
         "views": 1000, "likes": 9, "comments": 4},
        {"permalink_id": "vB2", "url": "https://rumble.com/vB2-y.html", "title": "B", "views": 50}]}
    r = auth.post("/api/integrations/rumble/import", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2 and r.json()["total_views"] == 1050
    ch = auth.get("/api/channels").json()[0]
    assert ch["followers"] == 321 and ch["total_views"] == 1050
    posts = auth.get("/api/posts").json()
    assert {p["title"] for p in posts} == {"A", "B"}
    # import again with higher counts updates instead of duplicating
    body["videos"][0]["views"] = 1500
    assert auth.post("/api/integrations/rumble/import", json=body).json()["total_views"] == 1550
    assert len(auth.get("/api/posts").json()) == 2
    assert auth.post("/api/integrations/rumble/import", json={"videos": []}).status_code == 422
    assert i


def test_twitch_clips_and_lifetime(auth, monkeypatch):
    def handler(req):
        if req.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "APP", "expires_in": 5000})
        p = req.url.path
        if p == "/helix/users":
            return httpx.Response(200, json={"data": [{"id": "99", "login": "me", "display_name": "Me"}]})
        if p == "/helix/channels/followers":
            return httpx.Response(200, json={"total": 5, "data": []})
        if p == "/helix/streams":
            return httpx.Response(200, json={"data": []})
        if p == "/helix/videos":
            return httpx.Response(200, json={"data": [{"id": "v1", "title": "VOD", "url": "u", "published_at": "2026-10-07T00:00:00Z",
                                                       "view_count": 40}], "pagination": {}})
        if p == "/helix/clips":
            assert req.url.params["broadcaster_id"] == "99"
            return httpx.Response(200, json={"data": [{"id": "c1", "title": "Big play", "url": "https://clips.twitch.tv/c1",
                                                       "created_at": "2026-10-08T00:00:00Z", "view_count": 60}], "pagination": {}})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "twitch", {"login": "me", "client_id": "CID", "client_secret": "S"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_status"] == "ok" and r["last_result"]["total_views"] == 100 and r["last_result"]["posts_created"] == 2


def test_youtube_lifetime_views(auth, monkeypatch):
    def handler(req):
        p = req.url.path
        if p.endswith("/channels"):
            return httpx.Response(200, json={"items": [{"id": "UC" + "a" * 22, "snippet": {"title": "Me"},
                "statistics": {"subscriberCount": "10", "viewCount": "123456"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]})
        if p.endswith("/playlistItems"):
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "v1"}}]})
        if p.endswith("/videos"):
            return httpx.Response(200, json={"items": [{"id": "v1", "snippet": {"title": "Old", "publishedAt": "2020-01-01T00:00:00Z"},
                                                        "statistics": {"viewCount": "77"}}]})
        return httpx.Response(404)

    mock(monkeypatch, handler)
    i = connect(auth, "youtube", {"channel": "@me", "api_key": "K"})
    r = auth.post(f"/api/integrations/{i['id']}/sync").json()
    assert r["last_result"]["total_views"] == 123456
    d = auth.get(f"/api/dashboard?start={date.today() - timedelta(days=29)}&end={date.today()}").json()
    assert d["kpis"]["views_lifetime"] == 123456
    assert d["kpis"]["views"] == 0, "the 2020 video isn't 'new' in the last 30 days"
    row = [c for c in d["channels"] if c["lifetime_views"]][0]
    assert row["lifetime_views"] == 123456


def test_views_gained_from_history(auth):
    db = SessionLocal()
    try:
        today = date.today()
        for back, value in ((40, 1000), (20, 1500), (0, 2600)):
            db.add(StatSnapshot(metric="views_total", day=today - timedelta(days=back), value=value))
        db.commit()
        assert views_gained(db, today - timedelta(days=30)) == (1600, today - timedelta(days=40))
        assert views_gained(db, today - timedelta(days=60))[0] is None
        assert views_gained(db, None)[0] == 2600
    finally:
        db.close()
    s = auth.get(f"/api/dashboard/series/views_gained?start={date.today() - timedelta(days=89)}&bucket=month").json()
    assert s["points"] and any(p["value"] for p in s["points"] if p["value"] is not None)
    t = auth.get(f"/api/dashboard/series/views_total?start={date.today() - timedelta(days=89)}").json()
    assert t["points"][-1]["value"] == 2600
