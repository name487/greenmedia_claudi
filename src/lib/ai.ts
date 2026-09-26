import { getDB } from '../data/store';
import type { BrandVoice, Client, ContentVariant, MetricDay, Platform, Review } from '../data/types';

// All AI calls go through the backend (server/index.mjs) so provider keys never ship inside the
// mobile or desktop binaries. With no API URL configured, a local template engine keeps the app usable offline.

export interface AIResult<T> {
  data: T;
  source: 'ai' | 'template';
}

async function callServer<T>(task: string, payload: unknown): Promise<T | null> {
  const base = getDB().settings.apiUrl.replace(/\/$/, '');
  if (!base) return null;
  try {
    const res = await fetch(`${base}/api/ai/${task}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

const voiceOf = (c: Client): BrandVoice => c.brandVoice;

export async function draftReviewReply(review: Review, client: Client): Promise<AIResult<string>> {
  const remote = await callServer<{ reply: string }>('review-reply', { review, client: { companyName: client.companyName, industry: client.industry, city: client.city }, brandVoice: voiceOf(client) });
  if (remote?.reply) return { data: remote.reply, source: 'ai' };
  return { data: templateReply(review, client), source: 'template' };
}

function templateReply(review: Review, c: Client): string {
  const name = review.author.split(' ')[0];
  const sign = `— Team ${c.companyName}`;
  if (review.language === 'hi') {
    return `${name} जी, आपके सुंदर शब्दों के लिए धन्यवाद! हमें ख़ुशी है कि आपका अनुभव अच्छा रहा। फिर मिलेंगे। ${sign}`;
  }
  if (review.sentiment === 'negative') {
    return `Hi ${name}, we're truly sorry to hear about your experience — this isn't the standard we hold ourselves to. We'd like to make it right; please reach out to us at ${c.contact.phone} so our team can look into this personally. ${sign}`;
  }
  if (review.sentiment === 'neutral') {
    return `Hi ${name}, thank you for taking the time to share your feedback. We're always working to improve, and your comments help us do that. We hope to give you an even better experience on your next visit. ${sign}`;
  }
  return `Hi ${name}, thank you so much for the kind words! ${c.brandVoice.preferredPhrases[0] ?? 'We appreciate you'} — we're glad to be ${c.brandVoice.preferredPhrases[1] ?? 'at your service'}. See you again soon! ${sign}`;
}

export interface GeneratedContent {
  masterCopy: string;
  hashtags: string[];
  variants: ContentVariant[];
  creativeBrief: string;
}

export const PLATFORM_FORMAT: Record<Platform, string> = { gmb: '4:3', facebook: '1:1', instagram: '4:5', linkedin: '1.91:1', youtube: '16:9', x: '16:9' };
const PLATFORM_LIMIT: Record<Platform, number> = { gmb: 1500, facebook: 2000, instagram: 2200, linkedin: 3000, youtube: 5000, x: 280 };

export async function generateContent(client: Client, topic: string, contentType: string, platforms: Platform[]): Promise<AIResult<GeneratedContent>> {
  const remote = await callServer<GeneratedContent>('content', { client: { companyName: client.companyName, industry: client.industry, city: client.city, website: client.website }, brandVoice: voiceOf(client), topic, contentType, platforms });
  if (remote?.masterCopy) return { data: remote, source: 'ai' };

  const cta = client.brandVoice.ctaStyle;
  const tags = [`#${client.city.replace(/\s+/g, '')}`, `#${client.industry.replace(/\s+/g, '')}`, `#${topic.split(' ').map((w) => w[0]?.toUpperCase() + w.slice(1)).join('')}`, '#ShopLocal'];
  const master = `${topic} at ${client.companyName}! As ${client.brandVoice.preferredPhrases[1] ?? `a trusted name in ${client.city}`}, we're bringing you something worth checking out. ${cta} today.`;
  const variant = (p: Platform): string => {
    switch (p) {
      case 'gmb': return `${master} Visit ${client.website}`;
      case 'instagram': return `✨ ${topic} ✨\n\n${master}\n\n${tags.join(' ')}`;
      case 'linkedin': return `We're excited to share: ${topic}.\n\nAt ${client.companyName}, we believe in serving ${client.city} with care and consistency. ${cta} to learn more.\n\n${tags.slice(0, 3).join(' ')}`;
      case 'x': return `${topic} at ${client.companyName} 🎉 ${cta}! ${tags.slice(0, 2).join(' ')}`.slice(0, PLATFORM_LIMIT.x);
      case 'youtube': return `${topic} | ${client.companyName}, ${client.city}\n\n${master}\n\nWebsite: ${client.website}`;
      default: return `${master} ${tags.slice(0, 3).join(' ')}`;
    }
  };
  return {
    source: 'template',
    data: {
      masterCopy: master,
      hashtags: tags,
      variants: platforms.map((p) => ({ platform: p, copy: variant(p).slice(0, PLATFORM_LIMIT[p]), format: PLATFORM_FORMAT[p] })),
      creativeBrief: `Visual for "${topic}" — ${client.brandVoice.tone.toLowerCase()} mood, ${client.industry.toLowerCase()} setting in ${client.city}. Logo bottom-right, headline max 6 words, CTA button "${cta}". Export sizes: ${platforms.map((p) => `${p} ${PLATFORM_FORMAT[p]}`).join(', ')}.`,
    },
  };
}

export interface ReportInput {
  client: Client;
  current: MetricDay[];
  previous: MetricDay[];
  rankUp: number;
  rankDown: number;
  reviewsReplied: number;
  postsPublished: number;
}

export function sumMetrics(days: MetricDay[]) {
  return days.reduce(
    (a, d) => ({ gmbViews: a.gmbViews + d.gmbViews, gmbCalls: a.gmbCalls + d.gmbCalls, gmbDirections: a.gmbDirections + d.gmbDirections, webClicks: a.webClicks + d.webClicks, organicSessions: a.organicSessions + d.organicSessions, socialReach: a.socialReach + d.socialReach, engagement: a.engagement + d.engagement, leads: a.leads + d.leads }),
    { gmbViews: 0, gmbCalls: 0, gmbDirections: 0, webClicks: 0, organicSessions: 0, socialReach: 0, engagement: 0, leads: 0 },
  );
}

export const pctChange = (cur: number, prev: number) => (prev ? Math.round(((cur - prev) / prev) * 100) : 0);

export async function generateReportSummary(input: ReportInput): Promise<AIResult<string>> {
  const cur = sumMetrics(input.current);
  const prev = sumMetrics(input.previous);
  const remote = await callServer<{ summary: string }>('report', { client: { companyName: input.client.companyName, industry: input.client.industry }, current: cur, previous: prev, rankUp: input.rankUp, rankDown: input.rankDown, reviewsReplied: input.reviewsReplied, postsPublished: input.postsPublished });
  if (remote?.summary) return { data: remote.summary, source: 'ai' };

  const dir = (n: number) => (n >= 0 ? `up ${n}%` : `down ${Math.abs(n)}%`);
  const views = pctChange(cur.gmbViews, prev.gmbViews);
  const leads = pctChange(cur.leads, prev.leads);
  const organic = pctChange(cur.organicSessions, prev.organicSessions);
  return {
    source: 'template',
    data: [
      `Performance summary: Google Business Profile views were ${dir(views)} (${cur.gmbViews.toLocaleString()}), organic sessions ${dir(organic)}, and total leads ${dir(leads)} at ${cur.leads}.`,
      `Search visibility: ${input.rankUp} keyword(s) improved and ${input.rankDown} declined.`,
      `Actions taken: ${input.reviewsReplied} review replies published and ${input.postsPublished} posts published across channels.`,
      `Next month: ${leads < 0 ? 'prioritise conversion — refresh GMB offers and add call-to-action posts; ' : 'scale what is working — increase posting cadence on top channels; '}${input.rankDown > input.rankUp ? 'recover slipping keywords with on-page updates; ' : 'build content for keywords close to page one; '}keep review response time under 24 hours.`,
    ].join('\n\n'),
  };
}
