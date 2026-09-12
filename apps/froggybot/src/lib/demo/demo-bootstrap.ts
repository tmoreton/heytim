import type { Bootstrap, Bot, BotTemplate, Skill } from '../types';
import { CHIEF_TEMPLATE_ID, chiefFirst } from '../bot-branding';
import { loadDemoCatalog } from '../demo-catalog';
import { createDemoChief } from '../demo-chief';
import { demoDecisionsForGroup } from '../demo-decisions';
import { createInitialDemoBots, toolIdsForTemplate } from '../demo-fixtures';

import { demoState, demoTimestamp, processingMessage } from './demo-state';

const ensureDemoChief = (chief: Bot) => {
  if (demoState.bots.some((bot) => bot.systemRole === 'chief')) return;
  demoState.bots = chiefFirst([chief, ...demoState.bots]);
  demoState.groups = demoState.groups.map((group) => ({
    ...group,
    bots: [
      {
        id: chief.id,
        ownerId: 'demo-user',
        name: chief.name,
        tagline: chief.tagline,
        color: chief.color,
        systemRole: 'chief',
      },
      ...demoState.bots
        .filter((bot) => ['research-reports', 'trip-planner'].includes(bot.id))
        .map((bot) => ({
          id: bot.id,
          ownerId: 'demo-user',
          name: bot.name,
          tagline: bot.tagline,
          color: bot.color,
          systemRole: bot.systemRole,
        })),
    ],
  }));
  demoState.groupMessages.set(
    'launch-room',
    (demoState.groupMessages.get('launch-room') ?? []).map((message) =>
      message.authorId === CHIEF_TEMPLATE_ID
        ? { ...message, authorName: chief.name, authorColor: chief.color }
        : message,
    ),
  );
};

const initializeCatalogBots = (templates: BotTemplate[], skills: Skill[]): void => {
  if (demoState.initialCatalogLoaded) return;
  demoState.bots = createInitialDemoBots(templates, skills, demoTimestamp);
  demoState.initialCatalogLoaded = true;
};

const saveTemplate = (template: BotTemplate, toolIds: string[]): Bot => {
  const current = new Date().toISOString();
  const bot: Bot = {
    id: `bot-${template.id}-${Date.now()}`,
    name: template.name,
    tagline: template.tagline,
    prompt: template.prompt,
    color: template.color,
    skillIds: template.skillIds,
    toolIds,
    extraToolIds: template.toolIds,
    alwaysAllowedToolIds: [],
    templateId: template.id,
    templateVersion: template.version,
    createdAt: current,
    updatedAt: current,
    lastMessage: 'Tell me what you would like help with.',
    lastMessageAt: current,
  };
  demoState.bots = chiefFirst([bot, ...demoState.bots]);
  demoState.messages.set(bot.id, []);
  return bot;
};

export const demoBootstrap = async (): Promise<Bootstrap> => {
  const catalog = await loadDemoCatalog();
  const chiefTemplate = catalog.botTemplates.find((template) => template.id === CHIEF_TEMPLATE_ID);
  if (!chiefTemplate) throw new Error('The required Chief bot is unavailable.');
  initializeCatalogBots(catalog.botTemplates, catalog.skills);
  ensureDemoChief(createDemoChief(chiefTemplate, catalog.skills, demoTimestamp));
  return {
    bots: chiefFirst(demoState.bots.map((bot) => ({
      ...bot,
      processing: Boolean(processingMessage(demoState.messages.get(bot.id) ?? [])),
    }))),
    botTemplates: catalog.botTemplates,
    connectionProviders: [],
    needsBotOnboarding: false,
    groups: demoState.groups.map((group) => {
      const active = processingMessage(demoState.groupMessages.get(group.id) ?? []);
      return {
        ...group,
        processing: Boolean(active),
        processingBotName: active?.authorName,
        members: [...group.members],
        bots: [...group.bots],
        decisions: demoDecisionsForGroup(group.id),
      };
    }),
    tools: [...catalog.tools, ...demoState.personalConnections],
    retiredToolIds: [],
    skills: [
      ...catalog.skills,
      ...demoState.personalSkills.map(({ instructions: _instructions, ...skill }) => skill),
    ],
  };
};

export const demoInstallBotTemplate = async (templateId: string): Promise<Bot> => {
  const catalog = await loadDemoCatalog();
  initializeCatalogBots(catalog.botTemplates, catalog.skills);
  const template = catalog.botTemplates.find((item) => item.id === templateId);
  if (!template) throw new Error('Bot not found in the library.');
  if (demoState.bots.some((bot) => bot.templateId === template.id)) {
    throw new Error('This bot is already in your team.');
  }
  return saveTemplate(template, toolIdsForTemplate(template, catalog.skills));
};
