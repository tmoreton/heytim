import type { Attachment, Bot, Group, GroupDraft, Message } from '../types';

import { cloneGroup, demoState } from './demo-state';

export const demoGroupMessages = (groupId: string): Message[] => [
  ...(demoState.groupMessages.get(groupId) ?? []),
];

export const demoDeleteGroup = (groupId: string): void => {
  demoState.groups = demoState.groups.filter((group) => group.id !== groupId);
  demoState.groupMessages.delete(groupId);
};

export const demoSaveGroup = (draft: GroupDraft, groupId?: string): Group => {
  const now = new Date().toISOString();
  const previous = demoState.groups.find((group) => group.id === groupId);
  const selectedBots = draft.botIds
    .map((id) => demoState.bots.find((bot) => bot.id === id))
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
  demoState.groups = previous
    ? demoState.groups.map((item) => (item.id === group.id ? group : item))
    : [group, ...demoState.groups];
  if (!demoState.groupMessages.has(group.id)) demoState.groupMessages.set(group.id, []);
  return group;
};

export const demoJoinGroup = (_token: string): Group => cloneGroup(demoState.groups[0]);

export const demoSendGroup = (
  groupId: string,
  text: string,
  replyBotId?: string,
  attachmentIds: string[] = [],
): void => {
  const current = demoState.groupMessages.get(groupId) ?? [];
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
      .map((id) => demoState.uploadedAttachments.get(id))
      .filter((attachment): attachment is Attachment => Boolean(attachment))
      .map((attachment) => ({ ...attachment })),
    createdAt: new Date().toISOString(),
    status: 'complete',
  });
  const group = demoState.groups.find((item) => item.id === groupId);
  const selectedBots = replyBotId === 'all'
    ? [...(group?.bots ?? [])].sort((left, right) =>
        Number(right.systemRole === 'chief') - Number(left.systemRole === 'chief')
          || left.name.localeCompare(right.name),
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
  demoState.groupMessages.set(groupId, current);
  demoState.groups = demoState.groups.map((item) =>
    item.id === groupId
      ? { ...item, lastMessage: text, lastMessageAt: new Date().toISOString() }
      : item,
  );
  roundBots.forEach((bot, index) => {
    setTimeout(() => completeBotRound(groupId, requestId, bot, index, roundBots.length), 800 + index * 800);
  });
};

type RoundBot = Group['bots'][number] & {
  roundRole: 'solo' | 'lead' | 'contributor' | 'synthesizer';
};

const roundAnswer = (bot: RoundBot): string => {
  if (bot.roundRole === 'lead') {
    return `I’m coordinating around the room’s fixed constraints: **under $1,200**, no driving, a walkable destination, vegetarian food, and a Sunday return before 6 PM. Research will verify the travel and price assumptions; Trip Planner will turn the best option into a usable itinerary.`;
  }
  if (bot.roundRole === 'contributor' && bot.id === 'research-reports') {
    return `**Evidence check**\n\nPortland, Maine is the strongest fit. The Boston–Portland train is roughly 2½ hours, the Old Port is walkable, and a central one-night stay can fit the budget. Providence is cheaper but feels less like a getaway; New York creates more travel time and budget pressure.`;
  }
  if (bot.roundRole === 'contributor') {
    return `**Practical plan**\n\nTake the 8:50 AM train Saturday, leave bags near the Old Port, and keep the day walkable. Book dinner around 7 PM with a vegetarian-first shortlist. On Sunday, use a late-morning lighthouse cruise or waterfront walk, then take the early-afternoon train home to preserve the 6 PM buffer.`;
  }
  if (bot.roundRole === 'synthesizer') {
    return `**Decision: Portland, Maine**\n\nIt best satisfies the group’s travel-time, walkability, food, and budget constraints.\n\n**Working budget**\n- Train: $180–240\n- Central hotel: $320–420\n- Food: $220\n- Activities and local transport: $120\n- Buffer: $150\n\n**Next steps**\n1. You: confirm the Saturday train by Tuesday.\n2. Jordan: choose between the two dinner options.\n3. Chief: keep the itinerary current after bookings.\n\nI created **portland-weekend-plan.pdf** so the group can use the final itinerary outside this chat.`;
  }
  return `I’ll handle this from my role: ${bot.tagline}`;
};

const completeBotRound = (
  groupId: string,
  requestId: string,
  bot: RoundBot,
  index: number,
  roundSize: number,
): void => {
  const answer = roundAnswer(bot);
  demoState.groupMessages.set(
    groupId,
    (demoState.groupMessages.get(groupId) ?? []).map((message) =>
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
        : message.id === `${requestId}-assistant-${index + 1}`
            && index + 1 < roundSize
            && message.status === 'waiting'
          ? { ...message, status: 'pending' }
          : message,
    ),
  );
  demoState.groups = demoState.groups.map((item) =>
    item.id === groupId
      ? { ...item, lastMessage: answer, lastMessageAt: new Date().toISOString() }
      : item,
  );
};
