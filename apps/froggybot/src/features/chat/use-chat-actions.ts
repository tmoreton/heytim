import { Alert, Share } from 'react-native';

import type { FrogBotApi } from '@/lib/api';
import { endSession } from '@/lib/auth';
import type {
  Bot,
  BotDraft,
  ConversationSelection,
  Group,
  GroupDraft,
  GroupMember,
  Message,
} from '@/lib/types';

import type { BotAction } from './bot-action-sheets';
import type { ChatOverlay } from './chat-overlay';
import { isActiveResponse } from './chat-state';
import type { useAttachments } from './use-attachments';
import type { useChatData } from './use-chat-data';

const directTurnId = (message: Message) => message.id.replace(/-assistant$/, '');

type Options = {
  api: FrogBotApi;
  demo: boolean;
  overlay: ChatOverlay;
  setOverlay: (overlay: ChatOverlay) => void;
  selectedBot?: Bot;
  editingBot?: Bot;
  selectedGroup?: Group;
  selection?: ConversationSelection;
  activeReplyBotId?: string;
  selectedReplyBotName?: string;
  sending: boolean;
  setSending: (sending: boolean) => void;
  chat: ReturnType<typeof useChatData>;
  attachments: ReturnType<typeof useAttachments>;
  unregisterPushToken: () => Promise<void>;
  onSignedOut: () => void;
};

