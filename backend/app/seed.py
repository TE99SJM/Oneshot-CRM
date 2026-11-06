"""Demo data so every screen has something to show.  Run:  python -m app.seed"""
import random
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Activity, Channel, Contact, Deal, Funnel, FunnelStage, Post, utcnow


def has_business_data(db: Session) -> bool:
    return bool(db.scalar(select(func.count(Contact.id))) or db.scalar(select(func.count(Channel.id))))


def seed_demo(db: Session) -> dict:
    rnd = random.Random(42)
    now = utcnow()

    channels = [
        Channel(name="YouTube", kind="social", platform="youtube", handle="@gamingoutdoorsmen",
                url="https://youtube.com/@gamingoutdoorsmen", followers=4200),
        Channel(name="Facebook Page", kind="social", platform="facebook", handle="Gaming Outdoorsmen", followers=2650),
        Channel(name="Rumble", kind="social", platform="rumble", handle="gamingoutdoorsmen", followers=880),
        Channel(name="TikTok", kind="social", platform="tiktok", handle="@gamingoutdoorsmen", followers=6100),
        Channel(name="Online Store", kind="website", platform="shopify", url="https://example.com", monthly_cost=39),
        Channel(name="Email List", kind="email", platform="mailchimp", followers=740, monthly_cost=13),
        Channel(name="Facebook Ads", kind="ads", platform="meta", monthly_cost=150),
        Channel(name="Referrals", kind="direct"),
    ]
    db.add_all(channels)
    db.flush()

    product = Funnel(name="Product Sales", description="Social content -> store visit -> purchase")
    product.stages = [FunnelStage(name=n, probability=p, kind=k, position=i) for i, (n, p, k) in enumerate([
        ("Engaged", 5, "open"), ("Lead captured", 20, "open"), ("Cart / quote", 50, "open"),
        ("Checkout", 80, "open"), ("Won", 100, "won"), ("Lost", 0, "lost")])]
    sponsor = Funnel(name="Sponsorships", description="Brand deals and paid partnerships")
    sponsor.stages = [FunnelStage(name=n, probability=p, kind=k, position=i) for i, (n, p, k) in enumerate([
        ("Outreach", 10, "open"), ("Pitch sent", 25, "open"), ("Negotiating", 60, "open"),
        ("Signed", 100, "won"), ("Declined", 0, "lost")])]
    db.add_all([product, sponsor])
    db.flush()

    first = ["Jake", "Emma", "Luke", "Olivia", "Mason", "Ava", "Cole", "Mia", "Wyatt", "Lily", "Hunter", "Grace",
             "Tyler", "Chloe", "Brady", "Nora", "Logan", "Ruby", "Carter", "Hazel"]
    last = ["Anderson", "Johnson", "Peterson", "Olson", "Larson", "Nelson", "Carlson", "Hanson", "Berg", "Lund"]
    companies = ["", "", "", "North Woods Outfitters", "Lakeside Bait & Tackle", "Prairie Gear Co.", "Ridge Line Optics"]
    statuses = ["lead"] * 5 + ["prospect"] * 3 + ["customer"] * 3 + ["inactive"]
    contacts = []
    for i in range(32):
        fn, ln = rnd.choice(first), rnd.choice(last)
        c = Contact(first_name=fn, last_name=ln, email=f"{fn.lower()}.{ln.lower()}{i}@example.com",
                    phone=f"218-555-{1000 + i:04d}", company=rnd.choice(companies), status=rnd.choice(statuses),
                    source_channel_id=rnd.choice(channels).id,
                    tags=",".join(rnd.sample(["hunting", "fishing", "gaming", "wholesale", "vip", "newsletter"], 2)))
        c.created_at = now - timedelta(days=rnd.randint(0, 120))
        contacts.append(c)
    db.add_all(contacts)
    db.flush()

    deals = []
    titles_p = ["Decoy bundle", "Trail cam kit", "Merch order", "Ice fishing package", "Custom decal set", "Gift card"]
    titles_s = ["Optics brand review", "Apparel sponsorship", "Tackle box integration", "Energy drink spot"]
    for i in range(26):
        f = product if i < 18 else sponsor
        stage = rnd.choice(f.stages)
        d = Deal(title=rnd.choice(titles_p if f is product else titles_s), funnel_id=f.id, stage_id=stage.id,
                 status=stage.kind, value=round(rnd.uniform(25, 400) if f is product else rnd.uniform(300, 2500), 2),
                 contact_id=rnd.choice(contacts).id, channel_id=rnd.choice(channels).id,
                 expected_close=(now + timedelta(days=rnd.randint(3, 45))).date())
        d.created_at = now - timedelta(days=rnd.randint(1, 150))
        if stage.kind != "open":
            d.closed_at = now - timedelta(days=rnd.randint(0, 90))
        deals.append(d)
    db.add_all(deals)

    social = [c for c in channels if c.kind == "social"]
    ideas = ["Opening day prep", "Gear review: budget trail cams", "Ice house tour", "Duck call tutorial",
             "Truck bed storage build", "Q&A livestream", "Top 5 lures for walleye", "Behind the scenes"]
    for i in range(20):
        ch = rnd.choice(social)
        offset = rnd.randint(-40, 14)
        when = (now + timedelta(days=offset)).replace(hour=rnd.choice([9, 12, 18]), minute=0, second=0, microsecond=0)
        status = "published" if offset < 0 else rnd.choice(["idea", "draft", "scheduled"])
        p = Post(channel_id=ch.id, title=rnd.choice(ideas), status=status,
                 body="Hook, value, call to action -> link in bio.",
                 scheduled_at=when if status != "idea" else None, published_at=when if status == "published" else None)
        if status == "published":
            p.views = rnd.randint(300, 15000)
            p.likes, p.comments = p.views // rnd.randint(15, 40), p.views // rnd.randint(80, 200)
            p.shares, p.clicks = p.views // rnd.randint(100, 300), p.views // rnd.randint(40, 120)
        db.add(p)

    for i in range(10):
        c = rnd.choice(contacts)
        db.add(Activity(kind=rnd.choice(["note", "call", "email", "dm"]), contact_id=c.id,
                        summary=rnd.choice(["Asked about bulk pricing", "Left voicemail", "Sent catalog link",
                                            "DM'd after comment on video", "Interested in spring order"])))
    for i in range(6):
        db.add(Activity(kind="task", contact_id=rnd.choice(contacts).id,
                        summary=rnd.choice(["Follow up on quote", "Send sponsor media kit", "Ship sample",
                                            "Check in after purchase"]),
                        due_at=now + timedelta(days=rnd.randint(-3, 7))))
    db.commit()
    return {"channels": len(channels), "contacts": len(contacts), "deals": len(deals), "funnels": 2, "posts": 20}


if __name__ == "__main__":
    from .database import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        if has_business_data(session):
            print("Database already has data; demo seed skipped.")
        else:
            print("Seeded:", seed_demo(session))
