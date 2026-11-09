"""Channel data: API metrics saved at sync, CRM-derived numbers, display choices, combined dashboard."""
from datetime import date, timedelta

import httpx

from app.database import SessionLocal
from app.integrations import facebook, service
from app.integrations.base import SyncContext
from app.integrations.registry import PROVIDERS
from app.models import Channel, ChannelMetric, Integration, MetricSnapshot, Order, Post, utcnow


def _sync(monkeypatch, provider, fn, name="Conn"):
    monkeypatch.setattr(PROVIDERS[provider], "sync", fn)
    with SessionLocal() as db:
        integ = Integration(provider=provider, name=name, config="{}")
        db.add(integ)
        db.commit()
        service.run_sync(db, db.get(Integration, integ.id))
        i = db.get(Integration, integ.id)
        assert i.last_status == "ok", i.last_error
        return i.channel_id


def test_api_metrics_saved_and_listed(auth, monkeypatch):
    def yt(ctx):
        ctx.stats["followers"] = 1200
        ctx.metric("yt_minutes_watched_28d", 5400, "Minutes watched", "minutes", "Watch time", "28d")
        ctx.metric("yt_avg_view_pct_28d", 41.5, "Average % viewed", "pct", "Watch time", "28d", "avg")
        ctx.metric("skipped", None)
        ctx.db.add(Post(channel_id=ctx.channel.id, title="a", status="published", views=100, likes=8, comments=2,
                        published_at=utcnow() - timedelta(days=2)))
        ctx.db.add(Post(channel_id=ctx.channel.id, title="b", status="published", views=300, likes=10,
                        published_at=utcnow() - timedelta(days=40)))
    cid = _sync(monkeypatch, "youtube", yt)
    with SessionLocal() as db:                      # pretend we had a reading 10 days ago
        db.add(MetricSnapshot(channel_id=cid, key="followers", day=date.today() - timedelta(days=10), value=1000))
        db.commit()
    start = (date.today() - timedelta(days=7)).isoformat()
    data = auth.get(f"/api/metrics/channels/{cid}", params={"start": start, "end": date.today().isoformat()}).json()
    m = {x["key"]: x for x in data["metrics"]}
    assert m["followers"]["value"] == 1200 and m["followers"]["source"] == "api" and m["followers"]["change"] == 200
    assert m["yt_minutes_watched_28d"]["unit"] == "minutes" and m["yt_minutes_watched_28d"]["window_label"] == "last 28 days"
    assert "skipped" not in m
    assert m["posts"]["value"] == 1 and m["post_views"]["value"] == 100 and m["posts_all"]["value"] == 2
    assert m["engagement_rate"]["value"] == 10.0 and m["posts"]["source"] == "crm"
    assert data["is_default"] and data["display"].count("followers") == 1 and data["channel"]["group"] == "social"
    # choose what to show
    r = auth.put(f"/api/metrics/channels/{cid}/display", json={"keys": ["yt_minutes_watched_28d", "followers", "followers"]})
    assert r.json() == {"display": ["yt_minutes_watched_28d", "followers"], "is_default": False}
    assert auth.get(f"/api/metrics/channels/{cid}").json()["display"] == ["yt_minutes_watched_28d", "followers"]
    r = auth.put(f"/api/metrics/channels/{cid}/display", json={"reset": True}).json()
    assert r["is_default"]
    assert auth.put("/api/metrics/channels/9999/display", json={"keys": []}).status_code == 404


