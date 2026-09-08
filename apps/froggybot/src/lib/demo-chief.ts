import type { Bot, BotTemplate, Skill } from './types';
import { CHIEF_COLOR, CHIEF_TEMPLATE_ID } from './bot-branding';

export const createDemoChief = (
  template: BotTemplate,
  skills: Skill[],
  timestamp: string,
): Bot => {
  const skillToolIds = skills
    .filter((skill) => template.skillIds.includes(skill.id))
    .flatMap((skill) => skill.requiredToolIds);
  return {
    id: CHIEF_TEMPLATE_ID,
    name: template.name,
    tagline: template.tagline,
    color: CHIEF_COLOR,
    prompt: template.prompt,
    toolIds: [...new Set([...template.toolIds, ...skillToolIds])],
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
