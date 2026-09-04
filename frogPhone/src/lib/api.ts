import { fetchAuthSession } from 'aws-amplify/auth';

import { apiUrl } from './cloud';
import { demoBootstrap, demoMessages, demoSaveBot, demoSend } from './demo';
import type { Bootstrap, Bot, BotDraft, Message } from './types';

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) throw new Error('Your session expired. Please sign in again.');

  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      ...init?.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.message ?? 'The request failed.');
  return body as T;
};

export const createApi = (demo: boolean) => ({
  bootstrap: async (): Promise<Bootstrap> => (demo ? demoBootstrap() : request<Bootstrap>('/bootstrap')),
  messages: async (botId: string): Promise<Message[]> =>
    demo
      ? demoMessages(botId)
      : request<{ messages: Message[] }>(`/bots/${botId}/messages`).then((value) => value.messages),
  saveBot: async (draft: BotDraft, botId?: string): Promise<Bot> =>
    demo
      ? demoSaveBot(draft, botId)
      : request<Bot>(botId ? `/bots/${botId}` : '/bots', {
          method: botId ? 'PUT' : 'POST',
          body: JSON.stringify(draft),
        }),
  sendMessage: async (bot: Bot, text: string): Promise<void> => {
    if (demo) return demoSend(bot, text);
    await request(`/bots/${bot.id}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
  },
  share: async (botId: string, scope: 'bot' | 'chat'): Promise<string> => {
    if (demo) return `frogbot://share/demo-${scope}-${botId}`;
    return request<{ url: string }>('/shares', {
      method: 'POST',
      body: JSON.stringify({ botId, scope }),
    }).then((value) => value.url);
  },
  importShare: async (token: string): Promise<Bot> => {
    if (demo) return demoBootstrap().bots[0];
    return request<Bot>(`/shares/${encodeURIComponent(token)}/import`, { method: 'POST' });
  },
});
