import type { Message } from './types';

const ACTIVE_STATUSES = new Set<Message['status']>([
  'waiting',
  'pending',
  'running',
  'needs_input',
  'awaiting_approval',
]);

const clockFormatter = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
});

const parseTime = (value?: string): number | undefined => {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

export const formatElapsed = (durationMs: number): string => {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 1) return `${seconds}s`;
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m ${seconds}s`;
};

const activeLabel = (status: Message['status']): string => {
  if (status === 'pending') return 'Queued';
  if (status === 'waiting') return 'Waiting';
  if (status === 'awaiting_approval') return 'Waiting for approval';
  if (status === 'needs_input') return 'Waiting for input';
  return 'Running';
};

export const messageTimingLabel = (
  message: Message,
  now = Date.now(),
  formatClock = (date: Date) => clockFormatter.format(date),
): string => {
  const started = parseTime(message.startedAt ?? message.createdAt);
  if (started === undefined) return '';
  const clock = formatClock(new Date(started));
  if (message.role === 'user' && message.authorType !== 'bot') return `Sent ${clock}`;
  const completed = parseTime(message.completedAt);
  const active = ACTIVE_STATUSES.has(message.status);
  const elapsed = completed === undefined && !active ? undefined : (completed ?? now) - started;
  if (elapsed === undefined) return `Started ${clock}`;
  const label = active
    ? activeLabel(message.status)
    : message.status === 'cancelled'
      ? 'Stopped after'
      : message.status === 'error'
        ? 'Failed after'
        : 'Ran';
  const timing = `Started ${clock} · ${label} ${formatElapsed(elapsed)}`;
  const activityUpdated = parseTime(message.activityUpdatedAt);
  if (!active || activityUpdated === undefined) return timing;
  const sinceUpdate = Math.max(0, now - activityUpdated);
  return `${timing} · ${sinceUpdate < 5_000 ? 'Updated just now' : `Updated ${formatElapsed(sinceUpdate)} ago`}`;
};
