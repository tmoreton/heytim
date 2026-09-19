import { apiContractPaths } from './api-contract.generated.ts';

const segment = (value: string): string => encodeURIComponent(value);
const withCursor = (path: string, cursor?: string): string =>
  cursor ? `${path}?cursor=${segment(cursor)}` : path;

const contractPath = (
  id: keyof typeof apiContractPaths,
  params: Record<string, string> = {},
): string => {
  const template = apiContractPaths[id];
  if (!template) throw new Error(`Unknown API route: ${id}`);
  const path = template.replace(/\{([^}]+)\}/g, (_match, name: string) => {
    const value = params[name];
    if (value === undefined) throw new Error(`Missing ${name} for API route ${id}`);
    return segment(value);
  });
  if (path.includes('{')) throw new Error(`Incomplete API route: ${id}`);
  return path;
};

export const apiRoutes = {
  account: contractPath('accountDelete'),
  bootstrap: contractPath('bootstrap'),
  bot: (botId: string) => contractPath('botUpdate', { botId }),
  bots: contractPath('botCreate'),
  botDocuments: (botId: string) => contractPath('botDocuments', { botId }),
  botMessages: (botId: string, cursor?: string) =>
    withCursor(contractPath('botMessagesList', { botId }), cursor),
  botMessageAction: (botId: string, turnId: string, action: 'approve' | 'cancel') => contractPath(
    action === 'approve' ? 'botMessageApprove' : 'botMessageCancel',
    { botId, turnId },
  ),
  botSchedules: (botId: string) => contractPath('botSchedulesList', { botId }),
  botSchedule: (botId: string, scheduleId: string) =>
    contractPath('botScheduleUpdate', { botId, scheduleId }),
  botScheduleRun: (botId: string, scheduleId: string) =>
    contractPath('botScheduleRun', { botId, scheduleId }),
  botScheduleRuns: (botId: string) => contractPath('botScheduleRuns', { botId }),
  botTemplateInstall: (templateId: string) => contractPath('botTemplateInstall', { templateId }),
  browserStatus: (botId: string) => contractPath('browserStatus', { botId }),
  browserOpen: (botId: string) => contractPath('browserOpen', { botId }),
  browserResume: (botId: string) => contractPath('browserResume', { botId }),
  browserClose: (botId: string) => contractPath('browserClose', { botId }),
  browserProfile: (botId: string) => contractPath('browserProfileDelete', { botId }),
  connection: (connectionId: string) => contractPath('connectionDelete', { connectionId }),
  connectionAuthorization: (providerId: string) => contractPath('connectionAuthorize', { providerId }),
  connections: contractPath('connectionsList'),
  devicePushToken: contractPath('pushTokenPut'),
  fileDownload: (fileId: string) => contractPath('fileDownload', { fileId }),
  group: (groupId: string) => contractPath('groupUpdate', { groupId }),
  groups: contractPath('groupCreate'),
  groupSchedules: (groupId: string) => contractPath('groupSchedulesList', { groupId }),
  groupSchedule: (groupId: string, scheduleId: string) =>
    contractPath('groupScheduleUpdate', { groupId, scheduleId }),
  groupScheduleRun: (groupId: string, scheduleId: string) =>
    contractPath('groupScheduleRun', { groupId, scheduleId }),
  groupScheduleRuns: (groupId: string) => contractPath('groupScheduleRuns', { groupId }),
  groupFileDownload: (groupId: string, fileId: string) =>
    contractPath('groupFileDownload', { groupId, fileId }),
  groupInvites: (groupId: string) => contractPath('groupInviteCreate', { groupId }),
  groupMember: (groupId: string, memberId: string) =>
    contractPath('groupMemberDelete', { groupId, memberId }),
  groupMessages: (groupId: string, cursor?: string) =>
    withCursor(contractPath('groupMessagesList', { groupId }), cursor),
  groupDecisions: (groupId: string) => contractPath('groupDecisionCreate', { groupId }),
  groupDecision: (groupId: string, decisionId: string) =>
    contractPath('groupDecisionDelete', { groupId, decisionId }),
  groupMemory: (groupId: string) => contractPath('groupMemoryList', { groupId }),
  groupMemoryRecord: (groupId: string, recordId: string) =>
    contractPath('groupMemoryUpdate', { groupId, memoryRecordId: recordId }),
  joinGroup: (token: string) => contractPath('groupInviteJoin', { token }),
  memory: contractPath('memoryList'),
  memoryExport: contractPath('memoryExport'),
  memoryRecord: (recordId: string) => contractPath('memoryUpdate', { memoryRecordId: recordId }),
  publicInvite: (kind: string, token: string) =>
    contractPath('publicInvite', { kind, token }),
  share: (token: string) => contractPath('shareDelete', { token }),
  shareImport: (token: string) => contractPath('shareImport', { token }),
  shares: contractPath('sharesList'),
  skill: (skillId: string) => contractPath('skillGet', { skillId }),
  skillShare: (skillId: string) => contractPath('skillShare', { skillId }),
  skillShareImport: (token: string) => contractPath('skillShareImport', { token }),
  skills: contractPath('skillCreate'),
  githubSkillsScan: contractPath('githubSkillsScan'),
  githubSkillPreview: contractPath('githubSkillPreview'),
  upload: (fileId: string) => contractPath('uploadComplete', { fileId }),
  uploads: contractPath('uploadCreate'),
} as const;
