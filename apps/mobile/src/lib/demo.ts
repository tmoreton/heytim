import type {
  Bootstrap,
  Bot,
  BotDraft,
  Group,
  GroupDraft,
  Message,
  ScheduledTask,
  ScheduledTaskDraft,
  SkillDetail,
  SkillDraft,
} from './types';

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
    toolIds: ['web', 'web_search', 'calculator'],
    extraToolIds: ['calculator'],
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
    extraToolIds: [],
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

let skills: SkillDetail[] = [
  {
    id: 'planner',
    version: 1,
    name: 'Planner',
    description: 'Turn goals into practical next steps.',
    instructions: `# Planner

Turn an outcome into a short plan that can be acted on immediately.

1. Restate the desired outcome and any hard constraints.
2. Identify the smallest useful milestone.
3. Order the work by dependency and risk.
4. Call out the one decision or missing fact that could materially change the plan.
5. End with the next concrete action.

Prefer five useful steps over a long generic checklist.`,
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
    instructions: `# Researcher

Research claims before presenting them as fact.

1. Clarify the question, timeframe, and decision it supports.
2. Prefer primary and authoritative sources.
3. Compare more than one source when the claim is consequential or disputed.
4. Separate directly supported facts from inference.
5. Cite the source URL next to the claim it supports.
6. State important uncertainty and what would resolve it.

Do not pad the answer with search process. Lead with the useful conclusion.`,
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
    instructions: `# Writer

Produce writing that is ready to use.

1. Preserve the user's facts, intent, and level of certainty.
2. Match the audience and requested channel.
3. Lead with the point and remove throat-clearing.
4. Prefer concrete language and natural sentence rhythm.
5. Return the finished draft before optional notes.

Ask a question only when a missing detail would materially change the result.`,
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
    instructions: `# Deep Research

Turn a broad question into a compact research plan, then return a useful conclusion rather than a research diary.

1. Define the decision, scope, timeframe, and important unknowns.
2. Track the research threads that materially affect the answer.
3. Delegate independent lines of inquiry when they can be investigated in parallel.
4. Prefer primary sources and verify consequential claims with more than one source.
5. Separate sourced facts, synthesis, and uncertainty.
6. Lead with the conclusion, cite evidence beside each important claim, and end with remaining gaps.

Do not confuse the number of sources with quality. Stop when further research is unlikely to change the conclusion.`,
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
    instructions: `# Analyst

Analyze the decision behind the question, not just the surface request.

1. State the objective and the criteria that matter.
2. Separate known inputs from assumptions and estimates.
3. Use consistent units and show material calculations.
4. Compare the strongest options against the same criteria.
5. Test what changes under a reasonable downside or upside scenario.
6. Recommend one path and name the fact most likely to reverse it.

Use tables only when they make the comparison easier to scan.`,
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
    instructions: `# Data Analyst

Use executable analysis to turn structured data or quantitative questions into checked conclusions.

1. Confirm the question, units, relevant fields, and expected output.
2. Inspect the data shape and quality before calculating results.
3. Use code for transformations, statistics, or comparisons that are not trivial.
4. Check missing values, outliers, and assumptions that could change the conclusion.
5. Verify key results with a second calculation or sanity check.
6. Lead with the finding, explain the method briefly, and distinguish evidence from interpretation.

Never invent unavailable data. State what additional input would be needed.`,
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
    instructions: `# Editor

Return an improved version that still sounds like the author.

1. Preserve facts, intent, uncertainty, and any required terminology.
2. Put the main point first and organize supporting ideas in a natural order.
3. Remove repetition, filler, and unnecessary qualifiers.
4. Replace vague phrasing with concrete language without inventing details.
5. Match the requested audience, channel, and level of formality.
6. Return the finished revision first, followed only by material editorial notes.

Do not silently change the author's position.`,
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
    instructions: `# Brainstormer

Produce meaningfully different directions instead of superficial variations.

1. Restate the goal and constraints in one sentence.
2. Generate ideas across several distinct strategies or frames.
3. Make each idea concrete enough to evaluate or test.
4. Remove duplicates and weak variations.
5. Pressure-test the most promising ideas for effort, risk, and likely impact.
6. Recommend the best two or three directions and the cheapest useful experiment for each.

Favor a small set of strong, varied ideas over a long unranked list.`,
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
    instructions: `# Teacher

Help the learner build a usable mental model.

1. Infer the learner's level from the conversation and define unfamiliar terms in plain language.
2. Start with the central idea before adding detail.
3. Use one concrete example that maps directly to the idea.
4. Explain common misconceptions or failure modes when they matter.
5. Break procedures into small steps with clear outcomes.
6. End with a short check-for-understanding question or practice prompt when appropriate.

Do not use jargon as a substitute for explanation.`,
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
    instructions: `# Browser Research

Use this skill when answering requires navigating a site, following links, or reading information that a simple search result does not expose.

1. Search first to identify the most relevant primary or authoritative pages.
2. Use the interactive browser only when navigation or page interaction is necessary.
3. Never submit forms, accept terms, purchase anything, or change an account unless the user has explicitly requested that exact action.
4. Keep a short record of the pages inspected and distinguish page facts from your inference.
5. Return a concise synthesis with direct links and call out anything that could not be verified.`,
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
    instructions: `# Fact Checker

For every material claim:

1. Restate the claim precisely enough to test.
2. Prefer primary sources, official records, and direct documentation.
3. Seek at least one independent source when the claim is contested or consequential.
4. Label the result as supported, contradicted, mixed, outdated, or unverified.
5. Explain the evidence and its limitations without overstating certainty.

Include direct source links beside the conclusions they support.`,
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
    instructions: `# Meeting Prep

Build a compact briefing that helps the user enter the meeting ready to decide and act.

- Clarify the desired outcome, participants, time available, and decisions required.
- Research only public professional context that is relevant to the meeting.
- Separate known facts from assumptions and suggested talking points.
- Provide an agenda, the most important questions, likely concerns, and a clear close.
- End with a short pre-meeting checklist and any missing information worth gathering.`,
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
    instructions: `# Product Manager

Start with the user and the outcome, not a feature list.

1. Define the target user, problem, current workaround, and desired outcome.
2. Identify the smallest valuable scope and explicitly list what is out of scope.
3. Turn assumptions into testable questions or acceptance criteria.
4. Surface dependencies, risks, edge cases, and measurable success signals.
5. Recommend the next decision or experiment instead of producing unnecessary ceremony.`,
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
    instructions: `# Project Manager

Use the task tracker for work that has multiple dependent steps.

- Define the outcome and completion criteria before making the plan.
- Break work into concrete tasks with an owner, dependency, and useful target date when known.
- Keep milestones few and outcome-oriented.
- Track decisions, open questions, blockers, and risks separately.
- Update the task list as work changes, and finish with the next three actions that unblock progress.`,
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
    instructions: `# Summarizer

Preserve meaning while removing repetition and low-value detail.

1. Identify the intended reader and the decision or understanding the summary should support.
2. Lead with the central conclusion or theme.
3. Keep important numbers, dates, qualifications, disagreements, and action items exact.
4. Do not invent context or smooth over uncertainty in the source.
5. Use the shortest structure that remains clear: a paragraph for simple material, sections only when they make distinct themes or actions easier to scan.`,
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
    { id: 'web', name: 'Web reader', description: 'Open and summarize links.', provider: 'stan' },
    { id: 'web_search', name: 'Web search', description: 'Search the live web and return relevant sources.', provider: 'agentcore-gateway' },
    { id: 'calculator', name: 'Calculator', description: 'Do exact arithmetic.', provider: 'frogbot' },
    { id: 'current_time', name: 'World clock', description: 'Check time by timezone.', provider: 'frogbot' },
    { id: 'task_list', name: 'Task tracker', description: 'Keep a live checklist during longer work.', provider: 'stan' },
    { id: 'delegate', name: 'Focused delegate', description: 'Hand a focused subtask to a fresh agent.', provider: 'stan' },
    { id: 'code_interpreter', name: 'Code interpreter', description: 'Run code in an isolated AgentCore sandbox.', provider: 'agentcore' },
    { id: 'browser', name: 'Interactive browser', description: 'Navigate and interact with websites.', provider: 'agentcore' },
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
    ? [...(group?.bots ?? [])].sort((left, right) => left.name.localeCompare(right.name))
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
