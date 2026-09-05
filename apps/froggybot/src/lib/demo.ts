import type {
  Bootstrap,
  Bot,
  BotDraft,
  Connection,
  ConnectionDraft,
  Group,
  GroupDraft,
  Message,
  ScheduledTask,
  ScheduledTaskDraft,
  SkillDetail,
  SkillDraft,
} from './types';
import { loadDemoCatalog, loadDemoSkill } from './demo-catalog';

const timestamp = new Date().toISOString();

let bots: Bot[] = [
  {
    id: 'chief',
    name: 'Chief',
    tagline: 'Keeps the work moving and connects the dots.',
    color: '#58BEAA',
    prompt: 'Act as my chief of staff. Clarify priorities and always end with the best next action.',
    toolIds: ['current_time', 'calculator'],
    extraToolIds: ['current_time', 'calculator'],
    skillIds: ['group-decision'],
    systemRole: 'chief',
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'I pulled the loose ends into one short plan.',
    lastMessageAt: timestamp,
  },
];

let groups: Group[] = [
  {
    id: 'launch-room',
    name: 'Launch crew',
    memory: 'Launch on Friday. Keep decisions concise, assign one owner per action, and preserve the approved brand voice.',
    ownerId: 'demo-user',
    currentUserId: 'demo-user',
    isOwner: true,
    members: [
      { id: 'demo-user', name: 'You', role: 'owner' },
      { id: 'jordan', name: 'Jordan', role: 'member' },
    ],
    bots: [
      {
        id: 'chief',
        ownerId: 'demo-user',
        name: 'Chief',
        tagline: bots[0].tagline,
        color: bots[0].color,
        systemRole: 'chief',
      },
    ],
    createdAt: timestamp,
    updatedAt: timestamp,
    lastMessage: 'I will turn that into the launch checklist.',
    lastMessageAt: timestamp,
  },
];

let schedules: ScheduledTask[] = [
  {
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
  },
];

let personalSkills: SkillDetail[] = [];
let personalConnections: Connection[] = [];

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

export const demoBootstrap = async (): Promise<Bootstrap> => {
  const catalog = await loadDemoCatalog().catch(() => ({ tools: [], skills: [] }));
  return {
    bots: [...bots],
    groups: groups.map((group) => ({
      ...group,
      members: [...group.members],
      bots: [...group.bots],
    })),
    tools: [...catalog.tools, ...personalConnections],
    skills: [
      ...catalog.skills,
      ...personalSkills.map(({ instructions: _instructions, ...skill }) => skill),
    ],
  };
};

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
  if (bots.find((bot) => bot.id === botId)?.systemRole === 'chief') {
    throw new Error('Chief coordinates your other bots and cannot be deleted.');
  }
  bots = bots.filter((bot) => bot.id !== botId);
  schedules = schedules.filter((task) => task.botId !== botId);
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
    .map((bot) => ({
      id: bot.id,
      ownerId: 'demo-user',
      name: bot.name,
      tagline: bot.tagline,
      color: bot.color,
      systemRole: bot.systemRole,
    }));
  const group: Group = {
    id: previous?.id ?? `group-${Date.now()}`,
    name: draft.name,
    memory: draft.memory,
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
    systemRole: previous?.systemRole,
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

export const demoSend = (bot: Bot, text: string, task?: ScheduledTask): void => {
  const current = messages.get(bot.id) ?? [];
  const requestId = String(Date.now());
  current.push(
    {
      id: `${requestId}-user`,
      role: 'user',
      text,
      source: task ? 'schedule' : undefined,
      scheduleName: task?.name,
      createdAt: new Date().toISOString(),
      status: 'complete',
    },
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
    if (task) {
      schedules = schedules.map((item) =>
        item.id === task.id
          ? { ...item, lastRunAt: new Date().toISOString(), lastStatus: 'complete', updatedAt: new Date().toISOString() }
          : item,
      );
    }
  }, 900);
};

export const demoListSchedules = async (botId: string): Promise<ScheduledTask[]> =>
  schedules.filter((task) => task.botId === botId).map((task) => ({ ...task }));

export const demoSaveSchedule = async (
  botId: string,
  draft: ScheduledTaskDraft,
  scheduleId?: string,
): Promise<ScheduledTask> => {
  const current = new Date().toISOString();
  const previous = schedules.find((task) => task.id === scheduleId && task.botId === botId);
  const task: ScheduledTask = {
    ...draft,
    id: previous?.id ?? `schedule-${Date.now()}`,
    botId,
    createdAt: previous?.createdAt ?? current,
    updatedAt: current,
    lastRunAt: previous?.lastRunAt,
    lastStatus: previous?.lastStatus,
  };
  schedules = previous
    ? schedules.map((item) => (item.id === task.id ? task : item))
    : [task, ...schedules];
  return { ...task };
};

export const demoDeleteSchedule = async (botId: string, scheduleId: string): Promise<void> => {
  schedules = schedules.filter((task) => task.botId !== botId || task.id !== scheduleId);
};

