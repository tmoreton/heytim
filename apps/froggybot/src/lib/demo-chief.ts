import type { Bot, BotTemplate, Skill } from './types';
import { CHIEF_COLOR, CHIEF_TEMPLATE_ID } from './bot-branding';
import { toolIdsForTemplate } from './demo-fixtures';

export const createDemoChief = (
  template: BotTemplate,
  skills: Skill[],
  timestamp: string,
): Bot => {
  return {
    id: CHIEF_TEMPLATE_ID,
    name: template.name,
    tagline: template.tagline,
    color: CHIEF_COLOR,
    prompt: template.prompt,
    toolIds: toolIdsForTemplate(template, skills),
    extraToolIds: template.toolIds,
    alwaysAllowedToolIds: [],
    skillIds: template.skillIds,
    templateId: template.id,
    templateVersion: template.version,
    systemRole: 'chief',
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'I pulled the loose ends into one short plan.',
    lastMessageAt: timestamp,
  };
};
