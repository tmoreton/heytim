import type { ScheduleRun, ScheduledTask, ScheduledTaskDraft } from '../types';

import { demoSend } from './demo-bots';
import { demoSendGroup } from './demo-groups';
import { demoState } from './demo-state';

export const demoListSchedules = async (botId: string): Promise<ScheduledTask[]> =>
  demoState.schedules.filter((task) => task.botId === botId).map((task) => ({ ...task }));

export const demoSaveSchedule = async (
  botId: string,
  draft: ScheduledTaskDraft,
  scheduleId?: string,
): Promise<ScheduledTask> => {
  const current = new Date().toISOString();
  const previous = demoState.schedules.find(
    (task) => task.id === scheduleId && task.botId === botId,
  );
  const task: ScheduledTask = {
    ...draft,
    id: previous?.id ?? `schedule-${Date.now()}`,
    botId,
    createdAt: previous?.createdAt ?? current,
    updatedAt: current,
    lastRunAt: previous?.lastRunAt,
    lastStatus: previous?.lastStatus,
  };
  demoState.schedules = previous
    ? demoState.schedules.map((item) => (item.id === task.id ? task : item))
    : [task, ...demoState.schedules];
  return { ...task };
};

export const demoDeleteSchedule = async (botId: string, scheduleId: string): Promise<void> => {
  demoState.schedules = demoState.schedules.filter(
    (task) => task.botId !== botId || task.id !== scheduleId,
  );
};

export const demoRunSchedule = async (botId: string, scheduleId: string): Promise<void> => {
  const task = demoState.schedules.find((item) => item.botId === botId && item.id === scheduleId);
  const bot = demoState.bots.find((item) => item.id === botId);
  const group = demoState.groups.find((item) => item.id === botId);
  if (!task || (!bot && !group)) throw new Error('Scheduled task not found.');
  const current = new Date().toISOString();
  demoState.schedules = demoState.schedules.map((item) =>
    item.id === task.id
      ? { ...item, lastRunAt: current, lastStatus: 'pending', updatedAt: current }
      : item,
  );
  const runId = `run-${Date.now()}`;
  demoState.scheduleRuns = [{
    id: runId,
    botId,
    scheduleId,
    scheduleName: task.name,
    prompt: task.prompt,
    status: 'pending',
    createdAt: current,
  }, ...demoState.scheduleRuns];
  if (bot) demoSend(bot, task.prompt, task);
  else if (group) demoSendGroup(group.id, task.prompt, 'all');
  setTimeout(() => {
    demoState.scheduleRuns = demoState.scheduleRuns.map((run) => run.id === runId ? {
      ...run,
      status: 'complete',
      completedAt: new Date().toISOString(),
      output: 'Today’s priorities are to confirm the owner, verify the deadline, and publish the smallest useful result.',
    } : run);
  }, 900);
};

export const demoScheduleRuns = async (botId: string): Promise<ScheduleRun[]> =>
  demoState.scheduleRuns.filter((run) => run.botId === botId).map((run) => ({ ...run }));
