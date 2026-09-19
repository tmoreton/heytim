import type { Bootstrap, Bot, BotDocument, BotDraft } from '../types';

export interface BotsApi {
  bootstrap(): Promise<Bootstrap>;
  installBotTemplate(templateId: string): Promise<Bot>;
  botDocuments(botId: string): Promise<BotDocument[]>;
  saveBot(draft: BotDraft, botId?: string): Promise<Bot>;
  clearBotChat(botId: string, forgetMemory?: boolean): Promise<void>;
  deleteBot(botId: string): Promise<void>;
}
