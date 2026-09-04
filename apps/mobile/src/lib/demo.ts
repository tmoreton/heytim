import type { Bootstrap, Bot, BotDraft, Group, GroupDraft, Message, SkillDetail, SkillDraft } from './types';

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

let groups: Group[] = [
  {
    id: 'launch-room',
    name: 'Launch crew',
    ownerId: 'demo-user',
    currentUserId: 'demo-user',
    isOwner: true,
    members: [
      { id: 'demo-user', name: 'You', role: 'owner' },
      { id: 'jordan', name: 'Jordan', role: 'member' },
    ],
    bots: [
      { id: 'chief', ownerId: 'demo-user', name: 'Chief', tagline: bots[0].tagline, color: bots[0].color },
      {
        id: 'draft-partner',
        ownerId: 'demo-user',
        name: 'Draft Partner',
        tagline: bots[2].tagline,
        color: bots[2].color,
      },
    ],
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'I will turn that into the launch checklist.',
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
  {
    id: 'deep-research',
    version: 1,
    name: 'Deep Research',
    description: 'Break down broad questions and produce a sourced, decision-ready synthesis.',
    instructions: 'Plan the research, delegate independent threads, verify material claims, and lead with the conclusion.',
    requiredToolIds: ['web', 'web_search', 'task_list', 'delegate'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'analyst',
    version: 1,
    name: 'Analyst',
    description: 'Compare options, test assumptions, and turn evidence into a recommendation.',
    instructions: 'Use consistent criteria, state assumptions, test scenarios, and recommend one path.',
    requiredToolIds: ['calculator'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'data-analyst',
    version: 1,
    name: 'Data Analyst',
    description: 'Inspect data, calculate results, and verify conclusions with executable code.',
    instructions: 'Inspect data quality, use executable analysis, verify the key result, and distinguish evidence from interpretation.',
    requiredToolIds: ['calculator', 'code_interpreter'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'editor',
    version: 1,
    name: 'Editor',
    description: 'Improve clarity, structure, and tone while preserving the author\'s meaning.',
    instructions: 'Preserve meaning, lead with the point, remove repetition, and return the finished revision first.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'brainstormer',
    version: 1,
    name: 'Brainstormer',
    description: 'Generate distinct ideas, pressure-test them, and identify the strongest directions.',
    instructions: 'Generate distinct strategies, remove duplicates, pressure-test the strongest, and suggest cheap experiments.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'teacher',
    version: 1,
    name: 'Teacher',
    description: 'Explain difficult subjects at the learner\'s level and check understanding.',
    instructions: 'Build a clear mental model, define jargon, use a concrete example, and check understanding.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'browser-research',
    version: 1,
    name: 'Browser Research',
    description: 'Investigate interactive or multi-page websites and report traceable findings.',
    instructions: 'Search first, browse only when navigation is needed, avoid unrequested actions, and link the pages inspected.',
    requiredToolIds: ['browser', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'fact-checker',
    version: 1,
    name: 'Fact Checker',
    description: 'Check concrete claims against reliable sources and explain the verdict.',
    instructions: 'Test each claim against primary sources, label the verdict, explain limitations, and link the evidence.',
    requiredToolIds: ['web', 'web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'meeting-prep',
    version: 1,
    name: 'Meeting Prep',
    description: 'Turn a meeting goal and attendee context into a focused briefing.',
    instructions: 'Clarify the outcome, research relevant public context, prepare an agenda and questions, and end with a checklist.',
    requiredToolIds: ['web_search'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'product-manager',
    version: 1,
    name: 'Product Manager',
    description: 'Shape product ideas into user problems, decisions, and testable requirements.',
    instructions: 'Start with the user problem, define the smallest valuable scope, surface risks, and recommend the next experiment.',
    requiredToolIds: [],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'project-manager',
    version: 1,
    name: 'Project Manager',
    description: 'Organize an outcome into owners, milestones, risks, and a maintained action list.',
    instructions: 'Define completion, track concrete tasks and dependencies, surface blockers, and keep the action list current.',
    requiredToolIds: ['task_list'],
    source: 'official',
    visibility: 'public',
    editable: false,
  },
  {
    id: 'summarizer',
    version: 1,
    name: 'Summarizer',
    description: 'Compress long material into an accurate summary tailored to the reader.',
    instructions: 'Lead with the central conclusion, preserve exact facts and qualifications, and remove repetition without inventing context.',
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

const groupMessages = new Map<string, Message[]>([
  [
    'launch-room',
    [
      {
        id: 'group-human',
        role: 'user',
        authorType: 'user',
        authorId: 'jordan',
        authorName: 'Jordan',
        isMine: false,
        text: 'Can we turn today\'s decisions into a launch plan?',
        createdAt: timestamp,
        status: 'complete',
      },
      {
        id: 'group-bot',
        role: 'assistant',
        authorType: 'bot',
        authorId: 'chief',
        authorName: 'Chief',
        authorColor: bots[0].color,
        text: 'Yes. I will turn that into the launch checklist and call out the decisions that still need an owner.',
        createdAt: timestamp,
        status: 'complete',
      },
    ],
  ],
]);

export const demoBootstrap = (): Bootstrap => ({
  bots: [...bots],
  groups: groups.map((group) => ({
    ...group,
    members: [...group.members],
    bots: [...group.bots],
  })),
  tools: [
    { id: 'web', name: 'Web reader', description: 'Open and summarize links.' },
    { id: 'web_search', name: 'Web search', description: 'Search the live web and return relevant sources.' },
    { id: 'calculator', name: 'Calculator', description: 'Do exact arithmetic.' },
    { id: 'current_time', name: 'World clock', description: 'Check time by timezone.' },
    { id: 'x_search', name: 'X / Twitter search', description: 'Search recent public posts on X.' },
    { id: 'youtube_search', name: 'YouTube research', description: 'Find videos and inspect metadata and comments.' },
    { id: 'task_list', name: 'Task tracker', description: 'Keep a live checklist during longer work.' },
    { id: 'delegate', name: 'Focused delegate', description: 'Hand a focused subtask to a fresh agent.' },
    { id: 'code_interpreter', name: 'Code interpreter', description: 'Run code in an isolated AgentCore sandbox.' },
    { id: 'browser', name: 'Interactive browser', description: 'Navigate and interact with websites.' },
  ],
  skills: skills.map(({ instructions: _instructions, ...skill }) => skill),
});

export const demoMessages = (botId: string): Message[] => [...(messages.get(botId) ?? [])];

export const demoGroupMessages = (groupId: string): Message[] => [...(groupMessages.get(groupId) ?? [])];

export const demoClearBotChat = (botId: string): void => {
  messages.set(botId, []);
  const now = new Date().toISOString();
  bots = bots.map((bot) =>
    bot.id === botId
      ? { ...bot, lastMessage: 'Ready when you are.', lastMessageAt: now, updatedAt: now }
      : bot,
  );
};

export const demoDeleteBot = (botId: string): void => {
  bots = bots.filter((bot) => bot.id !== botId);
  messages.delete(botId);
  groups = groups.map((group) => ({
    ...group,
    bots: group.bots.filter((bot) => bot.id !== botId),
  }));
};

export const demoDeleteGroup = (groupId: string): void => {
  groups = groups.filter((group) => group.id !== groupId);
  groupMessages.delete(groupId);
};

export const demoSaveGroup = (draft: GroupDraft, groupId?: string): Group => {
  const now = new Date().toISOString();
  const previous = groups.find((group) => group.id === groupId);
  const selectedBots = draft.botIds
    .map((id) => bots.find((bot) => bot.id === id))
    .filter((bot): bot is Bot => Boolean(bot))
    .map((bot) => ({ id: bot.id, ownerId: 'demo-user', name: bot.name, tagline: bot.tagline, color: bot.color }));
  const group: Group = {
    id: previous?.id ?? `group-${Date.now()}`,
    name: draft.name,
    ownerId: previous?.ownerId ?? 'demo-user',
    currentUserId: 'demo-user',
    isOwner: true,
    members: previous?.members ?? [{ id: 'demo-user', name: 'You', role: 'owner' }],
    bots: selectedBots,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
    lastMessage: previous?.lastMessage ?? 'Start the conversation.',
    lastMessageAt: previous?.lastMessageAt ?? now,
  };
  groups = previous ? groups.map((item) => (item.id === group.id ? group : item)) : [group, ...groups];
  if (!groupMessages.has(group.id)) groupMessages.set(group.id, []);
  return group;
};

export const demoJoinGroup = (_token: string): Group => ({ ...groups[0], members: [...groups[0].members], bots: [...groups[0].bots] });

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

export const demoSendGroup = (groupId: string, text: string, replyBotId?: string): void => {
  const current = groupMessages.get(groupId) ?? [];
  const requestId = String(Date.now());
  current.push({
    id: `${requestId}-user`,
    role: 'user',
    authorType: 'user',
    authorId: 'demo-user',
    authorName: 'You',
    isMine: true,
    text,
    createdAt: new Date().toISOString(),
    status: 'complete',
  });
  const group = groups.find((item) => item.id === groupId);
  const replyBots = replyBotId === 'all'
    ? (group?.bots ?? [])
    : (group?.bots.filter((item) => item.id === replyBotId) ?? []);
  replyBots.forEach((bot, index) => {
    current.push({
      id: `${requestId}-assistant-${index}`,
      role: 'assistant',
      authorType: 'bot',
      authorId: bot.id,
      authorName: bot.name,
      authorColor: bot.color,
      text: '',
      createdAt: new Date().toISOString(),
      status: 'pending',
    });
  });
  groupMessages.set(groupId, current);
  groups = groups.map((item) =>
    item.id === groupId ? { ...item, lastMessage: text, lastMessageAt: new Date().toISOString() } : item,
  );
  replyBots.forEach((bot, index) => {
    setTimeout(() => {
      const prior = index > 0 ? ` Building on ${replyBots[index - 1].name}'s contribution,` : '';
      const answer = `${bot.name} here.${prior} I will contribute from my role: ${bot.tagline}`;
      groupMessages.set(
        groupId,
        (groupMessages.get(groupId) ?? []).map((message) =>
          message.id === `${requestId}-assistant-${index}`
            ? { ...message, text: answer, status: 'complete', createdAt: new Date().toISOString() }
            : message,
        ),
      );
      groups = groups.map((item) =>
        item.id === groupId ? { ...item, lastMessage: answer, lastMessageAt: new Date().toISOString() } : item,
      );
    }, 700 + index * 500);
  });
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
