import type { AppConstraints, Bot, Group, GroupDecision, GroupMember, Message } from '@froggybot/contracts';

export const demoConstraints: AppConstraints = {
  botNameMaxLength: 48,
  botTaglineMaxLength: 120,
  botPromptMaxLength: 12_000,
  groupNameMaxLength: 64,
  groupMemoryMaxLength: 4_000,
  messageMaxLength: 8_000,
  scheduleNameMaxLength: 64,
  schedulePromptMaxLength: 8_000,
  scheduleDayOfMonthMin: 1,
  scheduleDayOfMonthMax: 28,
  skillNameMaxLength: 80,
  skillDescriptionMaxLength: 240,
  skillInstructionsMaxLength: 20_000,
  memoryMaxLength: 16_000,
  maxAttachmentsPerMessage: 5,
  imageMaxBytes: 3_750_000,
  documentMaxBytes: 4_500_000,
  maxPhotoDimension: 1_920,
};

export const withDemoBotActions = (bot: Bot): Bot => ({
  ...bot,
  allowedActions: ['edit', 'documents', 'browser', 'schedule', 'share', 'clear', ...(bot.systemRole === 'chief' ? [] : ['delete'] as const)],
});

const withDemoMemberActions = (member: GroupMember, isOwner: boolean): GroupMember => ({
  ...member,
  allowedActions: isOwner && member.role !== 'owner' ? ['remove'] : !isOwner && member.id === 'demo-user' ? ['leave'] : [],
});

export const withDemoDecisionActions = (decision: GroupDecision): GroupDecision => ({
  ...decision,
  allowedActions: ['remove'],
});

export const withDemoGroupActions = (group: Group): Group => ({
  ...group,
  allowedActions: group.isOwner
    ? ['edit', 'share', 'schedule', 'delete', 'manageMemory']
    : ['view', 'viewMemory'],
  members: group.members.map((member) => withDemoMemberActions(member, group.isOwner)),
  decisions: group.decisions.map(withDemoDecisionActions),
});

export const withDemoMessageActions = (message: Message, savedDecisionIds: Set<string>): Message => ({
  ...message,
  allowedActions: message.authorType === 'bot'
    && message.status === 'complete'
    && (message.roundRole === 'solo' || message.roundRole === 'synthesizer')
    && !savedDecisionIds.has(message.id)
    ? ['saveDecision']
    : [],
});
