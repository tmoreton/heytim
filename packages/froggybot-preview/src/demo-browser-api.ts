import type { BotBrowserState } from '@froggybot/contracts';
import type { BrowserApi } from '@froggybot/client';

/** Preview must never pretend that a real authenticated browser or saved login exists. */
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
