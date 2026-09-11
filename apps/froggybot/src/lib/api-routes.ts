const segment = (value: string): string => encodeURIComponent(value);
const withCursor = (path: string, cursor?: string): string =>
  cursor ? `${path}?cursor=${segment(cursor)}` : path;

export const apiRoutes = {
  account: '/account',
  bootstrap: '/bootstrap',
  bot: (botId: string) => `/bots/${segment(botId)}`,
  bots: '/bots',
  botDocuments: (botId: string) => `/bots/${segment(botId)}/documents`,
  botMessages: (botId: string, cursor?: string) => withCursor(`/bots/${segment(botId)}/messages`, cursor),
  botMessageAction: (botId: string, turnId: string, action: 'approve' | 'cancel') =>
    `/bots/${segment(botId)}/messages/${segment(turnId)}/${action}`,
  botSchedules: (botId: string) => `/bots/${segment(botId)}/schedules`,
  botSchedule: (botId: string, scheduleId: string) =>
    `/bots/${segment(botId)}/schedules/${segment(scheduleId)}`,
  botScheduleRun: (botId: string, scheduleId: string) =>
    `/bots/${segment(botId)}/schedules/${segment(scheduleId)}/run`,
  botScheduleRuns: (botId: string) => `/bots/${segment(botId)}/runs`,
  botTemplateInstall: (templateId: string) => `/bot-templates/${segment(templateId)}/install`,
  connection: (connectionId: string) => `/connections/${segment(connectionId)}`,
  connections: '/connections',
  gmailAuthorization: '/connections/gmail/authorization',
  devicePushToken: '/devices/push-token',
  fileDownload: (fileId: string) => `/files/${segment(fileId)}/download`,
  group: (groupId: string) => `/groups/${segment(groupId)}`,
  groups: '/groups',
  groupSchedules: (groupId: string) => `/groups/${segment(groupId)}/schedules`,
  groupSchedule: (groupId: string, scheduleId: string) => `/groups/${segment(groupId)}/schedules/${segment(scheduleId)}`,
  groupScheduleRun: (groupId: string, scheduleId: string) => `/groups/${segment(groupId)}/schedules/${segment(scheduleId)}/run`,
  groupScheduleRuns: (groupId: string) => `/groups/${segment(groupId)}/runs`,
  groupFileDownload: (groupId: string, fileId: string) =>
    `/groups/${segment(groupId)}/files/${segment(fileId)}/download`,
  groupInvites: (groupId: string) => `/groups/${segment(groupId)}/invites`,
  groupMember: (groupId: string, memberId: string) =>
    `/groups/${segment(groupId)}/members/${segment(memberId)}`,
  groupMessages: (groupId: string, cursor?: string) => withCursor(`/groups/${segment(groupId)}/messages`, cursor),
  groupDecisions: (groupId: string) => `/groups/${segment(groupId)}/decisions`,
  groupDecision: (groupId: string, decisionId: string) =>
    `/groups/${segment(groupId)}/decisions/${segment(decisionId)}`,
  groupMemory: (groupId: string) => `/groups/${segment(groupId)}/memory`,
  groupMemoryRecord: (groupId: string, recordId: string) =>
    `/groups/${segment(groupId)}/memory/${segment(recordId)}`,
  joinGroup: (token: string) => `/group-invites/${segment(token)}/join`,
  memory: '/memory',
  memoryExport: '/memory/export',
  memoryRecord: (recordId: string) => `/memory/${segment(recordId)}`,
  publicInvite: (kind: string, token: string) =>
    `/public/invites/${segment(kind)}/${segment(token)}`,
  share: (token: string) => `/shares/${segment(token)}`,
  shareImport: (token: string) => `/shares/${segment(token)}/import`,
  shares: '/shares',
  skill: (skillId: string) => `/skills/${segment(skillId)}`,
  skillShare: (skillId: string) => `/skills/${segment(skillId)}/share`,
  skillShareImport: (token: string) => `/skill-shares/${segment(token)}/import`,
  skills: '/skills',
  upload: (fileId: string) => `/uploads/${segment(fileId)}/complete`,
  uploads: '/uploads',
} as const;
