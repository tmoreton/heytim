import { Asset } from 'expo-asset';

import type { FrogBotApi } from './api';
import { createDemoBrowserApi } from './browser-api';
import { deleteDemoGroupDecision, saveDemoGroupDecision } from './demo-decisions';
import {
  demoBotDocuments,
  demoUploadAttachment,
} from './demo/demo-assets';
import {
  demoClearBotChat,
  demoDeleteBot,
  demoMessages,
  demoSaveBot,
  demoSend,
} from './demo/demo-bots';
import { demoBootstrap, demoInstallBotTemplate } from './demo/demo-bootstrap';
import {
  demoDeleteGroup,
  demoGroupMessages,
  demoJoinGroup,
  demoSaveGroup,
  demoSendGroup,
} from './demo/demo-groups';
import {
  demoDeleteSchedule,
  demoListSchedules,
  demoRunSchedule,
  demoScheduleRuns,
  demoSaveSchedule,
} from './demo/demo-schedules';
import {
  demoDeleteConnection,
  demoGetSkill,
  demoImportSkill,
  demoSaveSkill,
} from './demo/demo-skills';

const demoImageUrl = Asset.fromModule(
  require('../../assets/images/frogbot-foreground.png'),
).uri;

export const createDemoApi = (): FrogBotApi => ({
  ...createDemoBrowserApi(),
  invitePreview: async ({ kind, token }) => {
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
  },
  bootstrap: demoBootstrap,
  installBotTemplate: demoInstallBotTemplate,
  messages: async (botId) => ({ messages: demoMessages(botId) }),
  botDocuments: demoBotDocuments,
  saveBot: async (draft, botId) => demoSaveBot(draft, botId),
  clearBotChat: async (botId) => demoClearBotChat(botId),
  deleteBot: async (botId) => demoDeleteBot(botId),
  uploadAttachment: demoUploadAttachment,
  downloadFile: async (fileId) => fileId === 'demo-thumbnail-preview'
    ? demoImageUrl
    : `data:text/plain;charset=utf-8,${encodeURIComponent('FroggyBot preview attachment')}`,
  sendMessage: async (bot, text) => demoSend(bot, text),
  cancelMessage: async () => {},
  approveMessage: async () => {},
  schedules: demoListSchedules,
  saveSchedule: demoSaveSchedule,
  deleteSchedule: demoDeleteSchedule,
  runSchedule: demoRunSchedule,
  scheduleRuns: demoScheduleRuns,
  groupSchedules: demoListSchedules,
  saveGroupSchedule: demoSaveSchedule,
  deleteGroupSchedule: demoDeleteSchedule,
  runGroupSchedule: demoRunSchedule,
  groupScheduleRuns: demoScheduleRuns,
  groupMessages: async (groupId) => ({ messages: demoGroupMessages(groupId) }),
  saveGroup: async (draft, groupId) => demoSaveGroup(draft, groupId),
  deleteGroup: async (groupId) => demoDeleteGroup(groupId),
  sendGroupMessage: async (groupId, text, replyBotId, attachmentIds) => demoSendGroup(groupId, text, replyBotId, attachmentIds),
  shareGroup: async (groupId) => `https://froggybot.com/invite?kind=group&token=demo-${groupId}`,
  joinGroup: async (token) => demoJoinGroup(token),
  removeGroupMember: async () => {},
  saveGroupDecision: async (groupId, messageId) => saveDemoGroupDecision(
    groupId,
    demoGroupMessages(groupId).find((message) => message.id === messageId),
  ),
  deleteGroupDecision: deleteDemoGroupDecision,
  registerPushToken: async () => {},
  unregisterPushToken: async () => {},
  sharedLinks: async () => [],
  memories: async () => ({ records: [], rawConversationRetentionDays: 30 }),
  createMemory: async () => { throw new Error('Sign in to manage memory.'); },
  updateMemory: async () => { throw new Error('Sign in to manage memory.'); },
  deleteMemory: async () => {},
  exportMemory: async () => { throw new Error('Sign in to export memory.'); },
  groupMemories: async () => ({ records: [], rawConversationRetentionDays: 30 }),
  createGroupMemory: async () => { throw new Error('Sign in to manage group memory.'); },
  updateGroupMemory: async () => { throw new Error('Sign in to manage group memory.'); },
  deleteGroupMemory: async () => {},
  revokeShare: async () => {},
  deleteAccount: async () => {},
  share: async (botId, scope) => `https://froggybot.com/invite?kind=${scope}&token=demo-${scope}-${botId}`,
  importShare: async () => (await demoBootstrap()).bots[0],
  skill: demoGetSkill,
  saveSkill: demoSaveSkill,
  shareSkill: async (skillId) => `https://froggybot.com/invite?kind=skill&token=demo-${skillId}`,
  importSkill: demoImportSkill,
  beginConnection: async () => { throw new Error('Sign in to connect an account.'); },
  deleteConnection: async (connectionId) => demoDeleteConnection(connectionId),
});
