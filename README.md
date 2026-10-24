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
- **AI Review Queue.** Each review goes through sentiment and language detection, then an AI draft. You can then edit, regenerate, approve, reject or publish. **Every reply must be approved before it is published** (2★ or lower are flagged for an account manager). Editing a reply resets its approval. A failed publish is marked `failed` and can be retried.
- **AI Content Studio.** A topic becomes master copy, variants for each platform (GMB, Facebook, Instagram, LinkedIn, YouTube, X) and a creative brief. Content then moves draft → in review → scheduled → published, and can optionally require client approval.
- **Creative Studio** (web). One master image previewed at 6 platform sizes, each exportable as a PNG.
- **Social Hub.** Monthly calendar, publishing queue, and reconnect prompts for expired tokens.
- **SEO Center.** Rank tracking, the biggest movers, GSC/GA4 traffic and technical tasks.
- **Analytics.** GMB, website, social and leads data over 7, 30 or 45 days.
- **Reports.** AI monthly narrative, KPI comparison and ranking movement. Deliver as PDF (print), email or WhatsApp.
- **Tasks and audit trail.** Every write action is logged with who, what and when.

**Safety defaults:** nothing is published without approval (see [Approval guarantee](#approval-guarantee)). Auto-publish is an explicit opt-in per client and per channel.

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

- **AI Reviews:** **Sync reviews** (and the scheduler) pulls new reviews from Google into `gmb_reviews` and AI-drafts replies. Only approved replies are posted to Google. See [AI Review Queue](#ai-review-queue).
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
- **Auto-publish.** The one exception to [approval](#approval-guarantee): positive 4–5★ replies are auto-published only when the client opted in (*Client Workspace → Publishing safety*) and the review is under 14 days old.

**The screen**

- A source banner shows where the reviews come from: *Live from Google*, *Waiting for Google API approval*, *Sample reviews*, or a sync error with a link to reconnect.
- Stat tiles: needs reply (and AI drafts ready), negative waiting, oldest waiting (and how many are over 48h), and 90-day response rate with average reply time and rating.
- Search and filters by rating, sentiment and source (Google or sample), plus sort by priority, newest, oldest or lowest rating.
- **Priority** puts negative and 2★ reviews first, then the longest-waiting ones.
- Tabs: Needs reply / Approved / Negative / Published / All.
- Each card shows a ⏱ waiting badge (amber over 24h, red over 48h), the AI draft editor, and Approve / Publish / Reject / Regenerate.
- Bulk actions: tick reviews (or **Select all**), then *Draft AI replies*, *Approve*, *Publish* or *Reject*. Each review follows the single-review rules: approval first, and role permissions. *Publish approved* only sends replies that are already approved. Any that can't be done are listed.

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
- **Approval rules:** every reply must be approved before publishing ([Approval guarantee](#approval-guarantee)). Only roles with `review.approve` or `review.publish` can approve or publish.

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

## Master Dashboard

The home page (`GET /api/dashboard`, scoped to the clients each user can see) shows:

- **Headline numbers:**
  - clients, and how many are at risk
  - reviews needing a reply (negative, over 48h)
  - items **waiting for approval** (replies + posts)
  - 30-day response rate with average reply time and rating
  - posts going out in the next 7 days (published in 30 days, failed)
  - leads, with the change against the previous 30 days
- **Integrations strip:**
  - Google profiles live, awaiting API approval, or in error
  - clients live on Facebook/Instagram, and accounts that need reconnecting
  - AI model, with AI vs template drafts and tokens used in 30 days (from `audit_logs`)
  - scheduler mode
- **Needs attention:** failed posts, negative reviews waiting, expired social logins, Google errors or pending approval. Each item links straight to the fix.
- **Client health**, lowest first. Each client gets a 0–100 score with the reasons behind it:
  - negative reviews waiting, replies over 48h
  - failed posts
  - Google not connected or failing, expired social logins
  - leads down 20%+

  Shown as *Good* (80+), *Watch* (50–79) or *At risk*, with Google/Meta live status and the client's numbers.

The keys under `kpis` are unchanged for the mobile app; the new numbers are under `master`.

## Approval guarantee

**Nothing is published without approval.** The approval is recorded on the item itself (`approved_by`, `approved_at`), and the lowest-level publish functions refuse anything without it. So no button, API call, bulk action, scheduler run, Celery task or future code path can skip it.

| | Rule |
|---|---|
| Review replies | Every reply needs **Approve** (permission `review.approve`) before **Publish** (`review.publish`), whatever the rating. People with both get *Approve & publish*, which records two steps. Editing, regenerating, rejecting or reopening clears the approval, and so does the reviewer editing the review on Google. |
| Posts | Only *Approve & schedule* (or creating the post as scheduled, which needs approval rights; with client approval mode on, only the client) makes a post publishable. Unscheduling, requesting changes, editing or re-adapting a failed post sends it back to Draft and clears the approval. |
| Last line of defence | `review_queue.publish` raises "hasn't been approved". `content_service` moves an unapproved row back to Draft and logs `publish blocked (not approved)`, so Google and Meta are never called. |
| Exceptions | **Auto-publish**: off by default. A person turns it on per client. It covers only positive 4–5★ replies to reviews under 14 days old, and is recorded as `approval_rule = "auto_publish"`. Negative reviews always wait for a person. **Post automatically** (Google Post): off by default, turned on by someone who can approve, covers only the daily Google text posts, recorded as `approval_rule = "auto_google_post"`; editing a post clears it. |

`tests/test_approval_guard.py` tries every route around this and checks that the fake Google and Meta receive nothing. The end-to-end test checks the same in a real browser.

## End-to-end test

`e2e/` drives the real API and Django site in a browser. Google, Meta and OpenAI are replaced by the same fakes the unit tests use, and the fakes report what they received.

```bash
pip install -r backend/requirements.txt -r web/requirements.txt
cd e2e && npm install && npx playwright install chromium && ./run.sh
```

It runs these steps:
1. The dashboard loads.
2. Connect Google for a client: the location links, reviews are imported and AI drafts are written.
3. The AI reply can't be published before approval, in the UI, through the API, or by a role without rights, and Google has received nothing.
4. Edit, approve, then publish: Google receives exactly the approved text, and the review history records each step.
5. Connect Meta and link the client's Page and Instagram.
6. Save an AI post draft. It can't be published as a draft or while in review, and Meta has received nothing.
7. Approve & schedule, then Publish now: a Facebook photo post and an Instagram post go out.
8. The calendar, dashboard and audit trail show the result.

Screenshots go to `e2e/artifacts/`. CI runs it on every push (job **End-to-end**).

## Deploy the demo

**Locally or on any server with Docker (production mode).** This runs PostgreSQL, Redis, the API, a Celery worker with beat, and Django on gunicorn:
```bash
docker compose -f docker-compose.demo.yml up -d --build --wait
# http://127.0.0.1:8000 → sign in with a demo button (password demo1234)
```
- 24 demo clients are seeded on first start.
- Google, Meta and OpenAI stay simulated until their keys are set; `docker-compose.demo.yml` passes them through from your shell or a `.env` file next to it.
- To serve it on a domain:
  - put HTTPS in front
  - set `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain`, `DJANGO_SECURE_COOKIES=1` and `WEB_APP_URL=https://your-domain`
  - set strong `JWT_SECRET` and `DJANGO_SECRET_KEY`
- CI builds and starts this stack on every push (job **Demo stack**).

**Public demo on Render (free plan).** `render.yaml` is a blueprint:
1. render.com → **New → Blueprint** → select this repository → **Apply**.
2. It creates PostgreSQL, `greenmedia-api` and `greenmedia-web`, wires them together, and generates the secrets. Scheduling runs inside the API, so no Redis or worker is needed for the demo.
3. Open the `greenmedia-web` URL and sign in with a demo button.
4. Optional: add `OPENAI_API_KEY`, the Google keys (`GOOGLE_REDIRECT_URI=https://<api host>/api/google/callback`), the Meta keys, and your own `TOKEN_ENCRYPTION_KEY` in the API service's environment.

> A public demo has well-known demo logins: anyone with the link can sign in. Don't connect real Google or Meta accounts to it. For real use, deploy with `SEED_DEMO=0` and create your own admin (`python -m app.manage create-admin`).

Hosting notes:
- `postgres://` database URLs are accepted (converted for SQLAlchemy).
- Bare hostnames are accepted for `API_URL` and `WEB_APP_URL` (`https://` is added).
- Django trusts the platform's HTTPS proxy on Render.

## Tests

```bash
cd backend && pytest -q          # 188 tests: Preference (fields, validation, photos, progress, AI facts, poster logo and colour, hashtag modes, publish switches), Settings (QR codes and standees, profiles, delete account, refunds, legal), My Plan (billing, coupons, practice checkout, Razorpay callback / webhook / forgery), monthly Report (summary, targets, trends, insights, PDF link), Google Media (validation, one a day, approval, live media API, retry), Google Post (daily keyword posts, auto-post as a standing approval), AI Post (items, posters, viral videos, approve/schedule, video publishing), owner review replies, owner home, Meta connect from the app, business score, clients/contacts CRUD, CSV import, users/roles/login, permissions, tenant isolation, escalation, state machines, publish failures,
                                 #   and the Google flow (agency + per-client OAuth, encrypted tokens, persisted refresh, locations, review import, reply, posts, insights, revoked access, diagnostics, review fetch/edits, sample-data fallback, queue filters and bulk actions, OpenAI requests/errors/retry, brand-voice prompt, audit details,
                                 #   content statuses, AI post drafts, single-winner publishing, retries/backoff, Celery dispatch,
                                 #   Meta connect/link/publish to Facebook & Instagram, per-platform adapt + checks, calendar,
                                 #   approval guarantee on every publish path, master dashboard KPIs,
                                 #   phone OTP sign-in: codes, limits, profiles, MSG91/Twilio)
REDIS_TEST_URL=redis://127.0.0.1:6379/0 pytest -q tests/test_content_scheduling.py   # + a real Redis broker and Celery worker
TEST_DATABASE_URL=postgresql+psycopg://greenmedia:greenmedia@127.0.0.1:5432/greenmedia_test pytest -q   # same suite on PostgreSQL
cd mobile  && flutter analyze && flutter test   # 47 tests: Preference (progress, socials, tabs, poster fields, logo upload, hashtags, colour, choices, publish and religious switches, AI terms), Settings (privacy choice, legal, QRs, standee scan, change profile, refund, delete account), My Plan (billing details, compare, choose plan, coupon, pay, back active), Report (summary, filters, trends, download, month), Google Media (tabs, where/what to upload, gallery + camera upload, approve, retry), Google Post (approve, edit, reject, post automatically, write now), AI Post (tabs, viral video flow, items + poster), owner review replies + reply settings, owner home (help, Facebook/Instagram connect, carousel, performance, calendar, keyword planner), phone OTP sign-in, email login, role-based navigation, escalation UI, API contract
```

The Flutter tests use JSON fixtures captured from the real API, so they catch contract drift.

## Mobile app sign-in (phone + OTP)

The Flutter app opens on **mobile-number sign-in**, built for business owners:
1. **Enter your phone number.** +91 by default; +971, +1 and +44 are also supported. A tick appears when the number is valid, and *Get OTP* enables.
2. **Verify your mobile number.** Enter the 4-digit code; it checks itself once the last digit is in. A 30-second timer runs before *Resend code*, and SMS autofill and paste work.
3. **Select profile.** Every account linked to that number is listed. A business owner with two businesses sees both. Businesses not yet linked to Google show **Needs Google**, and agency staff appear under *Agency team*. With a single profile the app opens straight away.

Staff can still use **Sign in with email**.

**Who can sign in.** Only existing accounts whose **Mobile number** is set: *Settings → Team members*, or `phone` on `POST/PATCH /api/users`. Several accounts may share a number; that's what profile selection is for.

**Security**
- Only a hash of the code is stored.
- A code expires after 5 minutes and can be used once.
- 5 wrong tries lock the code; at most 5 codes per number per hour, 30 seconds apart.
- The request step answers the same way for unknown numbers, so it can't be used to probe which numbers have accounts, and no SMS is sent for them.
- Choosing a profile requires the short-lived token from verification, and the chosen account must use that number.
- Sign-ins are audited as `signed in (phone OTP)`.

**Sending the SMS** (`backend/.env`)
- `SMS_PROVIDER=console` (default): the code only appears in the API log. On demo installs (`SEED_DEMO=1`) the app also shows a "Demo server — code 1234" chip.
- `SMS_PROVIDER=msg91`: for India. Needs `MSG91_AUTH_KEY` and a DLT-approved OTP template (`MSG91_TEMPLATE_ID`, with `##OTP##`).
- `SMS_PROVIDER=twilio`: needs `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM`.
- With a real provider the code is never in the API response.

**Demo numbers:**
- **98765 43210:** Dr. Anjali Rao, who owns *Smile Dental Studio* and *GlowUp Salon & Spa*, so you'll see profile selection.
- **90000 00001 … 90000 00005:** admin, account manager, SEO, content, designer.

| Method & path | What it does |
|---|---|
| `POST /api/auth/otp/request` `{phone, country_code?}` | Send a code. Returns `masked`, `length`, `resend_in` (and `dev_code` on console/demo only). |
| `POST /api/auth/otp/verify` `{phone, code}` | Returns `otp_token` (10 min) and `profiles` (title, subtitle, kind, Google state, group). |
| `POST /api/auth/otp/select` `{otp_token, user_id}` | Signs in to that profile, returning the normal access token. |

## Mobile home for business owners

A business owner who signs in to the app lands on a home page modelled on Dhanda AI's (agency staff open the same
page from a client's screen with **Business score**). Top to bottom:

- **Top bar** with the business, phone and city, and **Help**: a popup to call or WhatsApp the account manager.
- **Score carousel** (swipe):
  - **Marketing Score** gauge out of 100. *Improve Marketing Score* lists the points for rating, reviews, replies to
    the last 50 reviews, new reviews, Google posts, profile connection, search visibility and customer actions, each with
    a tip, plus *Download Report* (a printable page behind a signed 15-minute link).
  - **Growth in Marketing Score** — this week's daily score (saved once a day in `score_snapshots`).
  - **Marketing Tracker** — this week's targets vs achieved: AI posts approved, AI posts published and review replies
    (`WEEKLY_POST_TARGET`, `WEEKLY_REPLY_TARGET`, default 5), with "N more to achieve the target".
- **Google's Performance** — Views, Leads, Calls, Directions, Website for 30 / 60 / 120 days with a daily chart.
- **Social Calendar** — posts per day (Generated / Approved / Posted) and how many wait for approval.
- **Keywords** and the **Keyword Planner**: the keywords the business tracks, and a search (country, city, keyword)
  that returns ideas with monthly searches and competition. Terms Google already showed the profile for come first with
  their real impressions (marked *Google*); the rest are **estimates** until a keyword-volume provider is connected.
  Each search uses one of the month's credits (`KEYWORD_SEARCH_MONTHLY_LIMIT`, default 20).
- **Competitor Analysis** — local competitors within 5 km and the surrounding area beyond, each row expanding to the
  address, distance and number of ratings. Staff add real competitors with
  `POST /api/clients/{id}/competitors` (`name`, `rating`, `review_count`, `address`, `distance_km`), which replaces the
  demo list.
- **Stay active on Social Media** — Facebook / Instagram status and **Connect**, which the owner does themselves:
  "Taking you to Facebook/Instagram" → Facebook's login in the in-app browser → back in the app the Page is linked
  (or the owner picks one if their login manages several). If the login doesn't finish, the app explains why — closed
  early, a permission switched off, no Page, no Instagram Business account on the Page, Page already used — with
  *Connect again* and *Show me step by step*. API: `POST /api/clients/{id}/meta/connect` (`{"platform"}` → `auth_url`),
  `GET …/meta/connect/{attempt}`, `POST …/{attempt}/choose`, `POST …/{attempt}/cancel`. Needs `META_APP_ID`,
  `META_APP_SECRET` and `META_REDIRECT_URI` like the web dashboard's Meta connection.
- **Get more Google reviews** — QR of the profile's "write a review" link, WhatsApp share and copy.
- **Growth Action** — a floating checklist of 10 actions (profile, approve and publish posts, reply to reviews, connect
  Facebook and Instagram, track keywords, get new reviews, reach a score of 70), each opening the right screen.

Search keywords sync from the Business Profile Performance API (`searchkeywords/impressions/monthly`) with every Google
sync. Demo databases get sample keywords, competitors and two weeks of score history (marked as sample in the app).
API: `GET /api/clients/{id}/score` (the whole home page), `GET …/performance?days=30|60|120`, `GET …/calendar?month=YYYY-MM`,
`GET …/keyword-planner`, `POST …/keyword-planner/search`, `POST|DELETE …/keyword-planner/keywords`.

## Mobile Review Replies (business owners)

The owner's **Replies** tab, modelled on Dhanda AI:

- **Reviews Trend** (reviews per week, this month or the last 3 months) and the **Google Ratings** card, swipeable.
- **All / Pending / Replied** with counts, and a filter (sort, star rating).
- Each review shows the reply as **Owner — You replied …** with **edit** and **delete**. A **Keyword Used | Search Volume**
  table lists the business's search keywords the reply contains (the keyword words are bold in the reply); the
  business's own name never counts, and keywords made of the same words show once.
- Pending reviews: **Reply with AI** (drafts with the brand voice and Reply Settings) or **Write reply**, then **Post reply**.
  Saving is the approval, so only people who can approve can post. Owners post their own replies directly, except to
  1-2★ reviews, which are saved as approved and posted by the account manager (the escalation rule).
- **Settings → Reply Settings**: per category (3-5★ / 1-2★) the reply length — Ultra, Short, Medium, Long — and the
  language (same as the review, English, Hindi or any language from the searchable list), with a sample reply. AI drafts
  follow it and work in a couple of the business's search keywords where natural.

API: `POST /api/reviews/{id}/post` (`{"reply"}` — save, approve and post, or update a posted reply on Google),
`DELETE /api/reviews/{id}/reply` (removes it from Google), `GET /api/reviews/summary?client_id=&period=month|quarter`,
`GET|PUT /api/clients/{id}/reply-settings`; review lists now include `keywords_used`.

## Mobile AI Post (business owners)

The owner's **AI Post** tab, modelled on Dhanda AI:

- **Try Generating Viral Video (n/5)**: pick one of 8 templates (Stop Scrolling, POV: Found It, Deal Alert, …), see a
  **Preview** with the business's own products and end card, then **Generate Viral Video**. The server renders a 9:16 MP4
  in the background (Pillow frames + the bundled ffmpeg from `imageio-ffmpeg`; a Celery task when Redis is on). The app
  shows "Content Agent is creating the best video for your business…" with each step, or **Notify me when it's ready**.
- **Generate AI Post (n/5)**: **Select Item** or **Add New Item** (photo*, name*, description, price) and get a poster
  (1080×1350) with an AI caption that works in the business's search keywords.
- Review: **Your video is ready** → **Reject** or **Approve** → **Select Date & Time** (calendar with already-scheduled
  days in green, time wheels; it suggests the next free day at 7:00 AM India time) → **Successfully Scheduled**.
- Lists: **Scheduled (Pending / Approved / Rejected)**, **Posted** (This Week / This Month / Last 3 Months / Lifetime) and
  **Not Posted**. Each post shows the keywords it targets with search volumes, an estimated view count, the caption with
  keywords highlighted, and share / download.
- Nothing posts without approval. Videos go to Facebook (`/{page}/videos`) and Instagram Reels; Google gets the cover image.
  Media is served from `/media`; set `PUBLIC_BASE_URL` to the API's public **https** address (Meta and Google fetch media
  from it) and `MEDIA_DIR` to a persistent volume. Monthly limits: `AI_POSTS_MONTHLY`, `VIRAL_VIDEOS_MONTHLY` (5 each).

API: `GET|POST /api/clients/{id}/items` (multipart `image`, `name`, `description`, `price`), `DELETE …/items/{item}`,
`GET /api/video-templates`, `GET /api/clients/{id}/ai-posts/overview`, `GET …/ai-posts?tab=pending|approved|rejected|posted|not_posted&period=`,
`POST …/ai-posts/poster {item_id}`, `POST …/ai-posts/video {template, item_ids?}`, `GET …/ai-posts/{post}`,
`GET …/ai-posts/free-slot?month=`, `POST …/ai-posts/{post}/approve {scheduled_at}`, `POST …/ai-posts/{post}/reject`.

## Mobile Google Post (business owners)

The owner's **Google Post** tab, modelled on Dhanda AI.

- **Google works best with keywords**: the card shows the business's keywords; **Optimise keywords** opens the Keyword
  Planner to add or remove them.
- **Content Agent**: with **Post daily on Google** on (the default), the scheduler writes tomorrow's text-only Google
  post every day at the posting time (default 10:00 AM India time). Each post is built around one keyword, taking turns
  by least-used and then by search volume; searches for the business's own name are skipped. Each day has a different
  angle (tip, why us, FAQ, …). With an AI key the AI writes it in the brand voice without hashtags; otherwise a template
  quotes the search phrase. **✎** writes the next one now.
- Posts are grouped as **Waiting for your approval / Scheduled / Posted / Not posted / Rejected**. Each card shows the
  keyword and its monthly searches, with the phrase highlighted in the text. Actions: **Approve** (posts on its day),
  **Edit** (clears any approval), **Reject**.
- **Post automatically**: off by default; turning it on asks first, and only someone who approves posts can. It is a
  standing approval recorded on each post as `approval_rule = "auto_google_post"` with the person who turned it on. It
  covers only these daily Google text posts, an edited post needs approval again, and if that person loses the right to
  approve, posts wait again.

API: `GET /api/clients/{id}/google-posts`, `PUT …/google-posts/settings {daily?, auto?, time?: "HH:MM"}`,
`POST …/google-posts/generate {keyword?}`, `PATCH …/google-posts/{post} {text}`; approve / reject use
`POST …/ai-posts/{post}/approve {scheduled_at}` and `…/reject`. The daily job runs in `python -m app.jobs`, the in-process
scheduler, and Celery beat (`greenmedia.google_posts`, hourly).

## Mobile Google Media (business owners)

The owner's **Google Media** tab, modelled on Dhanda AI. Owners' bottom bar has Dhanda's five tabs, Home / Replies /
AI Post / Google Post / Google Media; Analytics, Report, My Plan, Settings and Sign out open from their avatar on Home.

- **Where it will upload? → Click here to know**: a sketch of their Google Maps listing with their photos, and "Fresh
  photos can get you up to 25% more calls".
- **Scheduled / Uploaded / Not Posted** with counts ("3 Media scheduled") and a grid of photos and videos. Tap one to see
  it large, plus **Approve** (added by someone who can't approve), **Retry** (not posted) or **Remove** (not uploaded yet).
- **Upload Media → Open Gallery** (several at once) or **Open Camera** (photo, or video up to 30 s).
  **What to Upload?** swipes through Google's photo kinds: Exterior, Interior, Product, Staff in Action, Food and Drink,
  Common Area, Team, Something Else.
  Then pick the kind and **Now** or **One a day** (one per day from tomorrow at 11:00 AM India time, skipping days that
  already have one).
- The scheduler uploads approved items when due. Live profiles use the Business Profile media API
  (`POST …/locations/{id}/media` with `sourceUrl` and `locationAssociation.category`); demo profiles are simulated.
  Temporary Google errors retry up to 5 times; other errors land in Not Posted with Google's message. An upload cut
  off half-way isn't retried blindly, since Google may already have it.
- Google's rules are checked on upload: photos at least 250 × 250 px (re-encoded as JPEG, location data dropped);
  videos MP4/MOV, up to 75 MB and 30 seconds, with a thumbnail from the first frame. Google downloads the file, so
  `PUBLIC_BASE_URL` must be the API's public **https** address.

API: `GET /api/google-media/categories`, `GET /api/clients/{id}/google-media?tab=scheduled|uploaded|not_posted`,
`POST /api/clients/{id}/google-media` (multipart `file`, `category`, `when=now|spread`), `POST …/google-media/{m}/approve`,
`POST …/google-media/{m}/retry`, `DELETE …/google-media/{m}`.

## Mobile Report (business owners)

**Report** (from the avatar on an owner's Home), modelled on Dhanda AI. It shows the last full month by default; tap the
title to pick any of the last 12 months.

- **Sep 26 Performance Summary (vs Aug 26)**: Profile Views, Leads, Calls, Direction Req., Media Uploaded, Engagement
  (calls + directions + website clicks as a share of views), Review Replies, Google Posts and Website. Each tile shows the
  month's number and the change against the month before; the tiles scroll sideways.
- **Growth Action Report**: what was done against the targets (target vs achieved bars) for SEO posts published on
  Google, media uploaded and review replies. Filters: **Last Month** (by week, W1–W5), or Last 3, 6 or 12 Months (by
  month). Weekly targets: `WEEKLY_POST_TARGET` (5), `WEEKLY_MEDIA_TARGET` (3), `WEEKLY_REPLY_TARGET` (5).
- **Performance Report**: 6 or 12-month line charts for Score, Views, Engagement, Leads, Calls, Direction Requests and
  Views v/s Engagements Conversion, each with a one-line insight ("… saw a 38% drop in Profile Views in Sep 26 compared
  to Aug 26, but with ongoing improvements, growth is expected in coming months.").
- **Download**: a PDF opened through a 15-minute signed link (the phone's browser can't send our login token). Pages:
  Performance Summary, Growth Action Report, Performance Report, the agents' status (review replies waiting, media
  queued) and **What You Should Do Now?** from the Growth Action checklist. The pages are drawn with Pillow, so there is
  no extra dependency.

The demo seeds 13 months of Google metrics and weekly Business Score points for its first three businesses, so the
12-month charts have history.

API: `GET /api/clients/{id}/monthly-report?month=YYYY-MM`, `POST /api/clients/{id}/monthly-report/link?month=` →
`{url, filename, expires_at}`, `GET /api/clients/{id}/monthly-report.pdf?t=…`.

## Mobile My Plan (business owners)

**My Plan** (from the avatar on an owner's Home), modelled on Dhanda AI:

- **Your Pro Plan is Active / Not Activated / Expired**, with the date it's valid till and the days left.
- **Unlock Your Growth! Start @ ₹999/-** opens the plan comparison (Starter / Pro / 3 Year Plan, feature by feature),
  then **Go Premium** opens **Choose your plan**: ₹999 / month, ₹16,000 for 12 months, ₹27,000 for 24 months or ₹36,000
  for 36 months. A coupon code can be applied, then **Continue** goes to payment.
- **Billing Details**: VAT/GSTIN (format-checked), billing address, and shipping address or "same as billing".
- **No Active Mandates**: nothing is debited automatically; every payment is one the owner makes. **Payments** lists
  each one with its date, period, coupon and status.

**Payment** goes through **Razorpay Payment Links**: the app opens Razorpay's hosted page, so the app needs no payment
SDK. A plan becomes active only when Razorpay confirms the payment, through any of these:
- the signed redirect back (`/api/plan/razorpay/callback`)
- the signed webhook (`POST /api/plan/razorpay/webhook`, event `payment_link.paid`)
- Razorpay's own answer when the app asks after the owner returns

The app's word alone never activates a plan. Paying again extends the plan from the end of the current one.

Settings: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (set the webhook in the Razorpay
dashboard to `{PUBLIC_BASE_URL}/api/plan/razorpay/webhook`). `COUPONS` takes the form `CODE:10%,CODE2:500` (a
percentage, or rupees off). Without keys, `PAYMENTS_DEMO=1` (default when `SEED_DEMO=1`) uses a practice checkout page
that is clearly marked and moves no money; with `PAYMENTS_DEMO=0` and no keys, the app says online payment isn't set up.

API: `GET /api/clients/{id}/plan`, `PUT …/plan/billing`, `POST …/plan/quote {plan, coupon}`,
`POST …/plan/checkout {plan, coupon}` → `{id, url, …}`, `GET …/plan/payments/{payment}`.

## Mobile Settings (business owners)

**Settings** (from the avatar on an owner's Home), modelled on Dhanda AI. Agency staff keep the server/AI settings page.

- **Business card**: name, phone and business code; **My Plan** (Upgrade to Pro, or the plan and its end date) → Manage.
- **Tools**:
  - **Preference**: see below.
  - **Configure QR Standee**: scan a pre-printed standee with the camera (or type its code) to link it to the
    business. The agency makes standee codes with `POST /api/qr-standees {count}`; each prints `{PUBLIC_BASE_URL}/q/{code}`
    (PNG at `/q/{code}.png`).
  - **My QRs**: generate up to 50 trackable "review us on Google" QR codes. `/q/{code}` counts the scan and opens the
    business's Google review form. Each shows its scans and last scan, and **Download** gives a printable standee PNG
    ("Loved your visit? Review us on Google", business name, QR, stars).
  - **Keyword Planner**.
- **Account**:
  - **Change Profile**: switch to another business on the same mobile number, with no new OTP.
  - **Logout**.
  - **Delete Account**: type DELETE to confirm. The login stops working at once, the phone and email are removed, and
    the account manager gets a task to delete the business's data within 30 days.
- **Privacy**: **Analytics & Personalisation**, off unless the person turns it on. It is stored per person
  (`prefs.analytics`); the app has no tracking SDKs yet.
- **Legal**: **Privacy Policy** and **Terms of Service**, served by the API (`/api/legal/privacy|terms`, also as web pages
  at `/legal/privacy|terms` for store listings), and **Refund Request**: the refund policy per plan, and **Request Refund**
  for a payment within `REFUND_DAYS` (7). It creates a refund request and a task for the account manager. Monthly plans
  aren't refundable.
- The legal text describes what this product actually does (Google/Meta access, AI drafting, Razorpay, DPDP Act 2023
  rights). **Have a lawyer review it** and set `LEGAL_COMPANY`, `LEGAL_EMAIL`, `LEGAL_ADDRESS` and `LEGAL_UPDATED`.

API: `GET /api/clients/{id}/settings`, `GET|PUT …/preference`, `GET|POST …/qrs`, `POST …/qrs/claim {code}`,
`POST …/qrs/{qr}/link` → standee PNG, `GET|POST …/refunds`, `GET /api/auth/profiles`, `POST /api/auth/switch {user_id}`,
`PUT /api/auth/prefs {analytics}`, `POST /api/auth/delete-account {confirm: "DELETE"}`, `GET /api/legal/{privacy|terms|refund}`.

### Preference

What the business tells us about itself, so posts look and sound like it (modelled on Dhanda AI's Preference page).
A bar on top shows the next missing step out of 6 (Google, Facebook or Instagram, a top selling item, the logo, an
interior photo, a team photo); tapping it goes there. Tabs jump to each part:

- **Socials**: Google, Facebook and Instagram connection, with Connect for the missing ones.
- **Selling**: top selling items (Add Product).
- **Branding** ("Below details will be used in Posters"): a live poster preview; brand name, phone and address on the
  poster, additional info, founder name, gender and photo (and whether to show the founder in promotions); the
  business's story (how it is different, why visit, the industry's low standards and its answers to them and to
  malpractices, common customer mistakes, guidelines, nearest landmark); the logo and up to 5 interior and 5 team
  photos; up to 10 custom hashtags with **Use Exact Hashtag** (only these) or **Use Additional Tags** (these first,
  then generated ones).
- **Advance Settings**: brand colour, tagline, description, website, tone of voice; target gender, age group, region,
  model ethnicity, audience and CTA; which platforms to publish on; which religious festivals to post for; the
  **Terms of AI usage**; Open my Google Profile.

Each field saves on its own. AI drafts use the owner's facts and audience (never inventing others), posters and video
end cards use the brand name, phone, address, logo and colour, and captions follow the hashtag choice. A platform
switched off gets no AI posts.

API: `GET /api/clients/{id}/preference` → `{values, photos, socials, products, progress, labels, choices}`,
`PATCH …/preference` with only the changed fields (unknown fields and invalid choices are refused; more than 10
hashtags is a 422), `POST …/preference/photos/{slot}` (multipart `image`) and `DELETE …/preference/photos/{slot}`
(slots: `logo`, `founder`, `interior_1`…`interior_5`, `team_1`…`team_5`). `GET /api/legal/ai` is the AI usage terms.
## Building the mobile apps

```bash
cd mobile
flutter build apk --release --dart-define=API_URL=https://api.yourdomain      # Android
flutter build appbundle --release --dart-define=API_URL=https://api.yourdomain # Play Store
flutter build ipa --release --dart-define=API_URL=https://api.yourdomain       # iOS (on a Mac, with your Apple team)
```

Release builds only talk to HTTPS APIs. Plain `http://` is allowed only in Android debug builds and for localhost/LAN on iOS.

**CI** (`.github/workflows/build.yml`) runs the API tests, Django checks with a live smoke test of every page, and Flutter analyze and tests. It also builds a release **Android APK**, which you can download from the run's Artifacts. The unsigned **iOS build** runs on a macOS runner, whose minutes cost 10× Linux ones and are the first to stop when the account's spending limit is reached. It is opt-in: run the workflow by hand (Actions → CI → Run workflow), or set the repository variable `IOS_BUILD=true`. Otherwise it shows as skipped. Set the repository variable `API_URL` to bake your API address into those builds. Store releases need your Android keystore and Apple signing.

## Deploying

See also [Deploy the demo](#deploy-the-demo) (Docker images: `backend/Dockerfile`, `web/Dockerfile`).

- **API:** `uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4` behind HTTPS. Set `DATABASE_URL` to PostgreSQL, a strong `JWT_SECRET`, and `SEED_DEMO=0`.
- **Web:** `python manage.py collectstatic && gunicorn greenmedia_web.wsgi`. Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` and `API_URL`. Static files are served by WhiteNoise.

## Roadmap to production

1. **More integrations.** Google Business Profile is live (see above). Next come Search Console, GA4, Meta, LinkedIn and YouTube, following the same pattern as `backend/app/google/` with `backend/app/publishers.py` as the seam.
2. **Real-time reviews.** Switch from polling to GBP Pub/Sub notifications, and move the scheduler to a dedicated worker when running several API processes.
3. **Migrations.** Add Alembic before the first production schema change. Tables are currently created by `create_all`.
4. **Phase 3–4.** WhatsApp Business API, push notifications, lead CRM, then SaaS billing, white-label branding and custom domains. `tenant_id` is already on every row.
