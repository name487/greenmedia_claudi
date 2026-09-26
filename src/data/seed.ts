import type { Client, ContentItem, DB, Keyword, MetricDay, Platform, Review, Task, User } from './types';
import { detectSentiment } from '../lib/sentiment';

// Deterministic PRNG so the demo data is identical on every device.
function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

const TENANT = 'tnt_greenmedia';

export const DEMO_USERS: User[] = [
  { id: 'u_admin', tenantId: TENANT, name: 'Aarav Mehta', email: 'admin@greenmedia.in', role: 'admin' },
  { id: 'u_am', tenantId: TENANT, name: 'Priya Nair', email: 'priya@greenmedia.in', role: 'account_manager' },
  { id: 'u_seo', tenantId: TENANT, name: 'Rohit Verma', email: 'rohit@greenmedia.in', role: 'seo' },
  { id: 'u_content', tenantId: TENANT, name: 'Sneha Iyer', email: 'sneha@greenmedia.in', role: 'content' },
  { id: 'u_design', tenantId: TENANT, name: 'Kabir Shah', email: 'kabir@greenmedia.in', role: 'designer' },
  { id: 'u_client', tenantId: TENANT, name: 'Dr. Anjali Rao', email: 'anjali@smiledental.in', role: 'client', clientId: 'c_1' },
];

const BUSINESSES: [string, string, string][] = [
  ['Smile Dental Studio', 'Dental Clinic', 'Pune'],
  ['Spice Route Kitchen', 'Restaurant', 'Bengaluru'],
  ['FitNation Gym', 'Fitness', 'Mumbai'],
  ['UrbanNest Realty', 'Real Estate', 'Hyderabad'],
  ['GlowUp Salon & Spa', 'Beauty', 'Delhi'],
  ['BrightKids Academy', 'Education', 'Chennai'],
  ['AutoCare Pro', 'Automotive', 'Ahmedabad'],
  ['Sunrise Eye Hospital', 'Healthcare', 'Jaipur'],
  ['The Coffee Collective', 'Cafe', 'Kochi'],
  ['LegalEase Associates', 'Legal', 'Kolkata'],
  ['PetPals Veterinary', 'Veterinary', 'Indore'],
  ['CraftWood Interiors', 'Interior Design', 'Surat'],
  ['Heritage Stay Homestay', 'Hospitality', 'Udaipur'],
  ['QuickFix Electricals', 'Home Services', 'Nagpur'],
  ['Zen Yoga Shala', 'Wellness', 'Rishikesh'],
  ['MediPlus Pharmacy', 'Pharmacy', 'Lucknow'],
  ['StyleStreet Boutique', 'Retail', 'Chandigarh'],
  ['CloudNine IVF Centre', 'Healthcare', 'Pune'],
  ['GreenLeaf Organics', 'Grocery', 'Mysuru'],
  ['PixelPerfect Studio', 'Photography', 'Goa'],
  ['SafeHands Physiotherapy', 'Healthcare', 'Nashik'],
  ['BookWorm Library Cafe', 'Cafe', 'Bhopal'],
  ['SkyHigh Travels', 'Travel', 'Vadodara'],
  ['IronCore Constructions', 'Construction', 'Coimbatore'],
];

const FIRST = ['Rahul', 'Neha', 'Vikram', 'Ananya', 'Arjun', 'Meera', 'Karan', 'Isha', 'Dev', 'Pooja', 'Sanjay', 'Tara', 'Farhan', 'Lakshmi', 'John', 'Simran'];
const LAST = ['Sharma', 'Patel', 'Reddy', 'Gupta', 'Khan', 'Das', 'Joshi', 'Menon', 'Singh', 'Kapoor', 'Fernandes', 'Bose'];

