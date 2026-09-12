import type { Bot, BotBrowserState } from '@froggybot/contracts';
import { apiErrorCode } from './http.ts';

export function hasBrowserCapability(bot: Bot): boolean {
  return [...bot.toolIds, ...(bot.extraToolIds ?? [])].includes('browser');
}

export function shouldUseBotBrowserForChatLinks(bot: Bot | undefined, groupMode: boolean): boolean {
  return Boolean(bot && !groupMode && hasBrowserCapability(bot));
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
  const byCode: Record<string, string> = {
    browser_bot_busy: 'The bot is working. Wait for it to finish, or stop it in chat.',
    browser_handoff_incomplete: 'The previous browser handoff did not finish. Disconnect it, then open again.',
    browser_operation_in_progress: 'The browser is still connecting or disconnecting. Check status in a moment.',
    browser_session_expired: 'This browser session ended. Open it again to continue.',
    browser_capability_required: 'Enable the browser tool for this bot first.',
    browser_start_unconfirmed: 'The browser could not connect. Disconnect it, then try again.',
    browser_state_changed: 'The browser state changed. Check status and try again.',
  };
  const coded = apiErrorCode(value);
  if (coded && byCode[coded]) return byCode[coded];
  if (status === 409) return 'The browser state changed. Check status and try again.';
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
