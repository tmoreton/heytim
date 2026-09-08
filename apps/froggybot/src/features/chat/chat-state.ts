import type { Bootstrap, ConversationSelection, Message } from '@/lib/types';

const REFRESHING_STATUSES = new Set<Message['status']>(['pending', 'running', 'waiting']);
const PENDING_STATUSES = new Set<Message['status']>([
  ...REFRESHING_STATUSES,
  'needs_input',
  'awaiting_approval',
]);
const ACTIVE_RESPONSE_STATUSES = new Set<Message['status']>(['pending', 'running']);

export const isRefreshingMessage = (message: Message): boolean =>
  REFRESHING_STATUSES.has(message.status);

export const isPendingMessage = (message: Message): boolean =>
  PENDING_STATUSES.has(message.status);

export const isActiveResponse = (message: Message): boolean =>
  ACTIVE_RESPONSE_STATUSES.has(message.status);

export function chooseAvailableSelection(
  next: Bootstrap,
  current?: ConversationSelection,
): ConversationSelection | undefined {
  if (current?.kind === 'bot' && next.bots.some((bot) => bot.id === current.id)) return current;
  if (current?.kind === 'group' && next.groups.some((group) => group.id === current.id)) return current;
  if (next.groups[0]) return { kind: 'group', id: next.groups[0].id };
  if (next.bots[0]) return { kind: 'bot', id: next.bots[0].id };
  return undefined;
}