def test_sales_derived_and_combined_by_type(auth, monkeypatch):
    def shop(ctx):
        for ext, total, state, who in [("o1", 50, "COMPLETED", "a@x.com"), ("o2", 30, "COMPLETED", "a@x.com"),
                                       ("o3", 20, "CANCELED", "b@x.com"), ("o4", 100, "COMPLETED", "c@x.com")]:
            ctx.db.add(Order(source="square", external_id=ext, channel_id=ctx.channel.id, total=total, net=total - 2,
                             processing_fee=2, item_count=2, state=state, customer_email=who, ordered_at=utcnow()))
        ctx.metric("square_items", 12, "Catalog items", "num", "Products")
    sq = _sync(monkeypatch, "square", shop, "Shop")
    def tt(ctx):
        ctx.metric("followers", 500)
        ctx.metric("total_likes_received", 9000)
    def yt(ctx):
        ctx.metric("followers", 1500)
        ctx.metric("total_likes_received", 1000)
    a = _sync(monkeypatch, "tiktok", tt, "TT")
    b = _sync(monkeypatch, "youtube", yt, "YT")
    m = {x["key"]: x["value"] for x in auth.get(f"/api/metrics/channels/{sq}").json()["metrics"]}
    assert m["orders"] == 3 and m["gross_sales"] == 180 and m["net_sales"] == 174 and m["canceled_orders"] == 1
    assert m["buyers"] == 2 and m["repeat_buyers"] == 1 and m["avg_order_value"] == 60 and m["items_sold"] == 6
    for cid in (a, b):
        auth.put(f"/api/metrics/channels/{cid}/display", json={"keys": ["followers", "total_likes_received"]})
    with SessionLocal() as db:            # Square channel -> sales group
        assert db.get(Channel, sq).kind in ("direct", "marketplace", "website")
    auth.put(f"/api/metrics/channels/{sq}/display", json={"keys": ["gross_sales", "avg_order_value", "square_items"]})
    groups = {g["key"]: g for g in auth.get("/api/metrics/combined").json()["groups"]}
    social = {x["key"]: x for x in groups["social"]["metrics"]}
    assert social["followers"]["total"] == 2000 and social["followers"]["channels"] == 2
    assert social["total_likes_received"]["total"] == 10000
    assert [p["channel"] for p in social["followers"]["per_channel"]] == ["YT", "TT"]
    sales = {x["key"]: x for x in groups["sales"]["metrics"]}
    assert sales["gross_sales"]["total"] == 180 and sales["square_items"]["total"] == 12
    assert groups["sales"]["label"] == "Sales channels" and "followers" not in sales


def test_combined_average_and_metric_update(auth, monkeypatch):
    vals = iter([40, 60, 50])
    def fn(ctx):
        ctx.metric("rate", next(vals), "Rate", "pct", "Engagement", "28d", "avg")
    a = _sync(monkeypatch, "youtube", fn, "A")
    b = _sync(monkeypatch, "tiktok", fn, "B")
    for cid in (a, b):
        auth.put(f"/api/metrics/channels/{cid}/display", json={"keys": ["rate"]})
    g = auth.get("/api/metrics/combined").json()["groups"][0]
    assert g["metrics"][0]["total"] == 50 and g["metrics"][0]["change"] is None
    with SessionLocal() as db:            # a re-sync updates the row and today's snapshot instead of adding
        integ = db.query(Integration).filter_by(name="A").one()
        service.run_sync(db, integ)
        assert db.query(ChannelMetric).filter_by(channel_id=a, key="rate").one().value == 50
        assert db.query(MetricSnapshot).filter_by(channel_id=a, key="rate").count() == 1


def test_facebook_insights_fall_back_one_by_one(client):
    calls = []
    def h(req):
        m = req.url.params.get("metric")
        calls.append(m)
        if "," in (m or "") or m == "page_impressions":
            return httpx.Response(400, json={"error": {"message": "(#100) The value must be a valid insights metric"}})
        return httpx.Response(200, json={"data": [{"name": m, "values": [{"value": 7}, {"value": 11}]}]})
    with SessionLocal() as db, httpx.Client(transport=httpx.MockTransport(h)) as c:
        ch = Channel(name="Page", kind="social", platform="Facebook")
        db.add(ch)
        db.flush()
        ctx = SyncContext(db=db, client=c, channel=ch, config={}, secrets={"page_token": "t"}, last_sync_at=None)
        facebook._page_metrics(ctx, {"id": "1", "followers_count": 300, "fan_count": 280, "overall_star_rating": 4.6})
    assert len(calls) == 1 + len(facebook.INSIGHTS)
    assert ctx.metrics["followers"]["value"] == 300 and ctx.metrics["fb_star_rating"]["unit"] == "stars"
    assert ctx.metrics["fb_media_views_28d"]["value"] == 11 and "fb_impressions_28d" not in ctx.metrics


def test_period_validation(auth):
    assert auth.get("/api/metrics/combined", params={"start": "2026-02-02", "end": "2026-02-01"}).status_code == 422
    assert auth.get("/api/metrics/channels").status_code == 200