const REVIEW_TEXT: [number, string, string][] = [
  [5, 'Absolutely wonderful experience. The staff were friendly and very professional. Highly recommend!', 'en'],
  [5, 'Best in the city! Quick service and great value for money.', 'en'],
  [4, 'Good service overall, a little wait time but worth it.', 'en'],
  [5, 'बहुत अच्छी सेवा, स्टाफ बहुत मददगार है।', 'hi'],
  [3, 'Service was okay. Nothing special, pricing could be clearer.', 'en'],
  [2, 'Waited over 40 minutes even with an appointment. Not happy with the delay.', 'en'],
  [1, 'Very rude behaviour at the front desk and nobody called me back. Terrible experience.', 'en'],
  [4, 'Clean place, polite team. Parking is a bit difficult.', 'en'],
  [5, 'They solved my problem in one visit. Thank you so much!', 'en'],
  [2, 'The quality has dropped compared to last year. Disappointed.', 'en'],
];

const KEYWORDS = ['near me', 'best {i} in {c}', '{i} {c}', 'affordable {i}', 'top rated {i}', '{i} open now'];

function daysAgo(n: number, from = new Date()) {
  const d = new Date(from);
  d.setDate(d.getDate() - n);
  return d;
}

export const isoDate = (d: Date) => d.toISOString().slice(0, 10);

