import type { BotBrowserContext, BotBrowserOpenOptions, BotBrowserState } from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';

export interface BrowserApi {
  browserStatus(context: BotBrowserContext): Promise<BotBrowserState>;
  openBrowser(context: BotBrowserContext, options?: BotBrowserOpenOptions): Promise<BotBrowserState>;
  resumeBrowser(context: BotBrowserContext, rememberLogin: boolean): Promise<BotBrowserState>;
  closeBrowser(context: BotBrowserContext): Promise<BotBrowserState>;
  forgetBrowserLogin(context: BotBrowserContext): Promise<BotBrowserState>;
}

type Request = <T>(path: string, init?: RequestInit, timeoutMs?: number) => Promise<T>;
export const BROWSER_MUTATION_TIMEOUT_MS = 40_000;

const browserActionPath = (botId: string, action: string): string => {
  if (action === 'open') return apiRoutes.browserOpen(botId);
  if (action === 'resume') return apiRoutes.browserResume(botId);
  if (action === 'close') return apiRoutes.browserClose(botId);
  if (action === 'profile') return apiRoutes.browserProfile(botId);
  return apiRoutes.browserStatus(botId);
};

export const browserPath = ({ botId, groupId }: BotBrowserContext, action = '', query = false) => {
  const path = browserActionPath(botId, action);
  return `${path}${query && groupId ? `?groupId=${encodeURIComponent(groupId)}` : ''}`;
};

export function createBrowserApi(request: Request): BrowserApi {
  const post = (context: BotBrowserContext, action: string, rememberLogin?: boolean, options?: BotBrowserOpenOptions) =>
    request<BotBrowserState>(browserPath(context, action), {
      method: 'POST',
      cache: 'no-store',
      body: JSON.stringify({ ...options, ...(context.groupId ? { groupId: context.groupId } : {}), ...(rememberLogin === undefined ? {} : { rememberLogin }) }),
    }, BROWSER_MUTATION_TIMEOUT_MS);
  return {
    browserStatus: (context) => request(browserPath(context, '', true), { cache: 'no-store' }),
    openBrowser: (context, options) => post(context, 'open', undefined, options),
    resumeBrowser: (context, rememberLogin) => post(context, 'resume', rememberLogin),
    closeBrowser: (context) => post(context, 'close'),
    forgetBrowserLogin: (context) => request(browserPath(context, 'profile', true), { method: 'DELETE', cache: 'no-store' }, BROWSER_MUTATION_TIMEOUT_MS),
  };
}
