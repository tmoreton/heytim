import type { Bot, BotTemplate, Group, ScheduledTask, Skill } from '@froggybot/contracts';

const INITIAL_DEMO_BOTS = [
  {
    templateId: 'trip-planner',
    lastMessage: 'Tell me who is traveling and what matters most to each person.',
  },
  {
    templateId: 'event-planner',
    lastMessage: 'What are we organizing, and who needs to be involved?',
  },
  {
    templateId: 'research-reports',
    lastMessage: 'Give me the question or data, and I will return the useful conclusion.',
  },
] as const;

export const toolIdsForTemplate = (template: BotTemplate, skills: Skill[]): string[] => {
  const requiredToolIds = skills
    .filter((skill) => template.skillIds.includes(skill.id))
    .flatMap((skill) => skill.requiredToolIds);
  return [...new Set([...template.toolIds, ...requiredToolIds])];
};

export const createInitialDemoBots = (
  templates: BotTemplate[],
  skills: Skill[],
  timestamp: string,
): Bot[] => {
  const templatesById = new Map(templates.map((template) => [template.id, template]));
  return INITIAL_DEMO_BOTS.flatMap(({ templateId, lastMessage }): Bot[] => {
    const template = templatesById.get(templateId);
    if (!template) return [];
    return [{
      id: template.id,
      name: template.name,
      tagline: template.tagline,
      color: template.color,
      prompt: template.prompt,
      toolIds: toolIdsForTemplate(template, skills),
      extraToolIds: [...template.toolIds],
      alwaysAllowedToolIds: [],
      skillIds: [...template.skillIds],
      templateId: template.id,
      templateVersion: template.version,
      createdAt: timestamp,
      updatedAt: timestamp,
      lastMessage,
      lastMessageAt: timestamp,
    }];
  });
};

export const createInitialDemoGroups = (timestamp: string): Group[] => [{
  id: 'launch-room',
  name: 'Weekend in Portland',
  memory: 'Two adults leaving Boston Saturday morning. Keep the total under $1,200, avoid driving, include vegetarian food, and return by 6 PM Sunday.',
  ownerId: 'demo-user',
  currentUserId: 'demo-user',
  isOwner: true,
  members: [
    { id: 'demo-user', name: 'You', role: 'owner' },
    { id: 'jordan', name: 'Jordan', role: 'member' },
  ],
  bots: [],
  decisions: [],
  createdAt: timestamp,
  updatedAt: timestamp,
  lastMessage: 'Portland is the best fit. The itinerary and budget are ready.',
  lastMessageAt: timestamp,
}];

export const createInitialDemoSchedules = (timestamp: string): ScheduledTask[] => [{
  id: 'morning-priorities',
  botId: 'chief',
  name: 'Morning priorities',
  prompt: 'Review what we have discussed and give me the three most important priorities for today.',
  frequency: 'daily',
  time: '09:00',
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  enabled: true,
  createdAt: timestamp,
  updatedAt: timestamp,
}];
