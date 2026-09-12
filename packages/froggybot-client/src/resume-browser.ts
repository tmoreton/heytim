import type { BrowserApi } from './browser-api.ts';
import type { BotBrowserState } from '@froggybot/contracts';

/** Only an acknowledged profile-save response permits another resume request. */
export async function resumeBrowserWithProfilePolling({ api, botId, rememberLogin, onState, isActive = () => true,
  wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)), now = Date.now,
}: {
  api: BrowserApi; botId: string; rememberLogin: boolean; onState: (state: BotBrowserState) => void;
  isActive?: () => boolean; wait?: (ms: number) => Promise<void>; now?: () => number;
}): Promise<BotBrowserState | undefined> {
  const deadline = now() + 30_000;
  let latest: BotBrowserState | undefined;
  for (let attempt = 0; attempt < 8 && isActive(); attempt += 1) {
    // Rejections intentionally escape: an uncertain network result is never retried.
    latest = await api.resumeBrowser({ botId }, rememberLogin);
    onState(latest);
    if (latest.status !== 'resuming' || latest.resumedTurnId || now() >= deadline) return latest;
    if (attempt < 7) await wait(2000);
  }
  return latest;
}
