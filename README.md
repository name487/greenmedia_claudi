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

## Going live with Google Business Profile

Clients linked to a real Google location are **live**. Their reviews, rating and daily insights are pulled from Google, and approved replies and GMB posts are published to Google. Every other client stays on demo data. Linking a client deletes that client's demo reviews and metrics, so real and fake data never mix.

### One-time setup (Google Cloud)

1. **Create a project** at [console.cloud.google.com](https://console.cloud.google.com/). Then, under *APIs & Services → Library*, enable these four APIs:
   **My Business Account Management API**, **My Business Business Information API**, **Google My Business API** and **Business Profile Performance API**.
2. **Request API access.** The Business Profile APIs start with a quota of 0. Submit Google's [Business Profile API access request](https://developers.google.com/my-business/content/prereqs) for this project. Until it is approved, calls fail with a quota error, which the app shows on screen.
3. **Configure the OAuth consent screen** (*APIs & Services → OAuth consent screen*): choose External, name it "Green Media Command Center", and add the scope `…/auth/business.manage`. While the app is in *Testing*, add `greenmediaseoteam2@gmail.com` as a test user. Note that in Testing mode Google expires refresh tokens after **7 days**. For uninterrupted sync, **publish** the app and complete Google's verification.
4. **Create credentials** (*APIs & Services → Credentials → Create OAuth client ID*): choose *Web application*, and add the authorized redirect URI `https://<your-api-host>/api/google/callback` (locally: `http://localhost:8001/api/google/callback`).
5. **Configure the API server.** Put these in `backend/.env` and restart the API:
   ```
   GOOGLE_CLIENT_ID=…apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=…
   GOOGLE_REDIRECT_URI=https://<your-api-host>/api/google/callback
   WEB_APP_URL=https://<your-web-host>
   TOKEN_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   SCHEDULER_INTERVAL_MINUTES=15
   ```

### Connect and link (in the app)

1. Sign in to the web app as an Admin or Account Manager, then open **GMB Center → Google connections**.
2. Click **Connect Google account**, sign in as **greenmediaseoteam2@gmail.com** (the account with management rights), and approve.
3. Every location that account manages is listed. For each one, pick the matching client and click **Link & sync**. Reviews, rating and 90 days of insights are imported immediately.
4. From then on:
   - **AI Reviews:** the "Sync new reviews" button pulls reviews from Google. Approved replies are posted to Google, and 2★ replies still need approval first.
   - **Content Studio:** GMB variants of approved content are posted to the profile as Google posts when you click "Publish now", or at their scheduled time.
   - **Scheduler:** every `SCHEDULER_INTERVAL_MINUTES`, the API re-syncs every live profile and publishes posts that are due. You can also run it from cron: `python -m app.jobs`.
   - **Errors:** if access is revoked or expires, the profile shows **Expired** with Google's error message, and **Reconnect** fixes it.

**Security:**
- The app never sees the Google password. Access uses OAuth only.
- The refresh token is encrypted at rest (Fernet).
- **Disconnect** removes the stored token and also revokes it on Google's side.
- The OAuth `state` is signed and expires after 15 minutes.

**Still simulated:** Facebook, Instagram, LinkedIn and YouTube publishing, plus the GA4/Search Console/social columns in analytics. After you link a client, those columns show 0 until their integrations are added.

## Tests

```bash
cd backend && pytest -q          # 23 tests: permissions, tenant isolation, escalation, state machines, publish failures,
                                 #   and the Google flow (OAuth, locations, review import, reply, posts, insights, revoked access)
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

1. **More integrations.** Google Business Profile is live (see above). Next come Search Console, GA4, Meta, LinkedIn and YouTube, following the same pattern as `backend/app/google/` with `backend/app/publishers.py` as the seam.
2. **Real-time reviews.** Switch from polling to GBP Pub/Sub notifications, and move the scheduler to a dedicated worker when running several API processes.
3. **Migrations.** Add Alembic before the first production schema change. Tables are currently created by `create_all`.
4. **Phase 3–4.** WhatsApp Business API, push notifications, lead CRM, then SaaS billing, white-label branding and custom domains. `tenant_id` is already on every row.
