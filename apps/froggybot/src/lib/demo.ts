import type {
  Bootstrap,
  Attachment,
  Bot,
  BotTemplate,
  BotDocument,
  BotDraft,
  Connection,
  ConnectionDraft,
  Group,
  GroupDraft,
  Message,
  ScheduleRun,
  ScheduledTask,
  ScheduledTaskDraft,
  SkillDetail,
  SkillDraft,
} from './types';
import { loadDemoCatalog, loadDemoSkill } from './demo-catalog';
import { CHIEF_COLOR, CHIEF_TEMPLATE_ID, chiefFirst, displayBotColor } from './bot-branding';
import { createDemoChief } from './demo-chief';
import { demoDecisionsForGroup } from './demo-decisions';
import {
  createInitialDemoBots,
  createInitialDemoGroups,
  createInitialDemoSchedules,
} from './demo-fixtures';

const timestamp = new Date().toISOString();

let bots = createInitialDemoBots(timestamp);

let groups = createInitialDemoGroups(timestamp);
let schedules = createInitialDemoSchedules(timestamp);

let personalSkills: SkillDetail[] = [];
let personalConnections: Connection[] = [];
const uploadedAttachments = new Map<string, Attachment>();
let scheduleRunItems: ScheduleRun[] = [];

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
  ['trip-planner', []],
  ['event-planner', []],
  ['research-reports', []],
]);

const botDocuments = new Map<string, BotDocument[]>([
  [
    'chief',
    [
      {
        id: 'demo-launch-checklist',
        name: 'launch-checklist.docx',
        size: 48_200,
        kind: 'document',
        format: 'docx',
        contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        createdAt: timestamp,
      },
    ],
  ],
  [
    'research-reports',
    [
      {
        id: 'demo-market-brief',
        name: 'market-research-brief.pdf',
        size: 284_300,
        kind: 'document',
        format: 'pdf',
        contentType: 'application/pdf',
        createdAt: timestamp,
      },
      {
        id: 'demo-source-data',
        name: 'source-data.xlsx',
        size: 91_700,
        kind: 'document',
        format: 'xlsx',
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        createdAt: timestamp,
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
        text: 'I want somewhere walkable with a genuinely good vegetarian dinner.',
        createdAt: timestamp,
        status: 'complete',
      },
      {
        id: 'group-bot',
        role: 'assistant',
        authorType: 'bot',
        authorId: 'chief',
        authorName: 'Chief',
        authorColor: CHIEF_COLOR,
        text: 'Got it. I’ll keep that as a room constraint and ask the team to compare the strongest options.',
        createdAt: timestamp,
        status: 'complete',
      },
    ],
  ],
]);

