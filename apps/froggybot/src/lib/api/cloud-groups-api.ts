import { apiRoutes } from '../api-routes';
import type { Group } from '../types';

import type { ApiRequest } from './cloud-transport';
import type { MessagePage } from './conversations-api';
import type { GroupsApi } from './groups-api';

export const createCloudGroupsApi = (request: ApiRequest): GroupsApi => ({
  groupMessages: (groupId, cursor) => request<MessagePage>(apiRoutes.groupMessages(groupId, cursor)),
  saveGroup: (draft, groupId) => request<Group>(groupId ? apiRoutes.group(groupId) : apiRoutes.groups, {
    method: groupId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }),
  deleteGroup: async (groupId) => {
    await request(apiRoutes.group(groupId), { method: 'DELETE' });
  },
  sendGroupMessage: async (groupId, text, replyBotId, attachmentIds = []) => {
    await request(apiRoutes.groupMessages(groupId), {
      method: 'POST',
      body: JSON.stringify({ text, replyBotId, attachmentIds }),
    });
  },
  shareGroup: (groupId) => request<{ url: string }>(
    apiRoutes.groupInvites(groupId),
    { method: 'POST' },
  ).then((value) => value.url),
  joinGroup: (token) => request<Group>(apiRoutes.joinGroup(token), { method: 'POST' }),
  removeGroupMember: async (groupId, memberId) => {
    await request(apiRoutes.groupMember(groupId, memberId), { method: 'DELETE' });
  },
  saveGroupDecision: (groupId, messageId) => request(apiRoutes.groupDecisions(groupId), {
    method: 'POST',
    body: JSON.stringify({ messageId }),
  }),
  deleteGroupDecision: async (groupId, decisionId) => {
    await request(apiRoutes.groupDecision(groupId, decisionId), { method: 'DELETE' });
  },
});
