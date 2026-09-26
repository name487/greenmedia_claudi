import { useSyncExternalStore } from 'react';
import { buildSeed } from './seed';
import type { AuditLog, DB, User } from './types';

const KEY = 'gm.db.v1';
const SESSION_KEY = 'gm.session';

function load(): DB {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const db = JSON.parse(raw) as DB;
      if (db.version === 1) return db;
    }
  } catch {
    /* storage unavailable or corrupt: fall back to seed */
  }
  return buildSeed();
}

let db: DB = load();
let session: string | null = (() => {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
})();
const listeners = new Set<() => void>();

function emit() {
  try {
    localStorage.setItem(KEY, JSON.stringify(db));
    if (session) localStorage.setItem(SESSION_KEY, session);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* persistence is best-effort */
  }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useDB(): DB {
  return useSyncExternalStore(subscribe, () => db);
}

export function useCurrentUser(): User | null {
  const d = useDB();
  const id = useSyncExternalStore(subscribe, () => session);
  return d.users.find((u) => u.id === id) ?? null;
}

export function getDB() {
  return db;
}

/** Immutable update: the recipe returns a new DB (or partial) derived from the current one. */
export function update(recipe: (d: DB) => Partial<DB>, audit?: Omit<AuditLog, 'id' | 'at' | 'userId'>) {
  db = { ...db, ...recipe(db) };
  if (audit && session) {
    const entry: AuditLog = { ...audit, id: uid('al'), at: new Date().toISOString(), userId: session };
    db = { ...db, audit: [entry, ...db.audit].slice(0, 500) };
  }
  emit();
}

export function login(email: string): User | null {
  const u = db.users.find((x) => x.email.toLowerCase() === email.trim().toLowerCase()) ?? null;
  session = u?.id ?? null;
  emit();
  return u;
}

export function logout() {
  session = null;
  emit();
}

export function resetDemo() {
  db = buildSeed();
  emit();
}

export function uid(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}
