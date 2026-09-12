import type {
  AccountApi,
  Bot,
  InvitePreview,
  MemoryRecord,
  MemorySnapshot,
  SharedLink,
  SkillDetail,
} from '@froggybot/contracts';
import { apiRoutes } from '@froggybot/contracts';

import type { ApiRequest, PublicApiRequest } from './cloud-transport';

export const createCloudAccountApi = (
  request: ApiRequest,
  publicRequest: PublicApiRequest,
): AccountApi => ({
  invitePreview: async ({ kind, token }) =>
    publicRequest<Omit<InvitePreview, 'token'>>(apiRoutes.publicInvite(kind, token))
      .then((value) => ({ ...value, token })),
  registerPushToken: async (token) => {
    await request(apiRoutes.devicePushToken, { method: 'PUT', body: JSON.stringify({ token }) });
  },
  unregisterPushToken: async (token) => {
    await request(apiRoutes.devicePushToken, { method: 'DELETE', body: JSON.stringify({ token }) });
  },
  sharedLinks: () => request<{ shares: SharedLink[] }>(apiRoutes.shares).then((value) => value.shares),
  memories: () => request<MemorySnapshot>(apiRoutes.memory),
  createMemory: (kind, content) => request<MemoryRecord>(apiRoutes.memory, {
    method: 'POST',
    body: JSON.stringify({ kind, content }),
  }),
  updateMemory: (recordId, content) => request<MemoryRecord>(apiRoutes.memoryRecord(recordId), {
    method: 'PUT',
    body: JSON.stringify({ content }),
  }),
  deleteMemory: async (recordId) => {
    await request(apiRoutes.memoryRecord(recordId), { method: 'DELETE' });
  },
  exportMemory: () => request<{ url: string }>(
    apiRoutes.memoryExport,
    { method: 'POST' },
  ).then((value) => value.url),
  groupMemories: (groupId) => request<MemorySnapshot>(apiRoutes.groupMemory(groupId)),
  createGroupMemory: (groupId, content) => request<MemoryRecord>(apiRoutes.groupMemory(groupId), {
    method: 'POST',
    body: JSON.stringify({ content }),
  }),
  updateGroupMemory: (groupId, recordId, content) => request<MemoryRecord>(
    apiRoutes.groupMemoryRecord(groupId, recordId),
    { method: 'PUT', body: JSON.stringify({ content }) },
  ),
  deleteGroupMemory: async (groupId, recordId) => {
    await request(apiRoutes.groupMemoryRecord(groupId, recordId), { method: 'DELETE' });
  },
  revokeShare: async (token) => {
    await request(apiRoutes.share(token), { method: 'DELETE' });
  },
  deleteAccount: async () => {
    await request(apiRoutes.account, { method: 'DELETE' });
  },
  share: (botId, scope) => request<{ url: string }>(apiRoutes.shares, {
    method: 'POST',
    body: JSON.stringify({ botId, scope }),
  }).then((value) => value.url),
  importShare: (token) => request<Bot>(apiRoutes.shareImport(token), { method: 'POST' }),
  skill: (skillId) => request<SkillDetail>(apiRoutes.skill(skillId)),
  saveSkill: (draft, skillId) => request<SkillDetail>(skillId ? apiRoutes.skill(skillId) : apiRoutes.skills, {
    method: skillId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }),
  shareSkill: (skillId) => request<{ url: string }>(
    apiRoutes.skillShare(skillId),
    { method: 'POST' },
  ).then((value) => value.url),
  importSkill: (token) => request<SkillDetail>(apiRoutes.skillShareImport(token), { method: 'POST' }),
  beginConnection: (providerId, returnUrl) => request<{ authorizationUrl: string }>(
    apiRoutes.connectionAuthorization(providerId),
    { method: 'POST', body: JSON.stringify({ returnUrl }) },
  ).then((value) => value.authorizationUrl),
  deleteConnection: async (connectionId) => {
    await request(apiRoutes.connection(connectionId), { method: 'DELETE' });
  },
});
