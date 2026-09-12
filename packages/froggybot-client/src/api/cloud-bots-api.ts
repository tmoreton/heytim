import type { Bootstrap, Bot, BotDocument, BotsApi } from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';

import type { ApiRequest } from './cloud-transport';
import { decodeBootstrap, decodeBot } from '../response-contract.ts';

export const createCloudBotsApi = (request: ApiRequest): BotsApi => ({
  bootstrap: () => request<Bootstrap>(apiRoutes.bootstrap, undefined, undefined, decodeBootstrap),
  installBotTemplate: (templateId) => request<Bot>(apiRoutes.botTemplateInstall(templateId), { method: 'POST' }, undefined, decodeBot),
  botDocuments: (botId) => request<{ documents: BotDocument[] }>(
    apiRoutes.botDocuments(botId),
  ).then((value) => value.documents),
  saveBot: (draft, botId) => request<Bot>(botId ? apiRoutes.bot(botId) : apiRoutes.bots, {
    method: botId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }, undefined, decodeBot),
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
