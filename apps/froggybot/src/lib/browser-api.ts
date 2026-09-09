import type { FrogBotApi } from './api';
import type { BotBrowserContext, BotBrowserState } from './types';

export type BrowserApi = Pick<FrogBotApi,
  'browserStatus' | 'openBrowser' | 'resumeBrowser' | 'closeBrowser' | 'forgetBrowserLogin'>;

type Request = <T>(path: string, init?: RequestInit, timeoutMs?: number) => Promise<T>;
export const BROWSER_MUTATION_TIMEOUT_MS = 40_000;

export const browserPath = ({ botId, groupId }: BotBrowserContext, action = '', query = false) =>
  `/bots/${encodeURIComponent(botId)}/browser${action ? `/${action}` : ''}${query && groupId ? `?groupId=${encodeURIComponent(groupId)}` : ''}`;

export function createBrowserApi(request: Request): BrowserApi {
  const post = (context: BotBrowserContext, action: string, rememberLogin?: boolean) =>
    request<BotBrowserState>(browserPath(context, action), {
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ ...(context.groupId ? { groupId: context.groupId } : {}), ...(rememberLogin === undefined ? {} : { rememberLogin }) }),
    }, BROWSER_MUTATION_TIMEOUT_MS);
  return {
    browserStatus: (context) => request(browserPath(context, '', true), { cache: 'no-store' }),
    openBrowser: (context) => post(context, 'open'),
    resumeBrowser: (context, rememberLogin) => post(context, 'resume', rememberLogin),
    closeBrowser: (context) => post(context, 'close'),
    forgetBrowserLogin: (context) => request(browserPath(context, 'profile', true), { method: 'DELETE', cache: 'no-store' }, BROWSER_MUTATION_TIMEOUT_MS),
  };
}

/** Demo must never pretend that a real authenticated browser or saved login exists. */
export function createDemoBrowserApi(): BrowserApi {
  const unavailable = async (): Promise<BotBrowserState> => {
    throw Object.assign(new Error('Sign in to use a private bot browser. Demo mode cannot connect or save logins.'), { status: 501 });
  };
  return {
    browserStatus: async (context) => ({ ...context, status: 'closed', hasSavedLogin: false, contextLabel: 'Demo — no private browser' }),
    openBrowser: unavailable,
    resumeBrowser: unavailable,
    closeBrowser: unavailable,
    forgetBrowserLogin: unavailable,
  };
}