export const demoRunSchedule = async (botId: string, scheduleId: string): Promise<void> => {
  const task = schedules.find((item) => item.botId === botId && item.id === scheduleId);
  const bot = bots.find((item) => item.id === botId);
  if (!task || !bot) throw new Error('Scheduled task not found.');
  const current = new Date().toISOString();
  schedules = schedules.map((item) =>
    item.id === task.id ? { ...item, lastRunAt: current, lastStatus: 'pending', updatedAt: current } : item,
  );
  demoSend(bot, task.prompt, task);
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
  const selectedBots = replyBotId === 'all'
    ? [...(group?.bots ?? [])].sort((left, right) =>
        Number(right.systemRole === 'chief') - Number(left.systemRole === 'chief') || left.name.localeCompare(right.name),
      )
    : (group?.bots.filter((item) => item.id === replyBotId) ?? []);
  const roundBots = replyBotId === 'all' && selectedBots.length > 1
    ? [
        { ...selectedBots[0], roundRole: 'lead' as const },
        ...selectedBots.slice(1).map((bot) => ({ ...bot, roundRole: 'contributor' as const })),
        { ...selectedBots[0], roundRole: 'synthesizer' as const },
      ]
    : selectedBots.map((bot) => ({ ...bot, roundRole: 'solo' as const }));
  roundBots.forEach((bot, index) => {
    current.push({
      id: `${requestId}-assistant-${index}`,
      role: 'assistant',
      authorType: 'bot',
      authorId: bot.id,
      authorName: bot.name,
      authorColor: bot.color,
      text: '',
      roundId: requestId,
      roundPosition: index + 1,
      roundSize: roundBots.length,
      roundRole: bot.roundRole,
      createdAt: new Date().toISOString(),
      status: index === 0 ? 'pending' : 'waiting',
    });
  });
  groupMessages.set(groupId, current);
  groups = groups.map((item) =>
    item.id === groupId ? { ...item, lastMessage: text, lastMessageAt: new Date().toISOString() } : item,
  );
  roundBots.forEach((bot, index) => {
    setTimeout(() => {
      const answer = bot.roundRole === 'lead'
        ? `I’ll coordinate this. My initial approach is to define the outcome, then ask each teammate to strengthen it from their specialty.`
        : bot.roundRole === 'contributor'
          ? `Building on ${roundBots[index - 1].name}’s contribution, I’d add this from my role: ${bot.tagline}`
          : bot.roundRole === 'synthesizer'
            ? `**Team answer**\n\nWe combined the plan and specialist input into one recommendation: start with the smallest useful outcome, verify the important facts, and then take the clearest next action.`
            : `I’ll handle this from my role: ${bot.tagline}`;
      groupMessages.set(
        groupId,
        (groupMessages.get(groupId) ?? []).map((message) =>
          message.id === `${requestId}-assistant-${index}`
            ? { ...message, text: answer, status: 'complete', createdAt: new Date().toISOString() }
            : message.id === `${requestId}-assistant-${index + 1}` && message.status === 'waiting'
              ? { ...message, status: 'pending' }
              : message,
        ),
      );
      groups = groups.map((item) =>
        item.id === groupId ? { ...item, lastMessage: answer, lastMessageAt: new Date().toISOString() } : item,
      );
    }, 800 + index * 800);
  });
};

export const demoGetSkill = async (skillId: string): Promise<SkillDetail> => {
  const personal = personalSkills.find((item) => item.id === skillId);
  return personal ? { ...personal } : loadDemoSkill(skillId);
};

export const demoSaveSkill = async (draft: SkillDraft, skillId?: string): Promise<SkillDetail> => {
  const existing = personalSkills.find((item) => item.id === skillId);
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
  personalSkills = existing
    ? personalSkills.map((item) => (item.id === saved.id ? saved : item))
    : [...personalSkills, saved];
  return saved;
};

export const demoSaveConnection = async (
  draft: ConnectionDraft,
  connectionId?: string,
): Promise<Connection> => {
  const existing = personalConnections.find((item) => item.id === connectionId);
  const saved: Connection = {
    id: existing?.id ?? `connection_${Date.now()}`,
    name: draft.name,
    description: draft.description,
    endpoint: draft.endpoint,
    authType: draft.authType,
    headerName: draft.authType === 'bearer' ? 'Authorization' : draft.headerName,
    hasCredential: draft.authType === 'none' ? undefined : Boolean(draft.credential || existing?.hasCredential),
    connectionStatus: 'connected',
    provider: 'mcp',
    risk: draft.risk,
    source: 'user',
    editable: true,
  };
  personalConnections = existing
    ? personalConnections.map((item) => (item.id === saved.id ? saved : item))
    : [...personalConnections, saved];
  return saved;
};

export const demoDeleteConnection = (connectionId: string): void => {
  const inUse = bots.some((bot) => bot.toolIds.includes(connectionId));
  if (inUse) throw new Error('Remove this connection from its FroggyBot before deleting it.');
  personalConnections = personalConnections.filter((item) => item.id !== connectionId);
};

export const demoImportSkill = async (_token: string): Promise<SkillDetail> => {
  const catalog = await loadDemoCatalog();
  const first = catalog.skills[0];
  if (!first) throw new Error('No public skills are available.');
  return { ...(await loadDemoSkill(first.id)), relationship: 'installed' };
};
