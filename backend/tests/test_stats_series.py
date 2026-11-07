from datetime import timedelta

from app.database import SessionLocal
from app.models import Channel, Contact, Deal, StatSnapshot, utcnow


def test_series_all_metrics_after_demo(auth):
    assert auth.post("/api/demo/seed").status_code in (200, 201)
    for m in ["won_revenue", "open_pipeline", "win_rate", "contacts", "new_contacts", "audience", "views"]:
        r = auth.get(f"/api/dashboard/series/{m}", params={"tz_offset": -360})
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["bucket"] in ("day", "week", "month") and s["points"]
        assert all(p["start"] <= p["end"] for p in s["points"])
    assert auth.get("/api/dashboard/series/bogus").status_code == 404


def test_series_values_and_buckets(auth):
    now = utcnow()
    with SessionLocal() as db:
        f = auth.post("/api/funnels", json={"name": "S"}).json()
        stages = {s["name"]: s for s in f["stages"]}
        won_id = next(s["id"] for s in f["stages"] if s["kind"] == "won")
        lost_id = next(s["id"] for s in f["stages"] if s["kind"] == "lost")
        open_id = next(s["id"] for s in f["stages"] if s["kind"] == "open")
        assert stages
        db.add_all([
            Deal(title="a", value=100, funnel_id=f["id"], stage_id=won_id, status="won",
                 created_at=now - timedelta(days=5), closed_at=now - timedelta(days=2)),
            Deal(title="b", value=50, funnel_id=f["id"], stage_id=lost_id, status="lost",
                 created_at=now - timedelta(days=5), closed_at=now - timedelta(days=2)),
            Deal(title="c", value=70, funnel_id=f["id"], stage_id=open_id, status="open",
                 created_at=now - timedelta(days=3)),
            Contact(first_name="x", created_at=now - timedelta(days=4)),
            Contact(first_name="y", created_at=now - timedelta(days=1)),
            Channel(name="YT", platform="youtube", followers=120),
            StatSnapshot(metric="audience", day=(now - timedelta(days=3)).date(), value=100),
        ])
        db.commit()
    start = (now - timedelta(days=6)).date().isoformat()
    get = lambda m, **kw: auth.get(f"/api/dashboard/series/{m}", params={"start": start, **kw}).json()  # noqa: E731

    rev = get("won_revenue")
    assert rev["bucket"] == "day" and len(rev["points"]) == 7 and rev["total"] == 100
    pipe = [p["value"] for p in get("open_pipeline")["points"]]
    assert pipe[0] == 0 and max(pipe) == 220 and pipe[-1] == 70      # a+b+c open before day -2, only c after
    rate = [p["value"] for p in get("win_rate")["points"]]
    assert rate.count(None) == 6 and 50 in rate
    assert [p["value"] for p in get("contacts")["points"]][-1] == 2
    auth.get("/api/dashboard")                                          # records today's audience reading
    aud = [p["value"] for p in get("audience")["points"]]
    assert aud[0] is None and 100 in aud and aud[-1] == 120
    wk = get("won_revenue", bucket="week")
    assert wk["bucket"] == "week" and sum(p["value"] for p in wk["points"]) == 100
    assert auth.get("/api/dashboard/series/views", params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 422


def test_dashboard_period(auth):
    now = utcnow()
    with SessionLocal() as db:
        db.add_all([Contact(first_name="old", created_at=now - timedelta(days=100)),
                    Contact(first_name="new", created_at=now - timedelta(days=3))])
        db.commit()
    start = (now - timedelta(days=29)).date().isoformat()
    k = auth.get("/api/dashboard", params={"start": start}).json()["kpis"]
    assert k["contacts"] == 2 and k["new_contacts"] == 1
    assert auth.get("/api/dashboard").json()["kpis"]["new_contacts"] == 2          # all time
    assert auth.get("/api/dashboard", params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 422
