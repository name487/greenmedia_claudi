// End-to-end: connect → review → AI reply → approve → publish, the same for a social post, and proof that nothing
// reaches Google or Meta before it is approved. Run with ./run.sh (starts the API with fake Google/Meta/OpenAI + Django).
import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const WEB = process.env.E2E_WEB_URL || 'http://127.0.0.1:8000';
const API = `http://127.0.0.1:${process.env.E2E_API_PORT || 8001}`;
const FAKES = `http://127.0.0.1:${process.env.E2E_FAKE_PORT || 8099}/`;
const OUT = 'artifacts';
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const fakes = async () => (await fetch(FAKES)).json();
const apiToken = async (email) => (await (await fetch(`${API}/api/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email, password: 'demo1234' }) })).json()).access_token;
const apiPost = async (token, path) => (await fetch(`${API}${path}`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })).status;
const pad = (n) => String(n).padStart(2, '0');
const ist = (d0) => { const d = new Date(d0.getTime() + 330 * 60e3); return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
let step = 0;
const ok = (msg) => console.log(`✓ ${++step}. ${msg}`);

async function session(email) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  // Stand-ins for Google's and Facebook's consent screens: approve and return to the API callback with a code
  await page.route(/\/(clients\/\d+|social)\/$/, async (route) => {
    const body = route.request().postData() || '';
    if (route.request().method() !== 'POST' || !/action=(google_connect|meta_connect)/.test(body)) return route.continue();
    const resp = await route.fetch({ maxRedirects: 0 });
    const u = new URL(resp.headers()['location']);
    const cb = body.includes('meta_connect') ? 'meta' : 'google';
    route.fulfill({ status: 302, headers: { location: `${API}/api/${cb}/callback?code=good-code&state=${encodeURIComponent(u.searchParams.get('state'))}` } });
  });
  await page.goto(`${WEB}/login/`);
  await page.fill('#email', email);
  await page.fill('#password', 'demo1234');
  await page.click('button[type=submit]');
  await page.waitForURL(`${WEB}/`);
  return page;
}
const flash = async (p) => (await p.locator('.messages').allInnerTexts()).join(' | ').replace(/\s+/g, ' ');
const statValue = async (p, label) => Number((await p.locator('.stat', { hasText: label }).locator('.stat-value').innerText()).replace(/\D/g, '') || 0);

try {
  const admin = await session('admin@greenmedia.in');
  const adminToken = await apiToken('admin@greenmedia.in');
  const contentToken = await apiToken('sneha@greenmedia.in');

  // 1. Master dashboard
  assert.ok(await admin.locator('text=Client health').count(), 'dashboard shows the client health table');
  const waitingBefore = await statValue(admin, 'Waiting for approval');
  await admin.screenshot({ path: `${OUT}/01-dashboard.png`, fullPage: true });
  ok(`dashboard loads (${waitingBefore} items waiting for approval)`);

  // 2. Connect Google for Smile Dental → location linked, reviews imported, AI drafts written
  await admin.goto(`${WEB}/clients/1/`);
  await admin.locator('#google').getByRole('button', { name: /^(Re)?[cC]onnect Google$/ }).click();
  await admin.waitForLoadState('networkidle');
  assert.match(await flash(admin), /Google connected and “Smile Dental Studio - Baner” linked/);
  ok('Google connected and location linked');

  // 3. Review with an AI reply, not publishable yet
  await admin.goto(`${WEB}/reviews/?client=1&filter=all&q=Meena`);
  let card = admin.locator('section.review', { hasText: 'Meena K' });
  assert.match(await card.locator('.ai-meta').first().innerText(), /AI draft · openai\//);
  assert.equal(await card.getByRole('button', { name: 'Publish to Google' }).count(), 0, 'no direct publish before approval');
  const rid = Number((await card.getAttribute('id')).slice(1));
  assert.equal(await apiPost(adminToken, `/api/reviews/${rid}/publish`), 409, 'API refuses to publish an unapproved reply');
  assert.equal(await apiPost(contentToken, `/api/reviews/${rid}/publish`), 403, 'content role cannot publish');
  assert.equal(await apiPost(contentToken, `/api/reviews/${rid}/approve`), 403, 'content role cannot approve');
  const writer = await session('sneha@greenmedia.in');
  await writer.goto(`${WEB}/reviews/?client=1&filter=all&q=Meena`);
  const wcard = writer.locator('section.review', { hasText: 'Meena K' });
  assert.equal(await wcard.getByRole('button', { name: 'Approve', exact: true }).count(), 0);
  assert.equal(await wcard.getByRole('button', { name: /Publish|Approve & publish/ }).count(), 0, 'writer sees no publish/approve buttons');
  assert.deepEqual((await fakes()).google_replies, {}, 'nothing reached Google');
  ok('AI reply drafted; publish blocked without approval (UI, API, roles) — Google received nothing');

  // 4. Edit → approve → publish
  const finalReply = 'Hi Meena, we are truly sorry about the wait. Please call us on +91 98765 43210 so we can make it right. — Dr. Anjali & Team';
  await card.locator('textarea[name=reply]').fill(finalReply);
  await card.getByRole('button', { name: 'Save edit' }).click();
  card = admin.locator('section.review', { hasText: 'Meena K' });
  assert.match(await card.locator('.ai-meta').first().innerText(), /Edited by your team/);
  await card.getByRole('button', { name: 'Approve', exact: true }).click();
  card = admin.locator('section.review', { hasText: 'Meena K' });
  assert.deepEqual((await fakes()).google_replies, {}, 'approval alone publishes nothing');
  await card.getByRole('button', { name: 'Publish to Google' }).click();
  assert.match(await flash(admin), /Reply published to Google/);
  assert.deepEqual((await fakes()).google_replies, { 'r-new': finalReply }, 'Google received exactly the approved text');
  card = admin.locator('section.review', { hasText: 'Meena K' });
  await card.locator('details summary', { hasText: 'History' }).click();
  const history = await card.locator('ul.history').innerText();
  assert.match(history, /published reply to Google/);
  assert.match(history, /approved reply/);
  assert.match(history, /edited reply/);
  await card.screenshot({ path: `${OUT}/04-review-published.png` });
  ok('edited, approved, published — Google got the approved text; history recorded');

  // 5. Connect Meta and link the Page + Instagram
  await admin.goto(`${WEB}/social/`);
  await admin.locator('#meta').getByRole('button', { name: /^Connect/ }).click();
  await admin.waitForLoadState('networkidle');
  assert.match(await flash(admin), /Connected Meta as Green Media SEO/);
  await admin.locator('#meta tbody tr').first().getByRole('button', { name: 'Link' }).click();
  assert.match(await flash(admin), /Linked Facebook and Instagram/);
  ok('Meta connected; Facebook Page + Instagram linked to Smile Dental');

  // 6. AI post draft → cannot publish until approved
  await admin.goto(`${WEB}/content/?client=1`);
  await admin.fill('input[name=topic]', 'Monsoon check-up offer');
  for (const name of ['Facebook', 'Instagram', 'Google Business']) await admin.locator('label.chip', { hasText: name }).click();
  await admin.fill('input[name=image_url]', 'https://cdn.example.com/monsoon.jpg');
  await admin.getByRole('button', { name: 'Save AI draft' }).click();
  assert.match(await flash(admin), /written by AI/);
  let row = admin.locator('#board li.content-row', { hasText: 'Monsoon check-up offer' }).first();
  const cid = Number((await row.getAttribute('id')).slice(1));
  assert.equal(await row.getByRole('button', { name: 'Publish now' }).count(), 0);
  assert.equal(await apiPost(adminToken, `/api/content/${cid}/publish`), 409, 'API refuses to publish a draft');
  await row.locator('summary', { hasText: 'Edit · set time' }).click();
  await row.locator('input[name=scheduled_at]').fill(ist(new Date(Date.now() + 2 * 86400e3)));
  await row.getByRole('button', { name: 'Set time' }).click();
  row = admin.locator('#board li.content-row', { hasText: 'Monsoon check-up offer' }).first();
  await row.getByRole('button', { name: 'Send for approval' }).click();
  assert.equal(await apiPost(contentToken, `/api/content/${cid}/approve`), 403, 'content role cannot approve posts');
  assert.equal(await apiPost(adminToken, `/api/content/${cid}/publish`), 409, 'API refuses to publish a post in review');
  assert.deepEqual((await fakes()).meta_posts, [], 'nothing reached Meta');
  ok('AI post drafted; publish blocked until approved — Meta received nothing');

  // 7. Approve & schedule → publish now → Facebook photo + Instagram post
  row = admin.locator('#board li.content-row', { hasText: 'Monsoon check-up offer' }).first();
  await row.getByRole('button', { name: 'Approve & schedule' }).click();
  assert.match(await flash(admin), /Approved and scheduled/);
  assert.deepEqual((await fakes()).meta_posts, [], 'scheduling publishes nothing early');
  await admin.goto(`${WEB}/content/?client=1&board=scheduled&r=${Date.now()}#board`);
  await admin.locator('#board li.content-row', { hasText: 'Monsoon check-up offer' }).first().getByRole('button', { name: 'Publish now' }).click();
  assert.match(await flash(admin), /Published to Facebook, Instagram/);
  const paths = (await fakes()).meta_posts.map((x) => x.path);
  assert.deepEqual(paths, ['PAGE1/photos', 'IG1/media', 'IG1/media_publish']);
  ok('approved, scheduled, published to Facebook (photo) and Instagram');

  // 8. Calendar + dashboard reflect it
  await admin.goto(`${WEB}/social/?client=1&view=week`);
  assert.ok(await admin.locator('#calendar a.cal-post.g-published', { hasText: 'Monsoon check-up offer' }).count(), 'calendar shows the published post');
  await admin.goto(`${WEB}/`);
  await admin.screenshot({ path: `${OUT}/08-dashboard-after.png`, fullPage: true });
  const audit = await (await fetch(`${API}/api/audit?limit=200`, { headers: { Authorization: `Bearer ${adminToken}` } })).json();
  for (const action of ['approved reply', 'published reply to Google', 'approved & scheduled: Monsoon check-up offer', 'published: Monsoon check-up offer']) {
    assert.ok(audit.some((a) => a.action === action), `audit log has “${action}”`);
  }
  ok('calendar, dashboard and audit trail updated');
  console.log(`\nAll ${step} steps passed.`);
} catch (e) {
  console.error('\n✗ E2E failed:', e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
