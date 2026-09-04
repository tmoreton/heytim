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
  demoListSchedules,
  demoRunSchedule,
  demoSaveSchedule,
  demoSend,
  demoSendGroup,
} from './demo';
import type {
  Bootstrap,
  Bot,
  BotDraft,
  Group,
  GroupDraft,
  Invitation,
  InvitePreview,
  Message,
  ScheduledTask,
  ScheduledTaskDraft,
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
  invitePreview: async ({ kind, token }: Invitation): Promise<InvitePreview> =>
    demo
      ? {
          kind,
          token,
          title: kind === 'group' ? 'Weekend builders' : 'A FrogBot for you',
          description: 'Taylor invited you to bring people and FrogBots together.',
          inviterName: 'Taylor',
          peopleCount: 3,
          bots: demoBootstrap().groups[0]?.bots ?? [],
          expiresAt: Math.floor(Date.now() / 1000) + 30 * 24 * 60 * 60,
        }
      : publicRequest<Omit<InvitePreview, 'token'>>(
          `/public/invites/${encodeURIComponent(kind)}/${encodeURIComponent(token)}`,
        ).then((value) => ({ ...value, token })),
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
  sendMessage: async (bot: Bot, text: string): Promise<void> => {
    if (demo) return demoSend(bot, text);
    await request(`/bots/${bot.id}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
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
    if (demo) return `https://frogbot.expo.app/invite?kind=group&token=demo-${groupId}`;
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
  share: async (botId: string, scope: 'bot' | 'chat'): Promise<string> => {
    if (demo) return `https://frogbot.expo.app/invite?kind=${scope}&token=demo-${scope}-${botId}`;
    return request<{ url: string }>('/shares', {
      method: 'POST',
      body: JSON.stringify({ botId, scope }),
    }).then((value) => value.url);
  },
  importShare: async (token: string): Promise<Bot> => {
    if (demo) return demoBootstrap().bots[0];
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
    if (demo) return `https://frogbot.expo.app/invite?kind=skill&token=demo-${skillId}`;
    return request<{ url: string }>(`/skills/${encodeURIComponent(skillId)}/share`, { method: 'POST' }).then(
      (value) => value.url,
    );
  },
  importSkill: async (token: string): Promise<SkillDetail> => {
    if (demo) return demoImportSkill(token);
    return request<SkillDetail>(`/skill-shares/${encodeURIComponent(token)}/import`, { method: 'POST' });
  },
});
