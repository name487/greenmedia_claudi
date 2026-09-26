// Mirrors db/schema.sql. Every client-owned record carries clientId; every record belongs to a tenant
// so the internal tool can become a multi-tenant SaaS without a rebuild.

export type Role = 'admin' | 'account_manager' | 'seo' | 'content' | 'designer' | 'client';

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  account_manager: 'Account Manager',
  seo: 'SEO Specialist',
  content: 'Content Writer',
  designer: 'Designer',
  client: 'Client',
};

export type Platform = 'gmb' | 'facebook' | 'instagram' | 'linkedin' | 'youtube' | 'x';

export const PLATFORM_LABELS: Record<Platform, string> = {
  gmb: 'Google Business',
  facebook: 'Facebook',
  instagram: 'Instagram',
  linkedin: 'LinkedIn',
  youtube: 'YouTube',
  x: 'X',
};

export interface User {
  id: string;
  tenantId: string;
  name: string;
  email: string;
  role: Role;
  clientId?: string; // set for client-portal users
}

export interface BrandVoice {
  tone: string;
  preferredPhrases: string[];
  prohibitedClaims: string[];
  ctaStyle: string;
  languages: string[];
  escalationRule: string;
}

export interface Client {
  id: string;
  tenantId: string;
  companyName: string;
  website: string;
  industry: string;
  city: string;
  status: 'active' | 'onboarding' | 'paused';
  plan: 'Starter' | 'Growth' | 'Pro' | 'Agency';
  services: string[];
  accountManagerId: string;
  contact: { name: string; email: string; phone: string; designation: string };
  gmb: { locationId: string; connected: boolean; lastSync: string; rating: number; reviewCount: number };
  social: { platform: Platform; handle: string; connected: boolean }[];
  brandVoice: BrandVoice;
  // Safety: auto-publish is off unless explicitly enabled per channel.
  autoPublish: Partial<Record<Platform | 'reviews', boolean>>;
  notes: string;
}

export type Sentiment = 'positive' | 'neutral' | 'negative';
export type ReplyStatus = 'new' | 'drafted' | 'approved' | 'published' | 'rejected' | 'failed';

export interface Review {
  id: string;
  clientId: string;
  author: string;
  rating: number;
  text: string;
  language: string;
  sentiment: Sentiment;
  createdAt: string;
  reply?: string;
  replyStatus: ReplyStatus;
  publishedAt?: string;
}

export type ContentStatus = 'draft' | 'in_review' | 'approved' | 'scheduled' | 'published' | 'failed';

export interface ContentVariant {
  platform: Platform;
  copy: string;
  format: string; // e.g. 1:1, 4:5, 16:9, 9:16
}

export interface ContentItem {
  id: string;
  clientId: string;
  topic: string;
  contentType: 'post' | 'offer' | 'event' | 'update';
  masterCopy: string;
  hashtags: string[];
  variants: ContentVariant[];
  status: ContentStatus;
  scheduledAt?: string;
  createdBy: string;
  createdAt: string;
}

export interface Keyword {
  id: string;
  clientId: string;
  keyword: string;
  targetUrl: string;
  location: string;
  currentRank: number;
  previousRank: number;
  volume: number;
}

export interface MetricDay {
  date: string; // YYYY-MM-DD
  gmbViews: number;
  gmbCalls: number;
  gmbDirections: number;
  webClicks: number;
  organicSessions: number;
  socialReach: number;
  engagement: number;
  leads: number;
}

export interface Task {
  id: string;
  clientId: string;
  assignedTo: string;
  title: string;
  priority: 'low' | 'medium' | 'high';
  dueDate: string;
  status: 'todo' | 'in_progress' | 'review' | 'done';
}

export interface Report {
  id: string;
  clientId: string;
  periodStart: string;
  periodEnd: string;
  summary: string;
  createdAt: string;
  deliveredAt?: string;
  deliveredVia?: 'email' | 'whatsapp';
}

export interface AuditLog {
  id: string;
  userId: string;
  clientId?: string;
  action: string;
  entity: string;
  at: string;
}

export interface Settings {
  apiUrl: string;
  notifyOnNegativeReview: boolean;
  requireClientApproval: boolean;
  theme: 'system' | 'light' | 'dark';
}

export interface DB {
  version: number;
  users: User[];
  clients: Client[];
  reviews: Review[];
  content: ContentItem[];
  keywords: Keyword[];
  metrics: Record<string, MetricDay[]>; // by clientId
  tasks: Task[];
  reports: Report[];
  audit: AuditLog[];
  settings: Settings;
}
