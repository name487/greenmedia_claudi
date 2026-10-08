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
cp .env.example .env            # optional: add OPENAI_API_KEY (or ANTHROPIC_API_KEY)
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

### PostgreSQL

The API runs on PostgreSQL (recommended) or SQLite (a zero-setup file for quick demos). To use PostgreSQL:

```bash
docker compose up -d db          # PostgreSQL 16 on 127.0.0.1:5432 (or use any existing server)
# backend/.env
DATABASE_URL=postgresql+psycopg://greenmedia:greenmedia@127.0.0.1:5432/greenmedia
```

Tables are created on first start. Upgrading to a newer version adds any new tables and columns automatically, and your data is kept.

**For a real installation (no demo data)**, set `SEED_DEMO=0` and create your first admin. The password is prompted for, never typed on the command line:

```bash
cd backend
python -m app.manage create-admin --email you@greenmedia.in --name "Your Name"
```

Then sign in on the web app and add your data. With `SEED_DEMO=0` the database starts empty:

| What | How |
|---|---|
| Team members | **Settings → Team members → Add team member** (name, email, role, temporary password) |
| One client | **Clients → + Add client** |
| Many clients | **Clients → Import clients from CSV** (click *Download template* for the columns), or from the command line: `python -m app.manage import-clients clients.csv` |
| Client-portal logins | **Settings → Team members**, role **Client**, pick the client |
| Reviews, rating, insights | **Connect Google** on the client's workspace, or **GMB Center → Google connections**, then link the location (pulled from Google, not typed in) |
| Content, tasks, keywords | Created in the app as you work (Content Studio, Team & Tasks, SEO Center) |

The CSV needs only `company_name`. Optional columns are `website, industry, city, plan, status, services` (separated by `;`), `contact_name, contact_email, contact_phone`. The import is all-or-nothing: if any row is invalid, nothing is imported and you get the line numbers to fix. Clients that already exist, matched by name, are skipped, so re-running the same file is safe.

### Users, roles and login

- **Login.** The Django login page posts to the API (`POST /api/auth/login`). Passwords are checked with bcrypt, and the API returns a JWT. Django keeps the token in a signed, HttpOnly session cookie, and the Flutter app keeps it in the Keychain / Keystore.
- **Roles table.** Every agency has six built-in roles (Admin, Account Manager, SEO Specialist, Content Writer, Designer, Client). Each role stores which **sections** it can open and which **actions** it may perform. A database foreign key guarantees every user's role exists.
- **Enforced on every request.** The API re-reads the user and their role on each call. Editing a role, changing a user's role or disabling an account therefore takes effect immediately, even for people who are already signed in.
- **Admin screens** (**Settings → Team members / Roles & permissions**):
  - Create users, change roles, reset passwords and disable accounts.
  - Edit what each role can open and do.
  - Admins can't disable or demote themselves, and the Admin role always keeps Settings access, so nobody gets locked out.
- **Client-portal users** have the Client role and are linked to one client, so they only ever see that company's data.

### Clients and contacts API

The interactive docs are at `http://127.0.0.1:8001/docs`. The Django **Clients** and **Client Workspace** screens use these endpoints:

