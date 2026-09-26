# Green Media AI Command Center

Manage 100+ local-business clients from one dashboard: Google Business Profile, AI review replies, AI content for every social platform, creative sizing, SEO, analytics and monthly client reports. It's built from the *Green Media AI Command Center Blueprint V1* as a competitor to Dhanda AI.

**One codebase, every platform:**

| Platform | Shell | Output |
|---|---|---|
| iOS (iPhone / iPad) | Capacitor 8 (`ios/`, Swift Package Manager) | Xcode project → App Store |
| Android | Capacitor 8 (`android/`) | APK / AAB → Play Store |
| Desktop (Windows, macOS, Linux) | Electron (`electron/`) | `.exe`, `.dmg`, `.AppImage`, `.deb` |
| Web / PWA | Vite | static `dist/` |

The UI adapts to the device. Phones get a bottom tab bar, a "More" sheet, cards in place of tables, and iOS safe-area insets. Desktops and tablets get a full sidebar. Light and dark themes are both included.

## What's in the MVP

The MVP covers blueprint Phases 1–2 and part of Phase 3.

- **Login and role-based access.** Roles are Admin, Account Manager, SEO, Content, Designer and Client. Client-portal users only ever see their own company.
- **Master dashboard.** Shows KPI cards, a 30-day growth chart, a "needs attention" list (negative reviews and SEO drops) and a client performance table.
- **Clients.** Search and filter the client list. Each client has a workspace with profile, connected accounts, AI brand voice, publishing-safety switches, keywords, reviews, calendar, tasks, reports and notes.
- **GMB Center.** Shows connection health, sync, insights, customer actions, posts, offers and reviews.
- **AI Review Queue.** Each review goes through sentiment and language detection, then an AI draft. You can then edit, regenerate, reject, approve or publish. Replies to reviews rated 2 stars or lower must be approved before they can be published.
- **AI Content Studio.** You enter a topic, the AI writes master copy and a variant for each platform (GMB, Facebook, Instagram, LinkedIn, YouTube, X) plus a creative brief. The content then goes through approval, scheduling and publishing.
- **Creative Studio.** Upload one master image and preview it at 6 platform sizes (4:5, 1:1, 9:16, 4:3, 1.91:1, 16:9). Each size exports as a PNG.
- **Social Hub.** A unified monthly calendar, a publishing queue with retry for failed posts, and health checks for connected accounts (expired tokens are flagged).
- **SEO Center.** Tracked keywords with current and previous rank, the biggest movers, GSC clicks, GA4 organic sessions and technical tasks.
- **Analytics.** GMB, website, social and leads data over 7, 30 or 45 days, for one client or all of them.
- **Reports.** AI monthly summary, KPI comparison and ranking movement. Save as PDF (print), or send by email or WhatsApp.
- **Team and Tasks.** A kanban board with assignees, priorities and due dates, plus an **audit trail** of every action.
- **Settings.** API server, notifications, client-approval mode, theme, integrations list and the permission matrix.

**Safety defaults (from the blueprint):** everything needs human approval. Auto-publish is an explicit setting per client and per channel. Failed publications are shown clearly.

## Quick start

```bash
npm install
npm run dev            # web at http://localhost:5173
```

Sign in with any demo account on the login screen; any password works in demo mode. The app ships with 24 sample clients and 90 days of metrics, so it runs fully offline with template-based AI.

### Real AI

AI keys stay on the server and are never bundled into the mobile or desktop apps.

```bash
cp .env.example .env    # set ANTHROPIC_API_KEY (or AI_PROVIDER=openai + OPENAI_API_KEY)
npm run server          # http://localhost:8787
```

Then open **Settings → API server URL** in the app, enter the server address, and click **Test connection**. Review replies, content and reports will now come from the model. If the server can't be reached, the app falls back to templates.

> iOS and Android block plain `http://` requests. For devices, deploy the server behind HTTPS and add that origin to `CORS_ORIGINS`.

## Building the apps

### Desktop

```bash
npm run desktop:dev     # Electron + hot reload
npm run desktop         # run the production build in Electron
npm run desktop:dist    # installers in release/ (build each OS on that OS)
```

### Android

This needs Android Studio and JDK 21.

```bash
npm run android         # build web → cap sync → open Android Studio → Run
# or: npm run cap:sync && cd android && ./gradlew assembleDebug
```

### iOS

This needs macOS with Xcode 16 or later.

```bash
npm run ios             # build web → cap sync → open Xcode → pick a team → Run
```

After any web change, run `npm run cap:sync` to copy the new build into the native projects.

### CI

`.github/workflows/build.yml` builds the web bundle, an Android debug APK, an iOS simulator build, and Windows, macOS and Linux desktop installers on every push. You can download the results from the run's **Artifacts**. Store releases still need your signing keys: an Android keystore, an Apple team, and Windows/macOS code-signing certificates.

## Project layout

```
src/
  data/        types (mirror the DB), seed data, store (offline, localStorage), client scoping
  lib/         ai client (server → template fallback), permissions (RBAC), sentiment, platform bridge
  components/  layout (sidebar ↔ tab bar), icons, UI kit and charts
  pages/       one file per blueprint screen
server/        zero-dependency Node API: /api/health, /api/ai/review-reply, /api/ai/content, /api/ai/report
db/schema.sql  multi-tenant PostgreSQL schema (blueprint §4) with row-level security
electron/      desktop main process and preload
android/ ios/  Capacitor native projects
```

## Roadmap to production

The UI and workflows are complete, and the data layer is a local store. To go live:

1. **Backend data.** Move the store actions in `src/data/store.ts` to REST endpoints backed by `db/schema.sql`. Real auth needs bcrypt and optional TOTP 2FA, with JWT sessions carrying `tenant_id`.
2. **Integrations.** Use OAuth for Google Business Profile, GSC, GA4, Meta, LinkedIn and YouTube. Store tokens encrypted and handle token expiry and refresh. Check each platform's current API permissions before building against it.
3. **Scheduler.** A Redis/BullMQ worker should publish from `scheduled_posts`, sync reviews and metrics nightly, and log every failure.
4. **Phase 3–4.** WhatsApp Business API, lead CRM, push notifications (`@capacitor/push-notifications`), then SaaS billing, white-label branding and custom domains. Tenancy is already in the schema.
