import { fetchAuthSession } from 'aws-amplify/auth';

import type { FrogBotApi } from './api';
import { apiRoutes } from './api-routes';
import { apiUrl } from './cloud';
import type {
  Attachment,
  Bot,
  BotDocument,
  Connection,
  Group,
  InvitePreview,
  MemoryRecord,
  MemorySnapshot,
  Message,
  ScheduledTask,
  SharedLink,
  SkillDetail,
} from './types';

const responseBody = async (response: Response): Promise<Record<string, unknown>> => {
  const text = await response.text();
  if (!text) return {};
  try {
    const value: unknown = JSON.parse(text);
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  } catch {
    if (!response.ok) throw new Error(`The service returned an invalid response (${response.status}).`);
    throw new Error('The service returned an invalid response.');
  }
};

const responseError = (body: Record<string, unknown>, fallback: string) =>
  typeof body.message === 'string' ? body.message : fallback;

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) throw new Error('Your session expired. Please sign in again.');

  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      'content-type': 'application/json',
      ...init?.headers,
    },
  });
  const body = await responseBody(response);
  if (!response.ok) throw new Error(responseError(body, `The request failed (${response.status}).`));
  return body as T;
};

const publicRequest = async <T>(path: string): Promise<T> => {
  const response = await fetch(`${apiUrl}${path}`);
  const body = await responseBody(response);
  if (!response.ok) throw new Error(responseError(body, 'The invite could not be opened.'));
  return body as T;
};

export const createCloudApi = (): FrogBotApi => ({
  invitePreview: async ({ kind, token }) =>
    publicRequest<Omit<InvitePreview, 'token'>>(apiRoutes.publicInvite(kind, token))
      .then((value) => ({ ...value, token })),
  bootstrap: () => request(apiRoutes.bootstrap),
  installBotTemplate: (templateId) => request<Bot>(apiRoutes.botTemplateInstall(templateId), { method: 'POST' }),
  messages: (botId) => request<{ messages: Message[] }>(apiRoutes.botMessages(botId)).then((value) => value.messages),
  botDocuments: (botId) => request<{ documents: BotDocument[] }>(apiRoutes.botDocuments(botId)).then((value) => value.documents),
  saveBot: (draft, botId) => request<Bot>(botId ? apiRoutes.bot(botId) : apiRoutes.bots, {
    method: botId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }),
  clearBotChat: async (botId) => { await request(apiRoutes.botMessages(botId), { method: 'DELETE' }); },
  deleteBot: async (botId) => { await request(apiRoutes.bot(botId), { method: 'DELETE' }); },
  uploadAttachment: async (asset) => {
    const ticket = await request<{
      file: Attachment;
      upload: { url: string; fields: Record<string, string> };
    }>(apiRoutes.uploads, {
      method: 'POST',
      body: JSON.stringify({ filename: asset.name, size: asset.size }),
    });
    const form = new FormData();
    Object.entries(ticket.upload.fields).forEach(([key, value]) => form.append(key, value));
    if (asset.file) {
      form.append('file', asset.file, asset.name);
    } else {
      form.append('file', {
        uri: asset.uri,
        name: asset.name,
        type: ticket.file.contentType,
      } as unknown as Blob);
    }
    const uploaded = await fetch(ticket.upload.url, { method: 'POST', body: form });
    if (!uploaded.ok) throw new Error(`The file upload failed (${uploaded.status}).`);
    return request<Attachment>(apiRoutes.upload(ticket.file.id), { method: 'POST' });
  },
  downloadFile: (fileId, groupId) => request<{ url: string }>(
    groupId ? apiRoutes.groupFileDownload(groupId, fileId) : apiRoutes.fileDownload(fileId),
  ).then((value) => value.url),
  sendMessage: async (bot, text, attachmentIds = []) => {
    await request(apiRoutes.botMessages(bot.id), {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    });
  },
  cancelMessage: async (botId, turnId) => {
    await request(apiRoutes.botMessageAction(botId, turnId, 'cancel'), { method: 'POST' });
  },
  approveMessage: async (botId, turnId, always = false) => {
    await request(apiRoutes.botMessageAction(botId, turnId, 'approve'), {
      method: 'POST',
      body: JSON.stringify({ always }),
    });
  },
  schedules: (botId) => request<{ schedules: ScheduledTask[] }>(apiRoutes.botSchedules(botId)).then((value) => value.schedules),
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
  groupMessages: (groupId) => request<{ messages: Message[] }>(apiRoutes.groupMessages(groupId)).then((value) => value.messages),
  saveGroup: (draft, groupId) => request<Group>(groupId ? apiRoutes.group(groupId) : apiRoutes.groups, {
    method: groupId ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  }),
  deleteGroup: async (groupId) => { await request(apiRoutes.group(groupId), { method: 'DELETE' }); },
  sendGroupMessage: async (groupId, text, replyBotId) => {
    await request(apiRoutes.groupMessages(groupId), {
      method: 'POST',
      body: JSON.stringify({ text, replyBotId }),
    });
  },
  shareGroup: (groupId) => request<{ url: string }>(apiRoutes.groupInvites(groupId), { method: 'POST' }).then((value) => value.url),
  joinGroup: (token) => request<Group>(apiRoutes.joinGroup(token), { method: 'POST' }),
  removeGroupMember: async (groupId, memberId) => {
    await request(apiRoutes.groupMember(groupId, memberId), { method: 'DELETE' });
  },
  registerPushToken: async (token) => {
    await request(apiRoutes.devicePushToken, { method: 'PUT', body: JSON.stringify({ token }) });
  },
  unregisterPushToken: async (token) => {
    await request(apiRoutes.devicePushToken, { method: 'DELETE', body: JSON.stringify({ token }) });
  },
  sharedLinks: () => request<{ shares: SharedLink[] }>(apiRoutes.shares).then((value) => value.shares),
  memories: () => request<MemorySnapshot>(apiRoutes.memory),
  updateMemory: (recordId, content) => request<MemoryRecord>(apiRoutes.memoryRecord(recordId), {
    method: 'PUT',
    body: JSON.stringify({ content }),
  }),
  deleteMemory: async (recordId) => { await request(apiRoutes.memoryRecord(recordId), { method: 'DELETE' }); },
  exportMemory: () => request<{ url: string }>(apiRoutes.memoryExport, { method: 'POST' }).then((value) => value.url),
  revokeShare: async (token) => { await request(apiRoutes.share(token), { method: 'DELETE' }); },
  deleteAccount: async () => { await request(apiRoutes.account, { method: 'DELETE' }); },
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
  shareSkill: (skillId) => request<{ url: string }>(apiRoutes.skillShare(skillId), { method: 'POST' }).then((value) => value.url),
  importSkill: (token) => request<SkillDetail>(apiRoutes.skillShareImport(token), { method: 'POST' }),
  saveConnection: (draft, connectionId) => request<Connection>(
    connectionId ? apiRoutes.connection(connectionId) : apiRoutes.connections,
    { method: connectionId ? 'PUT' : 'POST', body: JSON.stringify(draft) },
  ),
  beginGmailConnection: (returnUrl) => request<{ authorizationUrl: string }>(apiRoutes.gmailAuthorization, {
    method: 'POST',
    body: JSON.stringify({ returnUrl }),
  }).then((value) => value.authorizationUrl),
  deleteConnection: async (connectionId) => {
    await request(apiRoutes.connection(connectionId), { method: 'DELETE' });
  },
});
