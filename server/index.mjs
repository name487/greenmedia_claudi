// Green Media AI Command Center — API server.
// Keeps AI provider keys off the iOS/Android/desktop binaries. Zero dependencies (Node 20+).
//
//   AI_PROVIDER=anthropic ANTHROPIC_API_KEY=... node server/index.mjs
//   AI_PROVIDER=openai    OPENAI_API_KEY=...    node server/index.mjs

import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';

// Minimal .env loader so `npm run server` works without extra packages.
if (existsSync('.env')) {
  for (const line of readFileSync('.env', 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  }
}

const PORT = Number(process.env.PORT || 8787);
const PROVIDER = (process.env.AI_PROVIDER || 'anthropic').toLowerCase();
const KEY = PROVIDER === 'openai' ? process.env.OPENAI_API_KEY : process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.AI_MODEL || (PROVIDER === 'openai' ? 'gpt-4.1-mini' : 'claude-sonnet-5');
const ORIGINS = (process.env.CORS_ORIGINS || 'http://localhost:5173,capacitor://localhost,https://localhost').split(',').map((s) => s.trim());

async function complete(system, user, maxTokens = 800) {
  if (!KEY) throw Object.assign(new Error('AI provider key not configured'), { status: 503 });
  if (PROVIDER === 'openai') {
    const r = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${KEY}` },
      body: JSON.stringify({ model: MODEL, max_tokens: maxTokens, messages: [{ role: 'system', content: system }, { role: 'user', content: user }] }),
    });
    if (!r.ok) throw Object.assign(new Error(`OpenAI ${r.status}: ${await r.text()}`), { status: 502 });
    return (await r.json()).choices[0].message.content.trim();
  }
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-api-key': KEY, 'anthropic-version': '2023-06-01' },
    body: JSON.stringify({ model: MODEL, max_tokens: maxTokens, system, messages: [{ role: 'user', content: user }] }),
  });
  if (!r.ok) throw Object.assign(new Error(`Anthropic ${r.status}: ${await r.text()}`), { status: 502 });
  const j = await r.json();
  return j.content.filter((b) => b.type === 'text').map((b) => b.text).join('').trim();
}

function voice(bv = {}) {
  return [
    `Tone: ${bv.tone || 'warm and professional'}.`,
    bv.preferredPhrases?.length ? `Preferred phrases (use naturally, not all at once): ${bv.preferredPhrases.join('; ')}.` : '',
    bv.prohibitedClaims?.length ? `Never claim or imply: ${bv.prohibitedClaims.join('; ')}.` : '',
    bv.ctaStyle ? `Call-to-action style: ${bv.ctaStyle}.` : '',
  ].filter(Boolean).join('\n');
}

function parseJSON(text) {
  const m = text.match(/\{[\s\S]*\}/);
  return JSON.parse(m ? m[0] : text);
}

const PLATFORM_GUIDE = {
  gmb: 'Google Business Profile post: up to 1500 chars, plain text, no hashtags, local and specific, ends with the CTA.',
  facebook: 'Facebook: conversational, 1-3 short paragraphs, up to 3 hashtags.',
  instagram: 'Instagram: hook in the first line, line breaks, emojis sparingly, 5-10 hashtags at the end.',
  linkedin: 'LinkedIn: professional, value-first, 2-4 short paragraphs, up to 3 hashtags.',
  youtube: 'YouTube description: title line, 2-3 sentence description, website link.',
  x: 'X: under 280 characters including hashtags.',
};
const FORMAT = { gmb: '4:3', facebook: '1:1', instagram: '4:5', linkedin: '1.91:1', youtube: '16:9', x: '16:9' };

const routes = {
  'GET /api/health': async () => ({ ok: true, ai: Boolean(KEY), provider: PROVIDER, model: MODEL }),

  'POST /api/ai/review-reply': async ({ review, client, brandVoice }) => {
    const system = `You write public replies to Google reviews on behalf of ${client.companyName}, a ${client.industry} business in ${client.city}.
${voice(brandVoice)}
Rules: reply in the same language as the review (language code: ${review.language}). 2-4 sentences. Address the reviewer by first name. Never reveal private details, admit legal liability, or offer compensation publicly. For negative reviews: apologise sincerely, acknowledge the specific issue, and invite them to continue offline. Output only the reply text.`;
    const reply = await complete(system, `Rating: ${review.rating}/5\nReviewer: ${review.author}\nReview: """${review.text}"""`, 400);
    return { reply };
  },

  'POST /api/ai/content': async ({ client, brandVoice, topic, contentType, platforms }) => {
    const system = `You are the social media copywriter for ${client.companyName} (${client.industry}, ${client.city}, ${client.website}).
${voice(brandVoice)}
Respond with JSON only, matching: {"masterCopy": string, "hashtags": string[], "variants": [{"platform": string, "copy": string}], "creativeBrief": string}.`;
    const user = `Create a ${contentType} about: ${topic}
Write one master copy, then one variant per platform following these rules:
${platforms.map((p) => `- ${p}: ${PLATFORM_GUIDE[p] || ''}`).join('\n')}
The creativeBrief describes one master visual (mood, subject, headline under 6 words, CTA) for a designer.`;
    const out = parseJSON(await complete(system, user, 2000));
    out.variants = (out.variants || []).filter((v) => platforms.includes(v.platform)).map((v) => ({ ...v, format: FORMAT[v.platform] }));
    return out;
  },

  'POST /api/ai/report': async ({ client, current, previous, rankUp, rankDown, reviewsReplied, postsPublished }) => {
    const system = `You are a marketing analyst at Green Media Technology writing the monthly report for ${client.companyName} (${client.industry}). Plain language for a business owner. Four short paragraphs: performance summary with the key numbers and % changes, search visibility, actions taken, and a concrete 3-point plan for next month. No markdown headings. Only use numbers given to you.`;
    const summary = await complete(system, JSON.stringify({ current, previous, keywordsImproved: rankUp, keywordsDeclined: rankDown, reviewsReplied, postsPublished }), 900);
    return { summary };
  },
};

function cors(req, res) {
  const origin = req.headers.origin;
  if (origin && (ORIGINS.includes(origin) || ORIGINS.includes('*') || origin === 'null' || origin.startsWith('file://'))) {
    res.setHeader('access-control-allow-origin', origin);
    res.setHeader('vary', 'origin');
  }
  res.setHeader('access-control-allow-methods', 'GET,POST,OPTIONS');
  res.setHeader('access-control-allow-headers', 'content-type,authorization');
}

createServer(async (req, res) => {
  cors(req, res);
  if (req.method === 'OPTIONS') return res.writeHead(204).end();
  const handler = routes[`${req.method} ${req.url.split('?')[0]}`];
  const send = (status, body) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
  if (!handler) return send(404, { error: 'not found' });
  try {
    let body = {};
    if (req.method === 'POST') {
      let raw = '';
      for await (const chunk of req) {
        raw += chunk;
        if (raw.length > 1e6) return send(413, { error: 'payload too large' });
      }
      body = raw ? JSON.parse(raw) : {};
    }
    send(200, await handler(body));
  } catch (err) {
    console.error(err.message);
    send(err.status || 500, { error: err.status === 503 ? err.message : 'request failed' });
  }
}).listen(PORT, () => console.log(`API on http://localhost:${PORT} · AI ${KEY ? `${PROVIDER}/${MODEL}` : 'disabled (no key)'}`));
