import type { ScheduleRun, ScheduledTask, ScheduledTaskDraft } from '../types';

export interface SchedulesApi {
  schedules(botId: string): Promise<ScheduledTask[]>;
  saveSchedule(botId: string, draft: ScheduledTaskDraft, scheduleId?: string): Promise<ScheduledTask>;
  deleteSchedule(botId: string, scheduleId: string): Promise<void>;
  runSchedule(botId: string, scheduleId: string): Promise<void>;
  scheduleRuns(botId: string): Promise<ScheduleRun[]>;
  groupSchedules(groupId: string): Promise<ScheduledTask[]>;
  saveGroupSchedule(
    groupId: string,
    draft: ScheduledTaskDraft,
    scheduleId?: string,
  ): Promise<ScheduledTask>;
  deleteGroupSchedule(groupId: string, scheduleId: string): Promise<void>;
  runGroupSchedule(groupId: string, scheduleId: string): Promise<void>;
  groupScheduleRuns(groupId: string): Promise<ScheduleRun[]>;
}
