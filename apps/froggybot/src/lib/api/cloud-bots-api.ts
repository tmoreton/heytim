import { apiRoutes } from '../api-routes';
import type { Bootstrap, Bot, BotDocument } from '../types';

import type { BotsApi } from './bots-api';
import type { ApiRequest } from './cloud-transport';

export const createCloudBotsApi = (request: ApiRequest): BotsApi => ({
  bootstrap: () => request<Bootstrap>(apiRoutes.bootstrap).then((value) => ({
    ...value,
    connectionProviders: value.connectionProviders ?? [],
  })),
  installBotTemplate: (templateId) => request<Bot>(apiRoutes.botTemplateInstall(templateId), { method: 'POST' }),
  botDocuments: (botId) => request<{ documents: BotDocument[] }>(
    apiRoutes.botDocuments(botId),
  ).then((value) => value.documents),
  saveBot: (draft, botId) => request<Bot>(botId ? apiRoutes.bot(botId) : apiRoutes.bots, {
    method: botId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }),
  clearBotChat: async (botId, forgetMemory = false) => {
    await request(apiRoutes.botMessages(botId), {
      method: 'DELETE',
      body: JSON.stringify({ forgetMemory }),
    });
  },
  deleteBot: async (botId) => {
    await request(apiRoutes.bot(botId), { method: 'DELETE' });
  },
});
