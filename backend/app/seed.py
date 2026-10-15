"""Deterministic demo data: 1 agency tenant, 6 users (one per role), 24 clients, reviews, keywords,
90 days of metrics, tasks and content. Run directly with `python -m app.seed --reset`."""

import random
import re
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine
from .models import (
    Client, ClientContact, ContentItem, ContentVariant, GmbAccount, Keyword, MetricDaily, Review, SocialAccount, Task, Tenant, User,
)
from .ai import PLATFORM_FORMAT
from .security import ensure_default_roles, hash_password
from .upgrade import add_missing_columns
from .sentiment import detect_sentiment

DEMO_PASSWORD = "demo1234"
# Demo mobile numbers for OTP sign-in (with SMS_PROVIDER=console the code is shown in the demo app / server log)
DEMO_PHONES = {"admin": "+919000000001", "account_manager": "+919000000002", "seo": "+919000000003", "content": "+919000000004",
               "designer": "+919000000005", "client": "+919876543210"}

USERS = [
    ("Aarav Mehta", "admin@greenmedia.in", "admin"),
    ("Priya Nair", "priya@greenmedia.in", "account_manager"),
    ("Rohit Verma", "rohit@greenmedia.in", "seo"),
    ("Sneha Iyer", "sneha@greenmedia.in", "content"),
    ("Kabir Shah", "kabir@greenmedia.in", "designer"),
    ("Dr. Anjali Rao", "anjali@smiledental.in", "client"),
]

BUSINESSES = [
    ("Smile Dental Studio", "Dental Clinic", "Pune"), ("Spice Route Kitchen", "Restaurant", "Bengaluru"),
    ("FitNation Gym", "Fitness", "Mumbai"), ("UrbanNest Realty", "Real Estate", "Hyderabad"),
    ("GlowUp Salon & Spa", "Beauty", "Delhi"), ("BrightKids Academy", "Education", "Chennai"),
    ("AutoCare Pro", "Automotive", "Ahmedabad"), ("Sunrise Eye Hospital", "Healthcare", "Jaipur"),
    ("The Coffee Collective", "Cafe", "Kochi"), ("LegalEase Associates", "Legal", "Kolkata"),
    ("PetPals Veterinary", "Veterinary", "Indore"), ("CraftWood Interiors", "Interior Design", "Surat"),
    ("Heritage Stay Homestay", "Hospitality", "Udaipur"), ("QuickFix Electricals", "Home Services", "Nagpur"),
    ("Zen Yoga Shala", "Wellness", "Rishikesh"), ("MediPlus Pharmacy", "Pharmacy", "Lucknow"),
    ("StyleStreet Boutique", "Retail", "Chandigarh"), ("CloudNine IVF Centre", "Healthcare", "Pune"),
    ("GreenLeaf Organics", "Grocery", "Mysuru"), ("PixelPerfect Studio", "Photography", "Goa"),
    ("SafeHands Physiotherapy", "Healthcare", "Nashik"), ("BookWorm Library Cafe", "Cafe", "Bhopal"),
    ("SkyHigh Travels", "Travel", "Vadodara"), ("IronCore Constructions", "Construction", "Coimbatore"),
]

FIRST = ["Rahul", "Neha", "Vikram", "Ananya", "Arjun", "Meera", "Karan", "Isha", "Dev", "Pooja", "Sanjay", "Tara", "Farhan", "Lakshmi", "John", "Simran"]
LAST = ["Sharma", "Patel", "Reddy", "Gupta", "Khan", "Das", "Joshi", "Menon", "Singh", "Kapoor", "Fernandes", "Bose"]

REVIEW_TEXT = [
    (5, "Absolutely wonderful experience. The staff were friendly and very professional. Highly recommend!", "en"),
    (5, "Best in the city! Quick service and great value for money.", "en"),
    (4, "Good service overall, a little wait time but worth it.", "en"),
    (5, "बहुत अच्छी सेवा, स्टाफ बहुत मददगार है।", "hi"),
    (3, "Service was okay. Nothing special, pricing could be clearer.", "en"),
    (2, "Waited over 40 minutes even with an appointment. Not happy with the delay.", "en"),
    (1, "Very rude behaviour at the front desk and nobody called me back. Terrible experience.", "en"),
    (4, "Clean place, polite team. Parking is a bit difficult.", "en"),
    (5, "They solved my problem in one visit. Thank you so much!", "en"),
    (2, "The quality has dropped compared to last year. Disappointed.", "en"),
]