| Method & path | What it does | Who |
|---|---|---|
| `GET /api/clients` | List clients. Filters: `q` (name, city, industry, website, or any contact's name/email/phone), `industry`, `service`, `plan`, `status`, `manager_id`. `sort=name\|pending\|rating\|newest` | anyone signed in (portal users see only their company) |
| `GET /api/clients/facets` | Values for the filter dropdowns (industries, services, plans, statuses, managers) | staff |
| `POST /api/clients` | Create a client. Names must be unique (case-insensitive). Accepts `contacts: [...]` or a single `contact_name/email/phone` | `client.edit` |
| `GET /api/clients/{id}` | Workspace: profile, contacts, KPIs, reviews, content, keywords, tasks, reports | anyone who can see it |
| `PATCH /api/clients/{id}` | Edit any of: name, website, industry, city, plan, status, services, account manager, notes, brand voice, auto-publish | `client.edit` |
| `DELETE /api/clients/{id}?confirm_name=…` | Permanently delete the client and all its data. You must retype the exact name. Portal logins for the client are disabled, and the audit log keeps a record | `client.edit` |
| `GET /api/clients/{id}/contacts` | List contacts, primary first | anyone who can see the client |
| `POST /api/clients/{id}/contacts` | Add a contact (`name`, `email`, `phone`, `designation`, `is_primary`). The first contact becomes primary | `client.edit` |
| `PATCH /api/clients/{id}/contacts/{cid}` | Edit a contact. `is_primary: true` makes it the primary contact | `client.edit` |
| `DELETE /api/clients/{id}/contacts/{cid}` | Remove a contact. If it was primary, the next contact is promoted | `client.edit` |
| `POST /api/clients/import` | Bulk-create clients from CSV (see above) | `client.edit` |

**AI:** without a key, review replies, content and reports come from built-in templates, so everything still works. Set `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) on the API server to switch to real model output, then press **Settings → Test AI connection**. Keys never ship inside the apps. See [AI replies with OpenAI](#ai-replies-with-openai).

## Going live with Google Business Profile

Clients linked to a real Google location are **live**. Their reviews, rating and daily insights are pulled from Google, and approved replies and GMB posts are published to Google. Every other client stays on demo data. Linking a client deletes that client's demo reviews and metrics, so real and fake data never mix.

### One-time setup (Google Cloud)

1. **Create a project** at [console.cloud.google.com](https://console.cloud.google.com/). Then, under *APIs & Services → Library*, enable these four APIs:
   **My Business Account Management API**, **My Business Business Information API**, **Google My Business API** and **Business Profile Performance API**.
2. **Request API access.** The Business Profile APIs start with a quota of 0. Submit Google's [Business Profile API access request](https://developers.google.com/my-business/content/prereqs) for this project. Until it is approved, calls fail with a quota error, which the app shows on screen.
3. **Configure the OAuth consent screen** (*APIs & Services → OAuth consent screen*): choose External, name it "Green Media Command Center", and add the scope `…/auth/business.manage`. While the app is in *Testing*, add `greenmediaseoteam2@gmail.com` as a test user. Note that in Testing mode Google expires refresh tokens after **7 days**. For uninterrupted sync, **publish** the app and complete Google's verification.
4. **Create credentials** (*APIs & Services → Credentials → Create OAuth client ID*): choose *Web application*, and add the authorized redirect URI `https://<your-api-host>/api/google/callback` (locally: `http://127.0.0.1:8001/api/google/callback`).
5. **Configure the API server.** Put these in `backend/.env` and restart the API:
   ```
   GOOGLE_CLIENT_ID=…apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=…
   GOOGLE_REDIRECT_URI=https://<your-api-host>/api/google/callback
   WEB_APP_URL=https://<your-web-host>
   TOKEN_ENCRYPTION_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
   SCHEDULER_INTERVAL_MINUTES=15
   ```

### Check the setup

**GMB Center → Google connections → Check Google setup** reads your configuration and shows:
- the Cloud project number, taken from the client ID (`437254480587-….apps.googleusercontent.com`)
- whether the client ID, secret and redirect URI look right, and whether the API and web app share a host
- direct links to enable each API, its quota page, the credentials page and the consent screen

**Run live check** calls each of the four APIs once with a connected Google account. Each one comes back as *Working*, *Not enabled* or *Quota 0* (access not approved yet). The same data is available from `GET /api/google/diagnostics?live=1`.

### Connect Google per client (Client Workspace)

Open a client and use the **Google Business Profile** panel:

1. Click **Connect Google**, sign in with the Google account that owns or manages *this* business's profile, and approve.
2. If that account manages one free location, it is linked and synced straight away. If it manages several, choose the right one under **Locations you can link** and click **Link**.
3. The panel then shows:
   - the connected profile: name, address, *View on Google Maps*, rating and review count
   - the Google account it is connected as
   - status and last sync
   - token state, with the expiry time of the current access token
4. Panel actions:
   - **Sync now**
   - **Test connection** (gets a fresh token now)
   - **Change location**
   - **Unlink location** (back to demo data)
   - **Disconnect Google** (revokes the client's sign-in)

### Or connect one agency account for many clients

1. Open **GMB Center → Google connections**. You need to be an Admin or Account Manager.
2. Click **Connect Google account** and sign in as **greenmediaseoteam2@gmail.com** (the account with management rights).
3. Every location that account manages is listed. Pick the matching client for each one and click **Link & sync**. These locations also appear in each client's location picker.

### After linking

- **AI Reviews:** **Sync reviews** (and the scheduler) pulls new reviews from Google into `gmb_reviews` and AI-drafts replies. Approved replies are posted to Google. 2★ replies still need approval first. See [AI Review Queue](#ai-review-queue).
- **Content Studio:** GMB variants of approved content are posted to the profile as Google posts, either on "Publish now" or at their scheduled time.
- **Scheduler:** with Redis, Celery beat publishes due posts every minute and syncs live profiles every `GOOGLE_SYNC_MINUTES`. See [Content scheduling](#content-scheduling-redis--celery). Without Redis, the API does both every `SCHEDULER_INTERVAL_MINUTES`, or you can run `python -m app.jobs` from cron.
- **Errors:** if access is revoked, the profile shows **Expired** with Google's error message. **Reconnect** fixes it.

### How tokens are stored and refreshed

| | Per-client sign-in | Agency connection |
|---|---|---|
| Table | `gmb_accounts` (that client's row) | `google_connections` |
| Refresh token | `refresh_token_enc` (Fernet-encrypted with `TOKEN_ENCRYPTION_KEY`) | `refresh_token_enc` (encrypted) |
| Access token | `access_token_enc` + `token_expires_at` (encrypted) | same columns |
| Also stored | `google_email`, `scopes`, `token_status`, linked `title`, `address`, `maps_uri` | `email`, `scopes`, `status` |

How refresh works:
- Before each Google call, a stored access token that expires within 2 minutes is swapped for a new one using the refresh token.
- The new token is saved back to the database. API workers, the scheduler and restarts all reuse it instead of each refreshing on their own.
- If Google rejects an access token early (401), the app refreshes once and retries the call.
- If the refresh token itself is revoked (`invalid_grant`), the sign-in is marked revoked, the profile shows *Expired*, and **Reconnect** heals it.
- Tokens are never returned by the API, which only reports their state and expiry.

**Endpoints** (Bearer token; changes need `client.edit`):

| Method & path | What it does |
|---|---|
| `POST /api/clients/{id}/google/connect` | Google consent URL for this client. The callback stores the tokens on the client's `gmb_accounts` row. |
| `GET /api/clients/{id}/google` | Connected profile, location, token state (never the tokens) |
| `GET /api/clients/{id}/google/locations` | Locations available from the client's sign-in and the agency connections, plus which client each is linked to |
| `POST /api/clients/{id}/google/link` | `{account, location, connection_id?}`: link, verified against Google, then sync |
| `POST /api/clients/{id}/google/unlink` | Back to demo data |
| `POST /api/clients/{id}/google/refresh` | Force a token refresh (a connection test) |
| `DELETE /api/clients/{id}/google` | Remove and revoke the client's sign-in |
| `GET /api/google/diagnostics[?live=1]` | Google Cloud project checks |

**Security:**
- The app never sees the Google password. Access uses OAuth only.
- Tokens are encrypted at rest (Fernet).
- The callback rejects a sign-in where the Business Profile permission was unticked.
- The OAuth `state` is signed, names the user and the client, and expires after 15 minutes. The user must still have `client.edit` when Google returns.
- **Disconnect** removes the stored token and revokes it on Google's side. It skips the revoke when another client or the agency connection uses the same Google account, because revoking cancels the whole grant.

**Still simulated:** Facebook, Instagram, LinkedIn and YouTube publishing, plus the GA4/Search Console/social columns in analytics. After you link a client, those columns show 0 until their integrations are added.

## AI Review Queue

**AI Reviews** in the web app (also `GET /api/reviews`) is the team's inbox for every client's Google reviews.

**Fetching from Google into `gmb_reviews`**

**Sync reviews**, the GMB page's sync and the scheduler all call Google's `accounts/*/locations/*/reviews`. Each new review is stored with:
- reviewer, photo, stars, text (Google's machine translation is stripped), language and sentiment
- Google's `createTime` and `updateTime`

How the sync behaves:
- **Incremental.** After the first import, it only pages through reviews updated since the last one it has.
- **Edits.** If a reviewer edits their review, the text, rating and sentiment are refreshed. A reply that was approved but not yet published goes back to *Drafted* for another look.
- **Replies made on Google.** A reply written directly on Google is mirrored as *Published*, so nobody drafts a second one.
- **AI drafts.** New unanswered reviews get an AI draft straight away, up to `REVIEW_AUTODRAFT_LIMIT` per client per sync. Without an AI key, the brand-voice template is used.
- **Auto-publish.** Positive 4–5★ replies are auto-published only when the client opted in (*Client Workspace → Publishing safety*) and the review is under 14 days old.

**The screen**

- A source banner shows where the reviews come from: *Live from Google*, *Waiting for Google API approval*, *Sample reviews*, or a sync error with a link to reconnect.
- Stat tiles: needs reply (and AI drafts ready), negative waiting, oldest waiting (and how many are over 48h), and 90-day response rate with average reply time and rating.
- Search and filters by rating, sentiment and source (Google or sample), plus sort by priority, newest, oldest or lowest rating.
- **Priority** puts negative and 2★ reviews first, then the longest-waiting ones.
- Tabs: Needs reply / Approved / Negative / Published / All.
- Each card shows a ⏱ waiting badge (amber over 24h, red over 48h), the AI draft editor, and Approve / Publish / Reject / Regenerate.
- Bulk actions: tick reviews (or **Select all**), then *Draft AI replies*, *Approve*, *Publish* or *Reject*. Each review follows the single-review rules: 2★ approval and role permissions. Any that can't be done are listed.

**Sample data while API approval is pending**

Until Google approves Business Profile API access, every review call fails with quota 0. So the team can still use the queue, **Sync reviews** falls back to realistic sample reviews (English, Hindi and Hinglish, every rating, some rating-only):

- **For a linked client** that gets a quota-0 answer: 6 sample reviews the first time, then one more per sync, like a review arriving.
- **For clients not linked to Google yet:** a first batch for clients with no reviews (10 clients per sync), then one new review per sync.
- **Labelling.** Samples are labelled *Sample* everywhere: card, filter, mobile app and audit log. Their replies are **never sent to Google**; publishing one only marks it published.
- **Clean-up.** They are deleted automatically on the first successful Google fetch for that client, and when a location is linked.
- **Turning it off.** `REVIEW_SAMPLE_DATA=0` stops sample reviews from ever being created.

| Method & path | What it does |
|---|---|
| `GET /api/reviews?filter=&client_id=&rating=&sentiment=&source=&q=&sort=&limit=&offset=` | Queue items, tab counts, `stats` and per-client `sources` (`live` / `approval_pending` / `error` / `sample` / `none`) |
| `POST /api/reviews/sync` `{client_id?}` | Fetch from Google, or sample data, then AI drafts. The response lists the clients where approval is pending. |
| `POST /api/reviews/bulk` `{ids, action}` | `draft` / `approve` / `publish` / `reject` for up to 100 reviews |
| `POST /api/reviews/{id}/draft` · `PATCH /api/reviews/{id}` · `POST /api/reviews/{id}/approve|reject|publish|reopen` | Single-review actions |

## AI replies with OpenAI

**Connect.** Put `OPENAI_API_KEY=sk-…` in `backend/.env` and restart the API. With no `AI_PROVIDER` set, OpenAI is used whenever that key exists.

- **Model:** `AI_MODEL`, default `gpt-4.1-mini`.
- **Optional settings:** `OPENAI_BASE_URL`, `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID`.
- **Checking the connection:** **Settings → AI connection** shows the provider, model and a masked key (`sk-…1234`). **Test AI connection** sends one tiny request and reports the latency, or the reason it failed with a fix:
  - invalid key
  - no credit (`insufficient_quota`)
  - model not available
  - rate limit
- **Where the key lives:** only in the server's environment. It is never stored in the database or shown in full.

**How requests are made.**
- The official Chat Completions API (`POST /v1/chat/completions`, `max_completion_tokens`).
- One automatic retry on a rate limit or server error.
- Every draft records the model, token usage, latency and OpenAI request id.
- If OpenAI fails, the reply falls back to the client's brand-voice template. The card shows **Template — AI not used: <reason>**, so nothing is silently wrong.

**Per-client brand voice** (*Client Workspace → AI brand voice*):
- **Fields:** tone, reply length (short/medium/long), sign-off, call to action, preferred phrases, things never to say, languages, the escalation rule, and free-text **Instructions for review replies**.
- **See the exact prompt the AI receives** shows the full system prompt.
- **Try it on a review** drafts a sample reply without saving anything.
- **Fixed safety rules** are appended after the client's instructions:
  - reply in the review's language
  - no private details
  - no admitting liability
  - no public refunds or discounts
  - apologise and take negatives offline
- The review text is wrapped in `<review>` tags and treated as data. A review saying "ignore your instructions" can't steer the reply.

**Workflow in the AI Review Queue.**
- **Draft:** automatic for new reviews, or **Generate AI reply**.
- **Edit:** type in the box, then **Save edit**. The reply is marked *Edited by your team* and needs approval again.
- **Regenerate:** with an optional note such as "shorter" or "mention online booking".
- **Approve, Reject, Reopen.**
- **Publish to Google:** through the official Business Profile API, `PUT accounts/{a}/locations/{l}/reviews/{id}/reply`. Google's `updateTime` becomes the published time.
- **Approval rules:** replies to reviews of 2★ or lower must be approved before publishing. Only roles with `review.approve` or `review.publish` can approve or publish.

**Audit trail.** Every step is a row in `audit_logs` with a `details` JSON column:

| Action | `details` |
|---|---|
| AI drafted / regenerated reply | source (`ai`/`template`), provider, model, token usage, ms, request id, instruction, reply, previous text, AI error |
| edited reply | before, after |
| approved / rejected / reopened | from → to status, reply |
| published reply to Google | target (`google`, `sample`, `simulated`), location, Google's `updateTime`, reply |
| publish failed | Google's error |
| `[auto]` … (user "System") | drafts and auto-publishes made by sync or the scheduler |
| brand voice changes | before/after per field |
| AI connection test | ok or error code |

- Each review card has a **History** list. The same data is at `GET /api/reviews/{id}/history`.
- The Team & Tasks page shows the full audit trail.

| Method & path | What it does |
|---|---|
| `GET /api/ai/status` · `POST /api/ai/test` | AI connection state and test (Settings) |
| `GET /api/clients/{id}/brand-voice` | Brand voice plus the exact system prompt |
| `POST /api/clients/{id}/brand-voice/try` | `{rating, text, author?, brand_voice?}`: a sample reply, nothing saved |
| `PATCH /api/clients/{id}` `{brand_voice: {...}}` | Save the voice (merged, validated, audited) |
| `POST /api/reviews/{id}/draft` `{instruction?}` | Draft or regenerate |
| `PATCH /api/reviews/{id}` `{reply}` | Edit |
| `POST /api/reviews/{id}/approve\|reject\|reopen\|publish` | State changes; publish posts to Google |
| `GET /api/reviews/{id}/history` | That review's audit entries |

## Content scheduling (Redis + Celery)

**`content_items` statuses**

| Status | Meaning | Shown under |
|---|---|---|
| `draft` | Written by AI, a template or a person; editable | **Draft** |
| `in_review` | Draft waiting for approval (or the client's approval, when that setting is on) | **Draft** ("awaiting approval") |
| `scheduled` | Approved with a publish time; the copy is locked. Also used while waiting to retry after a temporary error ("retrying"). | **Scheduled** |
| `publishing` | A worker is posting it right now | **Scheduled** ("Publishing…") |
| `published` | Every platform went out | **Published** |
| `failed` | A permanent error, or out of attempts. The reason is shown, with **Retry now**. | **Failed** |

Each platform version (`content_variants`) also tracks its own `status`, `published_at`, `error` and `external_post_id`. A retry only posts the platforms that haven't gone out yet. The item records `attempts`, `next_attempt_at`, `last_error`, `published_at`, and `ai_source` / `ai_model` for AI drafts.

**AI post drafts.** In Content Studio, choose a topic and platforms, plus optional *Notes for the AI*, then:
- **Generate with AI** shows a draft you can edit, or
- **Save AI draft** writes it straight to Drafts (`POST /api/content/draft`).

Drafts use the client's brand voice and the OpenAI connection, falling back to templates. The model, token usage and any AI error are recorded in `audit_logs`.

**From draft to published.** Send for approval → *Approve & schedule*. A publish time is required and must be in the future; times are entered in the web app's time zone (`TIME_ZONE`, IST by default).

While scheduled:
- **Reschedule** moves the time.
- **Unschedule** returns it to Draft so the copy can be edited.
- **Publish now** sends it immediately.

**Running the scheduler**
```bash
docker compose up -d redis          # or any Redis 6+
# backend/.env
REDIS_URL=redis://127.0.0.1:6379/0
# from backend/, next to the API:
celery -A app.celery_app worker -l info   # publishes
celery -A app.celery_app beat -l info     # every minute: queue due posts; every GOOGLE_SYNC_MINUTES: Google sync
# (development: one process)  celery -A app.celery_app worker -B -l info
```

**How it works**
- **Queueing.** Beat runs `dispatch_due` every minute. It queues one `publish_content` task per post whose time (or retry time) has arrived. **Publish now** queues the task immediately, and the page says "Queued".
- **The schedule lives in PostgreSQL, not in Redis.** Rescheduling is a database update with nothing to revoke. A Redis restart loses nothing: the next sweep re-queues whatever is due.
- **Never published twice.** A worker first claims the post with one conditional `UPDATE … SET status='publishing' WHERE status='scheduled' AND due`, and only the winner posts. Duplicate deliveries, two workers and double clicks are all no-ops. Tasks use `acks_late`, so a task lost with its worker is redelivered.
- **Retries.** Temporary errors (rate limits, 5xx, timeouts, network) retry after `CONTENT_RETRY_MINUTES`, doubling each time, up to `CONTENT_PUBLISH_MAX_ATTEMPTS` (default 3). Permanent errors fail straight away: account not connected, expired token, Google rejected the post, or API approval pending.
- **Stuck posts.** A post left in `publishing` by a crashed worker for 15 minutes goes back to `scheduled` and is retried.
- **Without Redis** (`REDIS_URL` empty), the same code runs in the API: **Publish now** posts inline, and due posts go out every `SCHEDULER_INTERVAL_MINUTES` (or via `python -m app.jobs` from cron). The Content Studio status panel says which mode is active.
- **Audit trail.** Every step is in `audit_logs` with details: who, from/to status, per-platform result and post id, errors, attempt number and retry time. Scheduler actions appear as `[scheduler] …`.

| Method & path | What it does |
|---|---|
| `POST /api/content/draft` | AI draft saved as Draft `{client_id, topic, platforms, content_type?, notes?, scheduled_at?}` |
| `POST /api/content/generate` | AI draft preview (not saved) |
| `POST /api/content` | Save a draft, send it for review, or schedule it directly (needs approval rights) |
| `PATCH /api/content/{id}` | Edit copy (draft/in review/failed) or `scheduled_at` (reschedule) |
| `POST /api/content/{id}/submit\|request_changes\|approve\|schedule\|unschedule\|publish\|retry` | Status changes. `publish`/`retry` dispatch now. |
| `DELETE /api/content/{id}` | Drafts and failed posts only |
| `GET /api/content/board?group=draft\|scheduled\|published\|failed\|all` | Status counts, items and scheduler mode |
| `GET /api/content?status=&client_id=&month=` | Plain list (calendar). `status` takes a status or a group. |

## Facebook & Instagram (Meta)

Facebook and Instagram are the first social platforms with real publishing. Everything else stays simulated until connected.

**One-time setup (Meta app)**
1. At [developers.facebook.com](https://developers.facebook.com/apps/), create a **Business** app and add **Facebook Login for Business**.
2. Under *Facebook Login → Settings*, add the **Valid OAuth Redirect URI** `http://127.0.0.1:8001/api/meta/callback` (your API host in production).
3. Request these permissions: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`.
   - In Development mode they work for people with a role on the app and their own Pages.
   - Clients' Pages need *Advanced Access* through App Review.
4. Put `META_APP_ID`, `META_APP_SECRET` and `META_REDIRECT_URI` (plus optionally `META_GRAPH_VERSION`, default `v23.0`) in `backend/.env` and restart the API.
5. Each client's Instagram must be a **professional (Business or Creator) account linked to its Facebook Page**.

**Connect and link** (*Social Hub → Facebook & Instagram*)
- **Connect Facebook & Instagram:** sign in with the Facebook account that manages the Pages.
  - The short-lived login is exchanged for a 60-day token, stored encrypted.
  - Each Page's own token is stored encrypted on the linked account. Page tokens obtained this way don't expire.
  - Reconnecting refreshes them.
- Every Page the login manages is listed with its Instagram account. Choose the client and press **Link**; Instagram is included when the Page has one.
- Linked accounts show **Live**. Other clients' accounts stay **Demo**, simulated.

**Publishing**
- **Facebook:** text and link posts go to `POST /{page-id}/feed`. Posts with an image go to `POST /{page-id}/photos`.
- **Instagram:** `POST /{ig-user-id}/media` (a container from the image URL), then `POST /{ig-user-id}/media_publish`.
- **Images:** Instagram needs an image, so posts have an **Image URL** field (a public `https://` link).
- **Errors** follow the scheduling rules:
  - Rate limits and Meta "transient" errors retry with backoff.
  - An expired or revoked login (code 190) fails the post, marks the account **expired** in Social Hub, and asks you to reconnect.
  - Missing permissions explain what to allow.

**Adapting content per platform**
- AI drafts already write one version per platform.
- **Adapt for each platform** (on a draft) rewrites every version from the master copy, using AI with the client's brand voice. Without AI it uses platform rules:
  - Instagram: no URLs ("link in bio"), up to 30 hashtags, 2,200 characters
  - Facebook: link kept, up to 3 hashtags
  - Google: no hashtags, 1,500 characters
  - X: 280 characters
- Every version is checked, and problems show under the post. Errors block scheduling until fixed: Instagram without an image, a non-https image, or too long for the platform. Warnings (link in an Instagram caption, too many hashtags, very long Facebook text) don't block.

**Calendar** (*Social Hub*)
- Month and week views of posts by publish time, coloured by status: scheduled (blue), published (green), failed (red), planned drafts (grey, dashed).
- The week view shows the time, client and each platform's result. On a phone it becomes a simple list.
- Clicking a post opens it in the Content Studio. Data comes from `GET /api/content/calendar?start=…&days=…`.

| Method & path | What it does |
|---|---|
| `GET /api/meta/status` · `POST /api/meta/connect` · `GET /api/meta/callback` | Connection state, Facebook login URL, OAuth return |
| `GET /api/meta/pages` | Pages with their Instagram accounts and linked clients (no tokens) |
| `POST /api/clients/{id}/meta/link` `{connection_id, page_id, instagram}` | Link the client's Page (+ Instagram) |
| `DELETE /api/clients/{id}/meta` · `DELETE /api/meta/connections/{id}` | Unlink a client · remove a login and revoke it |
| `POST /api/content/{id}/adapt` `{platforms?}` | Rewrite each platform version from the master copy |
| `GET /api/content/calendar?start=&days=&client_id=` | Posts in a date range for the calendar |

## Tests

```bash
cd backend && pytest -q          # 110 tests: clients/contacts CRUD, CSV import, users/roles/login, permissions, tenant isolation, escalation, state machines, publish failures,
                                 #   and the Google flow (agency + per-client OAuth, encrypted tokens, persisted refresh, locations, review import, reply, posts, insights, revoked access, diagnostics, review fetch/edits, sample-data fallback, queue filters and bulk actions, OpenAI requests/errors/retry, brand-voice prompt, audit details,
                                 #   content statuses, AI post drafts, single-winner publishing, retries/backoff, Celery dispatch,
                                 #   Meta connect/link/publish to Facebook & Instagram, per-platform adapt + checks, calendar)
REDIS_TEST_URL=redis://127.0.0.1:6379/0 pytest -q tests/test_content_scheduling.py   # + a real Redis broker and Celery worker
TEST_DATABASE_URL=postgresql+psycopg://greenmedia:greenmedia@127.0.0.1:5432/greenmedia_test pytest -q   # same suite on PostgreSQL
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
