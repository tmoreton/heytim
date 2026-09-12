import type { Group, GroupDecision, GroupsApi, MessagePage } from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';

import type { ApiRequest } from './cloud-transport';
import { decodeGroup, decodeGroupDecision, decodeMessagePage } from '../response-contract.ts';

export const createCloudGroupsApi = (request: ApiRequest): GroupsApi => ({
  groupMessages: (groupId, cursor) => request<MessagePage>(apiRoutes.groupMessages(groupId, cursor), undefined, undefined, decodeMessagePage),
  saveGroup: (draft, groupId) => request<Group>(groupId ? apiRoutes.group(groupId) : apiRoutes.groups, {
    method: groupId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }, undefined, decodeGroup),
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
  joinGroup: (token) => request<Group>(apiRoutes.joinGroup(token), { method: 'POST' }, undefined, decodeGroup),
  removeGroupMember: async (groupId, memberId) => {
    await request(apiRoutes.groupMember(groupId, memberId), { method: 'DELETE' });
  },
  saveGroupDecision: (groupId, messageId) => request<GroupDecision>(apiRoutes.groupDecisions(groupId), {
    method: 'POST',
    body: JSON.stringify({ messageId }),
  }, undefined, decodeGroupDecision),
  deleteGroupDecision: async (groupId, decisionId) => {
    await request(apiRoutes.groupDecision(groupId, decisionId), { method: 'DELETE' });
  },
});
