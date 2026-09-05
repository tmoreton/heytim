import { fetchAuthSession } from 'aws-amplify/auth';

import { apiUrl } from './cloud';
import {
  demoBootstrap,
  demoClearBotChat,
  demoDeleteBot,
  demoDeleteGroup,
  demoGetSkill,
  demoImportSkill,
  demoJoinGroup,
  demoMessages,
  demoGroupMessages,
  demoSaveGroup,
  demoSaveBot,
  demoSaveSkill,
  demoDeleteSchedule,
  demoDeleteConnection,
  demoListSchedules,
  demoRunSchedule,
  demoSaveSchedule,
  demoSaveConnection,
  demoSend,
  demoSendGroup,
} from './demo';
import type {
  Attachment,
  Bootstrap,
  Bot,
  BotDraft,
  Connection,
  ConnectionDraft,
  Group,
  GroupDraft,
  Invitation,
  InvitePreview,
  Message,
  ScheduledTask,
  ScheduledTaskDraft,
  SharedLink,
  SkillDetail,
  SkillDraft,
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
    if (!response.ok) {
      throw new Error(`The service returned an invalid response (${response.status}).`);
    }
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

export const createApi = (demo: boolean) => ({
  invitePreview: async ({ kind, token }: Invitation): Promise<InvitePreview> => {
    if (demo) {
      const bootstrap = await demoBootstrap();
      return {
          kind,
          token,
          title: kind === 'group' ? 'Weekend builders' : 'A FroggyBot for you',
          description: 'Taylor invited you to bring people and FroggyBots together.',
          inviterName: 'Taylor',
          peopleCount: 3,
          bots: bootstrap.groups[0]?.bots ?? [],
          expiresAt: Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60,
        };
    }
    return publicRequest<Omit<InvitePreview, 'token'>>(
      `/public/invites/${encodeURIComponent(kind)}/${encodeURIComponent(token)}`,
    ).then((value) => ({ ...value, token }));
  },
  bootstrap: async (): Promise<Bootstrap> => (demo ? demoBootstrap() : request<Bootstrap>('/bootstrap')),
  messages: async (botId: string): Promise<Message[]> =>
    demo
      ? demoMessages(botId)
      : request<{ messages: Message[] }>(`/bots/${botId}/messages`).then((value) => value.messages),
  saveBot: async (draft: BotDraft, botId?: string): Promise<Bot> =>
    demo
      ? demoSaveBot(draft, botId)
      : request<Bot>(botId ? `/bots/${botId}` : '/bots', {
          method: botId ? 'PUT' : 'POST',
          body: JSON.stringify(draft),
        }),
  clearBotChat: async (botId: string): Promise<void> => {
    if (demo) return demoClearBotChat(botId);
    await request(`/bots/${encodeURIComponent(botId)}/messages`, { method: 'DELETE' });
  },
  deleteBot: async (botId: string): Promise<void> => {
    if (demo) return demoDeleteBot(botId);
    await request(`/bots/${encodeURIComponent(botId)}`, { method: 'DELETE' });
  },
  uploadAttachment: async (asset: {
    uri: string;
    name: string;
    size: number;
    mimeType?: string;
    file?: File;
  }): Promise<Attachment> => {
    if (demo) {
      return {
        id: `demo-file-${Date.now()}`,
        name: asset.name,
        size: asset.size,
        kind: asset.mimeType?.startsWith('image/') ? 'image' : 'document',
        format: asset.name.split('.').pop()?.toLowerCase() ?? 'txt',
        contentType: asset.mimeType ?? 'application/octet-stream',
      };
    }
    const ticket = await request<{
      file: Attachment;
      upload: { url: string; fields: Record<string, string> };
    }>('/uploads', {
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
    return request<Attachment>(`/uploads/${encodeURIComponent(ticket.file.id)}/complete`, {
      method: 'POST',
    });
  },
  downloadFile: async (fileId: string, groupId?: string): Promise<string> =>
    demo
      ? `data:text/plain;charset=utf-8,${encodeURIComponent('FroggyBot preview attachment')}`
      : request<{ url: string }>(
          groupId
            ? `/groups/${encodeURIComponent(groupId)}/files/${encodeURIComponent(fileId)}/download`
            : `/files/${encodeURIComponent(fileId)}/download`,
        ).then((value) => value.url),
  sendMessage: async (bot: Bot, text: string, attachmentIds: string[] = []): Promise<void> => {
    if (demo) return demoSend(bot, text);
    await request(`/bots/${bot.id}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, attachmentIds }),
    });
  },
  cancelMessage: async (botId: string, turnId: string): Promise<void> => {
    if (demo) return;
    await request(
      `/bots/${encodeURIComponent(botId)}/messages/${encodeURIComponent(turnId)}/cancel`,
      { method: 'POST' },
    );
  },
  approveMessage: async (botId: string, turnId: string): Promise<void> => {
    if (demo) return;
    await request(
      `/bots/${encodeURIComponent(botId)}/messages/${encodeURIComponent(turnId)}/approve`,
      { method: 'POST' },
    );
  },
  schedules: async (botId: string): Promise<ScheduledTask[]> =>
    demo
      ? demoListSchedules(botId)
      : request<{ schedules: ScheduledTask[] }>(`/bots/${encodeURIComponent(botId)}/schedules`).then(
          (value) => value.schedules,
        ),
  saveSchedule: async (botId: string, draft: ScheduledTaskDraft, scheduleId?: string): Promise<ScheduledTask> =>
    demo
      ? demoSaveSchedule(botId, draft, scheduleId)
      : request<ScheduledTask>(
          scheduleId
            ? `/bots/${encodeURIComponent(botId)}/schedules/${encodeURIComponent(scheduleId)}`
            : `/bots/${encodeURIComponent(botId)}/schedules`,
          { method: scheduleId ? 'PUT' : 'POST', body: JSON.stringify(draft) },
        ),
  deleteSchedule: async (botId: string, scheduleId: string): Promise<void> => {
    if (demo) return demoDeleteSchedule(botId, scheduleId);
    await request(
      `/bots/${encodeURIComponent(botId)}/schedules/${encodeURIComponent(scheduleId)}`,
      { method: 'DELETE' },
    );
  },
  runSchedule: async (botId: string, scheduleId: string): Promise<void> => {
    if (demo) return demoRunSchedule(botId, scheduleId);
    await request(
      `/bots/${encodeURIComponent(botId)}/schedules/${encodeURIComponent(scheduleId)}/run`,
      { method: 'POST' },
    );
  },
  groupMessages: async (groupId: string): Promise<Message[]> =>
    demo
      ? demoGroupMessages(groupId)
      : request<{ messages: Message[] }>(`/groups/${groupId}/messages`).then((value) => value.messages),
  saveGroup: async (draft: GroupDraft, groupId?: string): Promise<Group> =>
    demo
      ? demoSaveGroup(draft, groupId)
      : request<Group>(groupId ? `/groups/${groupId}` : '/groups', {
          method: groupId ? 'PUT' : 'POST',
          body: JSON.stringify(draft),
        }),
  deleteGroup: async (groupId: string): Promise<void> => {
    if (demo) return demoDeleteGroup(groupId);
    await request(`/groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' });
  },
  sendGroupMessage: async (groupId: string, text: string, replyBotId?: string): Promise<void> => {
    if (demo) return demoSendGroup(groupId, text, replyBotId);
    await request(`/groups/${groupId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text, replyBotId }),
    });
  },
  shareGroup: async (groupId: string): Promise<string> => {
    if (demo) return `https://froggybot.com/invite?kind=group&token=demo-${groupId}`;
    return request<{ url: string }>(`/groups/${groupId}/invites`, { method: 'POST' }).then((value) => value.url);
  },
  joinGroup: async (token: string): Promise<Group> => {
    if (demo) return demoJoinGroup(token);
    return request<Group>(`/group-invites/${encodeURIComponent(token)}/join`, { method: 'POST' });
  },
  removeGroupMember: async (groupId: string, memberId: string): Promise<void> => {
    if (demo) return;
    await request(`/groups/${groupId}/members/${encodeURIComponent(memberId)}`, { method: 'DELETE' });
  },
  registerPushToken: async (token: string): Promise<void> => {
    if (demo) return;
    await request('/devices/push-token', { method: 'PUT', body: JSON.stringify({ token }) });
  },
  unregisterPushToken: async (token: string): Promise<void> => {
    if (demo) return;
    await request('/devices/push-token', { method: 'DELETE', body: JSON.stringify({ token }) });
  },
  sharedLinks: async (): Promise<SharedLink[]> =>
    demo ? [] : request<{ shares: SharedLink[] }>('/shares').then((value) => value.shares),
  revokeShare: async (token: string): Promise<void> => {
    if (demo) return;
    await request(`/shares/${encodeURIComponent(token)}`, { method: 'DELETE' });
  },
  deleteAccount: async (): Promise<void> => {
    if (demo) return;
    await request('/account', { method: 'DELETE' });
  },
  share: async (botId: string, scope: 'bot' | 'chat'): Promise<string> => {
    if (demo) return `https://froggybot.com/invite?kind=${scope}&token=demo-${scope}-${botId}`;
    return request<{ url: string }>('/shares', {
      method: 'POST',
      body: JSON.stringify({ botId, scope }),
    }).then((value) => value.url);
  },
  importShare: async (token: string): Promise<Bot> => {
    if (demo) return (await demoBootstrap()).bots[0];
    return request<Bot>(`/shares/${encodeURIComponent(token)}/import`, { method: 'POST' });
  },
  skill: async (skillId: string): Promise<SkillDetail> =>
    demo ? demoGetSkill(skillId) : request<SkillDetail>(`/skills/${encodeURIComponent(skillId)}`),
  saveSkill: async (draft: SkillDraft, skillId?: string): Promise<SkillDetail> =>
    demo
      ? demoSaveSkill(draft, skillId)
      : request<SkillDetail>(skillId ? `/skills/${encodeURIComponent(skillId)}` : '/skills', {
          method: skillId ? 'PUT' : 'POST',
          body: JSON.stringify(draft),
        }),
  shareSkill: async (skillId: string): Promise<string> => {
    if (demo) return `https://froggybot.com/invite?kind=skill&token=demo-${skillId}`;
    return request<{ url: string }>(`/skills/${encodeURIComponent(skillId)}/share`, { method: 'POST' }).then(
      (value) => value.url,
    );
  },
  importSkill: async (token: string): Promise<SkillDetail> => {
    if (demo) return demoImportSkill(token);
    return request<SkillDetail>(`/skill-shares/${encodeURIComponent(token)}/import`, { method: 'POST' });
  },
  saveConnection: async (draft: ConnectionDraft, connectionId?: string): Promise<Connection> =>
    demo
      ? demoSaveConnection(draft, connectionId)
      : request<Connection>(connectionId ? `/connections/${encodeURIComponent(connectionId)}` : '/connections', {
          method: connectionId ? 'PUT' : 'POST',
          body: JSON.stringify(draft),
        }),
  deleteConnection: async (connectionId: string): Promise<void> => {
    if (demo) return demoDeleteConnection(connectionId);
    await request(`/connections/${encodeURIComponent(connectionId)}`, { method: 'DELETE' });
  },
});

export type FrogBotApi = ReturnType<typeof createApi>;