const ensureDemoChief = (chief: Bot) => {
  if (bots.some((bot) => bot.systemRole === 'chief')) return;
  bots = chiefFirst([chief, ...bots]);
  groups = groups.map((group) => ({
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
      ...bots
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
  groupMessages.set(
    'launch-room',
    (groupMessages.get('launch-room') ?? []).map((message) =>
      message.authorId === CHIEF_TEMPLATE_ID
        ? { ...message, authorName: chief.name, authorColor: chief.color }
        : message,
    ),
  );
};

export const demoBootstrap = async (): Promise<Bootstrap> => {
  const catalog = await loadDemoCatalog();
  const chiefTemplate = catalog.botTemplates.find((template) => template.id === CHIEF_TEMPLATE_ID);
  if (!chiefTemplate) throw new Error('The required Chief bot is unavailable.');
  ensureDemoChief(createDemoChief(chiefTemplate, catalog.skills, timestamp));
  return {
    bots: chiefFirst(bots),
    botTemplates: catalog.botTemplates,
    needsBotOnboarding: false,
    groups: groups.map((group) => ({
      ...group,
      members: [...group.members],
      bots: [...group.bots],
      decisions: demoDecisionsForGroup(group.id),
    })),
    tools: [...catalog.tools, ...personalConnections],
    skills: [
      ...catalog.skills,
      ...personalSkills.map(({ instructions: _instructions, ...skill }) => skill),
    ],
  };
};

export const demoInstallBotTemplate = async (templateId: string): Promise<Bot> => {
  const catalog = await loadDemoCatalog();
  const template = catalog.botTemplates.find((item) => item.id === templateId);
  if (!template) throw new Error('Bot not found in the library.');
  if (bots.some((bot) => bot.templateId === template.id)) {
    throw new Error('This bot is already in your team.');
  }
  const requiredToolIds = catalog.skills
    .filter((skill) => template.skillIds.includes(skill.id))
    .flatMap((skill) => skill.requiredToolIds);
  return demoSaveBotTemplate(template, [...new Set([...template.toolIds, ...requiredToolIds])]);
};

const demoSaveBotTemplate = (template: BotTemplate, toolIds: string[]): Bot => {
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
  bots = chiefFirst([bot, ...bots]);
  messages.set(bot.id, []);
  return bot;
};

export const demoMessages = (botId: string): Message[] => [...(messages.get(botId) ?? [])];

export const demoUploadAttachment = async (asset: {
  name: string;
  size: number;
  mimeType?: string;
}): Promise<Attachment> => {
  const attachment: Attachment = {
    id: `demo-file-${Date.now()}-${uploadedAttachments.size}`,
    name: asset.name,
    size: asset.size,
    kind: asset.mimeType?.startsWith('image/') ? 'image' : 'document',
    format: asset.name.split('.').pop()?.toLowerCase() ?? 'txt',
    contentType: asset.mimeType ?? 'application/octet-stream',
    createdAt: new Date().toISOString(),
  };
  uploadedAttachments.set(attachment.id, attachment);
  return { ...attachment };
};

export const demoBotDocuments = async (botId: string): Promise<BotDocument[]> =>
  (botDocuments.get(botId) ?? []).map((document) => ({ ...document }));

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
  botDocuments.delete(botId);
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
    decisions: previous?.decisions ?? [],
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
    color: displayBotColor({ ...draft, systemRole: previous?.systemRole }),
    systemRole: previous?.systemRole,
    id: previous?.id ?? `bot-${Date.now()}`,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
    lastMessage: previous?.lastMessage ?? 'Ready when you are.',
    lastMessageAt: previous?.lastMessageAt ?? now,
  };
  bots = chiefFirst(previous ? bots.map((item) => (item.id === bot.id ? bot : item)) : [bot, ...bots]);
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
  const group = groups.find((item) => item.id === botId);
  if (!task || (!bot && !group)) throw new Error('Scheduled task not found.');
  const current = new Date().toISOString();
  schedules = schedules.map((item) =>
    item.id === task.id ? { ...item, lastRunAt: current, lastStatus: 'pending', updatedAt: current } : item,
  );
  const runId = `run-${Date.now()}`;
  scheduleRunItems = [{
    id: runId,
    botId,
    scheduleId,
    scheduleName: task.name,
    prompt: task.prompt,
    status: 'pending',
    createdAt: current,
  }, ...scheduleRunItems];
  if (bot) demoSend(bot, task.prompt, task);
  else if (group) demoSendGroup(group.id, task.prompt, 'all');
  setTimeout(() => {
    scheduleRunItems = scheduleRunItems.map((run) => run.id === runId ? {
      ...run,
      status: 'complete',
      completedAt: new Date().toISOString(),
      output: `Today’s priorities are to confirm the owner, verify the deadline, and publish the smallest useful result.`,
    } : run);
  }, 900);
};

export const demoScheduleRuns = async (botId: string): Promise<ScheduleRun[]> =>
  scheduleRunItems.filter((run) => run.botId === botId).map((run) => ({ ...run }));

export const demoSendGroup = (
  groupId: string,
  text: string,
  replyBotId?: string,
  attachmentIds: string[] = [],
): void => {
  const current = groupMessages.get(groupId) ?? [];
  const requestId = String(Date.now());
  current.push({
    id: `${requestId}-user`,
    role: 'user',
    authorType: 'user',
    authorId: 'demo-user',
    authorName: 'You',
    isMine: true,
    text: text || 'Please review the attached files.',
    attachments: attachmentIds
      .map((id) => uploadedAttachments.get(id))
      .filter((attachment): attachment is Attachment => Boolean(attachment))
      .map((attachment) => ({ ...attachment })),
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
        ? `I’m coordinating around the room’s fixed constraints: **under $1,200**, no driving, a walkable destination, vegetarian food, and a Sunday return before 6 PM. Research will verify the travel and price assumptions; Trip Planner will turn the best option into a usable itinerary.`
        : bot.roundRole === 'contributor'
          ? bot.id === 'research-reports'
            ? `**Evidence check**\n\nPortland, Maine is the strongest fit. The Boston–Portland train is roughly 2½ hours, the Old Port is walkable, and a central one-night stay can fit the budget. Providence is cheaper but feels less like a getaway; New York creates more travel time and budget pressure.`
            : `**Practical plan**\n\nTake the 8:50 AM train Saturday, leave bags near the Old Port, and keep the day walkable. Book dinner around 7 PM with a vegetarian-first shortlist. On Sunday, use a late-morning lighthouse cruise or waterfront walk, then take the early-afternoon train home to preserve the 6 PM buffer.`
          : bot.roundRole === 'synthesizer'
            ? `**Decision: Portland, Maine**\n\nIt best satisfies the group’s travel-time, walkability, food, and budget constraints.\n\n**Working budget**\n- Train: $180–240\n- Central hotel: $320–420\n- Food: $220\n- Activities and local transport: $120\n- Buffer: $150\n\n**Next steps**\n1. You: confirm the Saturday train by Tuesday.\n2. Jordan: choose between the two dinner options.\n3. Chief: keep the itinerary current after bookings.\n\nI created **portland-weekend-plan.pdf** so the group can use the final itinerary outside this chat.`
            : `I’ll handle this from my role: ${bot.tagline}`;
      groupMessages.set(
        groupId,
        (groupMessages.get(groupId) ?? []).map((message) =>
          message.id === `${requestId}-assistant-${index}`
            ? {
                ...message,
                text: answer,
                status: 'complete',
                createdAt: new Date().toISOString(),
                attachments: bot.roundRole === 'synthesizer' ? [{
                  id: `demo-portland-plan-${requestId}`,
                  name: 'portland-weekend-plan.pdf',
                  size: 184_000,
                  kind: 'document' as const,
                  format: 'pdf',
                  contentType: 'application/pdf',
                  createdAt: new Date().toISOString(),
                }] : undefined,
              }
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
