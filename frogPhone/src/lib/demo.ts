import type { Bootstrap, Bot, BotDraft, Message, SkillDetail, SkillDraft } from './types';

const timestamp = new Date().toISOString();

let bots: Bot[] = [
  {
    id: 'chief',
    name: 'Chief',
    tagline: 'Keeps the work moving and connects the dots.',
    color: '#58BEAA',
    prompt: 'Act as my chief of staff. Clarify priorities and always end with the best next action.',
    toolIds: ['current_time', 'calculator'],
    skillIds: ['planner'],
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'I pulled the loose ends into one short plan.',
    lastMessageAt: timestamp,
  },
  {
    id: 'research-scout',
    name: 'Research Scout',
    tagline: 'Finds the signal and brings back the evidence.',
    color: '#6C5CE7',
    prompt: 'Research carefully. Separate facts from inference and call out uncertainty.',
    toolIds: ['web', 'calculator'],
    skillIds: ['researcher'],
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'Three strong sources found. The second one is the key.',
    lastMessageAt: timestamp,
  },
  {
    id: 'draft-partner',
    name: 'Draft Partner',
    tagline: 'Turns rough thinking into clear words.',
    color: '#FFAA34',
    prompt: 'Help me write in a direct, warm voice. Return usable drafts.',
    toolIds: [],
    skillIds: ['writer'],
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'The launch note is tightened and ready to send.',
    lastMessageAt: timestamp,
  },
];

let skills: SkillDetail[] = [
  {
    id: 'planner',
    version: 1,
    name: 'Planner',
    description: 'Turn goals into practical next steps.',
    instructions: 'Turn a goal into a concise, ordered plan with assumptions, risks, and a next action.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'researcher',
    version: 1,
    name: 'Researcher',
    description: 'Investigate questions and synthesize evidence.',
    instructions: 'Research using reliable sources, separate facts from inference, and explain uncertainty.',
    requiredToolIds: ['web', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'writer',
    version: 1,
    name: 'Writer',
    description: 'Draft polished, audience-aware copy.',
    instructions: 'Create usable writing that preserves supplied facts and matches the requested voice.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
];

const messages = new Map<string, Message[]>([
  [
    'chief',
    [
      {
        id: 'welcome-chief',
        role: 'assistant',
        text: 'I am caught up. What should we move forward today?',
        createdAt: timestamp,
        status: 'complete',
      },
    ],
  ],
  [
    'research-scout',
    [
      {
        id: 'welcome-research',
        role: 'assistant',
        text: 'Give me the question and I will bring back the signal, sources, and uncertainty.',
        createdAt: timestamp,
        status: 'complete',
      },
    ],
  ],
  [
    'draft-partner',
    [
      {
        id: 'welcome-writer',
        role: 'assistant',
        text: 'Send the rough version. I will keep your meaning and make the words land.',
        createdAt: timestamp,
        status: 'complete',
      },
    ],
  ],
]);

export const demoBootstrap = (): Bootstrap => ({
  bots: [...bots],
  tools: [
    { id: 'web', name: 'Web reader', description: 'Open and summarize links.' },
    { id: 'web_search', name: 'Web search', description: 'Search the live web and return relevant sources.' },
    { id: 'calculator', name: 'Calculator', description: 'Do exact arithmetic.' },
    { id: 'current_time', name: 'World clock', description: 'Check time by timezone.' },
  ],
  skills: skills.map(({ instructions: _instructions, ...skill }) => skill),
});

export const demoMessages = (botId: string): Message[] => [...(messages.get(botId) ?? [])];

export const demoSaveBot = (draft: BotDraft, botId?: string): Bot => {
  const now = new Date().toISOString();
  const previous = bots.find((bot) => bot.id === botId);
  const bot: Bot = {
    ...draft,
    id: previous?.id ?? `bot-${Date.now()}`,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
    lastMessage: previous?.lastMessage ?? 'Ready when you are.',
    lastMessageAt: previous?.lastMessageAt ?? now,
  };
  bots = previous ? bots.map((item) => (item.id === bot.id ? bot : item)) : [bot, ...bots];
  if (!messages.has(bot.id)) messages.set(bot.id, []);
  return bot;
};

export const demoSend = (bot: Bot, text: string): void => {
  const current = messages.get(bot.id) ?? [];
  const requestId = String(Date.now());
  current.push(
    { id: `${requestId}-user`, role: 'user', text, createdAt: new Date().toISOString(), status: 'complete' },
    { id: `${requestId}-assistant`, role: 'assistant', text: '', createdAt: new Date().toISOString(), status: 'pending' },
  );
  messages.set(bot.id, current);
  setTimeout(() => {
    const response = `Understood. I would handle that as ${bot.name}: start with the smallest useful result, verify it, then bring back the decision that needs you.`;
    messages.set(
      bot.id,
      (messages.get(bot.id) ?? []).map((message) =>
        message.id === `${requestId}-assistant`
          ? { ...message, text: response, status: 'complete', createdAt: new Date().toISOString() }
          : message,
      ),
    );
    bots = bots.map((item) =>
      item.id === bot.id
        ? { ...item, lastMessage: response, lastMessageAt: new Date().toISOString(), updatedAt: new Date().toISOString() }
        : item,
    );
  }, 900);
};

export const demoGetSkill = async (skillId: string): Promise<SkillDetail> => {
  const skill = skills.find((item) => item.id === skillId);
  if (!skill) throw new Error('Skill not found.');
  return { ...skill };
};

export const demoSaveSkill = async (draft: SkillDraft, skillId?: string): Promise<SkillDetail> => {
  const existing = skills.find((item) => item.id === skillId);
  if (skillId && (!existing || !existing.editable)) throw new Error('Only your own skills can be edited.');
  const saved: SkillDetail = {
    ...draft,
    id: existing?.id ?? `skill-${Date.now()}`,
    version: (existing?.version ?? 0) + 1,
    source: 'user',
    editable: true,
    relationship: 'owner',
    updatedAt: new Date().toISOString(),
  };
  skills = existing ? skills.map((item) => (item.id === saved.id ? saved : item)) : [...skills, saved];
  return saved;
};

export const demoImportSkill = async (_token: string): Promise<SkillDetail> => ({ ...skills[0] });
