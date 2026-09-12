import type { Bot, BotDraft, Message, ScheduledTask } from '@froggybot/contracts';
import { chiefFirst, displayBotColor } from '@froggybot/client';
import { withDemoBotActions } from '../demo-contract';

import { demoState, removeBotFromDemoState } from './demo-state';

export const demoMessages = (botId: string): Message[] => [
  ...(demoState.messages.get(botId) ?? []),
];

export const demoClearBotChat = (botId: string): void => {
  demoState.messages.set(botId, []);
  const now = new Date().toISOString();
  demoState.bots = demoState.bots.map((bot) =>
    bot.id === botId
      ? { ...bot, lastMessage: 'Ready when you are.', lastMessageAt: now, updatedAt: now }
      : bot,
  );
};

export const demoDeleteBot = (botId: string): void => {
  if (demoState.bots.find((bot) => bot.id === botId)?.systemRole === 'chief') {
    throw new Error('Chief coordinates your other bots and cannot be deleted.');
  }
  removeBotFromDemoState(botId);
};

export const demoSaveBot = (draft: BotDraft, botId?: string): Bot => {
  const now = new Date().toISOString();
  const previous = demoState.bots.find((bot) => bot.id === botId);
  const bot: Bot = withDemoBotActions({
    ...draft,
    color: displayBotColor({ ...draft, systemRole: previous?.systemRole }),
    systemRole: previous?.systemRole,
    id: previous?.id ?? `bot-${Date.now()}`,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
    lastMessage: previous?.lastMessage ?? 'Ready when you are.',
    lastMessageAt: previous?.lastMessageAt ?? now,
  });
  demoState.bots = chiefFirst(
    previous
      ? demoState.bots.map((item) => (item.id === bot.id ? bot : item))
      : [bot, ...demoState.bots],
  );
  if (!demoState.messages.has(bot.id)) demoState.messages.set(bot.id, []);
  return bot;
};

export const demoSend = (bot: Bot, text: string, task?: ScheduledTask): void => {
  const steeredAt = new Date().toISOString();
  const current = (demoState.messages.get(bot.id) ?? []).map((message) =>
    message.role === 'assistant'
      && ['waiting', 'pending', 'running', 'needs_input', 'awaiting_approval'].includes(message.status)
      ? { ...message, text: 'Steered by you.', status: 'cancelled' as const, completedAt: steeredAt }
      : message,
  );
  const requestId = String(Date.now());
  const startedAt = new Date().toISOString();
  current.push(
    {
      id: `${requestId}-user`,
      role: 'user',
      text,
      source: task ? 'schedule' : undefined,
      scheduleName: task?.name,
      createdAt: startedAt,
      status: 'complete',
    },
    {
      id: `${requestId}-assistant`,
      role: 'assistant',
      text: '',
      createdAt: startedAt,
      startedAt,
      status: 'pending',
    },
  );
  demoState.messages.set(bot.id, current);
  setTimeout(() => {
    const stillActive = (demoState.messages.get(bot.id) ?? []).some(
      (message) => message.id === `${requestId}-assistant`
        && ['pending', 'running'].includes(message.status),
    );
    if (!stillActive) return;
    const response = `Understood. I would handle that as ${bot.name}: start with the smallest useful result, verify it, then bring back the decision that needs you.`;
    demoState.messages.set(
      bot.id,
      (demoState.messages.get(bot.id) ?? []).map((message) =>
        message.id === `${requestId}-assistant`
          ? { ...message, text: response, status: 'complete', completedAt: new Date().toISOString() }
          : message,
      ),
    );
    demoState.bots = demoState.bots.map((item) =>
      item.id === bot.id
        ? {
            ...item,
            lastMessage: response,
            lastMessageAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          }
        : item,
    );
    if (task) {
      demoState.schedules = demoState.schedules.map((item) =>
        item.id === task.id
          ? {
              ...item,
              lastRunAt: new Date().toISOString(),
              lastStatus: 'complete',
              updatedAt: new Date().toISOString(),
            }
          : item,
      );
    }
  }, 900);
};