export function useChatActions({
  api,
  demo,
  overlay,
  setOverlay,
  selectedBot,
  editingBot,
  selectedGroup,
  selection,
  activeReplyBotId,
  selectedReplyBotName,
  sending,
  setSending,
  chat,
  attachments,
  unregisterPushToken,
  onSignedOut,
}: Options) {
  const activeDirectTurn = selectedBot
    ? [...chat.messages].reverse().find(
        (message) => message.role === 'assistant' && isActiveResponse(message),
      )
    : undefined;

  const saveBot = async (value: BotDraft) => {
    const editing = overlay.kind === 'botEditor' && overlay.mode === 'edit';
    const saved = await api.saveBot(value, editing ? editingBot?.id : undefined);
    attachments.clear();
    chat.upsertBot(saved);
  };

  const installBotTemplate = async (templateId: string) => {
    const saved = await api.installBotTemplate(templateId);
    setOverlay({ kind: 'botLibrary' });
    attachments.clear();
    chat.upsertBot(saved, true);
    return saved;
  };

  const saveGroup = async (value: GroupDraft) => {
    const editing = overlay.kind === 'groupEditor' && overlay.mode === 'edit';
    const saved = await api.saveGroup(value, editing ? selectedGroup?.id : undefined);
    attachments.clear();
    chat.upsertGroup(saved);
  };

  const send = async (text: string) => {
    const selected = selectedBot ?? selectedGroup;
    if (
      (!text && attachments.attachments.length === 0)
      || !selected
      || sending
      || (chat.pending && !selectedBot)
      || attachments.uploading
    ) return false;
    setSending(true);
    try {
      const attachmentIds = attachments.attachments.map((item) => item.id);
      if (selectedGroup) {
        await api.sendGroupMessage(selectedGroup.id, text, activeReplyBotId, attachmentIds);
      } else if (selectedBot) {
        await api.sendMessage(selectedBot, text, attachmentIds);
      }
      if (selection && (selectedBot || activeReplyBotId)) {
        chat.markConversationProcessing(selection, selectedBot?.name ?? selectedReplyBotName);
      }
      attachments.clear();
      await chat.loadMessages();
      return true;
    } catch (value) {
      chat.setError(value instanceof Error ? value.message : 'Could not send that message.');
      return false;
    } finally {
      setSending(false);
    }
  };

  const stopResponse = async () => {
    if (!selectedBot || !activeDirectTurn) return;
    try {
      await api.cancelMessage(selectedBot.id, directTurnId(activeDirectTurn));
      await chat.loadMessages();
    } catch (value) {
      chat.setError(value instanceof Error ? value.message : 'Could not stop that response.');
    }
  };

  const respondToApproval = async (message: Message, always?: boolean) => {
    if (!selectedBot || message.status !== 'awaiting_approval') return;
    try {
      if (always === undefined) {
        await api.cancelMessage(selectedBot.id, directTurnId(message));
      } else {
        await api.approveMessage(selectedBot.id, directTurnId(message), always);
      }
      await chat.loadMessages();
      if (always) await chat.loadBootstrap();
    } catch (value) {
      chat.setError(value instanceof Error ? value.message : 'Could not update that approval request.');
    }
  };

  const shareBot = () => {
    if (!selectedBot) return;
    api.share(selectedBot.id, 'bot')
      .then((url) => Share.share({
        title: `Share ${selectedBot.name}`,
        message: `Add ${selectedBot.name} to FroggyBot: ${url}`,
        url,
      }))
      .catch((value) => Alert.alert(
        'Could not share',
        value instanceof Error ? value.message : 'Please try again.',
      ));
  };

  const runBotDeletion = async (requestedAction?: BotAction) => {
    if (!selectedBot || overlay.kind !== 'botConfirmation') return;
    const action = requestedAction ?? overlay.action;
    try {
      if (action === 'clear' || action === 'clearAndForget') {
        await api.clearBotChat(selectedBot.id, action === 'clearAndForget');
        chat.replaceBootstrap(await api.bootstrap());
        chat.clearMessages();
        setOverlay({ kind: 'none' });
        return;
      }
      await api.deleteBot(selectedBot.id);
      attachments.clear();
      await chat.refreshAfterMutation();
    } catch (value) {
      chat.setError(value instanceof Error ? value.message : 'Could not delete that conversation.');
    }
  };

  const shareGroup = async () => {
    if (!selectedGroup) throw new Error('Choose a group first.');
    return api.shareGroup(selectedGroup.id);
  };

  const removeGroupMember = async (member: GroupMember) => {
    if (!selectedGroup) return;
    await api.removeGroupMember(selectedGroup.id, member.id);
    attachments.clear();
    await chat.loadBootstrap();
  };

  const deleteGroup = async () => {
    if (!selectedGroup) return;
    await api.deleteGroup(selectedGroup.id);
    attachments.clear();
    await chat.refreshAfterMutation();
  };

  const deleteGroupDecision = async (decisionId: string) => {
    if (!selectedGroup) return;
    await api.deleteGroupDecision(selectedGroup.id, decisionId);
    chat.upsertGroup({
      ...selectedGroup,
      decisions: selectedGroup.decisions.filter((item) => item.id !== decisionId),
    });
  };

  const saveGroupDecision = async (message: Message) => {
    if (!selectedGroup) return;
    const decision = await api.saveGroupDecision(selectedGroup.id, message.id);
    chat.upsertGroup({
      ...selectedGroup,
      decisions: [
        decision,
        ...selectedGroup.decisions.filter((item) => item.id !== decision.id),
      ],
    });
  };

  const refreshAfterSchedule = async () => {
    chat.clearMessages(true);
    await Promise.all([chat.loadMessages(), chat.loadBootstrap()]);
  };

  const signOut = async () => {
    if (!demo) {
      try {
        await unregisterPushToken();
      } catch (value) {
        console.warn('Could not unregister the push token.', value);
      }
      await endSession();
    }
    onSignedOut();
  };

  const deleteAccount = async () => {
    if (demo) return;
    await api.deleteAccount();
    try {
      await endSession();
    } catch (value) {
      console.warn('Account deletion started, but local sign-out reported an error.', value);
    }
    setOverlay({ kind: 'none' });
    onSignedOut();
  };

  return {
    activeDirectTurn,
    deleteAccount,
    deleteGroup,
    deleteGroupDecision,
    installBotTemplate,
    refreshAfterSchedule,
    removeGroupMember,
    respondToApproval,
    runBotDeletion,
    saveBot,
    saveGroup,
    saveGroupDecision,
    send,
    shareBot,
    shareGroup,
    signOut,
    stopResponse,
  };
}