KEYWORDS = ["{i} near me", "best {i} in {c}", "{i} {c}", "affordable {i}", "top rated {i}", "{i} open now"]
PLANS = ["Starter", "Growth", "Pro", "Agency"]


def seed(db: Session) -> None:
    r = random.Random(42)
    now = datetime.now(timezone.utc)
    today = date.today()

    tenant = Tenant(name="Green Media Technology")
    db.add(tenant)
    db.flush()
    ensure_default_roles(db, tenant.id)

    pw = hash_password(DEMO_PASSWORD)
    users = {role: User(tenant_id=tenant.id, name=n, email=e, password_hash=pw, role=role, phone=DEMO_PHONES[role]) for n, e, role in USERS}
    db.add_all(users.values())
    db.flush()
    managers = [users["account_manager"].id, users["admin"].id]

    for i, (name, industry, city) in enumerate(BUSINESSES):
        slug = re.sub(r"[^a-z0-9]+", "", name.lower())
        plan = PLANS[i % 4]
        services = ["GMB Management", "Review Management"]
        if plan != "Starter":
            services.append("Social Media")
        if plan in ("Pro", "Agency"):
            services += ["SEO", "Monthly Reports"]
        c = Client(
            tenant_id=tenant.id, company_name=name, website=f"https://www.{slug}.in", industry=industry, city=city,
            status="onboarding" if i == 5 else "paused" if i == 13 else "active", plan=plan, services=services,
            account_manager_id=managers[i % 2],
            brand_voice={
                "tone": r.choice(["Warm and professional", "Friendly and upbeat", "Premium and concise", "Caring and reassuring"]),
                "preferred_phrases": ["Thank you for choosing us", f"your trusted {industry.lower()} in {city}"],
                "prohibited_claims": ["guaranteed results", "best in the world", "cheapest"],
                "cta_style": r.choice(["Call us", "Book online", "Visit us today", "WhatsApp us"]),
                "languages": ["en", "hi"],
                "escalation_rule": "Ratings of 2 or less go to the account manager before any reply is published.",
            },
            auto_publish={},
        )
        db.add(c)
        db.flush()
        db.add(ClientContact(tenant_id=tenant.id, client_id=c.id, name=f"{r.choice(FIRST)} {r.choice(LAST)}", email=f"owner@{slug}.in", phone=f"+91 9{r.randint(100000000, 999999999)}", designation="Owner"))
        db.add(GmbAccount(tenant_id=tenant.id, client_id=c.id, location_id=f"locations/{r.randint(10**9, 9 * 10**9)}", status="disconnected" if i == 5 else "connected",
                          last_sync=None if i == 5 else now, rating=round(3.6 + r.random() * 1.3, 1), review_count=r.randint(40, 900)))
        for p in ["facebook", "instagram", "linkedin"][: 1 if plan == "Starter" else 3]:
            db.add(SocialAccount(tenant_id=tenant.id, client_id=c.id, platform=p, handle=f"@{slug}", status="expired" if (i == 7 and p == "instagram") else "connected"))

        for k in range(r.randint(3, 7)):
            rating, text, lang = r.choice(REVIEW_TEXT)
            age = r.randint(0, 20)
            replied = age > 6 and r.random() > 0.3
            db.add(Review(
                tenant_id=tenant.id, client_id=c.id, external_review_id=f"demo_{c.id}_{k}", author=f"{r.choice(FIRST)} {r.choice(LAST)[0]}.",
                rating=rating, text=text, language=lang, sentiment=detect_sentiment(text, rating), created_at=now - timedelta(days=age),
                reply_status="published" if replied else "new", reply=f"Thank you for your feedback, we truly appreciate it! — {name}" if replied else None,
                published_at=now - timedelta(days=age - 1) if replied else None,
                approved_at=now - timedelta(days=age - 1) if replied else None, approved_by=users["account_manager"].id if replied else None,
            ))

        ind = industry.lower()
        for k, tpl in enumerate(KEYWORDS[: r.randint(3, 6)]):
            prev = r.randint(3, 40)
            db.add(Keyword(tenant_id=tenant.id, client_id=c.id, keyword=tpl.format(i=ind, c=city.lower()), target_url=c.website + (f"/{ind.replace(' ', '-')}" if k else ""),
                           location=city, previous_rank=prev, current_rank=max(1, prev + r.randint(-8, 5)), volume=r.randint(90, 6000)))

        scale = 0.5 + r.random() * 2
        for d in range(90):
            day = today - timedelta(days=89 - d)
            trend = 1 + d / 300
            wk = [1, 1.05, 1.1, 1.05, 1.2, 0.9, 0.8][day.weekday()]
            v = lambda base: round(base * scale * trend * wk * (0.8 + r.random() * 0.4))  # noqa: E731
            db.add(MetricDaily(tenant_id=tenant.id, client_id=c.id, date=day, gmb_views=v(180), gmb_calls=v(6), gmb_directions=v(9), web_clicks=v(14),
                               organic_sessions=v(120), social_reach=v(900), engagement=v(60), leads=v(3)))

        if i < 12:
            titles = [("Publish weekly GMB offer post", "content"), ("Fix missing meta descriptions", "seo"), ("Design Diwali campaign creative", "designer"),
                      ("Respond to negative review escalation", "account_manager"), ("Update service pages with FAQs", "seo"), ("Prepare monthly report", "account_manager")]
            title, role = r.choice(titles)
            db.add(Task(tenant_id=tenant.id, client_id=c.id, assigned_to=users[role].id, title=title, priority=r.choice(["low", "medium", "high"]),
                        due_date=today + timedelta(days=r.randint(-2, 10)), status=r.choice(["todo", "in_progress", "review", "done"])))

        if i < 8:
            topic = r.choice(["Festive season offer", "Meet our team", "Customer success story", "New service launch", "Weekend special"])
            when = (now + timedelta(days=r.randint(1, 12))).replace(hour=10 + r.randint(0, 8), minute=0, second=0, microsecond=0)
            cta = c.brand_voice["cta_style"]
            item = ContentItem(tenant_id=tenant.id, client_id=c.id, topic=topic, content_type=r.choice(["post", "offer", "update"]),
                               master_copy=f"Something special is coming to {name} in {city}! {cta} to know more.",
                               hashtags=[f"#{city}", f"#{industry.replace(' ', '')}", "#LocalBusiness"],
                               status=r.choice(["draft", "in_review", "scheduled", "scheduled", "published"]), scheduled_at=when, created_by=users["content"].id)
            for p in ["gmb"] + ["facebook", "instagram", "linkedin"][: 1 if plan == "Starter" else 3]:
                item.variants.append(ContentVariant(platform=p, copy=f"Something special is coming to {name}! {cta}.", format=PLATFORM_FORMAT[p]))
            if item.status in ("scheduled", "published"):
                item.approved_at, item.approved_by = now, users["account_manager"].id
            if item.status == "published":  # went out in the past, on every platform
                item.scheduled_at = item.published_at = when - timedelta(days=14)
                item.attempts = 1
                for v in item.variants:
                    v.status, v.published_at, v.external_post_id = "published", item.published_at, f"{v.platform}_demo{c.id}"
            db.add(item)

    db.flush()
    smile = db.scalar(select(Client).where(Client.company_name == "Smile Dental Studio"))
    users["client"].client_id = smile.id
    # The same owner also runs a salon: one phone number, two businesses → the app's "Select profile" screen
    glowup = db.scalar(select(Client).where(Client.company_name == "GlowUp Salon & Spa"))
    db.add(User(tenant_id=tenant.id, name="Dr. Anjali Rao", email="anjali@glowupsalon.in", password_hash=pw, role="client",
                client_id=glowup.id, phone=DEMO_PHONES["client"]))
    db.commit()


def init_db(seed_if_empty: bool = True) -> None:
    Base.metadata.create_all(engine)
    add_missing_columns(engine)  # older databases: add columns introduced since they were created
    with SessionLocal() as db:  # databases from before the roles table: give every tenant the built-in roles
        for tid in db.scalars(select(Tenant.id)):
            ensure_default_roles(db, tid)
        db.commit()
    if seed_if_empty:
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(Tenant)):
                seed(db)


if __name__ == "__main__":
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)
    init_db()
    print(f"Seeded. Sign in with any demo user and password '{DEMO_PASSWORD}'.")