export function buildSeed(): DB {
  const r = rng(42);
  const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)];
  const int = (lo: number, hi: number) => Math.floor(lo + r() * (hi - lo + 1));
  const managers = ['u_am', 'u_admin'];

  const clients: Client[] = BUSINESSES.map(([name, industry, city], i) => {
    const id = `c_${i + 1}`;
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '');
    const socials: Platform[] = ['facebook', 'instagram', 'linkedin', 'youtube'];
    const plan = (['Starter', 'Growth', 'Pro', 'Agency'] as const)[i % 4];
    return {
      id,
      tenantId: TENANT,
      companyName: name,
      website: `https://www.${slug}.in`,
      industry,
      city,
      status: i === 5 ? 'onboarding' : i === 13 ? 'paused' : 'active',
      plan,
      services: ['GMB Management', 'Review Management', ...(plan !== 'Starter' ? ['Social Media'] : []), ...(plan === 'Pro' || plan === 'Agency' ? ['SEO', 'Monthly Reports'] : [])],
      accountManagerId: managers[i % managers.length],
      contact: { name: `${pick(FIRST)} ${pick(LAST)}`, email: `owner@${slug}.in`, phone: `+91 9${int(100000000, 999999999)}`, designation: 'Owner' },
      gmb: { locationId: `locations/${int(1e9, 9e9)}`, connected: i !== 5, lastSync: daysAgo(0).toISOString(), rating: +(3.6 + r() * 1.3).toFixed(1), reviewCount: int(40, 900) },
      social: socials.slice(0, plan === 'Starter' ? 1 : 3).map((p) => ({ platform: p, handle: `@${slug}`, connected: !(i === 7 && p === 'instagram') })),
      brandVoice: {
        tone: pick(['Warm and professional', 'Friendly and upbeat', 'Premium and concise', 'Caring and reassuring']),
        preferredPhrases: ['Thank you for choosing us', `your trusted ${industry.toLowerCase()} in ${city}`],
        prohibitedClaims: ['guaranteed results', 'best in the world', 'cheapest'],
        ctaStyle: pick(['Call us', 'Book online', 'Visit us today', 'WhatsApp us']),
        languages: ['en', 'hi'],
        escalationRule: 'Ratings of 2 or less go to the account manager before any reply is published.',
      },
      autoPublish: {},
      notes: '',
    };
  });

  const reviews: Review[] = [];
  const keywords: Keyword[] = [];
  const metrics: Record<string, MetricDay[]> = {};
  const tasks: Task[] = [];
  const content: ContentItem[] = [];

  clients.forEach((c, ci) => {
    const count = int(3, 7);
    for (let k = 0; k < count; k++) {
      const [rating, text, language] = pick(REVIEW_TEXT);
      const age = int(0, 20);
      const replied = age > 6 && r() > 0.3;
      reviews.push({
        id: `rv_${c.id}_${k}`,
        clientId: c.id,
        author: `${pick(FIRST)} ${pick(LAST)[0]}.`,
        rating,
        text,
        language,
        sentiment: detectSentiment(text, rating),
        createdAt: daysAgo(age).toISOString(),
        replyStatus: replied ? 'published' : 'new',
        reply: replied ? `Thank you for your feedback, we truly appreciate it! — ${c.companyName}` : undefined,
        publishedAt: replied ? daysAgo(age - 1).toISOString() : undefined,
      });
    }

    const industry = c.industry.toLowerCase();
    KEYWORDS.slice(0, int(3, 6)).forEach((tpl, k) => {
      const kw = tpl === 'near me' ? `${industry} near me` : tpl.replace('{i}', industry).replace('{c}', c.city.toLowerCase());
      const prev = int(3, 40);
      keywords.push({ id: `kw_${c.id}_${k}`, clientId: c.id, keyword: kw, targetUrl: c.website + (k ? `/${industry.replace(/\s+/g, '-')}` : ''), location: c.city, previousRank: prev, currentRank: Math.max(1, prev + int(-8, 5)), volume: int(90, 6000) });
    });

    const scale = 0.5 + r() * 2;
    metrics[c.id] = Array.from({ length: 90 }, (_, d) => {
      const trend = 1 + (90 - d) / 300; // gentle growth toward today
      const wk = [0.8, 1, 1.05, 1.1, 1.05, 1.2, 0.9][daysAgo(d).getDay()];
      const v = (base: number) => Math.round(base * scale * trend * wk * (0.8 + r() * 0.4));
      return { date: isoDate(daysAgo(89 - d)), gmbViews: v(180), gmbCalls: v(6), gmbDirections: v(9), webClicks: v(14), organicSessions: v(120), socialReach: v(900), engagement: v(60), leads: v(3) };
    });

    if (ci < 12) {
      const titles = ['Publish weekly GMB offer post', 'Fix missing meta descriptions', 'Design Diwali campaign creative', 'Respond to negative review escalation', 'Update service pages with FAQs', 'Prepare monthly report'];
      const owners = ['u_content', 'u_seo', 'u_design', 'u_am', 'u_seo', 'u_am'];
      const t = int(0, titles.length - 1);
      tasks.push({ id: `t_${c.id}`, clientId: c.id, assignedTo: owners[t], title: titles[t], priority: pick(['low', 'medium', 'high']), dueDate: isoDate(daysAgo(-int(-2, 10))), status: pick(['todo', 'in_progress', 'review', 'done']) });
    }

    if (ci < 8) {
      const when = daysAgo(-int(1, 12));
      when.setHours(10 + int(0, 8), 0, 0, 0);
      content.push({
        id: `ct_${c.id}`,
        clientId: c.id,
        topic: pick(['Festive season offer', 'Meet our team', 'Customer success story', 'New service launch', 'Weekend special']),
        contentType: pick(['post', 'offer', 'update']),
        masterCopy: `Something special is coming to ${c.companyName} in ${c.city}! ${c.brandVoice.ctaStyle} to know more.`,
        hashtags: [`#${c.city}`, `#${industry.replace(/\s+/g, '')}`, '#LocalBusiness'],
        variants: (['gmb', ...c.social.map((s) => s.platform)] as Platform[]).map((p) => ({ platform: p, copy: `Something special is coming to ${c.companyName}! ${c.brandVoice.ctaStyle}.`, format: p === 'instagram' ? '4:5' : p === 'youtube' ? '16:9' : '1:1' })),
        status: pick(['draft', 'in_review', 'scheduled', 'scheduled', 'published']),
        scheduledAt: when.toISOString(),
        createdBy: 'u_content',
        createdAt: daysAgo(int(1, 5)).toISOString(),
      });
    }
  });

  return {
    version: 1,
    users: DEMO_USERS,
    clients,
    reviews,
    content,
    keywords,
    metrics,
    tasks,
    reports: [],
    audit: [],
    settings: { apiUrl: import.meta.env.VITE_API_URL ?? '', notifyOnNegativeReview: true, requireClientApproval: false, theme: 'system' },
  };
}
