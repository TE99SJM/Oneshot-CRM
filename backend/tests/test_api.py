def test_health_and_setup_flow(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/auth/status").json()["needs_setup"] is True
    assert client.get("/api/contacts").status_code == 401
    r = client.post("/api/auth/setup", json={"email": "Me@Example.com", "password": "supersecret"})
    assert r.status_code == 201
    assert client.post("/api/auth/setup", json={"email": "x@y.com", "password": "supersecret"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": "wrong"}).status_code == 401
    tok = client.post("/api/auth/login", json={"email": "me@example.com", "password": "supersecret"}).json()
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert me.json()["email"] == "me@example.com"


def test_channel_contact_crud_and_filters(auth):
    ch = auth.post("/api/channels", json={"name": "YouTube", "platform": "youtube", "followers": 100}).json()
    c = auth.post("/api/contacts", json={"first_name": "Ann", "email": "ann@x.com", "source_channel_id": ch["id"],
                                         "tags": "vip"}).json()
    auth.post("/api/contacts", json={"first_name": "Bob", "status": "customer"})
    assert auth.post("/api/contacts", json={"first_name": "Z", "source_channel_id": 999}).status_code == 422
    assert auth.get("/api/contacts").json()["total"] == 2
    assert auth.get("/api/contacts", params={"q": "ann"}).json()["total"] == 1
    assert auth.get("/api/contacts", params={"status": "customer"}).json()["items"][0]["first_name"] == "Bob"
    assert auth.get("/api/contacts", params={"channel_id": ch["id"]}).json()["total"] == 1
    r = auth.patch(f"/api/contacts/{c['id']}", json={"status": "prospect", "source_channel_id": None})
    assert r.json()["status"] == "prospect" and r.json()["source_channel_id"] is None
    stats = auth.get("/api/channels").json()[0]
    assert stats["contacts"] == 0
    assert auth.delete(f"/api/contacts/{c['id']}").status_code == 204
    assert auth.get(f"/api/contacts/{c['id']}").status_code == 404


def test_csv_round_trip(auth):
    auth.post("/api/channels", json={"name": "Etsy", "kind": "marketplace"})
    csv_body = "first_name,last_name,email,status,source_channel\nAl,Smith,al@x.com,customer,Etsy\n,,bad@x.com,,\n"
    r = auth.post("/api/contacts/import", files={"file": ("c.csv", csv_body, "text/csv")})
    assert r.json() == {"created": 1, "skipped": 1}
    again = auth.post("/api/contacts/import", files={"file": ("c.csv", csv_body, "text/csv")})
    assert again.json()["created"] == 0
    out = auth.get("/api/contacts/export.csv")
    assert "al@x.com" in out.text and "Etsy" in out.text


def test_funnel_and_deal_stage_moves(auth):
    f = auth.post("/api/funnels", json={"name": "Store"}).json()
    stages = {s["name"]: s for s in f["stages"]}
    assert len(stages) == 6
    d = auth.post("/api/deals", json={"title": "Kit", "value": 200, "funnel_id": f["id"],
                                      "stage_id": stages["Interest"]["id"]}).json()
    assert d["status"] == "open" and d["closed_at"] is None
    won = auth.patch(f"/api/deals/{d['id']}", json={"stage_id": stages["Won"]["id"]}).json()
    assert won["status"] == "won" and won["closed_at"]
    reopened = auth.patch(f"/api/deals/{d['id']}", json={"stage_id": stages["Intent"]["id"]}).json()
    assert reopened["status"] == "open" and reopened["closed_at"] is None

    # stage editing: cannot delete a stage holding deals
    keep = [{"id": s["id"], "name": s["name"], "probability": s["probability"], "kind": s["kind"]}
            for s in f["stages"] if s["name"] != "Intent"]
    assert auth.put(f"/api/funnels/{f['id']}", json={"name": "Store", "stages": keep}).status_code == 409
    # rename + add a stage
    full = [{"id": s["id"], "name": s["name"] + "!", "probability": s["probability"], "kind": s["kind"]}
            for s in f["stages"]] + [{"name": "Upsell", "probability": 90}]
    upd = auth.put(f"/api/funnels/{f['id']}", json={"name": "Store 2", "stages": full}).json()
    assert upd["name"] == "Store 2" and len(upd["stages"]) == 7 and upd["stages"][-1]["position"] == 6

    other = auth.post("/api/funnels", json={"name": "Other"}).json()
    bad = auth.post("/api/deals", json={"title": "x", "funnel_id": f["id"], "stage_id": other["stages"][0]["id"]})
    assert bad.status_code == 422


def test_posts_activities_dashboard(auth):
    ch = auth.post("/api/channels", json={"name": "TikTok"}).json()
    p = auth.post("/api/posts", json={"title": "Clip", "channel_id": ch["id"], "status": "published",
                                      "views": 1000, "likes": 50}).json()
    assert p["published_at"] is not None
    auth.post("/api/posts", json={"title": "Idea"})
    assert len(auth.get("/api/posts", params={"status": "idea"}).json()) == 1
    c = auth.post("/api/contacts", json={"first_name": "Ann"}).json()
    t = auth.post("/api/activities", json={"kind": "task", "summary": "Call", "contact_id": c["id"],
                                           "due_at": "2020-01-01T09:00:00"}).json()
    assert len(auth.get("/api/activities", params={"open_tasks": True}).json()) == 1
    dash = auth.get("/api/dashboard").json()
    assert dash["kpis"]["posts_published"] == 1 and dash["kpis"]["views"] == 1000
    assert dash["open_tasks"][0]["overdue"] is True
    auth.patch(f"/api/activities/{t['id']}", json={"done": True})
    assert auth.get("/api/activities", params={"open_tasks": True}).json() == []


def test_demo_seed(auth):
    r = auth.post("/api/demo/seed")
    assert r.status_code == 200 and r.json()["contacts"] == 32
    assert auth.post("/api/demo/seed").status_code == 409
    dash = auth.get("/api/dashboard").json()
    assert dash["kpis"]["contacts"] == 32 and len(dash["funnels"]) == 2
    assert len(auth.get("/api/channels").json()) == 8


def test_channel_import(auth):
    csv_text = (
        "Name,Type,Platform,Handle,URL,Followers / subscribers,Monthly cost (USD),Active,Notes\n"
        "The Forge - YouTube,Social,youtube,@The_Forge_sports,https://www.youtube.com/@The_Forge_sports,,,TRUE,\"Note, with comma\"\n"
        "The Forge - Main website,Website / store,Porkbun,,https://mooresforge.com,,$1.25,TRUE,Domain\n"
        "The Forge - Rumble,Social,rumble,,,1.2K,,FALSE,Placeholder\n"
        "Bad,Social,x,,,lots,,,\n"
        ",,,,,,,,\n"
    )
    r = auth.post("/api/channels/import", files={"file": ("c.csv", csv_text, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3 and r.json()["skipped"] == 1 and len(r.json()["errors"]) == 1
    chans = {c["name"]: c for c in auth.get("/api/channels").json()}
    assert chans["The Forge - Main website"]["kind"] == "website" and chans["The Forge - Main website"]["monthly_cost"] == 1.25
    assert chans["The Forge - Main website"]["platform"] == "porkbun"
    assert chans["The Forge - Rumble"]["followers"] == 1200 and chans["The Forge - Rumble"]["active"] is False
    assert chans["The Forge - YouTube"]["notes"] == "Note, with comma"
    # re-import updates instead of duplicating; tab-separated works too
    tsv = "Name\tFollowers / subscribers\nThe Forge - YouTube\t1500\n"
    r = auth.post("/api/channels/import", files={"file": ("c.tsv", tsv, "text/plain")}).json()
    assert r["updated"] == 1 and r["created"] == 0
    chans = {c["name"]: c for c in auth.get("/api/channels").json()}
    assert chans["The Forge - YouTube"]["followers"] == 1500 and chans["The Forge - YouTube"]["handle"] == "@The_Forge_sports"
    exp = auth.get("/api/channels/export").text
    assert exp.startswith("Name,Type,Platform") and "Website / store" in exp
