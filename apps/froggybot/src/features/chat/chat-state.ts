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

function sameJsonValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false;
    return left.every((value, index) => sameJsonValue(value, right[index]));
  }
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const keys = Object.keys(leftRecord);
  if (keys.length !== Object.keys(rightRecord).length) return false;
  return keys.every((key) => Object.hasOwn(rightRecord, key) && sameJsonValue(leftRecord[key], rightRecord[key]));
}

export function reconcileMessages(current: Message[], next: Message[]): Message[] {
  if (current === next) return current;
  const previousById = new Map(current.map((message) => [message.id, message]));
  let changed = current.length !== next.length;
  const reconciled = next.map((message, index) => {
    const previous = previousById.get(message.id);
    if (!previous || !sameJsonValue(previous, message)) {
      changed = true;
      return message;
    }
    if (current[index] !== previous) changed = true;
    return previous;
  });
  return changed ? reconciled : current;
}

export function reconcileBootstrap(current: Bootstrap | undefined, next: Bootstrap): Bootstrap {
  return current && sameJsonValue(current, next) ? current : next;
}

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
