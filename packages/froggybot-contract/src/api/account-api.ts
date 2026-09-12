import type {
  Bot,
  Invitation,
  InvitePreview,
  MemoryRecord,
  MemorySnapshot,
  SharedLink,
  SkillDetail,
  SkillDraft,
} from '../types';

export interface AccountApi {
  invitePreview(invitation: Invitation): Promise<InvitePreview>;
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
  beginConnection(providerId: string, returnUrl: string): Promise<string>;
  deleteConnection(connectionId: string): Promise<void>;
}
