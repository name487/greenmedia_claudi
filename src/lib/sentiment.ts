import type { Sentiment } from '../data/types';

const NEG = ['rude', 'terrible', 'worst', 'bad', 'disappoint', 'delay', 'waited', 'not happy', 'poor', 'dirty', 'never', 'refund', 'dropped'];
const POS = ['great', 'wonderful', 'best', 'excellent', 'amazing', 'friendly', 'recommend', 'thank', 'love', 'clean', 'polite', 'अच्छी'];

// Rating-first heuristic with keyword nudges; the server-side AI refines this when available.
export function detectSentiment(text: string, rating: number): Sentiment {
  const t = text.toLowerCase();
  const score = (rating - 3) * 2 + POS.filter((w) => t.includes(w)).length - NEG.filter((w) => t.includes(w)).length;
  if (score >= 2) return 'positive';
  if (score <= -2) return 'negative';
  return 'neutral';
}

export function detectLanguage(text: string): string {
  if (/[ऀ-ॿ]/.test(text)) return 'hi';
  if (/[஀-௿]/.test(text)) return 'ta';
  if (/[ఀ-౿]/.test(text)) return 'te';
  return 'en';
}
