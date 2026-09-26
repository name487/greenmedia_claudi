import { useState } from 'react';
import { useCurrentUser, useDB } from './store';
import type { Client } from './types';

/** Clients the signed-in user may see. Client-portal users are isolated to their own company. */
export function useVisibleClients(): Client[] {
  const db = useDB();
  const user = useCurrentUser();
  if (user?.clientId) return db.clients.filter((c) => c.id === user.clientId);
  return db.clients;
}

/** Client filter state that is pinned for client-portal users. */
export function useClientFilter(initial = 'all'): [string, (id: string) => void, boolean] {
  const user = useCurrentUser();
  const [value, set] = useState(initial);
  if (user?.clientId) return [user.clientId, () => {}, true];
  return [value, set, false];
}

export const matchClient = (filter: string) => (x: { clientId: string }) => filter === 'all' || x.clientId === filter;
