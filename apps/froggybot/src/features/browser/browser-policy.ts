import type { Bot, BotBrowserState } from '../../lib/types';

export function hasBrowserCapability(bot: Bot): boolean {
  return [...bot.toolIds, ...(bot.extraToolIds ?? [])].includes('browser');
}

export function isLiveViewUrl(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && !url.hash
      && /^bedrock-agentcore(?:-fips)?\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?$/.test(url.hostname)
      && url.pathname.includes('/live-view') && url.searchParams.has('X-Amz-Signature');
  } catch { return false; }
}

export function liveViewDeadline(state?: BotBrowserState): number {
  const times = [state?.liveViewExpiresAt, state?.sessionExpiresAt]
    .filter((value): value is string => Boolean(value)).map((value) => Date.parse(value));
  return times.length && times.every(Number.isFinite) ? Math.min(...times) : 0;
}

export function browserError(value: unknown, action: 'open' | 'resume' | 'close' | 'forget' | 'status'): string {
  const status = value && typeof value === 'object' && 'status' in value ? value.status : undefined;
  if (status === 409) return 'This bot or its browser is busy. Wait for the active response to finish, or stop it in chat, then try again.';
  if (status === 401) return 'Your FroggyBot session expired. Sign in again to reconnect.';
  if (status === 403) return 'Only this bot’s owner can open its private browser. Group browser handoff is not available.';
  if (status === 501) return 'A private bot browser is not available in demo mode. Sign in to use it.';
  if (action === 'resume') return 'Could not confirm the handoff. Check the status below before retrying; the bot may already have resumed.';
  return `Could not ${action === 'forget' ? 'forget the saved login' : action === 'status' ? 'check browser status' : `${action} the browser`}. Please try again.`;
}

export function withoutLiveView(state: BotBrowserState): BotBrowserState {
  const { liveViewUrl: _url, liveViewExpiresAt: _expiry, ...rest } = state;
  return rest;
}
