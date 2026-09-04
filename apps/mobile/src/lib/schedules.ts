import type { ScheduledTask, ScheduledTaskDraft } from './types';

export const WEEKDAYS = [
  { value: 'MON', short: 'Mon', label: 'Monday' },
  { value: 'TUE', short: 'Tue', label: 'Tuesday' },
  { value: 'WED', short: 'Wed', label: 'Wednesday' },
  { value: 'THU', short: 'Thu', label: 'Thursday' },
  { value: 'FRI', short: 'Fri', label: 'Friday' },
  { value: 'SAT', short: 'Sat', label: 'Saturday' },
  { value: 'SUN', short: 'Sun', label: 'Sunday' },
] as const;

export const deviceTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export const parseTimeInput = (value: string): string | undefined => {
  const match = value.trim().toLowerCase().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
  if (!match) return undefined;
  let hour = Number(match[1]);
  const minute = Number(match[2] ?? '0');
  const meridiem = match[3];
  if (minute > 59) return undefined;
  if (meridiem) {
    if (hour < 1 || hour > 12) return undefined;
    if (meridiem === 'am') hour = hour === 12 ? 0 : hour;
    if (meridiem === 'pm') hour = hour === 12 ? 12 : hour + 12;
  } else if (hour > 23) {
    return undefined;
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
};

export const formatTime = (value: string): string => {
  const [hourValue, minute = '00'] = value.split(':');
  const hour = Number(hourValue);
  if (!Number.isFinite(hour)) return value;
  const meridiem = hour >= 12 ? 'PM' : 'AM';
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute} ${meridiem}`;
};

export const describeSchedule = (task: Pick<ScheduledTaskDraft, 'frequency' | 'dayOfWeek' | 'time'>) => {
  const time = formatTime(task.time);
  if (task.frequency === 'daily') return `Every day at ${time}`;
  const day = WEEKDAYS.find((item) => item.value === task.dayOfWeek)?.label ?? 'Monday';
  return `Every ${day} at ${time}`;
};

export const latestRunLabel = (task: ScheduledTask): string | undefined => {
  if (!task.lastRunAt || !task.lastStatus) return undefined;
  const label = task.lastStatus === 'complete' ? 'Finished' : task.lastStatus === 'pending' ? 'Running' : 'Needs attention';
  const date = new Date(task.lastRunAt);
  const when = Number.isNaN(date.getTime()) ? undefined : date.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  return when ? `${label} ${when}` : label;
};
