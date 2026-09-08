import { createCloudApi } from './cloud-api';
import { createDemoApi } from './demo-api';
import type {
  Attachment,
  Bootstrap,
  Bot,
  BotDocument,
  BotDraft,
  Connection,
  ConnectionDraft,
  Group,
  GroupDraft,
  Invitation,
  InvitePreview,
  MemoryRecord,
  MemorySnapshot,
  Message,
  ScheduledTask,
  ScheduledTaskDraft,
  SharedLink,
  SkillDetail,
  SkillDraft,
} from './types';

type UploadAsset = {
  uri: string;
  name: string;
  size: number;
  mimeType?: string;
  file?: File;
};

export interface FrogBotApi {
  invitePreview(invitation: Invitation): Promise<InvitePreview>;
  bootstrap(): Promise<Bootstrap>;
  installBotTemplate(templateId: string): Promise<Bot>;
  messages(botId: string): Promise<Message[]>;
  botDocuments(botId: string): Promise<BotDocument[]>;
  saveBot(draft: BotDraft, botId?: string): Promise<Bot>;
  clearBotChat(botId: string, forgetMemory?: boolean): Promise<void>;
  deleteBot(botId: string): Promise<void>;
  uploadAttachment(asset: UploadAsset): Promise<Attachment>;
  downloadFile(fileId: string, groupId?: string): Promise<string>;
  sendMessage(bot: Bot, text: string, attachmentIds?: string[]): Promise<void>;
  cancelMessage(botId: string, turnId: string): Promise<void>;
  approveMessage(botId: string, turnId: string, always?: boolean): Promise<void>;
  schedules(botId: string): Promise<ScheduledTask[]>;
  saveSchedule(botId: string, draft: ScheduledTaskDraft, scheduleId?: string): Promise<ScheduledTask>;
  deleteSchedule(botId: string, scheduleId: string): Promise<void>;
  runSchedule(botId: string, scheduleId: string): Promise<void>;
  groupMessages(groupId: string): Promise<Message[]>;
  saveGroup(draft: GroupDraft, groupId?: string): Promise<Group>;
  deleteGroup(groupId: string): Promise<void>;
  sendGroupMessage(groupId: string, text: string, replyBotId?: string): Promise<void>;
  shareGroup(groupId: string): Promise<string>;
  joinGroup(token: string): Promise<Group>;
  removeGroupMember(groupId: string, memberId: string): Promise<void>;
  registerPushToken(token: string): Promise<void>;
  unregisterPushToken(token: string): Promise<void>;
  sharedLinks(): Promise<SharedLink[]>;
  memories(): Promise<MemorySnapshot>;
  createMemory(kind: 'fact' | 'preference', content: string): Promise<MemoryRecord>;
  updateMemory(recordId: string, content: string): Promise<MemoryRecord>;
  deleteMemory(recordId: string): Promise<void>;
  exportMemory(): Promise<string>;
  groupMemories(groupId: string): Promise<MemorySnapshot>;
  createGroupMemory(groupId: string, content: string): Promise<MemoryRecord>;
  updateGroupMemory(groupId: string, recordId: string, content: string): Promise<MemoryRecord>;
  deleteGroupMemory(groupId: string, recordId: string): Promise<void>;
  revokeShare(token: string): Promise<void>;
  deleteAccount(): Promise<void>;
  share(botId: string, scope: 'bot' | 'chat'): Promise<string>;
  importShare(token: string): Promise<Bot>;
  skill(skillId: string): Promise<SkillDetail>;
  saveSkill(draft: SkillDraft, skillId?: string): Promise<SkillDetail>;
  shareSkill(skillId: string): Promise<string>;
  importSkill(token: string): Promise<SkillDetail>;
  saveConnection(draft: ConnectionDraft, connectionId?: string): Promise<Connection>;
  beginGmailConnection(returnUrl: string): Promise<string>;
  deleteConnection(connectionId: string): Promise<void>;
}

export const createApi = (demo: boolean): FrogBotApi =>
  demo ? createDemoApi() : createCloudApi();
