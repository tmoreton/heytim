import type { Group, GroupDecision, GroupDraft } from '../types';

import type { MessagePage } from './conversations-api';

export interface GroupsApi {
  groupMessages(groupId: string, cursor?: string): Promise<MessagePage>;
  saveGroup(draft: GroupDraft, groupId?: string): Promise<Group>;
  deleteGroup(groupId: string): Promise<void>;
  sendGroupMessage(
    groupId: string,
    text: string,
    replyBotId?: string,
    attachmentIds?: string[],
  ): Promise<void>;
  shareGroup(groupId: string): Promise<string>;
  joinGroup(token: string): Promise<Group>;
  removeGroupMember(groupId: string, memberId: string): Promise<void>;
  saveGroupDecision(groupId: string, messageId: string): Promise<GroupDecision>;
  deleteGroupDecision(groupId: string, decisionId: string): Promise<void>;
}
