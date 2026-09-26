# Green Media AI Command Center

Manage 100+ local-business clients from one place: Google Business Profile, AI review replies, AI content for every social platform, creative sizing, SEO, analytics and monthly client reports. It's built from the *Green Media AI Command Center Blueprint V1* as a competitor to Dhanda AI.

## Architecture

```
┌──────────────────────┐   ┌────────────────────────────┐
│ Django web frontend  │   │ Flutter app                │
│ web/  (desktop +     │   │ mobile/  iOS + Android     │
│ mobile browsers)     │   │                            │
└──────────┬───────────┘   └─────────────┬──────────────┘
           │  server-to-server JSON + JWT │  HTTPS JSON + JWT
           └──────────────┬───────────────┘
                 ┌────────▼─────────┐
                 │ FastAPI backend  │  backend/
                 │ auth · RBAC ·    │  every business rule lives here
                 │ tenancy · AI ·   │
                 │ workflows · audit│
                 └────────┬─────────┘
          SQLite (dev) / PostgreSQL (prod) · Anthropic or OpenAI · Google / Meta / LinkedIn APIs
```

| Part | Stack | What it does |
|---|---|---|
| `backend/` | FastAPI, SQLAlchemy 2, PyJWT, bcrypt, httpx | The only component with a database. Handles auth, roles, multi-tenant isolation, the review, content and report workflows, AI orchestration, publishing and the audit log. |
| `web/` | Django 5 templates (no database) | Browser app for the agency team and client portal. Every page renders from the API. The user's token lives in a signed, HttpOnly session cookie. |
| `mobile/` | Flutter 3 (Material 3) | Native iOS and Android app. The token is stored in the Keychain / Android Keystore. |

The frontends hold no business logic, so a rule like "2★ replies need approval" is enforced once, on the server, for web and mobile alike.

## Features (blueprint Phase 1–2)

- **Roles.** Admin, Account Manager, SEO, Content, Designer and Client each see different sections and actions. Client-portal users are isolated to their own company.
- **Dashboard.** KPI cards, a 30-day growth chart, a "needs attention" list (negative reviews and SEO drops) and client performance.
- **Clients.** Search and filter clients. Each client workspace shows accounts, brand voice, **auto-publish switches per channel**, keywords, reviews, content, tasks, reports and notes.
- **GMB Center.** Connection health, sync, insights and posts.
- **AI Review Queue.** Each review goes through sentiment and language detection, then an AI draft. You can then edit, regenerate, approve, reject or publish. **Replies to reviews of 2★ or lower must be approved first.** Editing a reply resets its approval. A failed publish is marked `failed` and can be retried.
- **AI Content Studio.** A topic becomes master copy, variants for each platform (GMB, Facebook, Instagram, LinkedIn, YouTube, X) and a creative brief. Content then moves draft → in review → scheduled → published, and can optionally require client approval.
- **Creative Studio** (web). One master image previewed at 6 platform sizes, each exportable as a PNG.
- **Social Hub.** Monthly calendar, publishing queue, and reconnect prompts for expired tokens.
- **SEO Center.** Rank tracking, the biggest movers, GSC/GA4 traffic and technical tasks.
- **Analytics.** GMB, website, social and leads data over 7, 30 or 45 days.
- **Reports.** AI monthly narrative, KPI comparison and ranking movement. Deliver as PDF (print), email or WhatsApp.
- **Tasks and audit trail.** Every write action is logged with who, what and when.

**Safety defaults:** everything requires human approval. Auto-publish is an explicit setting per client and per channel.

## Run it locally

```bash
# 1. API  → http://127.0.0.1:8001  (interactive docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: add ANTHROPIC_API_KEY or OPENAI_API_KEY
uvicorn app.main:app --reload --port 8001

# 2. Web  → http://127.0.0.1:8000
cd web
pip install -r requirements.txt
API_URL=http://127.0.0.1:8001 python manage.py runserver 8000

# 3. Mobile (Android emulator reaches your machine at 10.0.2.2; iOS simulator at 127.0.0.1)
cd mobile
flutter pub get
flutter run                                              # picks a connected device/emulator
flutter run --dart-define=API_URL=https://api.yourdomain  # point at a deployed API
```

Sign in with any demo account; the password is `demo1234`. The login screens have one-tap buttons for each role. The API seeds 24 sample clients with 90 days of metrics on first start (`SEED_DEMO=1`). Run `python -m app.seed --reset` to reset them.

**AI:** without a key, review replies, content and reports come from built-in templates, so everything still works. Set `ANTHROPIC_API_KEY` (or `AI_PROVIDER=openai` plus `OPENAI_API_KEY`) on the API server to switch to real model output. Keys never ship inside the apps.

## Tests

```bash
cd backend && pytest -q          # 14 tests: permissions, tenant isolation, escalation, state machines, publish failures
cd mobile  && flutter analyze && flutter test   # 7 tests: login, role-based navigation, escalation UI, API contract
```

The Flutter tests use JSON fixtures captured from the real API, so they catch contract drift.

## Building the mobile apps

```bash
cd mobile
flutter build apk --release --dart-define=API_URL=https://api.yourdomain      # Android
flutter build appbundle --release --dart-define=API_URL=https://api.yourdomain # Play Store
flutter build ipa --release --dart-define=API_URL=https://api.yourdomain       # iOS (on a Mac, with your Apple team)
```

Release builds only talk to HTTPS APIs. Plain `http://` is allowed only in Android debug builds and for localhost/LAN on iOS.

**CI** (`.github/workflows/build.yml`) runs the API tests, Django checks with a live smoke test of every page, and Flutter analyze and tests. It also builds a release **Android APK** and an unsigned **iOS build**, which you can download from the run's Artifacts. Set the repository variable `API_URL` to bake your API address into those builds. Store releases need your Android keystore and Apple signing.

## Deploying

- **API:** `uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4` behind HTTPS. Set `DATABASE_URL` to PostgreSQL, a strong `JWT_SECRET`, and `SEED_DEMO=0`.
- **Web:** `python manage.py collectstatic && gunicorn greenmedia_web.wsgi`. Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and `API_URL`. Static files are served by WhiteNoise.

## Roadmap to production

1. **Official integrations.** `backend/app/publishers.py` is the seam for them. Add OAuth apps for Google Business Profile, Search Console, GA4, Meta, LinkedIn and YouTube, with encrypted token storage and refresh. Until then, publishing is simulated so the workflows can be exercised end to end. Check each platform's current API permissions before building.
2. **Scheduler.** A worker (Celery, RQ or APScheduler) should publish due `scheduled` content, pull new reviews (via GBP notifications), and sync daily metrics and ranks.
3. **Migrations.** Add Alembic before the first production schema change. Tables are currently created by `create_all`.
4. **Phase 3–4.** WhatsApp Business API, push notifications, lead CRM, then SaaS billing, white-label branding and custom domains. `tenant_id` is already on every row.
