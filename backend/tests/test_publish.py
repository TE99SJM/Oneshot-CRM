"""Compose & publish: Facebook, Instagram and YouTube against mock platform APIs."""
import io
import json
from datetime import timedelta

import httpx
import pytest
from PIL import Image

from app.database import SessionLocal
from app.integrations import base
from app.models import PublishJob, utcnow
from app.publishing import common, runner, youtube as ytpub


def png_bytes(color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGBA", (40, 30), color + (255,)).save(buf, "PNG")
    return buf.getvalue()


VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000


class FakePlatforms:
    """One handler for graph.facebook.com, rupload.facebook.com, Google OAuth and YouTube upload."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.forms: list[dict] = []
        self.ig_resumable_ok = True
        self.yt_received = b""
        self.reel_bytes = b""
        self.ig_bytes = b""
        self.fb_chunks: list[int] = []
        self.status_polls = 0
        self.deleted: list[str] = []

    @staticmethod
    def form(req: httpx.Request) -> dict:
        ct = req.headers.get("content-type", "")
        body = req.read()
        if "multipart" in ct:
            out = {}
            boundary = ct.split("boundary=")[1].encode()
            for part in body.split(b"--" + boundary):
                if b"name=\"" not in part:
                    continue
                head, _, val = part.partition(b"\r\n\r\n")
                name = head.split(b"name=\"")[1].split(b"\"")[0].decode()
                out[name] = val[:-2] if b"filename=" in head else val[:-2].decode()
            return out
        if "x-www-form-urlencoded" in ct:
            return dict(httpx.QueryParams(body.decode()))
        return {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        host, path = req.url.host, req.url.path
        if host == "oauth2.googleapis.com":
            f = self.form(req)
            if f["grant_type"] == "authorization_code":
                assert f["code"] == "4/abc" and f["code_verifier"]
                return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3599})
            assert f["refresh_token"] == "RT"
            return httpx.Response(200, json={"access_token": "AT2", "expires_in": 3599})
        if host == "www.googleapis.com" and path == "/youtube/v3/channels":
            assert req.headers["authorization"] == "Bearer AT"
            return httpx.Response(200, json={"items": [{"id": "UCme", "snippet": {"title": "Gaming Outdoorsmen"}}]})
        if host == "www.googleapis.com" and path == "/upload/youtube/v3/videos":
            meta = json.loads(req.read())
            assert meta["snippet"]["title"] == "Elk camp recap" and meta["status"]["privacyStatus"] == "unlisted"
            assert meta["snippet"]["tags"] == ["elk", "hunting"]
            assert int(req.headers["x-upload-content-length"]) == len(VIDEO)
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/session/xyz"})
        if host == "www.googleapis.com" and path == "/upload/session/xyz":
            rng = req.headers["content-range"]
            self.yt_received += req.read()
            total = int(rng.split("/")[1])
            if len(self.yt_received) < total:
                return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.yt_received) - 1}"})
            return httpx.Response(200, json={"id": "yt123", "status": {"uploadStatus": "uploaded"}})
        if host == "rupload.facebook.com":
            assert req.headers["authorization"] == "OAuth PT" and req.headers["offset"] == "0"
            data = req.read()
            assert int(req.headers["file_size"]) == len(data)
            if "/ig-api-upload/" in path:
                self.ig_bytes = data
            else:
                self.reel_bytes = data
            return httpx.Response(200, json={"success": True})
        if host == "graph.facebook.com":
            return self.graph(req, path.split("/", 2)[2])
        return httpx.Response(404, json={"error": {"message": f"unexpected {req.url}"}})

    def graph(self, req, p):
        if req.method == "GET":
            assert req.url.params["access_token"] == "PT"
            fields = req.url.params.get("fields", "")
            if p == "PAGE1" and fields == "instagram_business_account":
                return httpx.Response(200, json={"instagram_business_account": {"id": "IG1"}})
            if fields == "images":
                return httpx.Response(200, json={"images": [{"width": 40, "source": f"https://scontent.fbcdn.net/{p}.jpg"},
                                                            {"width": 20, "source": "small.jpg"}]})
            if fields == "status_code,status":
                self.status_polls += 1
                return httpx.Response(200, json={"status_code": "IN_PROGRESS" if self.status_polls == 1 else "FINISHED"})
            if fields == "permalink":
                return httpx.Response(200, json={"permalink": f"https://www.instagram.com/p/{p}/"})
            if fields == "permalink_url":
                return httpx.Response(200, json={"permalink_url": f"/PAGE1/posts/{p}"})
            return httpx.Response(404, json={"error": {"message": f"GET {p}"}})
        if req.method == "DELETE":
            self.deleted.append(p)
            return httpx.Response(200, json={"success": True})
        f = self.form(req)
        self.forms.append({"path": p, **{k: v for k, v in f.items() if isinstance(v, str)}})
        assert f["access_token"] == "PT"
        if p == "PAGE1/feed":
            return httpx.Response(200, json={"id": "PAGE1_feed%d" % len(self.forms)})
        if p == "PAGE1/photos":
            if f.get("published") == "false":
                return httpx.Response(200, json={"id": "ph%d" % len(self.forms)})
            return httpx.Response(200, json={"id": "ph9", "post_id": "PAGE1_photo"})
        if p == "PAGE1/videos":
            phase = f["upload_phase"]
            if phase == "start":
                return httpx.Response(200, json={"upload_session_id": "S1", "video_id": "V1", "start_offset": "0",
                                                 "end_offset": "3000"})
            if phase == "transfer":
                self.fb_chunks.append(len(f["video_file_chunk"]))
                s = int(f["start_offset"]) + len(f["video_file_chunk"])
                return httpx.Response(200, json={"start_offset": str(s), "end_offset": str(min(s + 3000, len(VIDEO)))})
            return httpx.Response(200, json={"success": True})
        if p == "PAGE1/video_reels":
            if f["upload_phase"] == "start":
                return httpx.Response(200, json={"video_id": "R1", "upload_url": "https://rupload.facebook.com/video-upload/v27.0/R1"})
            assert f["video_state"] == "PUBLISHED"
            return httpx.Response(200, json={"success": True})
        if p == "IG1/media":
            if f.get("upload_type") == "resumable":
                if not self.ig_resumable_ok:
                    return httpx.Response(400, json={"error": {"message": "Resumable upload not allowed for this app"}})
                return httpx.Response(200, json={"id": "C9", "uri": "https://rupload.facebook.com/ig-api-upload/v27.0/C9"})
            return httpx.Response(200, json={"id": "C%d" % len(self.forms)})
        if p == "IG1/media_publish":
            return httpx.Response(200, json={"id": "IGM_" + f["creation_id"]})
        return httpx.Response(404, json={"error": {"message": f"POST {p}"}})


@pytest.fixture()
def fake(monkeypatch):
    fp = FakePlatforms()
    monkeypatch.setattr(base, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(fp)))
    monkeypatch.setattr(runner, "start", runner.run_job)          # run synchronously in tests
    monkeypatch.setattr(common, "sleep", lambda s: None)
    monkeypatch.setattr(ytpub, "CHUNK", 2048)                     # exercise multi-chunk + 308 resume
    return fp


def connect(auth, provider, values):
    r = auth.post("/api/integrations", json={"provider": provider, "values": values, "sync_interval_minutes": 0})
    assert r.status_code == 201, r.text
    return r.json()


def upload(auth, *files):
    r = auth.post("/api/publish/media", files=[("files", f) for f in files])
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def accounts(auth, fake):
    fb = connect(auth, "facebook", {"page_id": "PAGE1", "page_token": "PT"})
    ig = connect(auth, "instagram", {"page_id": "PAGE1", "page_token": "PT"})
    yt = connect(auth, "youtube", {"channel": "@me", "api_key": "K", "oauth_client_id": "cid.apps.googleusercontent.com",
                                   "oauth_client_secret": "GOCSPX-x"})
    return fb, ig, yt


def youtube_sign_in(auth, yt):
    r = auth.get(f"/api/integrations/{yt['id']}/youtube/authorize")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert "youtube.upload" in url and "code_challenge=" in url and "redirect_uri=http%3A%2F%2F127.0.0.1" in url
    bad = auth.post(f"/api/integrations/{yt['id']}/youtube/connect", json={"pasted": "http://127.0.0.1/?error=access_denied"})
    assert bad.status_code == 422 and "cancelled" in bad.json()["detail"]
    r = auth.post(f"/api/integrations/{yt['id']}/youtube/connect",
                  json={"pasted": "http://127.0.0.1/?state=yt3&code=4/abc&scope=https://www.googleapis.com/auth/youtube.upload"})
    assert r.status_code == 200, r.text
    assert "refresh_token" in r.json()["saved_secrets"] and r.json()["config"]["upload_channel_title"] == "Gaming Outdoorsmen"


def test_targets_readiness_and_youtube_sign_in(auth, accounts):
    fb, ig, yt = accounts
    t = {x["platform"]: x for x in auth.get("/api/publish/targets").json()}
    assert t["facebook"]["ready"] and t["instagram"]["ready"] and t["instagram"]["public_media"] is False
    assert not t["youtube"]["ready"] and "Set up posting" in t["youtube"]["note"]
    vid = upload(auth, ("clip.mp4", VIDEO, "video/mp4"))[0]
    r = auth.post("/api/publish", json={"title": "x", "media_ids": [vid["id"]], "targets": [{"integration_id": yt["id"]}]})
    assert r.status_code == 422 and "Set up posting" in r.json()["detail"]
    youtube_sign_in(auth, yt)
    t = {x["platform"]: x for x in auth.get("/api/publish/targets").json()}
    assert t["youtube"]["ready"] and t["youtube"]["account"] == "Gaming Outdoorsmen"
    # editing the connection keeps the posting sign-in
    r = auth.patch(f"/api/integrations/{yt['id']}", json={"values": {"max_videos": "50"}}).json()
    assert "refresh_token" in r["saved_secrets"]


def test_validation(auth, accounts):
    fb, ig, yt = accounts
    img = upload(auth, ("a.png", png_bytes(), "image/png"))[0]
    vid = upload(auth, ("clip.mp4", VIDEO, "video/mp4"))[0]
    youtube_sign_in(auth, yt)
    cases = [
        ({"text": "hi", "targets": [{"integration_id": ig["id"]}]}, "needs at least one photo"),
        ({"text": "hi", "media_ids": [img["id"]], "targets": [{"integration_id": yt["id"]}]}, "exactly one video"),
        ({"media_ids": [img["id"], vid["id"]], "targets": [{"integration_id": fb["id"]}]}, "can't mix"),
        ({"targets": [{"integration_id": fb["id"]}]}, "needs some text"),
        ({"text": "x", "targets": [{"integration_id": fb["id"]}], "scheduled_at": "2020-01-01T00:00:00Z"}, "in the past"),
    ]
    for body, msg in cases:
        r = auth.post("/api/publish", json=body)
        assert r.status_code == 422 and msg in r.json()["detail"], (body, r.text)
    assert auth.get("/api/publish").json() == [] and auth.get("/api/posts").json() == []
    r = auth.post("/api/publish/media", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 422


def test_post_photos_everywhere_now(auth, accounts, fake):
    fb, ig, yt = accounts
    imgs = upload(auth, ("a.png", png_bytes(), "image/png"), ("b.jpg", b"", "image/jpeg"))
    # png got a JPEG copy for Instagram; public link serves it as JPEG
    r = auth.get(imgs[0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert auth.get("/api/media/public/doesnotexist_token_value_x.jpg").status_code == 404
    r = auth.post("/api/publish", json={"text": "New jerky flavors are live", "link": "https://shop.example.com",
                                        "media_ids": [m["id"] for m in imgs],
                                        "targets": [{"integration_id": fb["id"]}, {"integration_id": ig["id"]}]})
    assert r.status_code == 201, r.text
    job = auth.get(f"/api/publish/{r.json()['id']}").json()
    assert job["status"] == "done", job
    t = {x["platform"]: x for x in job["targets"]}
    assert t["facebook"]["status"] == "posted" and t["facebook"]["external_id"].startswith("PAGE1_feed")
    assert t["facebook"]["url"].startswith("https://www.facebook.com/PAGE1/posts/")
    assert t["instagram"]["status"] == "posted" and t["instagram"]["url"].startswith("https://www.instagram.com/p/")
    feed = next(f for f in fake.forms if f["path"] == "PAGE1/feed")
    assert feed["message"].endswith("https://shop.example.com") and "attached_media[1]" in feed
    carousel = next(f for f in fake.forms if f.get("media_type") == "CAROUSEL")
    assert len(carousel["children"].split(",")) == 2 and "New jerky" in carousel["caption"]
    children = [f for f in fake.forms if f.get("is_carousel_item") == "true"]
    assert all(c["image_url"].startswith("https://scontent.fbcdn.net/") for c in children)
    assert len(fake.deleted) == 2, "staged Facebook copies are removed after Instagram publishes"
    posts = auth.get("/api/posts").json()
    assert {p["status"] for p in posts} == {"published"} and len(posts) == 2
    with SessionLocal() as db:
        from app.models import Post
        rows = db.query(Post).all()
        assert {(p.external_source, p.external_id) for p in rows} == {("facebook", t["facebook"]["external_id"]),
                                                                      ("instagram", t["instagram"]["external_id"])}


def test_youtube_upload_and_facebook_video_and_reel(auth, accounts, fake):
    fb, ig, yt = accounts
    youtube_sign_in(auth, yt)
    vid = upload(auth, ("Elk camp.mp4", VIDEO, "video/mp4"))[0]
    r = auth.post("/api/publish", json={
        "title": "Elk camp recap", "text": "Day 3 at elk camp", "media_ids": [vid["id"]],
        "targets": [{"integration_id": yt["id"], "options": {"privacy": "unlisted", "tags": "elk, hunting"}},
                    {"integration_id": fb["id"]}, {"integration_id": ig["id"]}]})
    job = auth.get(f"/api/publish/{r.json()['id']}").json()
    t = {x["platform"]: x for x in job["targets"]}
    assert job["status"] == "done", job
    assert t["youtube"]["status"] == "processing" and t["youtube"]["url"] == "https://www.youtube.com/watch?v=yt123"
    assert fake.yt_received == VIDEO
    assert t["facebook"]["external_id"] == "V1" and sum(fake.fb_chunks) == len(VIDEO) and len(fake.fb_chunks) == 2
    finish = next(f for f in fake.forms if f.get("upload_phase") == "finish")
    assert finish["title"] == "Elk camp recap" and finish["description"] == "Day 3 at elk camp"
    assert fake.ig_bytes == VIDEO and t["instagram"]["external_id"] == "IGM_C9"
    reels = next(f for f in fake.forms if f.get("media_type") == "REELS")
    assert reels["upload_type"] == "resumable" and reels["share_to_feed"] == "true"
    # Facebook Reel option
    r = auth.post("/api/publish", json={"text": "Quick tip", "media_ids": [vid["id"]],
                                        "targets": [{"integration_id": fb["id"], "options": {"as_reel": True}}]})
    t = auth.get(f"/api/publish/{r.json()['id']}").json()["targets"][0]
    assert t["status"] == "processing" and t["url"] == "https://www.facebook.com/reel/R1" and fake.reel_bytes == VIDEO
    # one Content row per platform post, tagged so later syncs update it instead of duplicating
    posts = [p for p in auth.get("/api/posts").json() if "youtube.com" in (p.get("url") or "")]
    assert len(posts) == 1


def test_instagram_video_falls_back_to_public_address(auth, accounts, fake):
    fb, ig, yt = accounts
    fake.ig_resumable_ok = False
    vid = upload(auth, ("reel.mp4", VIDEO, "video/mp4"))[0]
    r = auth.post("/api/publish", json={"text": "reel", "media_ids": [vid["id"]], "targets": [{"integration_id": ig["id"]}]})
    t = auth.get(f"/api/publish/{r.json()['id']}").json()["targets"][0]
    assert t["status"] == "failed" and "public media address" in t["error"]
    auth.patch(f"/api/integrations/{ig['id']}", json={"values": {"public_base_url": "https://mserver.tail1.ts.net/"}})
    r = auth.post(f"/api/publish/{r.json()['id']}/retry")
    assert r.status_code == 200
    job = auth.get(f"/api/publish/{r.json()['id']}").json()
    assert job["status"] == "done" and job["targets"][0]["attempts"] == 2
    form = [f for f in fake.forms if f.get("video_url")][-1]
    assert form["video_url"] == f"https://mserver.tail1.ts.net{vid['url']}"


def test_schedule_edit_cancel_and_run_due(auth, accounts, fake):
    fb, ig, yt = accounts
    when = (utcnow() + timedelta(hours=2)).isoformat() + "Z"
    r = auth.post("/api/publish", json={"text": "Sale starts Friday", "targets": [{"integration_id": fb["id"]}],
                                        "scheduled_at": when})
    job = r.json()
    assert job["status"] == "scheduled" and job["targets"][0]["status"] == "pending"
    posts = auth.get("/api/posts").json()
    assert posts[0]["status"] == "scheduled", "scheduled posts show up in Content"
    runner.run_due()
    assert auth.get(f"/api/publish/{job['id']}").json()["status"] == "scheduled" and not fake.forms
    r = auth.patch(f"/api/publish/{job['id']}", json={"text": "Sale starts Saturday"})
    assert r.json()["text"] == "Sale starts Saturday" and auth.get("/api/posts").json()[0]["body"] == "Sale starts Saturday"
    with SessionLocal() as db:                    # time passes
        db.get(PublishJob, job["id"]).scheduled_at = utcnow() - timedelta(minutes=1)
        db.commit()
    runner.run_due()
    done = auth.get(f"/api/publish/{job['id']}").json()
    assert done["status"] == "done" and fake.forms[-1]["message"] == "Sale starts Saturday"
    assert auth.get("/api/posts").json()[0]["status"] == "published"
    # cancel another scheduled post: its placeholder in Content is removed
    r = auth.post("/api/publish", json={"text": "later", "targets": [{"integration_id": fb["id"]}], "scheduled_at": when})
    assert auth.post(f"/api/publish/{r.json()['id']}/cancel").json()["status"] == "canceled"
    assert len(auth.get("/api/posts").json()) == 1
    assert auth.delete(f"/api/publish/{r.json()['id']}").status_code == 204


def test_restart_marks_interrupted_and_cleanup(auth, accounts, fake):
    fb, ig, yt = accounts
    img = upload(auth, ("a.png", png_bytes(), "image/png"))[0]
    r = auth.post("/api/publish", json={"text": "x", "media_ids": [img["id"]], "targets": [{"integration_id": fb["id"]}],
                                        "scheduled_at": (utcnow() + timedelta(hours=1)).isoformat() + "Z"})
    with SessionLocal() as db:
        j = db.get(PublishJob, r.json()["id"])
        j.status, j.targets[0].status = "posting", "posting"
        db.commit()
    runner.reset_interrupted()
    job = auth.get(f"/api/publish/{r.json()['id']}").json()
    assert job["status"] == "failed" and "Interrupted" in job["targets"][0]["error"]
    with SessionLocal() as db:
        db.get(PublishJob, job["id"]).finished_at = utcnow() - timedelta(days=15)
        db.commit()
    assert runner.cleanup_media(force=True) == 1
    job = auth.get(f"/api/publish/{job['id']}").json()
    assert job["media_deleted"] and auth.post(f"/api/publish/{job['id']}/retry").status_code == 409
