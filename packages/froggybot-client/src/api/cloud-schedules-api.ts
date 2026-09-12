import type { ScheduleRun, ScheduledTask, SchedulesApi } from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';

import type { ApiRequest } from './cloud-transport';

export const createCloudSchedulesApi = (request: ApiRequest): SchedulesApi => ({
  schedules: (botId) => request<{ schedules: ScheduledTask[] }>(
    apiRoutes.botSchedules(botId),
  ).then((value) => value.schedules),
  saveSchedule: (botId, draft, scheduleId) => request<ScheduledTask>(
    scheduleId ? apiRoutes.botSchedule(botId, scheduleId) : apiRoutes.botSchedules(botId),
    { method: scheduleId ? 'PUT' : 'POST', body: JSON.stringify(draft) },
  ),
  deleteSchedule: async (botId, scheduleId) => {
    await request(apiRoutes.botSchedule(botId, scheduleId), { method: 'DELETE' });
  },
  runSchedule: async (botId, scheduleId) => {
    await request(apiRoutes.botScheduleRun(botId, scheduleId), { method: 'POST' });
  },
  scheduleRuns: (botId) => request<{ runs: ScheduleRun[] }>(
    apiRoutes.botScheduleRuns(botId),
  ).then((value) => value.runs),
  groupSchedules: (groupId) => request<{ schedules: ScheduledTask[] }>(
    apiRoutes.groupSchedules(groupId),
  ).then((value) => value.schedules),
  saveGroupSchedule: (groupId, draft, scheduleId) => request<ScheduledTask>(
    scheduleId ? apiRoutes.groupSchedule(groupId, scheduleId) : apiRoutes.groupSchedules(groupId),
    { method: scheduleId ? 'PUT' : 'POST', body: JSON.stringify(draft) },
  ),
  deleteGroupSchedule: async (groupId, scheduleId) => {
    await request(apiRoutes.groupSchedule(groupId, scheduleId), { method: 'DELETE' });
  },
  runGroupSchedule: async (groupId, scheduleId) => {
    await request(apiRoutes.groupScheduleRun(groupId, scheduleId), { method: 'POST' });
  },
  groupScheduleRuns: (groupId) => request<{ runs: ScheduleRun[] }>(
    apiRoutes.groupScheduleRuns(groupId),
  ).then((value) => value.runs),
});
