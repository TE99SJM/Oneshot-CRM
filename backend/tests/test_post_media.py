"""Attachments persist with content-calendar plans and survive normal upload cleanup."""
from datetime import timedelta

from sqlalchemy import create_engine, inspect, select, text

from app.database import Base, SessionLocal
from app.models import MediaFile, PostAttachment, PublishJob, PublishTarget, utcnow
from app.publishing import media as media_store, runner
from test_publish import VIDEO, png_bytes


def upload(auth, name="photo.png", data=None, mime="image/png"):
    r = auth.post("/api/publish/media", files=[("files", (name, data or png_bytes(), mime))])
    assert r.status_code == 201, r.text
    return r.json()[0]


def test_plan_saves_reopens_reorders_and_removes_media(auth):
    photo = upload(auth)
    video = upload(auth, "hunt.mp4", VIDEO, "video/mp4")
    response = auth.post("/api/posts", json={"title": "Daylight scope", "body": "Draft caption", "status": "draft",
        "media_ids": [photo["id"], video["id"]]})
    assert response.status_code == 201, response.text
    p = response.json()
    assert p["media_ids"] == [photo["id"], video["id"]]
    assert [m["filename"] for m in p["media"]] == ["photo.png", "hunt.mp4"]
    assert auth.get(f"/api/posts/{p['id']}").json()["media"] == p["media"]
    assert auth.get("/api/posts").json()[0]["media"] == p["media"]
    assert auth.get(video["url"]).content == VIDEO
    assert auth.get(photo["url"]).headers["content-type"] == "image/jpeg"
    # Editing text or dates does not clear attachments unless media_ids is provided.
    changed = auth.patch(f"/api/posts/{p['id']}", json={"body": "Updated caption"}).json()
    assert changed["media_ids"] == p["media_ids"]
    assert auth.patch(f"/api/posts/{p['id']}", json={"media_ids": [video["id"], photo["id"]]}).status_code == 200
    assert auth.get(f"/api/posts/{p['id']}").json()["media_ids"] == [video["id"], photo["id"]]
    changed = auth.patch(f"/api/posts/{p['id']}", json={"media_ids": [photo["id"]]}).json()
    assert changed["media_ids"] == [photo["id"]]
    assert auth.delete(f"/api/publish/media/{video['id']}").status_code == 204
    assert auth.get(photo["url"]).status_code == 200


def test_saved_plan_protects_files_until_detached(auth):
    photo = upload(auth)
    post = auth.post("/api/posts", json={"title": "Keep this", "media_ids": [photo["id"]]}).json()
    assert auth.delete(f"/api/publish/media/{photo['id']}").status_code == 409
    with SessionLocal() as db:
        db.get(MediaFile, photo["id"]).created_at = utcnow() - timedelta(days=60)
        db.commit()
    assert runner.cleanup_media(force=True) == 0
    assert auth.get(photo["url"]).status_code == 200
    assert auth.delete(f"/api/posts/{post['id']}").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(PostAttachment.post_id)) is None
    assert runner.cleanup_media(force=True) == 1
    assert auth.get(photo["url"]).status_code == 404


def test_invalid_attachments_do_not_modify_post(auth):
    photo = upload(auth)
    post = auth.post("/api/posts", json={"title": "Original", "media_ids": [photo["id"]]}).json()
    for ids, expected in [([999999], 404), ([photo["id"], photo["id"]], 422), ([photo["id"]] * 21, 422), (None, 422)]:
        r = auth.patch(f"/api/posts/{post['id']}", json={"title": "Must not save", "media_ids": ids})
        assert r.status_code == expected
        current = auth.get(f"/api/posts/{post['id']}").json()
        assert current["title"] == "Original" and current["media_ids"] == [photo["id"]]


def test_active_publish_job_cannot_silently_change_attachments(auth):
    photo = upload(auth)
    post = auth.post("/api/posts", json={"title": "Queued", "media_ids": [photo["id"]]}).json()
    with SessionLocal() as db:
        job = PublishJob(status="scheduled")
        job.targets.append(PublishTarget(platform="facebook", name="Page", post_id=post["id"]))
        db.add(job)
        db.commit()
    assert auth.patch(f"/api/posts/{post['id']}", json={"media_ids": []}).status_code == 409
    assert auth.patch(f"/api/posts/{post['id']}", json={"body": "Text", "media_ids": [photo["id"]]}).status_code == 200


def test_mixed_invalid_upload_cleans_partial_files(auth, monkeypatch, tmp_path):
    monkeypatch.setattr(media_store, "MEDIA_DIR", tmp_path)
    r = auth.post("/api/publish/media", files=[("files", ("good.png", png_bytes(), "image/png")),
        ("files", ("bad.txt", b"not media", "text/plain"))])
    assert r.status_code == 422
    assert list(tmp_path.iterdir()) == []
    with SessionLocal() as db:
        assert db.scalar(select(MediaFile.id)) is None


def test_attachment_table_is_additive_for_existing_installations(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    # Existing posts are untouched when startup creates the new association table.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT)"))
        conn.execute(text("INSERT INTO posts (id, title) VALUES (1, 'Existing plan')"))
    Base.metadata.create_all(engine)
    assert "post_attachments" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM posts WHERE id=1")).scalar() == "Existing plan"
    engine.dispose()
