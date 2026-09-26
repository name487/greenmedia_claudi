import type { Role } from '../data/types';

export type Section = 'dashboard' | 'clients' | 'gmb' | 'reviews' | 'content' | 'creative' | 'social' | 'seo' | 'analytics' | 'reports' | 'tasks' | 'settings';
export type Action = 'review.publish' | 'review.approve' | 'content.create' | 'content.approve' | 'content.publish' | 'client.edit' | 'report.deliver' | 'settings.edit';

const ALL: Section[] = ['dashboard', 'clients', 'gmb', 'reviews', 'content', 'creative', 'social', 'seo', 'analytics', 'reports', 'tasks', 'settings'];

const SECTIONS: Record<Role, Section[]> = {
  admin: ALL,
  account_manager: ALL.filter((s) => s !== 'settings'),
  seo: ['dashboard', 'clients', 'gmb', 'seo', 'analytics', 'reports', 'tasks'],
  content: ['dashboard', 'clients', 'gmb', 'reviews', 'content', 'creative', 'social', 'tasks'],
  designer: ['dashboard', 'clients', 'content', 'creative', 'social', 'tasks'],
  client: ['dashboard', 'reviews', 'content', 'analytics', 'reports'],
};

const ACTIONS: Record<Role, Action[]> = {
  admin: ['review.publish', 'review.approve', 'content.create', 'content.approve', 'content.publish', 'client.edit', 'report.deliver', 'settings.edit'],
  account_manager: ['review.publish', 'review.approve', 'content.create', 'content.approve', 'content.publish', 'client.edit', 'report.deliver'],
  seo: ['content.create'],
  content: ['content.create'],
  designer: ['content.create'],
  client: ['review.approve', 'content.approve'],
};

export const canSee = (role: Role, s: Section) => SECTIONS[role].includes(s);
export const can = (role: Role, a: Action) => ACTIONS[role].includes(a);
